"""Position recovery (stage 2.5) and the neighbour's box: the fix candidate from
the theft reel (Phase B, ruled 2026-09-13/15: the three real thefts were ALL
position recoveries onto a weak box of a NEIGHBOUR vehicle; the three ordinary-
stage matches filmed were all the yardstick's own errors).

For every s25 match of an in-process run (research_thefts.stage_run, match log
on) this measures how much the taken box overlaps the boxes the OTHER tracks
took this frame by the ordinary stages (s1 / s2 / confirm_pos / birth) - "held"
boxes - and sorts the match by the yardstick chains: SAME (the box is on the
chain the id was on), OTHER (a different chain that goes on being detected:
the id left its car for a neighbour = theft), SEAM/EMERGE (a different chain,
the old one gone), NONE (unlabelled). If the thefts sit under high overlap with
a held box and the good recoveries do not, a "held-box guard" in stage 2.5
(refuse a box that overlaps a box already taken this frame) is the fix, and
this table gives its threshold and its cost.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_recovery_guard.py PROJ CAM VARIANT
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402
from research_thefts import iou_mat, stage_run, LABEL_IOU  # noqa: E402
from research_tracker_break import base_variant  # noqa: E402

CONT_S = 2.0
CONT_HITS = 3
BINS = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.01]


def coverage(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """share of each a box (M,4) inside each b box (K,4)."""
    ix = np.clip(np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None)
    iy = np.clip(np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    return ix * iy / np.maximum(aa[:, None], 1e-6)


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps, vw, vh = con.execute("SELECT content_hash, fps, width, height FROM videos WHERE camera_id=?",
                                     (cam,)).fetchone()
    fps = float(fps)
    d = tracks_dir(parquet_path(proj, cam, chash, variant))
    meta = json.loads((d / "meta.json").read_text())
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    cf = defaultdict(list)
    hits = []
    for vi, v in enumerate(veh):
        hits.append(np.asarray([h[0] for h in v], dtype=np.int64))
        for h in v:
            cf[int(h[0])].append((vi, h[1], h[2], h[3], h[4]))

    extra = {"claim": []}
    by_box, log = stage_run(proj, cam, variant, meta, (int(vw), int(vh)) if vw and vh else None, extra)
    claim = {(c[0], c[1]): c for c in extra["claim"]}
    recs = sorted(log.values(), key=lambda r: (r[0], r[1]))
    by_frame = defaultdict(list)
    for r in recs:
        by_frame[r[0]].append(r)

    def chain_of(f: int, box) -> int:
        c = cf.get(f)
        if not c:
            return -1
        m = iou_mat(np.asarray([box], dtype=np.float64), np.asarray([x[1:] for x in c], dtype=np.float64))[0]
        j = int(m.argmax())
        return c[j][0] if m[j] >= LABEL_IOU else -1

    # each in-process id's chain per frame (from its output boxes)
    id_chain: dict = defaultdict(dict)
    for f, lst in by_box.items():
        for box, tid in lst:
            id_chain[tid][f] = chain_of(f, box)

    cont = int(round(CONT_S * fps))
    out = []
    for r in recs:
        f, tid, stage, was_lost, age, pred, det, conf = r[:8]
        if stage != "s25":
            continue
        new = chain_of(f, det)
        held_recs = [x for x in by_frame[f] if x[1] != tid and x[2] != "s25"]
        held = [x[6] for x in held_recs]
        ov_iou_nb = 0.0
        if held:
            H = np.asarray(held, dtype=np.float64)
            D = np.asarray([det], dtype=np.float64)
            m = iou_mat(D, H)[0]
            ov_iou = float(m.max())
            ov_cov = float(coverage(D, H).max())
            # the same overlap counting only boxes held by an id on ANOTHER chain
            # (a twin id on this id's own car is not a neighbour)
            nb = [i for i, x in enumerate(held_recs) if new < 0 or id_chain.get(x[1], {}).get(f, -2) != new]
            ov_iou_nb = float(m[nb].max()) if nb else 0.0
        else:
            ov_iou = ov_cov = 0.0
        prev = -1
        hist = id_chain.get(tid, {})
        for g in range(f - 1, f - cont - 1, -1):
            c = hist.get(g, -1)
            if c >= 0:
                prev = c
                break
        if new < 0 or prev < 0:
            kind = "NONE"
        elif new == prev:
            kind = "SAME"
        else:
            a_after = int(((hits[prev] >= f) & (hits[prev] <= f + cont)).sum())
            kind = "OTHER" if a_after >= CONT_HITS else "SEAM/EMERGE"
        # the finer kind (research_thefts' switch kinds): was the new car there before?
        kind2 = kind
        if kind in ("OTHER", "SEAM/EMERGE"):
            b_before = int(((hits[new] < f) & (hits[new] >= f - cont)).sum())
            if kind == "OTHER":
                kind2 = "THEFT" if b_before >= CONT_HITS else "EMERGENCE"
            else:
                kind2 = "A ENDS" if b_before >= CONT_HITS else "SEAM"
        cl = claim.get((f, tid))
        # where the NEIGHBOURS were last frame (their output boxes at f-1), and
        # where this id itself was: the jump's direction against the prediction
        prev_boxes = [(b, t) for b, t in by_box.get(f - 1, []) if t != tid]
        ov_prev = 0.0
        if prev_boxes:
            ov_prev = float(iou_mat(np.asarray([det], dtype=np.float64),
                                    np.asarray([b for b, _ in prev_boxes], dtype=np.float64)).max())
        own_prev = next((b for b, t in by_box.get(f - 1, []) if t == tid), None)
        c_det = ((det[0] + det[2]) / 2, (det[1] + det[3]) / 2)
        c_pred = ((pred[0] + pred[2]) / 2, (pred[1] + pred[3]) / 2)
        wmax = max(det[2] - det[0], pred[2] - pred[0], 1e-6)
        cost_pred = float(np.hypot(c_det[0] - c_pred[0], c_det[1] - c_pred[1]) / wmax)
        angle = None
        jump = None
        if own_prev is not None:
            c_own = ((own_prev[0] + own_prev[2]) / 2, (own_prev[1] + own_prev[3]) / 2)
            v_pred = (c_pred[0] - c_own[0], c_pred[1] - c_own[1])
            v_det = (c_det[0] - c_own[0], c_det[1] - c_own[1])
            jump = float(np.hypot(*v_det) / max(own_prev[2] - own_prev[0], 1e-6))
            n1, n2 = np.hypot(*v_pred), np.hypot(*v_det)
            if n1 > 0.5 and n2 > 0.5:
                angle = float(np.degrees(np.arccos(np.clip((v_pred[0] * v_det[0] + v_pred[1] * v_det[1]) / (n1 * n2), -1, 1))))
        # did the id's own car (chain prev) still have a box this frame, and was it taken?
        own_box_free = None
        if prev >= 0:
            ab = next((np.asarray(x[1:], dtype=np.float64) for x in cf.get(f, []) if x[0] == prev), None)
            if ab is not None:
                taken = [x[6] for x in by_frame[f] if x[1] != tid]
                own_box_free = bool(not taken or float(iou_mat(ab[None], np.asarray(taken, dtype=np.float64)).max()) < 0.5)
        out.append({"f": int(f), "id": int(tid), "lost": bool(was_lost), "age": int(age),
                    "conf": round(float(conf), 2), "kind": kind, "ov_iou": round(ov_iou, 3),
                    "ov_cov": round(ov_cov, 3), "w": round(float(det[2] - det[0]), 1),
                    "ov_prev": round(ov_prev, 3), "cost_pred": round(cost_pred, 3),
                    "jump": None if jump is None else round(jump, 3),
                    "angle": None if angle is None else round(angle, 1),
                    "own_box_free": own_box_free, "prev": int(prev), "new": int(new),
                    "ov_iou_nb": round(ov_iou_nb, 3), "kind2": kind2,
                    "u_iou": None if cl is None else round(cl[4], 3),
                    "u_fused": None if cl is None else round(cl[5], 3),
                    "u_birth": None if cl is None else round(cl[7], 3),
                    "t_iou": None if cl is None else round(cl[8], 3),
                    "t_len": None if cl is None else int(cl[9]),
                    "t_birth": None if cl is None else round(cl[10], 3)})

    print(f"{proj} cam{cam} {variant}: {len(out)} position recoveries "
          f"({sum(1 for o in out if o['lost'])} of lost ids); yardstick {len(veh)} vehicles")
    kinds = Counter(o["kind"] for o in out)
    print("  by chain: " + "  ".join(f"{k} {kinds[k]}" for k in ("SAME", "OTHER", "SEAM/EMERGE", "NONE")))
    for key, name in (("ov_iou", "max IoU with a box taken this frame by another id"),
                      ("ov_cov", "max share of the box inside another id's box")):
        print(f"  {name}:")
        print("     bin      " + "".join(f"{lo:>6.1f}" for lo in BINS[:-1]))
        for k in ("SAME", "OTHER", "SEAM/EMERGE", "NONE"):
            sub = [o[key] for o in out if o["kind"] == k]
            if not sub:
                continue
            h, _ = np.histogram(sub, bins=BINS)
            print(f"     {k:<12}" + "".join(f"{n:>6d}" for n in h) + f"   n={len(sub)}")
    # the guard at each threshold: thefts removed vs good recoveries removed
    print("  held-box guard (refuse the box when IoU with a taken box >= thr): "
          "OTHER refused / SAME refused / NONE refused")
    for thr in (0.2, 0.3, 0.4, 0.5, 0.6, 0.7):
        c = Counter(o["kind"] for o in out if o["ov_iou"] >= thr)
        print(f"     thr {thr:.1f}: {c['OTHER']:>4} / {c['SAME']:>5} / {c['NONE']:>5}   (of {kinds['OTHER']} / {kinds['SAME']} / {kinds['NONE']})")
    print("  same guard by COVERAGE (share of the box inside a taken box >= thr):")
    for thr in (0.3, 0.5, 0.7, 0.9):
        c = Counter(o["kind"] for o in out if o["ov_cov"] >= thr)
        print(f"     thr {thr:.1f}: {c['OTHER']:>4} / {c['SAME']:>5} / {c['NONE']:>5}")
    print("  held-box guard counting only boxes held by an id on ANOTHER chain (twins excluded):")
    for thr in (0.3, 0.4, 0.5, 0.6, 0.7):
        c = Counter(o["kind"] for o in out if o["ov_iou_nb"] >= thr)
        print(f"     thr {thr:.1f}: {c['OTHER']:>4} / {c['SAME']:>5} / {c['NONE']:>5}")
    print("  max IoU with a NEIGHBOUR's box of the previous frame (where the other ids were):")
    print("     bin      " + "".join(f"{lo:>6.1f}" for lo in BINS[:-1]))
    for k in ("SAME", "OTHER", "SEAM/EMERGE", "NONE"):
        sub = [o["ov_prev"] for o in out if o["kind"] == k]
        if sub:
            h, _ = np.histogram(sub, bins=BINS)
            print(f"     {k:<12}" + "".join(f"{n:>6d}" for n in h) + f"   n={len(sub)}")
    print("  neighbour guard (refuse the box when IoU with a neighbour's previous box >= thr): OTHER / SAME / NONE refused")
    for thr in (0.1, 0.2, 0.3, 0.4, 0.5):
        c = Counter(o["kind"] for o in out if o["ov_prev"] >= thr)
        print(f"     thr {thr:.1f}: {c['OTHER']:>4} / {c['SAME']:>5} / {c['NONE']:>5}")
    for k in ("OTHER", "SAME"):
        sub = [o for o in out if o["kind"] == k]
        if not sub:
            continue
        ang = [o["angle"] for o in sub if o["angle"] is not None]
        jmp = [o["jump"] for o in sub if o["jump"] is not None]
        cp = [o["cost_pred"] for o in sub]
        free = [o["own_box_free"] for o in sub if o["own_box_free"] is not None]
        print(f"  {k}: cost from the prediction median {np.median(cp):.2f} (>0.5: {sum(1 for c in cp if c > 0.5)}); "
              f"jump from the last box median {np.median(jmp) if jmp else float('nan'):.2f} widths; "
              f"angle vs prediction median {np.median(ang) if ang else float('nan'):.0f} deg (>60: {sum(1 for a in ang if a > 60)} of {len(ang)}); "
              f"own car's box present and free this frame: {sum(1 for x in free if x)} of {len(free)} known")
    # conf of the taken box, thefts vs good
    for k in ("OTHER", "SAME"):
        sub = [o["conf"] for o in out if o["kind"] == k]
        if sub:
            print(f"  {k}: taken-box conf median {np.median(sub):.2f}, <0.35 {sum(1 for c in sub if c < 0.35)} of {len(sub)}")
    claim_table(out, fps)
    p = Path(f"runs/v2_week1/recovery_guard_{proj}_{cam}_{variant}.json")
    p.write_text(json.dumps(out))
    print(f"  -> {p}")
    return 0


KINDS2 = ("SAME", "EMERGENCE", "A ENDS", "THEFT", "SEAM", "NONE")
UNCONF_CLAIM = 0.3      # the library's unconfirmed pass: linear_assignment(fused distance, thresh=0.7)
TENT_CLAIM = 0.2        # the tentatives' position rule: TRACKER_RECOVERY_MIN_IOU


def claim_table(out: list, fps: float) -> None:
    """The newborn-claim census (plan 2026-10-09, Step 1): for recoveries of
    LOST tracks, by the finer kind - lost age, and how many each candidate
    rule would refuse (N1 newborn claim, N2 + tentatives; each excepting a
    claimant born on the lost track's own last-seen box)."""
    lost = [o for o in out if o["lost"] and o.get("u_iou") is not None]
    print(f"  NEWBORN-CLAIM CENSUS: {len(lost)} recoveries of LOST tracks (fps {fps:g})")
    ages = (1, 2, 3, 5, 8, 12, 10 ** 6)
    print("     lost age (frames) <=" + "".join(f"{a if a < 10 ** 6 else 'more':>6}" for a in ages))
    for k in KINDS2:
        sub = [o["age"] for o in lost if o["kind2"] == k]
        if not sub:
            continue
        h, lo = [], 0
        for a in ages:
            h.append(sum(1 for x in sub if lo < x <= a)); lo = a
        print(f"     {k:<12}        " + "".join(f"{n:>6d}" for n in h) + f"   n={len(sub)}  median {np.median(sub):.0f} f")
    rules = {
        "newborn claims (no exception)": lambda o: o["u_fused"] >= UNCONF_CLAIM,
        "N1 newborn claims, born off the lost box": lambda o: o["u_fused"] >= UNCONF_CLAIM and o["u_birth"] <= 0.0,
        "tentative claims (no exception)": lambda o: o["t_iou"] >= TENT_CLAIM,
        "N2 = N1 or tentative born off the lost box": lambda o: (
            (o["u_fused"] >= UNCONF_CLAIM and o["u_birth"] <= 0.0) or (o["t_iou"] >= TENT_CLAIM and o["t_birth"] <= 0.0)),
    }
    print("     rule refuses:  " + "  ".join(f"{k:>10}" for k in KINDS2) + "   wrong/SAME")
    for name, fn in rules.items():
        c = Counter(o["kind2"] for o in lost if fn(o))
        wrong = c["EMERGENCE"] + c["A ENDS"] + c["THEFT"]
        ratio = wrong / c["SAME"] if c["SAME"] else float("inf")
        print(f"     {name}")
        print("                    " + "  ".join(f"{c[k]:>10d}" for k in KINDS2) + f"   {wrong}/{c['SAME']} = {ratio:.2f}")
    tot = Counter(o["kind2"] for o in lost)
    print("     (of)            " + "  ".join(f"{tot[k]:>10d}" for k in KINDS2))


if __name__ == "__main__":
    sys.exit(main())
