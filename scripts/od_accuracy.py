"""Per-minute, OD-level accuracy harness against the Miovision per-minute XML.

Two upgrades over per_movement_accuracy.py (which compares origin+movement at
15-min granularity):
  1. OD-LEVEL: compares our (origin_leg -> destination_leg) attribution to
     Miovision's origin->destination matrix, so destination errors (e.g. turns
     snapping to the wrong leg) are visible, not just origin+movement.
  2. PER-MINUTE: aligns counts minute-by-minute, exposing COMPENSATING errors
     net 30-min counts hide (a phantom turn in one minute + a missed turn in
     another cancel in the net but not per-minute). Reports gross (Σ|Δ| per
     minute) vs net (|ΣΔ|) error so the hidden error is explicit.

Ground truth: scripts/parse_miovision_xml.py (verified vs the 15-min CSV).
Our counts: vehicle_events.timestamp_video (footage-seconds from VIDEO_START).

Usage:
  py scripts/od_accuracy.py --db data/projects/97a7849a/_hybrid_tmp/oc.db \
      --start-hms 07:00:00 --minutes 30
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groundtruth import LEG_TO_APPROACH, NORM_MVT, VIDEO_START
from parse_miovision_xml import APPROACH, approaches, parse, slot_labels

PROJECT_DB = "data/projects/97a7849a/project.db"

# leg.cardinal_direction records the SIDE of the intersection the leg sits on
# (same convention as triangulate_manual._CARD_TO_DIR); the traffic ENTERING
# from that side travels the OPPOSITE cardinal — a leg on the N side feeds the
# SB approach ("SB N Belt Line Rd" in the Miovision XML). The original
# same-letter mapping here (N->"NB") was 180-degrees flipped for EVERY leg —
# it disagreed with the verified cam1 LEG_IDX (despite the old comment claiming
# agreement) and was only ever exercised for camera_id != 1, where it silently
# flipped manual_od_by_cell()'s volume-gate expecteds and _measure() reporting
# (found on the cam2 ReID generalization spike, 2026-07-08).
_CARD2PREFIX = {"N": "SB", "S": "NB", "E": "WB", "W": "EB"}


def leg_idx(camera_id: int, db: str = PROJECT_DB) -> dict[int, int]:
    """{leg_id: approach_idx} for a camera, by matching leg.cardinal_direction
    (the SIDE the leg is on) to the approach whose XML Name is prefixed by the
    OPPOSITE cardinal (the direction of travel entering from that side). Agrees
    with the hand-built, verified cam1 LEG_IDX. Works for 3-leg (T) and 4-way
    intersections alike."""
    appr = approaches(camera_id)                                  # {idx: name}
    prefix_to_idx = {(name or "").split()[0]: idx for idx, name in appr.items()}
    conn = sqlite3.connect(str(db))
    legs = conn.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (camera_id,)
    ).fetchall()
    conn.close()
    out: dict[int, int] = {}
    for leg_id, card in legs:
        idx = prefix_to_idx.get(_CARD2PREFIX.get((card or "").upper()))
        if idx is not None:
            out[leg_id] = idx
    return out


def idx_name(camera_id: int) -> dict[int, str]:
    """{approach_idx: short cardinal name} (e.g. {0:'SB',...}) from the camera's
    XML — the approach Name's leading token."""
    return {i: (name or "").split()[0] for i, name in approaches(camera_id).items()}


# Cam1 module-level defaults, kept for the existing cam1 callers that import
# LEG_IDX / IDX_NAME (hybrid_ocbot, process_camera_reid, visual_gate, ...). These
# are derived without a DB hit; the cardinal-based leg_idx(1) agrees with them.
# LEG_TO_APPROACH was corrected 2026-05-29 (legs were 180°-mislabeled — memory
# project_leg_labels_swapped), so this mapping is the verified-correct one.
_NAME_TO_IDX = {v: k for k, v in APPROACH.items()}
LEG_IDX = {leg: _NAME_TO_IDX[name] for leg, name in LEG_TO_APPROACH.items()}
IDX_NAME = {i: APPROACH[i].replace(" N Belt Line Rd", "").replace(" Northwest Dr", "").replace(" Private Driveway", "")
            for i in APPROACH}


