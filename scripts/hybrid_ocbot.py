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


def _load(db, where, camera_id=CAMERA):
    c = sqlite3.connect(str(db))
    rows = c.execute(
        "SELECT event_id, movement, origin_leg_id, destination_leg_id, "
        "start_frame, frame_number, trajectory_data "
        f"FROM vehicle_events WHERE camera_id=? AND rejected=0 AND ({where})",
        (camera_id,)).fetchall()
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


def borderline_merge_cells(turns, expected_by_cell, vol_factor=1.3,
                           band=0.2) -> list[dict]:
    """S5 — merge-gate borderline cells (docs/plan_flagqueue_B_2026-07-09.md).
    A turn cell whose RAW fragment count sits within +/-band of the volume-gate
    threshold (vol_factor x expected) is one noise-vehicle away from the merge
    decision flipping — the cam1 NB-left blind case (134 raw vs threshold 143 ->
    no merge -> +38 shipped). Only computable HERE, where raw pre-merge counts
    exist; the final DB has no trace of them. Returns one dict per borderline
    cell for the caller to surface (print now; review_flags when §3-A wires
    pass-2 into the product)."""
    from collections import Counter
    raw = Counter((ev["ol"], ev["dl"]) for ev in turns)
    out = []
    for cell, n in raw.items():
        exp = (expected_by_cell or {}).get(cell)
        if not exp:
            continue
        thr = vol_factor * max(exp, 1)
        if thr * (1 - band) <= n <= thr * (1 + band):
            out.append({"cell": cell, "raw": n, "expected": exp,
                        "threshold": round(thr, 1),
                        "merges": n > thr})
    return out


def _overlap(a, b):
    return not (a["e"] < b["s"] or b["e"] < a["s"])


def combine_regimes(oc_db, bot_db, out_db, *, merge_turns=True, merge_px=30.0,
                    merge_gap=40.0, merge_vol_factor=1.3, no_dedup=True,
                    dedup_px=60.0, start_hms="07:00:00", minutes=30.0,
                    camera_id=CAMERA, expected_by_cell=None):
    """Assemble the regime-split combined DB: OC/throughs arm + BoT/turns arm.
    combined = {oc_db events movement='through'} U {bot_db turn events}, with the
    A2 volume-gated intra-turn merge and (default-off) cross-backend boundary dedup.
    Writes out_db (a copy of oc_db with this camera's events replaced) and returns
    (oc_throughs_kept, oc_dropped, bot_turns_inserted). Shared by hybrid_ocbot.main
    (offline measure) and process_camera_reid.py (production orchestrator).
    camera_id parameterizes the camera (default cam1 for the legacy offline path).
    expected_by_cell overrides the volume-gate expecteds ({(origin,dest): count});
    default None keeps the legacy DEV behaviour of pulling Miovision manual counts
    — a GT runtime dependency a blind deployment cannot have. Pass the bank's
    supporting_count per path for the GT-free production gate."""
    oc_thru = _load(oc_db, "movement = 'through'", camera_id)
    bot_turn = _load(bot_db, "movement IN ('left','right','u_turn')", camera_id)
    keep_turn_ids = None
    if merge_turns:
        expected = (expected_by_cell if expected_by_cell is not None
                    else manual_od_by_cell(start_hms, minutes, camera_id=camera_id))
        keep_turn_ids = merge_turn_fragments(bot_turn, merge_px, merge_gap,
                                             expected_by_cell=expected, vol_factor=merge_vol_factor)
        for b in borderline_merge_cells(bot_turn, expected, merge_vol_factor):
            print(f"  [S5 borderline] cell {b['cell']}: raw {b['raw']} vs threshold "
                  f"{b['threshold']} (expected {b['expected']}) — merge decision is "
                  f"noise-sensitive; flag-queue material when §3-A wires pass-2")
    drop_oc = set()
    if not no_dedup:
        for bt in bot_turn:
            if bt["start"] is None:
                continue
            for oc in oc_thru:
                if oc["id"] in drop_oc or oc["start"] is None:
                    continue
                if _overlap(oc, bt) and math.hypot(
                        oc["start"][0] - bt["start"][0],
                        oc["start"][1] - bt["start"][1]) <= dedup_px:
                    drop_oc.add(oc["id"])
                    break
    shutil.copy2(oc_db, out_db)
    c = sqlite3.connect(str(out_db))
    cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall()
            if r[1] != "event_id"]
    collist = ",".join(cols)
    with c:
        c.execute("DELETE FROM vehicle_events WHERE camera_id=? AND NOT (movement='through')", (camera_id,))
        if drop_oc:
            c.executemany("DELETE FROM vehicle_events WHERE event_id=?", [(i,) for i in drop_oc])
        c.execute("ATTACH DATABASE ? AS botdb", (str(bot_db),))
        sel = collist.replace("vehicle_track_id", "-999 AS vehicle_track_id")
        id_filter = ""
        if keep_turn_ids is not None:
            id_filter = " AND event_id IN (%s)" % ",".join(str(i) for i in keep_turn_ids)
        n = c.execute(
            f"INSERT INTO vehicle_events ({collist}) SELECT {sel} FROM botdb.vehicle_events "
            f"WHERE camera_id=? AND rejected=0 AND movement IN ('left','right','u_turn'){id_filter}",
            (camera_id,)).rowcount
    c.execute("DETACH DATABASE botdb")
    c.close()
    return len(oc_thru) - len(drop_oc), len(drop_oc), n


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

    kept, dropped, n = combine_regimes(
        oc_db, bot_db, out_db, merge_turns=args.merge_turns, merge_px=args.merge_px,
        merge_gap=args.merge_gap, merge_vol_factor=args.merge_vol_factor,
        no_dedup=args.no_dedup, dedup_px=args.dedup_px,
        start_hms=args.start_hms, minutes=args.minutes)
    if args.merge_turns:
        print("turn-merge: volume-gated intra-turn fragment merge applied")
    print(f"OC throughs kept={kept} (dropped {dropped} as BoT-turn dups)  "
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
