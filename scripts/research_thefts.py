"""Thefts: where does a tracker id move from one vehicle to another? (Phase B,
2026-09-13, plan sure-plan-it-out-toasty-snowflake.md; operator: "instrument
and film first").

Truth for "one vehicle" = a yardstick chain (research_tracker_break.py
extract_all: deduped detections greedily linked, >= 15 hits, >= 120 px). Every
dump row is labelled with the chain whose box it overlaps best (IoU >= 0.3).
A SWITCH = one track id on chain A for >= 5 frames, then on chain B for >= 5
frames. Each switch is sorted by what the two vehicles were doing:
  THEFT        A goes on being detected after the switch AND B was detected
               before it (two vehicles in view: the id left a car still there
               for a car already there) - the plan's definition;
  EMERGENCE    A goes on, B only appears at the switch (the id jumps to a car
               coming into view: hand-off reel clip 6's kind);
  A ENDS       A stops being detected, B was already there (the id outlives
               its car and takes a neighbour);
  CHAIN SEAM   neither (the yardstick split one car into two chains - not a
               tracker event).
Each switch also carries: the overlap of A's and B's boxes around the switch
(the stacked / merging ambiguity the operator ruled a YARDSTICK error in
hand-off clips 1 and 3 - reported, not excluded, because the ruled theft in
back-fill clip 5b happened under heavy overlap), whether the two ids SWAPPED
cars (the id that had B then takes A), the frames the id went unseen, and -
from an in-process run of the same tracker with the match log on - the stage
that made the match onto B (s1 / s2 / s25 / unconf / confirm_pos) with the
track's state and lost age.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_thefts.py PROJ CAM VARIANT [--no-stages]
Writes runs/v2_week1/thefts_<proj>_<cam>_<variant>.json
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
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from research_tracker_break import base_variant  # noqa: E402

LABEL_IOU = 0.3
MIN_RUN = 5            # frames on each vehicle
CONT_S = 2.0           # "goes on" / "was there": hits within this many seconds
CONT_HITS = 3


def iou_mat(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU between tlbr rows of a (M,4) and b (K,4)."""
    ix = np.clip(np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None)
    iy = np.clip(np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None)
    inter = ix * iy
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    bb = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(aa[:, None] + bb[None, :] - inter, 1e-6)


def tlbr(r) -> np.ndarray:
    return np.array([r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2], dtype=np.float64)