def manual_per_minute(camera_id: int = 1):
    """Return (od, mv): od[minute_dt][(in,out)]=count, mv[minute_dt][(in,mvt)]=count,
    and od_label[(in,out)] = 'SB->EB right'."""
    inm = idx_name(camera_id) if camera_id != 1 else IDX_NAME
    data = parse(camera_id)
    labels = slot_labels(data["movements"], camera_id)  # slot -> (in_name, mvt, out_name)
    movements = data["movements"]             # slot -> (Name, in_idx, out_idx)
    od = defaultdict(lambda: defaultdict(int))
    mv = defaultdict(lambda: defaultdict(int))
    od_label = {}
    for tm, vols in data["per_min"].items():
        dt = datetime.fromisoformat(tm)
        for i, v in enumerate(vols):
            _, in_i, out_i = movements[i]
            _, mvt, _ = labels[i]
            od[dt][(in_i, out_i)] += v
            mv[dt][(in_i, mvt)] += v
            od_label[(in_i, out_i)] = f"{inm[in_i]}->{inm[out_i]} {mvt}"
    return od, mv, od_label


def manual_od_by_cell(start_hms="07:00:00", minutes=30.0, legmap=None, camera_id=1):
    """Miovision OD totals for the [start_hms, +minutes) WINDOW, keyed by our
    (origin_leg, dest_leg). Used as the expected per-cell turn volume for the
    intra-turn merge volume-gate and the raw-track path real-movement gate. NB:
    must be window-restricted — summing all minutes gives whole-day totals."""
    legmap = legmap or (LEG_IDX if camera_id == 1 else leg_idx(camera_id))
    inv = {idx: leg for leg, idx in legmap.items()}
    m_od, _, _ = manual_per_minute(camera_id)
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{start_hms}")
    win = {t0 + timedelta(minutes=i) for i in range(int(minutes))}
    out = defaultdict(float)
    for mn, per in m_od.items():
        if mn not in win:
            continue
        for (in_i, out_i), cnt in per.items():
            ol, dl = inv.get(in_i), inv.get(out_i)
            if ol is not None and dl is not None:
                out[(ol, dl)] += cnt
    return out


