"""Stage-2 A/B: same-camera duplicate-track dedup on THROUGH events. One vehicle
sometimes gets two near-coincident full-length tracks (bytetrack ID duplication);
the hybrid runs no_dedup=True so nothing removes them. This non-destructively
merges through events that overlap >50% in time AND stay within --sep px of each
other over the overlap (keep the longest-duration of each group), on a TEMP copy
of project.db, then re-measures with od_accuracy.

Turns are left untouched (low volume; snap-magnet gate already handles them).

Usage: py scripts/replay_dedup.py --camera 5 --sep 25 --minutes 30
"""
from __future__ import annotations
import argparse, json, math, os, shutil, sqlite3, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from groundtruth import VIDEO_START

PROJ_DB = "data/projects/97a7849a/project.db"


def _sep_over_overlap(a, b):
    _, sfa, efa, ta = a
    _, sfb, efb, tb = b
    lo, hi = max(sfa, sfb), min(efa, efb)
    if hi <= lo:
        return 1e9
    n, tot = 8, 0.0
    for k in range(n + 1):
        f = lo + (hi - lo) * k / n
        ia = min(len(ta) - 1, max(0, round((f - sfa) / (efa - sfa) * (len(ta) - 1)))) if efa > sfa else 0
        ib = min(len(tb) - 1, max(0, round((f - sfb) / (efb - sfb) * (len(tb) - 1)))) if efb > sfb else 0
        tot += math.hypot(ta[ia][0] - tb[ib][0], ta[ia][1] - tb[ib][1])
    return tot / (n + 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--sep", type=float, default=25.0, help="max mean separation (px) to call a duplicate")
    ap.add_argument("--overlap-frac", type=float, default=0.5)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=None)
    ap.add_argument("--db", default=PROJ_DB,
                    help="events DB to dedup (default: live project.db) — lets the pass "
                         "compose with a retrack DB (e.g. the cam2 bank-D arm)")
    ap.add_argument("--movements", default="through",
                    help="comma list of movements to dedup, or 'all' "
                         "(concurrent-dedup plan 2026-07-09: cam2's ID-splits sit in "
                         "TURN cells; scope is an ablation axis)")
    ap.add_argument("--out-db", default=None,
                    help="write the deduped DB here and KEEP it (default: temp, deleted); "
                         "skips the od_accuracy re-measure when set")
    args = ap.parse_args()
    cam = args.camera

    src = sqlite3.connect(args.db)
    if args.minutes is None:
        mx = src.execute("SELECT MAX(timestamp_video) FROM vehicle_events WHERE camera_id=? AND rejected=0", (cam,)).fetchone()[0]
        t0 = (__import__("datetime").datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}") - VIDEO_START).total_seconds()
        args.minutes = math.ceil((mx - t0) / 60.0)
    if args.movements == "all":
        mv_where = "1=1"
        mv_params: tuple = ()
    else:
        mvs = [m.strip() for m in args.movements.split(",") if m.strip()]
        mv_where = "movement IN (%s)" % ",".join("?" * len(mvs))
        mv_params = tuple(mvs)
    rows = src.execute("SELECT event_id,start_frame,frame_number,trajectory_data,origin_leg_id,destination_leg_id,movement "
                       f"FROM vehicle_events WHERE camera_id=? AND rejected=0 AND ({mv_where})",
                       (cam, *mv_params)).fetchall()
    src.close()

    # group by (OD cell, movement); only same-cell events can be duplicates of one vehicle
    by_cell: dict = {}
    for eid, sf, ef, tj, ol, dl, mv in rows:
        try:
            t = json.loads(tj) if tj else []
        except Exception:
            t = []
        if sf is None or ef is None or len(t) < 2:
            continue
        by_cell.setdefault((ol, dl, mv), []).append((eid, sf, ef, t))

    drop = set()
    for cell, evs in by_cell.items():
        n = len(evs)
        parent = list(range(n))
        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]; x = parent[x]
            return x
        for i in range(n):
            for j in range(i + 1, n):
                ov = min(evs[i][2], evs[j][2]) - max(evs[i][1], evs[j][1])
                if ov <= 0:
                    continue
                if ov / min(evs[i][2] - evs[i][1], evs[j][2] - evs[j][1]) < args.overlap_frac:
                    continue
                if _sep_over_overlap(evs[i], evs[j]) < args.sep:
                    parent[find(i)] = find(j)
        groups: dict = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        for members in groups.values():
            if len(members) < 2:
                continue
            keep = max(members, key=lambda i: evs[i][2] - evs[i][1])  # longest-duration survives
            for i in members:
                if i != keep:
                    drop.add(evs[i][0])

    tmp = Path(args.out_db) if args.out_db else Path(tempfile.gettempdir()) / f"dedup_cam{cam}.db"
    shutil.copy2(args.db, tmp)
    c = sqlite3.connect(str(tmp))
    with c:
        if drop:
            c.executemany("UPDATE vehicle_events SET rejected=1 WHERE event_id=?", [(i,) for i in drop])
    c.close()
    print(f"cam{cam} dedup sep={args.sep}px overlap>={args.overlap_frac} movements={args.movements}: "
          f"candidate events={len(rows)}, merged-away={len(drop)}\n")
    if args.out_db:
        print(f"(kept deduped DB at {tmp} — measure it yourself)")
        return 0
    subprocess.run([sys.executable, "scripts/od_accuracy.py", "--camera", str(cam),
                    "--db", str(tmp), "--start-hms", args.start_hms,
                    "--minutes", str(args.minutes)], check=False)
    try:
        os.remove(tmp)
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
