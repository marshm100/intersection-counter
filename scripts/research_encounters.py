"""ENCOUNTERS, JUDGED BY WHAT HAPPENS AFTER (2026-10-15). research_break_mechanism: 46 of the 64 labelled
cars broken inside the box are ids SWAPPED between neighbours where the two cars meet (side by side or one
hiding the other) - the detector still draws both boxes; the tracker, frame by frame, can't look ahead.
Offline we can. For every ENCOUNTER of two tracks that labelled cars ride (centres within MEET_W box widths
for >= 1 frame), compare the motion of the two pairings across it:
  keep  = A-before -> A-after, B-before -> B-after   (what the tracker did)
  swap  = A-before -> B-after, B-before -> A-after
cost = how far each "after" piece's first positions are from the "before" piece's constant-velocity
prediction (in box widths), plus the change in velocity. Truth from the labels: SWAP if a car entered on
one id and left on the other around this encounter; KEEP if each id carries one labelled car through it.
Gate for a relinker: swaps where swap < keep (caught) >= 60%, keeps where swap < keep (would break) <= 5%.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_encounters.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402

MEET_W = 1.0
K = 8              # frames of motion either side of the encounter


def runs(mask):
    out, s = [], None
    for i, m in enumerate(mask):
        if m and s is None:
            s = i
        if not m and s is not None:
            out.append((s, i - 1)); s = None
    if s is not None:
        out.append((s, len(mask) - 1))
    return out


def piece(r, lo, hi):
    return r[(r[:, 1] >= lo) & (r[:, 1] <= hi)]


def fit(p):
    """position and velocity (per frame) at the piece's end nearest the encounter, by least squares."""
    if len(p) < 2:
        return None
    t = p[:, 1] - p[:, 1].mean()
    vx = np.polyfit(t, p[:, 2], 1)[0] if np.ptp(t) > 0 else 0.0
    vy = np.polyfit(t, p[:, 3], 1)[0] if np.ptp(t) > 0 else 0.0
    return np.array([vx, vy])


def cost(before, after, w):
    if len(before) < 3 or len(after) < 3:
        return None
    vb, va = fit(before), fit(after)
    f0 = after[0, 1]
    pred = before[-1, 2:4] + vb * (f0 - before[-1, 1])
    return (np.hypot(*(after[0, 2:4] - pred)) + np.hypot(*(va - vb)) * K) / w


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    res = Counter()
    margins = {"SWAP": [], "KEEP": []}
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
        one = {ein[l["label_id"]]: l for l in labs if ein.get(l["label_id"]) is not None
               and ein.get(l["label_id"]) == eout.get(l["label_id"])}
        swapped = {}
        for l in labs:
            a, b = ein.get(l["label_id"]), eout.get(l["label_id"])
            if a is not None and b is not None and a != b:
                swapped[frozenset((a, b))] = l
        ids = set(one) | {t for p in swapped for t in p}
        tr = {t: rows[rows[:, 0] == t] for t in ids}
        tr = {t: r[np.argsort(r[:, 1])] for t, r in tr.items() if len(r)}
        lst = sorted(tr)
        for i, A in enumerate(lst):
            for B in lst[i + 1:]:
                a, b = tr[A], tr[B]
                com, ia, ib = np.intersect1d(a[:, 1], b[:, 1], return_indices=True)
                if len(com) < 2:
                    continue
                w = np.maximum(np.minimum(a[ia, 4], b[ib, 4]), 1)
                d = np.hypot(a[ia, 2] - b[ib, 2], a[ia, 3] - b[ib, 3]) / w
                key = frozenset((A, B))
                for s, e in runs(d <= MEET_W):
                    fs, fe = com[s], com[e]
                    if key in swapped:
                        l = swapped[key]
                        if not (l["entry_frame"] - 2 <= fs <= l["exit_frame"] + 2 or l["entry_frame"] <= fe <= l["exit_frame"]):
                            continue
                        truth = "SWAP"
                    elif A in one and B in one:
                        truth = "KEEP"
                    else:
                        continue
                    ab, bb = piece(a, fs - K, fs - 1), piece(b, fs - K, fs - 1)
                    aa, ba = piece(a, fe + 1, fe + K), piece(b, fe + 1, fe + K)
                    wm = float(np.median(w[s:e + 1]))
                    ck = [cost(ab, aa, wm), cost(bb, ba, wm)]
                    cs = [cost(ab, ba, wm), cost(bb, aa, wm)]
                    if None in ck or None in cs:
                        res[(truth, "too short")] += 1
                        continue
                    keep, swap = sum(ck), sum(cs)
                    verdict = "swap better" if swap < keep else "keep better"
                    res[(truth, verdict)] += 1
                    margins[truth].append(keep - swap)
                    print(f"  {truth} {clip['clip_id']:14} t{A}/t{B} f{int(fs)}-{int(fe)} ({e - s + 1} close frames) "
                          f"keep {keep:6.2f}  swap {swap:6.2f}  -> {verdict}")
    print()
    for k, n in sorted(res.items()):
        print(f"  {k[0]:5} {k[1]:12} {n:4}")
    for t, m in margins.items():
        if m:
            m = np.array(m)
            print(f"  {t}: keep - swap  quartiles {np.percentile(m, 25):.2f} / {np.median(m):.2f} / {np.percentile(m, 75):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
