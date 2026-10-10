"""Vehicle appearance probe, in the intersection zone only (2026-10-09; plan_basis "VEHICLE APPEARANCE PROBE").

The human's test at a switch: does the box the id takes look like the car it was on? Every earlier appearance
verdict used osnet_x0_25_msmt17 (a pedestrian model) and colour. Here: clip_veri (CLIP-ReID trained on VeRi-776
VEHICLES) and DINOv2 ViT-B/14, with osnet as the baseline.
  THEFTS  census THEFT / SWAP / EMERGENCE / A ENDS (research_thefts.py) whose taken box's ground point is inside
          the zone (hull of the drawn gate segments): chain A's boxes in the second before (up to N_REF) vs
          chain B's box at the switch.
  SAME    random in-zone points on the chains: the chain's own boxes in the second before vs its box now.
All boxes are the yardstick chains' detector boxes (research_tracker_break.extract_all).
Read-only. Usage:
  .venv/Scripts/python.exe -X utf8 scripts/probe_vehicle_reid.py PROJ CAM VARIANT [VARIANT ...] [--n-same N]
Writes runs/v2_week1/probe_vehicle_reid_<proj>_<cam>_<variant>.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_theft_appearance import auc  # noqa: E402

N_REF = 5
REAL = ("THEFT", "EMERGENCE", "A ENDS")
MODELS = ("osnet", "clip_veri", "dinov2")
W_BINS = ((0, 33), (33, 66), (66, 1e9))


def hull_contains(hull: np.ndarray, p: np.ndarray) -> bool:
    return cv2.pointPolygonTest(hull.astype(np.float32), (float(p[0]), float(p[1])), False) >= 0


def ground(b) -> np.ndarray:
    return np.array([(b[0] + b[2]) / 2, b[3]], dtype=np.float64)


class Dino:
    MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
    STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

    def __init__(self):
        self.m = torch.hub.load("facebookresearch/dinov2", "dinov2_vitb14").cuda().eval().half()

    @torch.no_grad()
    def features(self, boxes: np.ndarray, img: np.ndarray) -> np.ndarray:
        crops = []
        H, W = img.shape[:2]
        for x1, y1, x2, y2 in boxes:
            # square crop around the box, a small margin, padded with the frame's mean
            cx, cy, s = (x1 + x2) / 2, (y1 + y2) / 2, max(x2 - x1, y2 - y1) * 1.1 / 2
            xa, ya, xb, yb = int(cx - s), int(cy - s), int(np.ceil(cx + s)), int(np.ceil(cy + s))
            pad = np.zeros((yb - ya, xb - xa, 3), dtype=np.uint8)
            sx, sy = max(xa, 0), max(ya, 0)
            ex, ey = min(xb, W), min(yb, H)
            pad[sy - ya:ey - ya, sx - xa:ex - xa] = img[sy:ey, sx:ex]
            c = cv2.resize(pad, (224, 224), interpolation=cv2.INTER_CUBIC)[:, :, ::-1].astype(np.float32) / 255
            crops.append((c - self.MEAN) / self.STD)
        x = torch.from_numpy(np.stack(crops).transpose(0, 3, 1, 2)).cuda().half()
        return self.m(x).float().cpu().numpy()          # CLS embedding


def samples(proj: str, cam: int, variant: str, n_same: int, fps: float, hull: np.ndarray) -> list[dict]:
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{variant}.json").read_text())
    ev = json.loads(Path(f"runs/v2_week1/thefts_{proj}_{cam}_{variant}.json").read_text())
    hit = [{int(h[0]): h[1:5] for h in v} for v in veh]
    win = int(round(fps))

    def refs(chain: int, f: int) -> list:
        fs = sorted(x for x in hit[chain] if f - win <= x < f)
        if len(fs) < 3:
            return []
        pick = [fs[int(round(k))] for k in np.linspace(0, len(fs) - 1, min(N_REF, len(fs)))]
        return [(x, hit[chain][x]) for x in sorted(set(pick))]

    out = []
    for e in ev:
        if e["kind"] not in REAL:
            continue
        fb = int(e["f_first_B"])
        tk = next(((x, hit[e["B"]][x]) for x in range(fb, fb + 4) if x in hit[e["B"]]), None)
        if tk is None or not hull_contains(hull, ground(tk[1])):
            continue
        r = refs(int(e["A"]), int(e["f_last_A"]) + 1)
        if r:
            kind = "SWAP" if e["kind"] == "THEFT" and e["swap_with"] else e["kind"]
            out.append({"cls": "theft", "kind": kind, "take": tk, "refs": r})
    rng = np.random.default_rng(0)
    cand = [(ci, f) for ci, h in enumerate(hit) for f, b in h.items() if hull_contains(hull, ground(b))]
    for k in rng.permutation(len(cand)):
        if sum(s["cls"] == "same" for s in out) >= n_same:
            break
        ci, f = cand[int(k)]
        r = refs(ci, f)
        if r:
            out.append({"cls": "same", "kind": "SAME", "take": (f, hit[ci][f]), "refs": r})
    return out


def embed(vpath: str, smp: list, models: dict) -> dict:
    need = defaultdict(set)
    for s in smp:
        for f, b in [s["take"], *s["refs"]]:
            need[int(f)].add(tuple(float(v) for v in b))
    feats = {m: {} for m in models}
    cap = cv2.VideoCapture(vpath)
    lo, hi = min(need), max(need)
    cap.set(cv2.CAP_PROP_POS_FRAMES, lo)
    f = lo
    while f <= hi:
        if f in need:
            ok, img = cap.read()
            if not ok:
                break
            bl = sorted(need[f])
            bb = np.clip(np.asarray(bl, dtype=np.float32), 0, [639, 479, 639, 479])
            okb = (bb[:, 2] - bb[:, 0] >= 4) & (bb[:, 3] - bb[:, 1] >= 4)
            if okb.any():
                for name, m in models.items():
                    x = np.asarray(m.get_features(bb[okb], img) if name != "dinov2" else m.features(bb[okb], img),
                                   dtype=np.float64)
                    x /= np.maximum(np.linalg.norm(x, axis=1, keepdims=True), 1e-9)
                    for key, v in zip([b for b, o in zip(bl, okb) if o], x):
                        feats[name][(f, key)] = v
        elif not cap.grab():
            break
        f += 1
    cap.release()
    return feats


def score(smp: list, feats: dict) -> None:
    for s in smp:
        tk = (int(s["take"][0]), tuple(float(v) for v in s["take"][1]))
        s["w"] = float(s["take"][1][2] - s["take"][1][0])
        for name, F in feats.items():
            rs = [F[(int(f), tuple(float(v) for v in b))] for f, b in s["refs"]
                  if (int(f), tuple(float(v) for v in b)) in F]
            if rs and tk in F:
                r = np.mean(rs, axis=0)
                s[name] = float(1 - r @ F[tk] / max(np.linalg.norm(r), 1e-9))


def caught_at(pos: list, neg: list, fpr: float) -> float:
    if not pos or not neg:
        return float("nan")
    t = np.quantile(neg, 1 - fpr)
    return float(np.mean(np.asarray(pos) > t))


def report(variant: str, smp: list) -> dict:
    th = [s for s in smp if s["cls"] == "theft"]
    sm = [s for s in smp if s["cls"] == "same"]
    print(f"== {variant}: in-zone thefts {len(th)} ("
          + ", ".join(f"{k} {sum(s['kind'] == k for s in th)}" for k in ("THEFT", "SWAP", "EMERGENCE", "A ENDS"))
          + f"), same-car points {len(sm)}", flush=True)
    res = {}
    for name in MODELS:
        pos = [s[name] for s in th if name in s]
        neg = [s[name] for s in sm if name in s]
        a, c1, c01 = auc(pos, neg), caught_at(pos, neg, 0.01), caught_at(pos, neg, 0.001)
        passed = a >= 0.95 and c1 >= 0.5
        res[name] = passed
        line = f"  {name:9s} AUC {a:.3f}  caught at 1% refused {c1:.2f}  at 0.1% {c01:.2f}  " \
               f"{'PASS' if passed else 'FAIL'} | by width"
        for lo, hi in W_BINS:
            p = [s[name] for s in th if name in s and lo <= s["w"] < hi]
            n = [s[name] for s in sm if name in s and lo <= s["w"] < hi]
            line += f"  {lo}-{hi if hi < 1e9 else ''}px: AUC {auc(p, n):.2f} (n {len(p)}/{len(n)})"
        print(line, flush=True)
        for k in ("THEFT", "SWAP", "EMERGENCE", "A ENDS"):
            p = [s[name] for s in th if name in s and s["kind"] == k]
            if p:
                print(f"      {k:9s} AUC {auc(p, neg):.2f} (n {len(p)})")
    return res


def main() -> int:
    args = [a for a in sys.argv[1:]]
    n_same = 3000
    if "--n-same" in args:
        i = args.index("--n-same"); n_same = int(args[i + 1]); del args[i:i + 2]
    proj, cam, variants = args[0], int(args[1]), args[2:]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, fps = con.execute("SELECT path, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    pts = [p for r in con.execute("SELECT gate_segment FROM legs WHERE camera_id=?", (cam,)) if r[0]
           for p in json.loads(r[0])]
    hull = cv2.convexHull(np.asarray(pts, dtype=np.float32)).reshape(-1, 2)
    from boxmot.reid.core.reid import ReID
    models = {"osnet": ReID(weights="osnet_x0_25_msmt17.pt", device="cuda:0").model,
              "clip_veri": ReID(weights="clip_veri.pt", device="cuda:0").model,
              "dinov2": Dino()}
    verdicts = []
    for v in variants:
        smp = samples(proj, cam, v, n_same, float(fps), hull)
        score(smp, embed(vpath, smp, models))
        Path(f"runs/v2_week1/probe_vehicle_reid_{proj}_{cam}_{v}.json").write_text(json.dumps(
            [{k: x for k, x in s.items() if k not in ("refs", "take")} for s in smp]))
        verdicts.append(report(v, smp))
    for name in MODELS:
        print(f"GATE {name}: {'PASS' if all(r[name] for r in verdicts) else 'FAIL'} "
              f"(AUC >= 0.95 and >= 50% caught at 1% refused, every window)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