def our_per_minute(db, start_sec, end_sec, legmap=None, camera_id=None):
    """Bin our events by wall-clock minute. Returns (od, mv) same shape as manual.
    legmap already isolates the target camera's legs (leg_ids are globally unique
    per camera); pass camera_id to also scope the SQL explicitly."""
    legmap = legmap or LEG_IDX
    conn = sqlite3.connect(str(db))
    if camera_id is not None:
        rows = conn.execute(
            "SELECT origin_leg_id, destination_leg_id, movement, timestamp_video "
            "FROM vehicle_events WHERE camera_id=? AND rejected=0 "
            "AND timestamp_video>=? AND timestamp_video<?",
            (camera_id, start_sec, end_sec)).fetchall()
    else:
        rows = conn.execute(
            "SELECT origin_leg_id, destination_leg_id, movement, timestamp_video "
            "FROM vehicle_events WHERE rejected=0 AND timestamp_video>=? AND timestamp_video<?",
            (start_sec, end_sec)).fetchall()
    conn.close()
    od = defaultdict(lambda: defaultdict(int))
    mv = defaultdict(lambda: defaultdict(int))
    for ol, dl, mvt_raw, ts in rows:
        in_i = legmap.get(ol)
        out_i = legmap.get(dl)
        mvt = NORM_MVT.get(mvt_raw, mvt_raw)
        if in_i is None:
            continue
        minute = (VIDEO_START + timedelta(seconds=ts)).replace(second=0, microsecond=0)
        od[minute][(in_i, out_i)] += 1
        mv[minute][(in_i, mvt)] += 1
    return od, mv


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/projects/97a7849a/project.db")
    ap.add_argument("--camera", type=int, default=1, help="camera_id (default 1)")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--show-od", action="store_true", help="print per-OD-cell table")
    args = ap.parse_args()
    legmap = LEG_IDX if args.camera == 1 else leg_idx(args.camera)
    inm = IDX_NAME if args.camera == 1 else idx_name(args.camera)

    # footage-second window from the wall-clock start
    day = VIDEO_START.date().isoformat()
    t0 = datetime.fromisoformat(f"{day}T{args.start_hms}")
    start_sec = (t0 - VIDEO_START).total_seconds()
    end_sec = start_sec + args.minutes * 60
    minutes = [t0 + timedelta(minutes=i) for i in range(int(args.minutes))]

    m_od, m_mv, od_label = manual_per_minute(args.camera)
    o_od, o_mv = our_per_minute(Path(args.db), start_sec, end_sec, legmap=legmap,
                                camera_id=args.camera)

    # ---- Movement-level (origin, mvt): net + per-minute gross ----
    cells = set()
    for mn in minutes:
        cells |= set(m_mv.get(mn, {})) | set(o_mv.get(mn, {}))
    print(f"db={args.db}\nwindow {args.start_hms} +{args.minutes:.0f}min  ({len(minutes)} minutes)\n")
    print("=== MOVEMENT level (origin approach, movement) ===")
    print(f"{'cell':<18}{'manual':>7}{'ours':>6}{'net|d|':>8}{'gross|d|':>9}{'hidden':>7}")
    tot_man = tot_net = tot_gross = 0
    for cell in sorted(cells, key=lambda c: -sum(abs(o_mv.get(mn,{}).get(c,0)-m_mv.get(mn,{}).get(c,0)) for mn in minutes)):
        man = sum(m_mv.get(mn, {}).get(cell, 0) for mn in minutes)
        ours = sum(o_mv.get(mn, {}).get(cell, 0) for mn in minutes)
        gross = sum(abs(o_mv.get(mn, {}).get(cell, 0) - m_mv.get(mn, {}).get(cell, 0)) for mn in minutes)
        net = abs(ours - man)
        tot_man += man; tot_net += net; tot_gross += gross
        if man == 0 and ours == 0:
            continue
        in_i, mvt = cell
        print(f"{inm[in_i]+' '+mvt:<18}{man:>7}{ours:>6}{net:>8}{gross:>9}{gross-net:>7}")
    print(f"{'TOTAL':<18}{tot_man:>7}{'':>6}{tot_net:>8}{tot_gross:>9}{tot_gross-tot_net:>7}")
    print(f"  net agg_err   = {tot_net/tot_man*100:5.1f}%   (matches per_movement_accuracy)")
    print(f"  per-min gross = {tot_gross/tot_man*100:5.1f}%   (true error; gap = compensating/timing)")

    if args.show_od:
        print("\n=== OD level (origin->destination) ===")
        odcells = set()
        for mn in minutes:
            odcells |= set(m_od.get(mn, {})) | set(o_od.get(mn, {}))
        print(f"{'OD cell':<22}{'manual':>7}{'ours':>6}{'net|d|':>8}{'gross|d|':>9}")
        for cell in sorted(odcells, key=lambda c: -abs(sum(o_od.get(mn,{}).get(c,0) for mn in minutes)-sum(m_od.get(mn,{}).get(c,0) for mn in minutes))):
            man = sum(m_od.get(mn, {}).get(cell, 0) for mn in minutes)
            ours = sum(o_od.get(mn, {}).get(cell, 0) for mn in minutes)
            if man == 0 and ours == 0:
                continue
            gross = sum(abs(o_od.get(mn, {}).get(cell, 0) - m_od.get(mn, {}).get(cell, 0)) for mn in minutes)
            lbl = od_label.get(cell)
            if lbl is None:
                in_i, out_i = cell
                lbl = f"{inm.get(in_i,in_i)}->{inm.get(out_i,'?') if out_i is not None else 'None'}"
            print(f"{lbl:<22}{man:>7}{ours:>6}{abs(ours-man):>8}{gross:>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
