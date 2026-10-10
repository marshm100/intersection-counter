"""Vehicle appearance probe on the JOURNEY LABELS (2026-10-09; plan_basis "VEHICLE APPEARANCE PROBE").

The chain-yardstick probe (probe_vehicle_reid.py) turned out to measure the yardstick: by eye, the thefts the
models called "same car" were one truck split into two chains, and the "same car" points they called different
were chains that had jumped cars. Truth here is the operator's clicks: every labelled vehicle of the five DEV
clips (one per camera; the held-out clips are not touched) has an entry and an exit click (back tyre, frame).
Each click is matched to the detector box that contains it (detection cache); a few earlier boxes are followed
by overlap. Two tests, both inside the intersection:
  A  ENTRY vs EXIT   the car before the entry line (refs) vs the box at the exit click.
                     SAME = the same vehicle's exit box; DIFFERENT = another labelled vehicle's exit box
                     within EXIT_S seconds of this one's exit (the cars an id could slide onto).
  B  AT THE EXIT     the car in the RECENT_S seconds before its exit click (refs) vs its own box at the
                     click (SAME, the short-gap case of a normal match) and vs each other labelled vehicle's
                     box in that same frame within NEAR_W box widths (DIFFERENT: the side-by-side case).
Models: osnet_x0_25_msmt17 (pedestrian baseline), clip_veri (vehicle ReID, VeRi-776), DINOv2 ViT-B/14.
Gate (declared): AUC >= 0.95 and >= 50% of DIFFERENT caught at <= 1% of SAME refused.
Read-only. Usage: .venv/Scripts/python.exe -X utf8 scripts/probe_vehicle_reid_labels.py [PROJ]
Writes runs/v2_week1/probe_vehicle_reid_labels.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from probe_theft_appearance import auc  # noqa: E402
from probe_vehicle_reid import MODELS, Dino, caught_at  # noqa: E402
from research_thefts import iou_mat  # noqa: E402

EXIT_S = 2.0
RECENT_S = 0.5
NEAR_W = 2.0
N_REF = 4
CLICK_SLACK = 0.35       # a back-tyre click may sit just outside the box


def find_parquet(proj: str, cam: int, chash: str, f0: int, f1: int) -> Path:
    d = parquet_path(proj, cam, chash, "study_0700").parent
    for m in sorted(d.glob("study_[0-9][0-9][0-9][0-9].meta.json")):
        for lo, hi in json.loads(m.read_text()).get("windows", []):
            if lo <= f0 and f1 <= hi:
                return m.with_name(m.name.replace(".meta.json", ".parquet"))
    raise SystemExit(f"no study cache covers cam{cam} {f0}-{f1}")


def load_boxes(pqp: Path, f0: int, f1: int) -> dict:
    t = pq.read_table(pqp, columns=["frame_idx", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"],
                      filters=[("frame_idx", ">=", f0), ("frame_idx", "<=", f1)])
    fr = t.column("frame_idx").to_numpy().astype(np.int64)
    bb = np.stack([t.column(c).to_numpy() for c in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2")], axis=1)
    out = defaultdict(list)
    for f, b in zip(fr, bb.astype(np.float64)):
        out[int(f)].append(b)
    return {f: np.asarray(v) for f, v in out.items()}


def box_at(boxes: dict, f: int, x: float, y: float):
    B = boxes.get(f)
    if B is None or not len(B):
        return None
    # distance from the click to each box (0 inside); a back-tyre click sits at one end of the box and,
    # at 10 fps, the car may have moved a little: accept within CLICK_SLACK box widths, nearest first
    w = B[:, 2] - B[:, 0]
    dx = np.maximum(np.maximum(B[:, 0] - x, x - B[:, 2]), 0)
    dy = np.maximum(np.maximum(B[:, 1] - y, y - B[:, 3]), 0)
    d = np.hypot(dx, dy) / np.maximum(w, 1.0)
    k = int(d.argmin())
    if d[k] > CLICK_SLACK:
        return None
    tied = np.flatnonzero(d <= d[k] + 1e-9)
    if len(tied) > 1:      # inside several boxes: the smallest
        k = int(tied[np.argmin(w[tied] * (B[tied, 3] - B[tied, 1]))])
    return B[k]


def follow(boxes: dict, f: int, b: np.ndarray, frames: list[int]) -> list:
    """The same vehicle's boxes at the given frames (walking frame by frame from f, best IoU >= 0.4)."""
    out, cur, cf = {}, b, f
    for g in sorted(frames, key=lambda g: abs(g - f)):
        step = 1 if g > cf else -1
        ok = True
        for h in range(cf + step, g + step, step) if g != cf else []:
            B = boxes.get(h)
            if B is None or not len(B):
                continue
            m = iou_mat(cur[None], B)[0]
            if m.max() < 0.4:
                ok = False
                break
            cur = B[int(m.argmax())]
        if not ok:
            break
        cf = g
        out[g] = cur
    return [(g, out[g]) for g in sorted(out)]


