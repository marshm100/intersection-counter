"""INSIDE THE BOX, CAR BY CAR (2026-10-15, operator: "double counts are cars we miss ... tracking
still sucks ... ignore noise from tracking outside of the intersection and keep signal that is found
inside the intersection"). For every labelled full journey, only the stretch from its ENTRY click to
its EXIT click (the car inside the intersection), against the raw detector boxes and the dump:
  ONE TRACK       the same track id is under the entry click and the exit click
  NO TRACK IN/OUT no track under a click: DETECTED (a detector box holds the click - the tracker
                  dropped it) or NOT DETECTED (no box there - the detector missed it)
  BROKEN          two ids; at the break (entry track's death to exit track's birth):
                    SWAP      the entry id is still alive after the car's exit click: it left with
                              ANOTHER car (identity switch between neighbours)
                    HANDOFF   the exit track was born before the entry track died (two ids at once)
                    GAP-DET   the car is detected through the gap (>= 80% of frames): tracker's fault
                    GAP-MISS  the detector loses the car for part of the gap: detector's fault
                  plus how many other ids the car wore between, and where the break sits
                  (share of the way from the entry click to the exit click)
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_inside_box.py [STEM] [--list]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402

DET_PAD = 0.15        # a click "is in" a detector box padded by this share of its size
NEAR_W = 1.0          # a detection is the car's if its centre is within this many box widths
DETECTED = 0.8


def click_detected(det: dict, f: int, x: float, y: float) -> bool:
    for df in (-1, 0, 1):
        d = det.get(f + df)
        if d is None:
            continue
        w, h = d[:, 2] - d[:, 0], d[:, 3] - d[:, 1]
        if np.any((x >= d[:, 0] - DET_PAD * w) & (x <= d[:, 2] + DET_PAD * w)
                  & (y >= d[:, 1] - DET_PAD * h) & (y <= d[:, 3] + DET_PAD * h)):
            return True
    return False


def main() -> int:
    stem = next((a for a in sys.argv[1:] if not a.startswith("--")), "mm1")
    show = "--list" in sys.argv
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    tot = defaultdict(Counter)
    where = defaultdict(list)
    for clip in list_clips(PROJ):
        labels = list_labels(PROJ, clip["clip_id"])
        if not labels:
            continue
        cam = clip["camera_id"]
        window = "study_" + clip["clip_id"].split("_")[1]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        fps = float(fps)
        db, rows = locate(stem, {}, cam, window, chash)
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        byf = je.index_rows(rows, f_lo - je.SEARCH_FRAMES, f_hi + je.SEARCH_FRAMES)
        dups = je.duplicate_labels(labels, fps, byf)
        labs = [lb for lb in labels if lb["label_id"] not in dups
                and lb.get("entry_frame") is not None and lb.get("exit_frame") is not None]
        ein, eout = je._assign_clicks(labs, rows, byf, fps)
        tbl = pq.read_table(parquet_path(PROJ, cam, chash, window),
                            filters=[("frame_idx", ">=", f_lo - 400), ("frame_idx", "<=", f_hi + 400)]).to_pandas()
        det = {int(f): g[["bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"]].to_numpy()
               for f, g in tbl.groupby("frame_idx")}
        win = rows[(rows[:, 1] >= f_lo - 400) & (rows[:, 1] <= f_hi + 400)]
        tr = {int(t): win[win[:, 0] == t] for t in np.unique(win[:, 0])}
        T = tot[cam]
        for lb in labs:
            lid = lb["label_id"]
            fin, fout = int(lb["entry_frame"]), int(lb["exit_frame"])
            tin, tout = ein.get(lid), eout.get(lid)
            T["cars"] += 1
            if tin is None or tout is None:
                for side, t, f, x, y in (("IN", tin, fin, lb["entry_x"], lb["entry_y"]),
                                         ("OUT", tout, fout, lb["exit_x"], lb["exit_y"])):
                    if t is None:
                        k = f"NO TRACK {side}: " + ("DETECTED" if click_detected(det, f, x, y) else "NOT DETECTED")
                        T[k] += 1
                        if show:
                            print(f"  cam{cam} {clip['clip_id']} label {lid}: {k}")
                continue
            if tin == tout:
                T["ONE TRACK"] += 1
                continue
            a, b = tr.get(tin), tr.get(tout)
            if a is None or b is None or not len(a) or not len(b):
                T["BROKEN (ids outside window)"] += 1
                continue
            d0, b0 = int(a[-1, 1]), int(b[0, 1])
            # ids the car wore between: tracks living inside (d0, b0) near the straight path
            between = 0
            if b0 > d0:
                p0, p1 = a[-1, 2:4], b[0, 2:4]
                wref = max(float(np.median(np.r_[a[-5:, 4], b[:5, 4]])), 1.0)
                hit = n = 0
                for f in range(d0 + 1, b0):
                    s = (f - d0) / (b0 - d0)
                    c = p0 + s * (p1 - p0)
                    n += 1
                    d = det.get(f)
                    if d is not None and len(d):
                        cx, cy = (d[:, 0] + d[:, 2]) / 2, (d[:, 1] + d[:, 3]) / 2
                        hit += bool(np.any(np.hypot(cx - c[0], cy - c[1]) <= NEAR_W * wref))
                for t, r in tr.items():
                    if t in (tin, tout) or r[0, 1] <= d0 or r[-1, 1] >= b0:
                        continue
                    mid = r[len(r) // 2]
                    s = (mid[1] - d0) / (b0 - d0)
                    if np.hypot(*(mid[2:4] - (p0 + s * (p1 - p0)))) <= 1.5 * wref:
                        between += 1
                cov = hit / max(n, 1)
                k = "BROKEN GAP-DET" if cov >= DETECTED else "BROKEN GAP-MISS"
                gap = b0 - d0
            elif d0 > fout + je.SEARCH_FRAMES:
                # the entry id outlives the car's exit: it went on with ANOTHER car (identity switch)
                k, cov, gap = "BROKEN SWAP", 1.0, b0 - d0
            else:
                k, cov, gap = "BROKEN HANDOFF", 1.0, b0 - d0
            T[k] += 1
            frac = (d0 - fin) / max(fout - fin, 1)
            where[k].append(frac)
            if show:
                print(f"  cam{cam} {clip['clip_id']} label {lid}: {k} t{tin}->t{tout} gap {gap:+d}f "
                      f"det {cov:.0%} ids between {between} break at {frac:.0%} of the way")
    print(f"\nINSIDE THE BOX ({stem}), labelled full journeys, dev + held-out")
    keys = ["ONE TRACK", "BROKEN SWAP", "BROKEN HANDOFF", "BROKEN GAP-DET", "BROKEN GAP-MISS",
            "NO TRACK IN: DETECTED", "NO TRACK IN: NOT DETECTED",
            "NO TRACK OUT: DETECTED", "NO TRACK OUT: NOT DETECTED", "BROKEN (ids outside window)"]
    allc = Counter()
    for cam in sorted(tot):
        allc.update(tot[cam])
        print(f"  cam{cam}: cars {tot[cam]['cars']:4}  " + "  ".join(
            f"{k} {tot[cam][k]}" for k in keys if tot[cam][k]))
    print(f"  ALL : cars {allc['cars']:4}")
    for k in keys:
        if allc[k]:
            print(f"     {k:28} {allc[k]:4}  ({100 * allc[k] / allc['cars']:.1f}%)")
    for k, v in where.items():
        print(f"  {k}: break at median {np.median(v):.0%} of the way from entry to exit "
              f"(quartiles {np.percentile(v, 25):.0%} / {np.percentile(v, 75):.0%})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
