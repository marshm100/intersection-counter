"""What the PHANTOMS are (2026-10-11, operator: "dissect it"): counted events inside a
labelled clip that no labelled vehicle's click claims (backend/services/journey_eval.py).
Dev-validation only; no new labels.

Each phantom's track is put in ONE bucket, first that applies:
  SIDE_BY_SIDE  within SIDE_BOXES box widths of ONE labelled vehicle's track, frame by frame,
                for >= TWIN_FRAC of its own life - the same vehicle seen twice at once
  STILL         moves less than STILL_BOXES box widths over its life (a parked or queued
                object, or a fixed false box)
  PIECE         starts within PIECE_S after a labelled vehicle's track ends (or ends within
                PIECE_S before one starts), within PIECE_BOXES box widths - a broken piece
  CLIP_EDGE     alive at the clip's start or end (a vehicle the labeller saw only in part)
  ALONE         none of the above - an unlabelled vehicle or something counted from nothing
For each: the gate tag and posterior source (track_fates), the movement, the box width,
the lifespan, and for SIDE_BY_SIDE / PIECE whether the labelled vehicle it shadows is
itself counted (then the phantom is an over-count of that vehicle) and with which movement.
Usage: .venv\\Scripts\\python.exe -X utf8 scripts/research_phantoms.py STEM[:PREFIXES] [--heldout]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from scripts.eval_journeys import PROJ, is_heldout, locate, parse  # noqa: E402

SIDE_BOXES, SIDE_MIN_S = 1.5, 0.3
PIECE_S, PIECE_BOXES = 3.0, 3.0
TWIN_FRAC = 0.5
STILL_BOXES = 2.0


def side_by_side(a: np.ndarray, b: np.ndarray, fps: float) -> float:
    """Fraction of b's rows that sit within SIDE_BOXES box widths of a in the same frame
    (0 when fewer than SIDE_MIN_S seconds of them do)."""
    fa = {int(r[1]): r for r in a}
    close = 0
    for r in b:
        q = fa.get(int(r[1]))
        if q is not None and np.hypot(q[2] - r[2], q[3] - r[3]) <= SIDE_BOXES * max(q[4], r[4]):
            close += 1
    return close / len(b) if close >= SIDE_MIN_S * fps else 0.0


def piece_gap(a: np.ndarray, b: np.ndarray, fps: float) -> float | None:
    """Seconds between the end of one and the start of the other when they join end to start."""
    best = None
    for x, y in ((a, b), (b, a)):
        e, s = x[np.argmax(x[:, 1])], y[np.argmin(y[:, 1])]
        gap = (s[1] - e[1]) / fps
        if -0.2 <= gap <= PIECE_S and np.hypot(e[2] - s[2], e[3] - s[3]) <= PIECE_BOXES * max(e[4], s[4]):
            best = gap if best is None else min(best, gap)
    return best


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    held = "--heldout" in sys.argv
    stem, prefixes = parse(args[0] if args else "dt2c")
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    tot: Counter = Counter()
    for clip in list_clips(PROJ):
        if is_heldout(clip["clip_id"]) != held:
            continue
        labels = list_labels(PROJ, clip["clip_id"])
        if not labels:
            continue
        cam = clip["camera_id"]
        window = "study_" + clip["clip_id"].split("_")[1]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        fps = float(fps)
        db, rows = locate(stem, prefixes, cam, window, chash)
        if db is None:
            continue
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        events = [dict(zip(("vehicle_track_id", "origin_leg_id", "destination_leg_id", "start_frame"), r))
                  for r in d.execute("SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
                                     "COALESCE(start_frame, frame_number) FROM vehicle_events "
                                     "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,))]
        fates = {int(r[0]): r[1:] for r in d.execute(
            "SELECT vehicle_track_id, gate_tag, posterior_source FROM track_fates "
            "WHERE camera_id=? AND disposition='counted'", (cam,))}
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        byf = je.index_rows(rows, f_lo - je.SEARCH_FRAMES, f_hi + je.SEARCH_FRAMES)
        dups = je.duplicate_labels(labels, fps, byf)
        lab = [lb for lb in labels if lb["label_id"] not in dups]
        entry_of, exit_of = je._assign_clicks(lab, rows, byf, fps)
        owner: dict = {}
        for side in (exit_of, entry_of):
            for lid, t in side.items():
                owner[t] = lid
        ev_by: dict = {}
        for e in events:
            ev_by.setdefault(int(e["vehicle_track_id"]), []).append(e)
        lab_by = {lb["label_id"]: lb for lb in lab}
        phantoms = [e for e in events if f_lo <= int(e.get("start_frame") or -1) <= f_hi
                    and int(e["vehicle_track_id"]) not in owner]
        lo, hi = f_lo - int(10 * fps), f_hi + int(10 * fps)
        win = rows[(rows[:, 1] >= lo) & (rows[:, 1] <= hi)]
        by_tid = {int(t): win[win[:, 0] == t] for t in np.unique(win[:, 0])}
        print(f"\n== {clip['clip_id']} ({stem}; fps {fps:g}): {len(phantoms)} phantoms")
        for e in phantoms:
            t = int(e["vehicle_track_id"])
            tr = by_tid.get(t)
            if tr is None or not len(tr):
                tr = rows[rows[:, 0] == t]
            tag, src = fates.get(t, (None, None))
            mv = f"{e['origin_leg_id']}->{e['destination_leg_id']}"
            w = float(np.median(tr[:, 4]))
            life = (tr[:, 1].max() - tr[:, 1].min()) / fps
            kind, who, note = "ALONE", None, ""
            fr = max(((side_by_side(o, tr, fps), lid) for ot, lid in owner.items()
                      if (o := by_tid.get(ot)) is not None and len(o)), default=(0.0, None))
            moved = float(np.hypot(*(tr[np.argmax(tr[:, 1]), 2:4] - tr[np.argmin(tr[:, 1]), 2:4]))) / max(w, 1.0)
            span = float(max(np.ptp(tr[:, 2]), np.ptp(tr[:, 3]))) / max(w, 1.0)
            note = f" close {fr[0]:.0%} moved {moved:.1f}w span {span:.1f}w"
            if fr[0] >= TWIN_FRAC:
                kind, who = "SIDE_BY_SIDE", fr[1]
            elif span < STILL_BOXES:
                kind = "STILL"
            if kind == "ALONE":
                best = None
                for ot, lid in owner.items():
                    o = by_tid.get(ot)
                    if o is None or not len(o):
                        continue
                    g = piece_gap(o, tr, fps)
                    if g is not None and (best is None or g < best[0]):
                        best = (g, lid)
                if best is not None:
                    kind, who = "PIECE", best[1]
                    note += f" gap {best[0]:+.1f}s"
            if kind == "ALONE" and (tr[:, 1].min() <= f_lo + fps or tr[:, 1].max() >= f_hi - fps):
                kind = "CLIP_EDGE"
            shadow = ""
            if who is not None:
                lb = lab_by[who]
                truth = (lb.get("entry_leg_id"), lb.get("exit_leg_id"))
                counted = [(x["origin_leg_id"], x["destination_leg_id"])
                           for tt in {entry_of.get(who), exit_of.get(who)} if tt is not None
                           for x in ev_by.get(tt, ())]
                same = (e["origin_leg_id"], e["destination_leg_id"]) == truth
                if counted:
                    sub = "OVERCOUNT (vehicle already counted)"
                    tot[f"{kind} | shadowed vehicle already counted"] += 1
                else:
                    sub = "STANDS IN (vehicle otherwise uncounted)"
                    tot[f"{kind} | stands in for an uncounted vehicle"] += 1
                    if same:
                        tot[f"{kind} | stands in, with the vehicle's true movement"] += 1
                shadow = (f"  shadows car {who} truth {truth[0]}->{truth[1]} "
                          f"{'same' if same else 'DIFFERENT'} movement; {sub}")
            tot[kind] += 1
            tot[f"tag {tag}"] += 1
            tot[f"{kind} | tag {tag}"] += 1
            if w < 30:
                tot[f"{kind} | box < 30 px"] += 1
            if w > 130:
                tot[f"{kind} | box > 130 px"] += 1
            print(f"  t{t:<6} {kind:12} tag {str(tag):12} src {str(src):15} {mv:7} "
                  f"box {w:5.1f}px life {life:4.1f}s{note}{shadow}")
    print("\nTOTALS:")
    for k, n in sorted(tot.items()):
        print(f"  {k:60} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
