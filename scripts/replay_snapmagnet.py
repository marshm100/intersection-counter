"""Stage-1 snap-magnet A/B: non-destructively drop candidate phantom-turn events
on a TEMP copy of project.db, then re-measure with the universal od_accuracy
metric. Faithful for the snap-magnet cameras (phantoms already live in
project.db; real throughs are present and untouched) and a no-op regression
check on a clean camera (cam3).

Candidates (all operate ONLY on turn events; throughs are never touched):
  none     baseline (shipped) — drop nothing.
  origin   drop a turn whose nearest origin-leg to traj[0] != its claimed
           origin leg (the snap-magnet rewrites origin to a leg the track never
           came from). Data-driven, uses the same `nearest` geometry build_bank
           groups by.
  straight drop a turn whose OWN trajectory straightness > --thr (a "turn" that
           is actually a straight line is a captured through).
  oracle   cap each turn cell to its Miovision manual count (achievable floor).

Usage:
  py scripts/replay_snapmagnet.py --camera 4 --filter origin
  py scripts/replay_snapmagnet.py --camera 4 --filter straight --thr 0.92
"""
from __future__ import annotations
import argparse, json, math, shutil, sqlite3, subprocess, sys, tempfile, os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from groundtruth import VIDEO_START, NORM_MVT
from od_accuracy import leg_idx, manual_od_by_cell

PROJ_DB = "data/projects/97a7849a/project.db"
TURNS = ("left", "right", "u_turn")


def _straightness(t):
    if len(t) < 2:
        return 1.0
    pd = sum(math.hypot(t[i][0]-t[i-1][0], t[i][1]-t[i-1][1]) for i in range(1, len(t)))
    if pd < 1e-9:
        return 1.0
    sd = math.hypot(t[-1][0]-t[0][0], t[-1][1]-t[0][1])
    return sd / pd


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--filter", choices=["none", "origin", "origin2", "straight", "polymagnet", "combo", "combo2", "oracle"], default="none")
    ap.add_argument("--thr", type=float, default=0.95, help="per-event straightness threshold (straight filter)")
    ap.add_argument("--poly-thr", type=float, default=0.90, help="bank turn-polyline straightness above which the path is a magnet (polymagnet/combo)")
    ap.add_argument("--magnet-support-factor", type=float, default=3.0, help="a turn polyline is a magnet only if support > factor*manual")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=None, help="default = full cached span")
    args = ap.parse_args()
    cam = args.camera

    src = sqlite3.connect(PROJ_DB)
    legs = {lid: json.loads(oz)[0] for lid, oz in
            src.execute("SELECT leg_id,origin_zone FROM legs WHERE camera_id=?", (cam,)) if oz}
    if args.minutes is None:
        mx = src.execute("SELECT MAX(timestamp_video) FROM vehicle_events WHERE camera_id=? AND rejected=0", (cam,)).fetchone()[0]
        t0 = (datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}") - VIDEO_START).total_seconds()
        args.minutes = math.ceil((mx - t0) / 60.0)
    rows = src.execute("SELECT event_id,origin_leg_id,destination_leg_id,movement,trajectory_data,timestamp_video "
                       "FROM vehicle_events WHERE camera_id=? AND rejected=0", (cam,)).fetchall()
    src.close()

    def nearest(pt):
        return min(legs, key=lambda l: math.hypot(pt[0]-legs[l][0], pt[1]-legs[l][1]))

    # bank turn cells (origin,dest) whose polyline is a snap-magnet: near-STRAIGHT
    # AND wildly OVER-SUPPORTED vs manual volume (real turns curve and have
    # support ~ manual; the support-ratio condition is what spares cam2's real
    # short/straight turns). Mirrors the production build_bank gate.
    magnet_cells = set()
    bank_path = Path(f"evaluations/recal_cam{cam}.json")
    if bank_path.exists():
        man_cell = manual_od_by_cell(args.start_hms, args.minutes, camera_id=cam)
        for p in json.loads(bank_path.read_text()).get("paths", []):
            if p.get("movement_label") not in TURNS:
                continue
            poly = p["polyline"]
            L = sum(math.hypot(poly[i][0]-poly[i-1][0], poly[i][1]-poly[i-1][1]) for i in range(1, len(poly)))
            s = math.hypot(poly[-1][0]-poly[0][0], poly[-1][1]-poly[0][1]) / L if L else 1.0
            man = man_cell.get((p["origin_leg_id"], p["destination_leg_id"]), 0)
            if s > args.poly_thr and p.get("supporting_count", 0) > args.magnet_support_factor * max(man, 1):
                magnet_cells.add((p["origin_leg_id"], p["destination_leg_id"]))

    drop = set()
    n_turns = 0
    if args.filter == "oracle":
        man = manual_od_by_cell(args.start_hms, args.minutes, camera_id=cam)  # (ol,dl)->manual
        by_cell = defaultdict(list)
        for eid, ol, dl, mv, tj, ts in rows:
            if mv in TURNS:
                by_cell[(ol, dl)].append((eid, ts))
        for cell, evs in by_cell.items():
            cap = int(round(man.get(cell, 0)))
            evs.sort(key=lambda e: e[1])
            for eid, _ in evs[cap:]:
                drop.add(eid)
    else:
        for eid, ol, dl, mv, tj, ts in rows:
            if mv not in TURNS:
                continue
            n_turns += 1
            try:
                t = json.loads(tj) if tj else []
            except Exception:
                t = []
            if len(t) < 2:
                continue
            if args.filter == "origin":
                if legs and nearest(t[0]) != ol:
                    drop.add(eid)
            elif args.filter == "origin2":
                # self-limiting: origin-rewrite AND the track is geometrically a
                # through (straight). Real turns curve -> spared (preserves cam1).
                if legs and nearest(t[0]) != ol and _straightness(t) > args.thr:
                    drop.add(eid)
            elif args.filter == "straight":
                if _straightness(t) > args.thr:
                    drop.add(eid)
            elif args.filter == "polymagnet":
                if (ol, dl) in magnet_cells:
                    drop.add(eid)
            elif args.filter == "combo":
                # origin-consistency OR drop turns riding a straight magnet polyline
                if (legs and nearest(t[0]) != ol) or (ol, dl) in magnet_cells:
                    drop.add(eid)
            elif args.filter == "combo2":
                # production design: self-limiting origin gate OR build-bank magnet cell
                if (legs and nearest(t[0]) != ol and _straightness(t) > args.thr) or (ol, dl) in magnet_cells:
                    drop.add(eid)

    tmp = Path(tempfile.gettempdir()) / f"snapmag_cam{cam}_{args.filter}.db"
    shutil.copy2(PROJ_DB, tmp)
    c = sqlite3.connect(str(tmp))
    with c:
        if drop:
            c.executemany("UPDATE vehicle_events SET rejected=1 WHERE event_id=?", [(i,) for i in drop])
    c.close()
    print(f"cam{cam} filter={args.filter} thr={args.thr}: turn events={n_turns}, dropped={len(drop)}\n")
    subprocess.run([sys.executable, "scripts/od_accuracy.py", "--camera", str(cam),
                    "--db", str(tmp), "--start-hms", args.start_hms,
                    "--minutes", str(args.minutes), "--show-od"], check=False)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