def stage_run(proj: str, cam: int, variant: str, meta: dict, frame_size) -> tuple[dict, dict]:
    """The dump's tracker, in process, match log on. Returns
    {frame: [(tlbr, in-process id)]} and {(frame, id): log record}."""
    from backend.services.detection_cache import DetectionCacheReader
    from backend.services.pipeline import _class_agnostic_nms
    from backend.services.tracker import create_tracker_backend
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    pq = parquet_path(proj, cam, chash, variant)
    kw = {}
    if meta.get("lost_buffer") is not None:
        kw["lost_track_buffer"] = int(meta["lost_buffer"])
    be = create_tracker_backend("bytetrack", track_activation_threshold=float(meta["activation"]),
                                minimum_matching_threshold=float(meta["match"]), frame_rate=int(fps),
                                frame_size=frame_size, collect_backfill=True, **kw)
    be.byte_track.match_log = []
    nms, buf = meta.get("nms_iou"), float(meta.get("bbox_buffer") or 1.0)
    assert buf == 1.0, "research_thefts: bbox buffer != 1 not reproduced"
    f0, f1 = meta["frames"]
    by_box: dict = defaultdict(list)
    it = DetectionCacheReader(pq).iter_frames()
    nxt = next(it, None)
    for f in range(f0, f1):
        while nxt is not None and nxt[0] < f:
            nxt = next(it, None)
        dets = []
        if nxt is not None and nxt[0] == f:
            dets = nxt[1]; nxt = next(it, None)
        if nms is not None and len(dets) > 1:
            dets = _class_agnostic_nms(dets, float(nms))
        for r in be.update(dets, f):
            by_box[f].append((r["bbox"], r["track_id"]))
        be.pop_backfill()
    log = {(rec[0], rec[1]): rec for rec in be.byte_track.match_log}
    return by_box, log


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    stages = "--no-stages" not in sys.argv
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps, vw, vh = con.execute("SELECT content_hash, fps, width, height FROM videos WHERE camera_id=?",
                                     (cam,)).fetchone()
    fps = float(fps)
    d = tracks_dir(parquet_path(proj, cam, chash, variant))
    meta = json.loads((d / "meta.json").read_text())
    rows = np.array(load_dump(d), dtype=np.float64, copy=True)
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    print(f"{proj} cam{cam} {variant}: {len(rows)} dump rows, {len(np.unique(rows[:, 0]))} tracks; "
          f"yardstick {len(veh)} vehicles")

    # chain boxes per frame, and each chain's hit frames
    cf = defaultdict(list)
    hits = []
    for vi, v in enumerate(veh):
        hits.append(np.asarray([h[0] for h in v], dtype=np.int64))
        for h in v:
            cf[int(h[0])].append((vi, h[1], h[2], h[3], h[4]))
    cbox = {vi: {int(h[0]): np.asarray(h[1:5], dtype=np.float64) for h in v} for vi, v in enumerate(veh)}

    # label every dump row with its chain
    rows = rows[np.argsort(rows[:, 1], kind="stable")]
    lab = np.full(len(rows), -1, dtype=np.int64)
    uf, s_ = np.unique(rows[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows))
    for f, a, b in zip(uf.astype(int), s_, e_):
        c = cf.get(f)
        if not c:
            continue
        R = np.stack([tlbr(r) for r in rows[a:b]])
        C = np.asarray([x[1:] for x in c], dtype=np.float64)
        m = iou_mat(R, C)
        k = m.argmax(axis=1)
        ok = m[np.arange(len(k)), k] >= LABEL_IOU
        lab[a:b][ok] = np.asarray([c[j][0] for j in k[ok]])
    # (chain, frame) -> track ids on it
    on_chain = defaultdict(set)
    for r, l in zip(rows, lab):
        if l >= 0:
            on_chain[(int(l), int(r[1]))].add(int(r[0]))

    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rt, lt = rows[order], lab[order]
    ut, st_ = np.unique(rt[:, 0], return_index=True); en_ = np.append(st_[1:], len(rt))
    cont = int(round(CONT_S * fps))
    events = []
    for tid, a, b in zip(ut.astype(int), st_, en_):
        seq = [(int(rt[i, 1]), int(lt[i]), i) for i in range(a, b) if lt[i] >= 0]
        runs = []          # [chain, first f, last f, n frames, row index of first, row index of last]
        for f, l, i in seq:
            if runs and runs[-1][0] == l:
                runs[-1][2] = f; runs[-1][3] += 1; runs[-1][5] = i
            else:
                runs.append([l, f, f, 1, i, i])
        for r1, r2 in zip(runs, runs[1:]):
            if r1[3] < MIN_RUN or r2[3] < MIN_RUN:
                continue
            A, B, fa, fb = int(r1[0]), int(r2[0]), int(r1[2]), int(r2[1])
            a_after = int(((hits[A] >= fb) & (hits[A] <= fb + cont)).sum())
            b_before = int(((hits[B] <= fa) & (hits[B] >= fa - cont)).sum())
            kind = ("THEFT" if a_after >= CONT_HITS and b_before >= CONT_HITS else
                    "EMERGENCE" if a_after >= CONT_HITS else
                    "A ENDS" if b_before >= CONT_HITS else "CHAIN SEAM")
            ov = 0.0
            for f in range(fa - 2, fb + 3):
                ba, bb = cbox[A].get(f), cbox[B].get(f)
                if ba is not None and bb is not None:
                    ov = max(ov, float(iou_mat(ba[None], bb[None])[0, 0]))
            # swap: an id that was on B before the switch is on A after it
            before_b = set().union(*(on_chain.get((B, f), set()) for f in range(fa - cont, fa + 1))) - {tid}
            after_a = set().union(*(on_chain.get((A, f), set()) for f in range(fb, fb + cont + 1))) - {tid}
            swap = sorted(before_b & after_a)
            ra, rb = rt[r1[5]], rt[r2[4]]
            events.append({"track": tid, "A": A, "B": B, "f_last_A": fa, "f_first_B": fb,
                           "unseen": int(fb - fa - 1), "kind": kind, "iou_ab": round(ov, 2),
                           "swap_with": swap, "a_after": a_after, "b_before": b_before,
                           "x": float(rb[2]), "y": float(rb[3]), "w": float(rb[4]),
                           "box_B": [float(v) for v in tlbr(rb)], "box_A": [float(v) for v in tlbr(ra)]})

    f_lo, f_hi = float(rows[:, 1].min()) + 60 * fps, float(rows[:, 1].max()) - 60 * fps
    for e in events:
        e["clear_of_ends"] = bool(f_lo <= e["f_first_B"] <= f_hi)

    if stages:
        by_box, log = stage_run(proj, cam, variant, meta, (int(vw), int(vh)) if vw and vh else None)
        found = 0
        n_same = 0
        for e in events:
            # the dump stores cx/cy/w/h as float32: find the in-process box by overlap
            pid = None
            cands = by_box.get(e["f_first_B"], [])
            if cands:
                m = iou_mat(np.asarray([e["box_B"]]), np.asarray([c[0] for c in cands]))[0]
                j = int(m.argmax())
                if m[j] > 0.95:
                    pid = cands[j][1]
                    n_same += 1
            rec = log.get((e["f_first_B"], pid)) if pid is not None else None
            if rec is None:
                e["stage"] = "back-fill/none" if pid is None else "no match (Kalman coast)"
                continue
            found += 1
            e["stage"] = rec[2]; e["was_lost"] = rec[3]; e["age"] = rec[4]
            e["iou_pred_det"] = round(float(iou_mat(np.asarray([rec[5]]), np.asarray([rec[6]]))[0, 0]), 2)
            e["det_conf"] = round(rec[7], 2)
        print(f"  in-process tracker reproduced the dump's box for {n_same} of {len(events)} switches; "
              f"stage found for {found}")

    kinds = Counter(e["kind"] for e in events)
    print(f"  switches (>= {MIN_RUN} frames on each vehicle): {len(events)}  " +
          "  ".join(f"{k} {kinds[k]}" for k in ("THEFT", "EMERGENCE", "A ENDS", "CHAIN SEAM")))
    for k in ("THEFT", "EMERGENCE", "A ENDS"):
        sub = [e for e in events if e["kind"] == k]
        if not sub:
            continue
        ovb = Counter("<=0.2" if e["iou_ab"] <= 0.2 else ("0.2-0.5" if e["iou_ab"] <= 0.5 else ">0.5") for e in sub)
        print(f"  {k}: {len(sub)}; A/B box overlap at the switch " +
              "  ".join(f"{b} {ovb[b]}" for b in ("<=0.2", "0.2-0.5", ">0.5")) +
              f"; swaps {sum(1 for e in sub if e['swap_with'])}; unseen frames median "
              f"{np.median([e['unseen'] for e in sub]):.0f}; box width median {np.median([e['w'] for e in sub]):.0f} px")
        if stages:
            st = Counter((e.get("stage"), "lost" if e.get("was_lost") else "tracked") for e in sub)
            print("     stage onto B: " + "; ".join(f"{s}/{t} {n}" for (s, t), n in st.most_common()))
            lost = [e["age"] for e in sub if e.get("was_lost")]
            if lost:
                print(f"     lost age when it took B: median {np.median(lost):.0f} f, "
                      f"<=5 f {sum(1 for x in lost if x <= 5)}, > 5 f {sum(1 for x in lost if x > 5)}")
            ip = [e["iou_pred_det"] for e in sub if "iou_pred_det" in e]
            if ip:
                print(f"     IoU(predicted box, B's box) median {np.median(ip):.2f}; B conf median "
                      f"{np.median([e['det_conf'] for e in sub if 'det_conf' in e]):.2f}")
        xs = [e["x"] for e in sub]
        print("     where (x of B's box): " + "  ".join(
            f"{lo}-{lo + 128}:{sum(1 for x in xs if lo <= x < lo + 128)}" for lo in range(0, 640, 128)))
    out = Path(f"runs/v2_week1/thefts_{proj}_{cam}_{variant}.json")
    out.write_text(json.dumps(events, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
