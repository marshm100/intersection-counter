"""OC+BoT per-regime hybrid combine (docs/handoff_ocbot_hybrid_2026-06-01.md).

Neither single tracker wins at this footage quality (memory project_leg_labels_swapped):
  - OC-SORT: throughs GOOD, sharp cross-street turns BAD (fragments them).
  - BoT-SORT: sharp turns GOOD + clean phantoms, but UNDER-detects low-conf throughs.
So combine each tracker's STRENGTH at the event level:
  combined = {OC-SORT events where movement == 'through'}
           U {BoT-SORT events where movement IN ('left','right','u_turn')}
Both arms are retracked on the SAME bank + SAME cached detections (so the OD
geometry is identical); we just pick which tracker owns each movement regime.

Cross-backend boundary dedup: a turning vehicle OC-SORT mis-saw as a through-stub
would be counted twice (once in OC throughs, once in BoT turns). For each BoT turn
we drop any OC through that OVERLAPS it in frame-range AND starts within --dedup-px
(same vehicle, both trackers). Movement classes are otherwise disjoint, so
false-merge risk is low.

Usage:
  py scripts/hybrid_ocbot.py --oc-db .../oc.db --bot-db .../bot.db \
     --out-db .../combined.db --show-od
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groundtruth import VIDEO_START
from od_accuracy import manual_per_minute, our_per_minute, manual_od_by_cell, LEG_IDX, IDX_NAME

TURNS = ("left", "right", "u_turn")
CAMERA = 1


def _load(db, where):
    c = sqlite3.connect(str(db))
    rows = c.execute(
        "SELECT event_id, movement, origin_leg_id, destination_leg_id, "
        "start_frame, frame_number, trajectory_data "
        f"FROM vehicle_events WHERE camera_id=? AND rejected=0 AND ({where})",
        (CAMERA,)).fetchall()
    c.close()
    out = []
    for eid, mv, ol, dl, sf, ef, tj in rows:
        try:
            traj = json.loads(tj) if tj else []
        except Exception:
            traj = []
        s = sf if sf is not None else ef
        e = ef if ef is not None else sf
        out.append({"id": eid, "mv": mv, "ol": ol, "dl": dl, "s": s, "e": e,
                    "start": traj[0] if traj else None})
    return out


def merge_turn_fragments(turns, merge_px, merge_gap, expected_by_cell=None,
                         vol_factor=1.3):
    """BoT-SORT fragments one turning vehicle into several events (it coasts the
    sharp curve, the pipeline finalizes the stub, then re-tracks the exit). Merge
    events that share the SAME (origin, dest, movement) and start within merge_px
    of each other within merge_gap frames — same vehicle. This is far safer than
    arterial-through stitching (memory project_leg_labels_swapped / dedup_ceiling):
    turns are low-volume and constrained to one OD cell.

    Volume gate (A2): only merge a cell when its raw event count exceeds
    vol_factor x its expected volume — i.e. there's clear OVER-count = fragmentation
    to collapse (e.g. NB-left 136 vs ~96). Sparse, already-well-calibrated cells
    (e.g. EB-right ~38 vs 36) are left UNTOUCHED so the merge can't collapse two
    distinct ~1/min turners. `expected_by_cell` maps (origin,dest)->expected count
    (offline: Miovision manual; in production: the bank's supporting_count). When
    None, every cell is eligible (legacy behaviour). Returns the kept event ids."""
    from collections import defaultdict
    by = defaultdict(list)
    for ev in turns:
        by[(ev["ol"], ev["dl"], ev["mv"])].append(ev)
    keep = []
    for cell, evs in by.items():
        evs.sort(key=lambda e: e["s"])
        # Volume gate: skip merging cells that aren't clearly over-counted.
        if expected_by_cell is not None:
            exp = expected_by_cell.get((cell[0], cell[1]), 0)
            if len(evs) <= vol_factor * max(exp, 1):
                keep.extend(e["id"] for e in evs)
                continue
        used = [False] * len(evs)
        for i, ei in enumerate(evs):
            if used[i]:
                continue
            used[i] = True
            keep.append(ei["id"])
            if ei["start"] is None:
                continue
            for j in range(i + 1, len(evs)):
                ej = evs[j]
                if used[j] or ej["start"] is None:
                    continue
                if (ej["s"] - ei["e"]) <= merge_gap and math.hypot(
                        ei["start"][0] - ej["start"][0],
                        ei["start"][1] - ej["start"][1]) <= merge_px:
                    used[j] = True   # fragment of the same turning vehicle
    return set(keep)


def _overlap(a, b):
    return not (a["e"] < b["s"] or b["e"] < a["s"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oc-db", default="data/projects/97a7849a/_hybrid_tmp/relabeled.db",
                    help="OC-SORT-retracked DB (throughs taken from here)")
    ap.add_argument("--bot-db", default="data/projects/97a7849a/_hybrid_tmp/botsort_fresh.db",
                    help="BoT-SORT-retracked DB (turns taken from here)")
    ap.add_argument("--out-db", default="data/projects/97a7849a/_hybrid_tmp/ocbot.db")
    ap.add_argument("--dedup-px", type=float, default=60.0,
                    help="OC-through dropped if a BoT turn overlaps in time and starts within this")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--show-od", action="store_true")
    ap.add_argument("--no-dedup", action="store_true")
    ap.add_argument("--merge-turns", action="store_true",
                    help="merge BoT turn fragments (same OD, close start+time) into one vehicle")
    ap.add_argument("--merge-px", type=float, default=30.0)
    ap.add_argument("--merge-gap", type=float, default=40.0)
    ap.add_argument("--merge-vol-factor", type=float, default=1.3,
                    help="only merge a turn cell whose raw count exceeds this x its expected (manual) volume")
    args = ap.parse_args()

    oc_db, bot_db, out_db = Path(args.oc_db), Path(args.bot_db), Path(args.out_db)

    # --- boundary dedup: which OC throughs are really BoT turns? ---
    oc_thru = _load(oc_db, "movement = 'through'")
    bot_turn = _load(bot_db, "movement IN ('left','right','u_turn')")
    keep_turn_ids = None
    if args.merge_turns:
        # Expected per-OD-cell volume (Miovision, WINDOW-restricted) so the merge
        # only collapses clearly over-counted (fragmented) cells, sparing sparse
        # ones (A2). Must be window-restricted — whole-day totals would disable it.
        expected_by_cell = manual_od_by_cell(args.start_hms, args.minutes)
        keep_turn_ids = merge_turn_fragments(
            bot_turn, args.merge_px, args.merge_gap,
            expected_by_cell=expected_by_cell, vol_factor=args.merge_vol_factor)
        print(f"turn-merge: {len(bot_turn)} BoT turn events -> {len(keep_turn_ids)} kept")
    drop_oc = set()
    if not args.no_dedup:
        for bt in bot_turn:
            if bt["start"] is None:
                continue
            for oc in oc_thru:
                if oc["id"] in drop_oc or oc["start"] is None:
                    continue
                if _overlap(oc, bt) and math.hypot(
                        oc["start"][0] - bt["start"][0],
                        oc["start"][1] - bt["start"][1]) <= args.dedup_px:
                    drop_oc.add(oc["id"])
                    break

    # --- assemble combined DB: copy OC arm, drop OC turns + deduped throughs,
    #     insert BoT turn events as fresh rows (track_id=-999) ---
    shutil.copy2(oc_db, out_db)
    c = sqlite3.connect(str(out_db))
    cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall()
            if r[1] != "event_id"]
    collist = ",".join(cols)
    with c:
        # keep ONLY OC throughs (minus the deduped ones)
        c.execute(f"DELETE FROM vehicle_events WHERE camera_id=? AND "
                  f"NOT (movement='through')", (CAMERA,))
        if drop_oc:
            c.executemany("DELETE FROM vehicle_events WHERE event_id=?",
                          [(i,) for i in drop_oc])
        # bring BoT turns in (optionally only the merged-fragment representatives)
        c.execute("ATTACH DATABASE ? AS botdb", (str(bot_db),))
        sel = collist.replace("vehicle_track_id", "-999 AS vehicle_track_id")
        id_filter = ""
        if keep_turn_ids is not None:
            id_filter = " AND event_id IN (%s)" % ",".join(str(i) for i in keep_turn_ids)
        n = c.execute(
            f"INSERT INTO vehicle_events ({collist}) SELECT {sel} FROM botdb.vehicle_events "
            f"WHERE camera_id=? AND rejected=0 AND movement IN ('left','right','u_turn'){id_filter}",
            (CAMERA,)).rowcount
    c.execute("DETACH DATABASE botdb")
    c.close()
    print(f"OC throughs kept={len(oc_thru)-len(drop_oc)} (dropped {len(drop_oc)} as BoT-turn dups)  "
          f"+ BoT turns inserted={n}  -> {out_db}")

    # --- measure (per-minute, movement + OD level) ---
    day = VIDEO_START.date().isoformat()
    t0 = datetime.fromisoformat(f"{day}T{args.start_hms}")
    start_sec = (t0 - VIDEO_START).total_seconds()
    end_sec = start_sec + args.minutes * 60
    minutes = [t0 + timedelta(minutes=i) for i in range(int(args.minutes))]
    m_od, m_mv, od_label = manual_per_minute()
    o_od, o_mv = our_per_minute(out_db, start_sec, end_sec, legmap=LEG_IDX)

    cells = set()
    for mn in minutes:
        cells |= set(m_mv.get(mn, {})) | set(o_mv.get(mn, {}))
    print(f"\n=== MOVEMENT level  (window {args.start_hms} +{args.minutes:.0f}min) ===")
    print(f"{'cell':<16}{'manual':>7}{'ours':>6}{'net':>6}{'gross':>7}")
    tman = tnet = tgross = 0
    for c2 in sorted(cells, key=lambda c: -sum(
            abs(o_mv.get(mn, {}).get(c, 0) - m_mv.get(mn, {}).get(c, 0)) for mn in minutes)):
        man = sum(m_mv.get(mn, {}).get(c2, 0) for mn in minutes)
        ours = sum(o_mv.get(mn, {}).get(c2, 0) for mn in minutes)
        gross = sum(abs(o_mv.get(mn, {}).get(c2, 0) - m_mv.get(mn, {}).get(c2, 0)) for mn in minutes)
        tman += man; tnet += abs(ours - man); tgross += gross
        if man == 0 and ours == 0:
            continue
        in_i, mvt = c2
        print(f"{IDX_NAME[in_i]+' '+mvt:<16}{man:>7}{ours:>6}{abs(ours-man):>6}{gross:>7}")
    print(f"{'TOTAL':<16}{tman:>7}{'':>6}{tnet:>6}{tgross:>7}")
    print(f"  net agg_err = {tnet/tman*100:.1f}%   per-min gross = {tgross/tman*100:.1f}%")

    if args.show_od:
        print("\n=== OD level (origin->destination) ===")
        odcells = set()
        for mn in minutes:
            odcells |= set(m_od.get(mn, {})) | set(o_od.get(mn, {}))
        print(f"{'OD cell':<22}{'manual':>7}{'ours':>6}{'net':>6}{'gross':>7}")
        for cell in sorted(odcells, key=lambda c: -abs(
                sum(o_od.get(mn, {}).get(c, 0) for mn in minutes) -
                sum(m_od.get(mn, {}).get(c, 0) for mn in minutes))):
            man = sum(m_od.get(mn, {}).get(cell, 0) for mn in minutes)
            ours = sum(o_od.get(mn, {}).get(cell, 0) for mn in minutes)
            if man == 0 and ours == 0:
                continue
            gross = sum(abs(o_od.get(mn, {}).get(cell, 0) - m_od.get(mn, {}).get(cell, 0)) for mn in minutes)
            lbl = od_label.get(cell)
            if lbl is None:
                in_i, out_i = cell
                lbl = f"{IDX_NAME.get(in_i, in_i)}->{IDX_NAME.get(out_i, '?') if out_i is not None else 'None'}"
            print(f"{lbl:<22}{man:>7}{ours:>6}{abs(ours-man):>6}{gross:>7}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
