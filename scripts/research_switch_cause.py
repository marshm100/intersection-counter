"""Measurement rd1 (2026-10-11): why does the tracker's prediction leave a car it can still see?
Declared in docs/plan_basis_2026-09-11.md "MEASUREMENT rd1 DECLARED".

Step T1 found ~90% of cam2's wrong switches start where motion was CONFIDENT, and in 60-65% the abandoned car A is
still detected at the switch frame. This re-runs the dump's tracker in process (research_breaks.run: match + miss
logs, the tracker's real inputs after NMS / dedup) and gives every census wrong switch (research_thefts.py:
THEFT / EMERGENCE / A ENDS; track T leaves chain A after f_last_A and lands on chain B at f_first_B) ONE cause
at the LEAVE frame f_last_A + 1 (T found in process by box_A at f_last_A), the first that applies:
  A UNDETECTED       no A yardstick hit at the switch frame
  A NOT IN INPUT     A's hit exists but its box never reached the tracker (conf <= 0.10, NMS, input dedup)
  A TAKEN            another id took A's box that frame: swap (the taker came from B) / twin (the taker was
                       already on A) / new, lost or elsewhere
  (cross-cut)        MERGED: the box T took holds >= 70% of A's box and is >= 1.5x its area - one box over two cars
  PRED OFF A         A's box free but IoU(T's prediction, A) < OFF_IOU; sub-cause over the last 1 s:
                       coasting (T unmatched >= 2 of the last 5 frames) / dragged (T adopted a box not on A, or
                       nearer B than A) / size jump (A's width vs the prediction > 1.5x) / velocity (the rest)
  A FREE ON PRED, T TOOK NOTHING   A's box free and on the prediction, but T matched nothing (a gate refused it)
  PRED ON A, B WON   stage order (A's box weak - s2 pool - and T took B in s1) / stacked (IoU(A, B) >= 0.3) / other
  UNCLEAR            T not found in process (IoU 0.95 on box_B), or T itself took A's box
Diagnostic only. Usage:
  .venv/Scripts/python.exe -X utf8 scripts/research_switch_cause.py PROJ CAM VARIANT [--smoke N]
Writes runs/v2_week1/switch_cause_<proj>_<cam>_<variant>.json and switch_cause_sheet_<...>_<cause>.png
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402
from research_breaks import BOX_MATCH, MAP_IOU, recipe_check, run  # noqa: E402
from research_thefts import iou_mat  # noqa: E402
from research_tracker_break import base_variant  # noqa: E402

WRONG = ("THEFT", "EMERGENCE", "A ENDS")
OFF_IOU = 0.2           # the recovery stage's own minimum overlap
STACK_IOU = 0.3
SIZE_JUMP = 1.5
COAST_LOOK, COAST_MIN = 5, 2
DRAG_S = 1.0
ON_A_IOU = 0.3          # a box T adopted counts as A's when it overlaps A's hit this much
SHEET_N = 12
MERGED_COVER = 0.7      # T's box holds >= 70% of A's box ...
MERGED_AREA = 1.5       # ... and is >= 1.5x its area: one box over two cars
CAUSES = ("A UNDETECTED", "A NOT IN INPUT", "A TAKEN", "PRED OFF A", "A FREE ON PRED, T TOOK NOTHING",
          "PRED ON A, B WON", "UNCLEAR")


def _iou(a, b) -> float:
    return float(iou_mat(np.asarray([a], dtype=np.float64), np.asarray([b], dtype=np.float64))[0, 0])


def _area(b) -> float:
    return max(b[2] - b[0], 0.0) * max(b[3] - b[1], 0.0)


def _cover(a, b) -> float:
    """Share of box a inside box b."""
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix * iy / max(_area(a), 1e-9)


def _centre(b):
    return ((b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0)


def classify(e: dict, ctx: dict) -> dict:
    """One cause (+ sub-cause and measurements) for one census switch."""
    # the LEAVE frame: the first frame after T's last frame on A (f_first_B can be several frames later -
    # EMERGENCE switches spend a median 4-10 frames coasting or on unlabelled boxes in between; rd1 v1
    # classified f_first_B and misread those, 2026-10-11)
    fa = int(e["f_last_A"])
    f = fa + 1
    hits, inputs, by_box = ctx["hits"], ctx["inputs"], ctx["by_box"]
    match, miss, match_by_frame = ctx["match"], ctx["miss"], ctx["match_by_frame"]
    out = {"track": e["track"], "kind": e["kind"], "f": f, "f_first_B": int(e["f_first_B"]),
           "gap": int(e["f_first_B"]) - f, "A": e["A"], "B": e["B"]}
    T = None
    for box, tid in by_box.get(fa, []):
        if _iou(box, e["box_A"]) >= MAP_IOU:
            T = tid
            break
    if T is None:
        return {**out, "cause": "UNCLEAR", "sub": "not in process"}
    rec = match.get((f, T))
    mrec = miss.get((f, T))
    if rec is None and mrec is None:
        return {**out, "cause": "UNCLEAR", "sub": "T removed at the leave frame"}
    if rec is not None:
        hb = hits[e["B"]].get(f)
        took_on = ("B" if hb is not None and _iou(rec[6], hb) >= ON_A_IOU else "not B (unlabelled / other)")
        out.update(T=T, stage=rec[2], pred=list(rec[5]), took=list(rec[6]), took_conf=rec[7], took_on=took_on)
    else:
        out.update(T=T, stage="none: coasted", pred=list(mrec[4]), took_on="nothing")
    a_box = hits[e["A"]].get(f)
    if a_box is None:
        return {**out, "cause": "A UNDETECTED", "sub": ""}
    out["a_box"] = list(a_box)
    inp = inputs.get(f)
    j = -1
    if inp is not None:
        m = iou_mat(np.asarray([a_box], dtype=np.float64), inp[0])[0]
        j = int(m.argmax())
        if m[j] < BOX_MATCH:
            j = -1
    if j < 0 or not inp[2][j]:
        return {**out, "cause": "A NOT IN INPUT", "sub": "absent" if j < 0 else "dropped by dedup",
                "a_conf": float(inp[1][j]) if j >= 0 else None}
    a_conf = float(inp[1][j])
    out["a_conf"] = a_conf
    if rec is not None and _iou(rec[6], a_box) >= BOX_MATCH:
        return {**out, "cause": "UNCLEAR", "sub": "T took A's box"}
    out["merged"] = (rec is not None and _cover(a_box, rec[6]) >= MERGED_COVER
                     and _area(rec[6]) >= MERGED_AREA * _area(a_box))
    for r in match_by_frame.get(f, []):
        if r[1] != T and _iou(r[6], a_box) >= BOX_MATCH:
            # where was the taker the frame before: on B (a swap), already on A (a twin), or elsewhere / new
            prev = match.get((f - 1, r[1]))
            ha, hb = hits[e["A"]].get(f - 1), hits[e["B"]].get(f - 1)
            on_a = _iou(prev[6], ha) if prev is not None and ha is not None else 0.0
            on_b = _iou(prev[6], hb) if prev is not None and hb is not None else 0.0
            origin = ("swap: taker came from B" if on_b >= ON_A_IOU and on_b > on_a else
                      "twin: taker already on A" if on_a >= ON_A_IOU else
                      "taker new / lost / elsewhere")
            extra = {}
            if origin.startswith("twin"):
                # how long both ids sat on A, and which is the younger (the duplicate)
                both = 0
                for g in range(f - 1, int(f - 2 * ctx["fps"]), -1):
                    hg = hits[e["A"]].get(g)
                    mt, mk = match.get((g, T)), match.get((g, r[1]))
                    if hg is None or mt is None or mk is None:
                        continue
                    if _iou(mt[6], hg) >= ON_A_IOU and _iou(mk[6], hg) >= ON_A_IOU:
                        both += 1
                born = ctx["born"]
                extra = {"twin_frames": both, "T_younger": born.get(T, f) > born.get(r[1], f),
                         "twin_iou": round(_iou(match[(f - 1, T)][6], match[(f - 1, r[1])][6]), 3)
                         if (f - 1, T) in match and (f - 1, r[1]) in match else None}
            return {**out, "cause": "A TAKEN", "sub": origin, "taker": r[1], "taker_stage": r[2], **extra}
    pred = rec[5] if rec is not None else mrec[4]
    iou_pa = _iou(pred, a_box)
    pw = max(pred[2] - pred[0], 1.0)
    aw = max(a_box[2] - a_box[0], 1.0)
    pc, ac = _centre(pred), _centre(a_box)
    out.update(iou_pred_a=round(iou_pa, 3), err_w=round(math.hypot(pc[0] - ac[0], pc[1] - ac[1]) / aw, 3),
               width_ratio=round(aw / pw, 3))
    if iou_pa < OFF_IOU:
        fps = ctx["fps"]
        n_coast = sum(1 for g in range(f - COAST_LOOK, f) if (g, T) in miss)
        dragged = 0
        for g in range(int(f - DRAG_S * fps), f):
            r = match.get((g, T))
            if r is None:
                continue
            ha, hb = hits[e["A"]].get(g), hits[e["B"]].get(g)
            on_a = _iou(r[6], ha) if ha is not None else 0.0
            on_b = _iou(r[6], hb) if hb is not None else 0.0
            if on_a < ON_A_IOU or on_b > on_a:
                dragged += 1
        # Kalman speed vs A's observed speed (widths per frame), A's last 0.5 s
        fa = sorted(g for g in hits[e["A"]] if f - fps / 2 <= g <= f)
        a_speed = None
        if len(fa) >= 2:
            c0, c1 = _centre(hits[e["A"]][fa[0]]), _centre(hits[e["A"]][fa[-1]])
            a_speed = math.hypot(c1[0] - c0[0], c1[1] - c0[1]) / max(fa[-1] - fa[0], 1) / aw
        out.update(n_coast=n_coast, dragged_frames=dragged, a_speed_w=a_speed)
        sub = ("coasting" if n_coast >= COAST_MIN else
               "dragged" if dragged >= 1 else
               "size jump" if max(aw / pw, pw / aw) > SIZE_JUMP else "velocity")
        return {**out, "cause": "PRED OFF A", "sub": sub + (" (T took nothing)" if rec is None else "")}
    if rec is None:
        # A's box free and on the prediction, and T took nothing: a gate refused it
        return {**out, "cause": "A FREE ON PRED, T TOOK NOTHING",
                "sub": "A weak (s2 / recovery)" if a_conf <= ctx["activation"] else "A strong"}
    iou_ab = _iou(a_box, rec[6])
    out["iou_a_b"] = round(iou_ab, 3)
    sub = ("stage order" if a_conf <= ctx["activation"] and rec[2] == "s1" else
           "stacked" if iou_ab >= STACK_IOU else "other")
    return {**out, "cause": "PRED ON A, B WON", "sub": sub}


def sheet(res: list[dict], vpath: str, tag: str, cause: str) -> None:
    import cv2
    pick = [r for r in res if r["cause"] == cause and "pred" in r]  # drawn at the LEAVE frame
    if not pick:
        return
    rng = np.random.default_rng(0)
    pick = [pick[i] for i in sorted(rng.choice(len(pick), min(SHEET_N, len(pick)), replace=False))]
    cap = cv2.VideoCapture(vpath)
    tiles = []
    for r in pick:
        cap.set(cv2.CAP_PROP_POS_FRAMES, r["f"])
        ok, img = cap.read()
        if not ok:
            continue
        bs = [b for b in (r.get("pred"), r.get("a_box"), r.get("took")) if b is not None]
        x1 = int(max(0, min(b[0] for b in bs) - 40)); y1 = int(max(0, min(b[1] for b in bs) - 40))
        x2 = int(min(img.shape[1], max(b[2] for b in bs) + 40)); y2 = int(min(img.shape[0], max(b[3] for b in bs) + 40))
        for b, col in ((r.get("a_box"), (0, 255, 0)), (r.get("took"), (0, 0, 255)), (r.get("pred"), (0, 255, 255))):
            if b is not None:
                cv2.rectangle(img, (int(b[0]), int(b[1])), (int(b[2]), int(b[3])), col, 1)
        t = cv2.resize(img[y1:y2, x1:x2], (240, 180), interpolation=cv2.INTER_CUBIC)
        t = cv2.copyMakeBorder(t, 14, 2, 2, 2, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(t, f"f{r['f']} {r['kind']} {r['sub']} {r.get('stage', '')}", (2, 11),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1)
        tiles.append(t)
    cap.release()
    if not tiles:
        return
    while len(tiles) % 4:
        tiles.append(np.full_like(tiles[0], 255))
    grid = np.concatenate([np.concatenate(tiles[i:i + 4], axis=1) for i in range(0, len(tiles), 4)])
    out = Path(f"runs/v2_week1/switch_cause_sheet_{tag}_{cause.replace(' ', '_').replace(',', '')}.png")
    cv2.imwrite(str(out), grid)
    print(f"  sheet -> {out} (green = A's real box, red = the box T took, yellow = T's prediction)")


def main() -> int:
    smoke = int(sys.argv[sys.argv.index("--smoke") + 1]) if "--smoke" in sys.argv else 0
    args = [a for a in sys.argv[1:] if not a.startswith("--") and a != str(smoke)]
    proj, cam, variant = args[0], int(args[1]), args[2]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps, vw, vh, vpath = con.execute(
        "SELECT content_hash, fps, width, height, path FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    meta = json.loads((tracks_dir(parquet_path(proj, cam, chash, variant)) / "meta.json").read_text())
    recipe_check(meta)
    if smoke:
        meta["frames"] = [meta["frames"][0], meta["frames"][0] + smoke]
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    ev = [e for e in json.loads(Path(f"runs/v2_week1/thefts_{proj}_{cam}_{variant}.json").read_text())
          if e["kind"] in WRONG and meta["frames"][0] <= e["f_first_B"] < meta["frames"][1]]
    hits = [{int(h[0]): [float(v) for v in h[1:5]] for h in v} for v in veh]
    inputs, by_box, match, match_by_frame, miss, _, be = run(
        proj, cam, variant, meta, (int(vw), int(vh)) if vw and vh else None)
    born: dict = {}
    for g in sorted(by_box):
        for _, tid in by_box[g]:
            born.setdefault(tid, g)
    ctx = {"born": born, "hits": hits, "inputs": inputs, "by_box": by_box, "match": match, "miss": miss,
           "match_by_frame": match_by_frame, "fps": fps, "activation": float(meta["activation"])}
    res = [classify(e, ctx) for e in ev]
    n = len(res)
    judged = [r for r in res if r["cause"] != "UNCLEAR"]
    nj = max(len(judged), 1)
    print(f"{proj} cam{cam} {variant}: {n} wrong switches; judged {len(judged)} "
          f"(UNCLEAR {n - len(judged)}: {dict(Counter(r['sub'] for r in res if r['cause'] == 'UNCLEAR'))})")
    kinds = ("THEFT", "EMERGENCE", "A ENDS")
    print(f"  {'cause':<34}" + "".join(f"{k:>11}" for k in kinds) + f"{'all':>8}{'of judged':>11}")
    for c in CAUSES:
        sub = [r for r in res if r["cause"] == c]
        if not sub:
            continue
        print(f"  {c:<34}" + "".join(f"{sum(1 for r in sub if r['kind'] == k):>11}" for k in kinds)
              + f"{len(sub):>8}" + (f"{len(sub) / nj:>10.0%}" if c != "UNCLEAR" else ""))
        subs = Counter(r["sub"] for r in sub)
        if c != "UNCLEAR":
            for s, k in subs.most_common():
                print(f"      {s:<30}" + "".join(f"{sum(1 for r in sub if r['sub'] == s and r['kind'] == kk):>11}"
                                              for kk in kinds) + f"{k:>8}" + f"{k / nj:>10.0%}")
    print("  at the leave frame T: " + "; ".join(f"{k} {v}" for k, v in Counter(r.get("took_on", "?") for r in judged).most_common())
          + f"; frames from leaving A to landing on B: median {np.median([r['gap'] for r in res]):.0f}")
    mg = [r for r in judged if r.get("merged")]
    print(f"  across causes: T took a MERGED box (holds >= {MERGED_COVER:.0%} of A, >= {MERGED_AREA}x its area): "
          f"{len(mg)} of {len(judged)} judged ({len(mg) / nj:.0%}); by cause "
          f"{dict(Counter(r['cause'] for r in mg))}")
    tw = [r for r in res if r["sub"].startswith("twin")]
    if tw:
        print(f"  TWIN (two ids on A, T leaves): T is the YOUNGER id in {sum(r['T_younger'] for r in tw)} of {len(tw)}; "
              f"frames both on A in the 2 s before: median {np.median([r['twin_frames'] for r in tw]):.0f}; "
              f"IoU of the two ids' boxes the frame before: median "
              f"{np.median([r['twin_iou'] for r in tw if r['twin_iou'] is not None] or [np.nan]):.2f}")
    off = [r for r in res if r["cause"] == "PRED OFF A"]
    if off:
        print(f"  PRED OFF A medians: prediction-to-A error {np.median([r['err_w'] for r in off]):.2f} widths; "
              f"IoU(pred, A) {np.median([r['iou_pred_a'] for r in off]):.2f}; A width / pred width "
              f"{np.median([r['width_ratio'] for r in off]):.2f}; frames unmatched (last 5) "
              f"{np.median([r['n_coast'] for r in off]):.0f}; A conf {np.median([r['a_conf'] for r in off]):.2f}")
    on = [r for r in res if r["cause"] == "PRED ON A, B WON"]
    if on:
        print(f"  PRED ON A medians: IoU(pred, A) {np.median([r['iou_pred_a'] for r in on]):.2f}; A conf "
              f"{np.median([r['a_conf'] for r in on]):.2f}; T's box conf {np.median([r['took_conf'] for r in on]):.2f}; "
              f"IoU(A, B) {np.median([r['iou_a_b'] for r in on]):.2f}; stages {dict(Counter(r['stage'] for r in on))}")
    tag = f"{proj}_{cam}_{variant}" + ("_smoke" if smoke else "")
    Path(f"runs/v2_week1/switch_cause_{tag}.json").write_text(json.dumps(res, default=float))
    top = Counter(r["cause"] for r in judged).most_common(2)
    for c, _ in top:
        sheet(res, vpath, tag, c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