def main() -> int:
    proj = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else "97a7849a"
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    clips = con.execute("SELECT clip_id, camera_id, start_frame, end_frame, fps FROM journey_clips "
                        "WHERE label NOT LIKE '%held out%'").fetchall()
    from boxmot.reid.core.reid import ReID
    models = {"osnet": ReID(weights="osnet_x0_25_msmt17.pt", device="cuda:0").model,
              "clip_veri": ReID(weights="clip_veri.pt", device="cuda:0").model,
              "dinov2": Dino()}
    from backend.services.vehicle_verifier import Verifier
    for name, wpath in (("ver_all", "data/models/verifier_v1_all.pt"), ("ver_nocam2", "data/models/verifier_v1_nocam2.pt")):
        if Path(wpath).exists():
            models[name] = Verifier(wpath)
    if "--only-new" in sys.argv:
        models = {k: v for k, v in models.items() if k.startswith("ver_") or k == "clip_veri"}
    pairs = []
    for clip, cam, f0, f1, fps in clips:
        vpath, chash = con.execute("SELECT path, content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
        boxes = load_boxes(find_parquet(proj, cam, chash, f0, f1), f0 - 50, f1 + 50)
        labs = con.execute("SELECT label_id, entry_frame, entry_x, entry_y, exit_frame, exit_x, exit_y "
                           "FROM journey_labels WHERE clip_id=? AND exit_frame IS NOT NULL", (clip,)).fetchall()
        step = max(1, int(round(RECENT_S * fps / N_REF)))
        veh = []
        for lid, fe, xe, ye, fx, xx, yx in labs:
            be, bx = box_at(boxes, fe, xe, ye), box_at(boxes, fx, xx, yx)
            if be is None or bx is None:
                continue
            ent = follow(boxes, fe, be, [fe - k * step for k in range(N_REF)])
            rec = follow(boxes, fx, bx, [fx - k * step for k in range(1, N_REF + 1)])
            veh.append({"id": lid, "fe": fe, "fx": fx, "ent": ent, "exit": (fx, bx), "recent": rec})
        print(f"{clip}: {len(labs)} labelled journeys, {len(veh)} with both clicks on a detector box", flush=True)
        for v in veh:
            if len(v["ent"]) >= 2:
                pairs.append({"clip": clip, "test": "A", "cls": "same", "refs": v["ent"], "take": v["exit"]})
                for u in veh:
                    if u is not v and abs(u["fx"] - v["fx"]) <= EXIT_S * fps:
                        pairs.append({"clip": clip, "test": "A", "cls": "diff", "refs": v["ent"], "take": u["exit"]})
            if len(v["recent"]) >= 2:
                f, b = v["exit"]
                pairs.append({"clip": clip, "test": "B", "cls": "same", "refs": v["recent"], "take": (f, b)})
                w = b[2] - b[0]
                for u in veh:
                    if u is v or abs(u["fx"] - f) > EXIT_S * fps:
                        continue
                    ub = follow(boxes, u["fx"], u["exit"][1], [f])
                    if not ub:
                        continue
                    o = ub[0][1]
                    d = np.hypot((o[0] + o[2] - b[0] - b[2]) / 2, (o[1] + o[3] - b[1] - b[3]) / 2)
                    if d <= NEAR_W * w and iou_mat(o[None], b[None])[0, 0] < 0.5:
                        pairs.append({"clip": clip, "test": "B", "cls": "diff", "refs": v["recent"], "take": (f, o)})
        # embed this clip's crops
        need = defaultdict(set)
        for p in pairs:
            if p["clip"] == clip:
                for f, b in [p["take"], *p["refs"]]:
                    need[int(f)].add(tuple(float(x) for x in b))
        feats = {m: {} for m in models}
        cap = cv2.VideoCapture(vpath)
        lo, hi = min(need), max(need)
        cap.set(cv2.CAP_PROP_POS_FRAMES, lo)
        for f in range(lo, hi + 1):
            if f not in need:
                if not cap.grab():
                    break
                continue
            ok, img = cap.read()
            if not ok:
                break
            bl = sorted(need[f])
            bb = np.clip(np.asarray(bl, dtype=np.float32), 0, [639, 479, 639, 479])
            for name, m in models.items():
                x = np.asarray(m.features(bb, img) if hasattr(m, "features") else m.get_features(bb, img),
                               dtype=np.float64)
                x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)
                for key, e in zip(bl, x):
                    feats[name][(f, key)] = e
        cap.release()
        for p in pairs:
            if p["clip"] != clip:
                continue
            tk = (int(p["take"][0]), tuple(float(x) for x in p["take"][1]))
            p["w"] = float(p["take"][1][2] - p["take"][1][0])
            for name, F in feats.items():
                rs = [F[(int(f), tuple(float(x) for x in b))] for f, b in p["refs"]]
                r = np.mean(rs, axis=0)
                p[name] = float(1 - r @ F[tk] / max(np.linalg.norm(r), 1e-9))

    Path("runs/v2_week1/probe_vehicle_reid_labels.json").write_text(json.dumps(
        [{k: v for k, v in p.items() if k not in ("refs", "take")} for p in pairs]))
    for test, title in (("A", "ENTRY vs EXIT"), ("B", "AT THE EXIT, side by side")):
        print(f"\n== TEST {test}: {title}")
        for scope in ["all", *[c[0] for c in clips]]:
            P = [p for p in pairs if p["test"] == test and (scope == "all" or p["clip"] == scope)]
            ns, nd = sum(p["cls"] == "same" for p in P), sum(p["cls"] == "diff" for p in P)
            line = f"  {scope:14s} same {ns:4d} diff {nd:4d} |"
            for name in models:
                pos = [p[name] for p in P if p["cls"] == "diff"]
                neg = [p[name] for p in P if p["cls"] == "same"]
                a, c1 = auc(pos, neg), caught_at(pos, neg, 0.01)
                line += f" {name} AUC {a:.3f} caught@1% {c1:.2f}{' PASS' if a >= 0.95 and c1 >= 0.5 else ''} |"
            print(line, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
