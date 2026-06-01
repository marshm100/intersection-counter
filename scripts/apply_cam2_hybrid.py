"""Build (and optionally apply) the cam2 regime-hybrid: bytetrack THROUGHS (from
project.db, good at cam2) + BoT-SORT merged TURNS (from cam2_bank.db). Best cam2
config (21.1%/38.4% vs 26.5% baseline). Writes a hybrid DB; --apply swaps cam2's
events into project.db (backup first) + applies the cam2 bank paths.

Usage:
  py scripts/apply_cam2_hybrid.py                 # build hybrid DB + report
  py scripts/apply_cam2_hybrid.py --apply         # + write to project.db
"""
from __future__ import annotations
import argparse, json, shutil, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from groundtruth import VIDEO_START, NORM_MVT
from hybrid_ocbot import merge_turn_fragments
from measure_cam2 import manual_per_minute_cam2, LEG_IDX

PROJECT = "97a7849a"
CAMERA = 2
PROJ_DB = f"data/projects/{PROJECT}/project.db"
BOT_DB = f"data/projects/{PROJECT}/_hybrid_tmp/cam2_bank.db"
BANK = "evaluations/recal_cam2.json"


def _bot_turn_keep_ids(start_hms, minutes):
    """Load BoT turn events (cam2_bank.db) with real event_id, volume-gated merge,
    return the kept event_ids."""
    start_sec = (datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{start_hms}") - VIDEO_START).total_seconds()
    mins = [datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{start_hms}") + timedelta(minutes=i) for i in range(int(minutes))]
    m_mv = manual_per_minute_cam2()
    inv = {v: k for k, v in LEG_IDX.items()}
    man_tot = defaultdict(float)
    for mn in mins:
        for (ii, mvt), n in m_mv.get(mn, {}).items():
            man_tot[(inv.get(ii), mvt)] += n
    c = sqlite3.connect(BOT_DB)
    rows = c.execute("SELECT event_id,origin_leg_id,destination_leg_id,movement,start_frame,frame_number,trajectory_data,timestamp_video "
                     "FROM vehicle_events WHERE camera_id=2 AND rejected=0 AND movement IN ('left','right','u_turn')").fetchall()
    c.close()
    turns = []
    for eid, ol, dl, mv, sf, ef, tj, ts in rows:
        if not (start_sec <= ts < start_sec + minutes * 60):
            continue
        try: traj = json.loads(tj) if tj else []
        except Exception: traj = []
        turns.append({"id": eid, "ol": ol, "dl": dl, "mv": mv, "s": sf or ef, "e": ef or sf,
                      "start": traj[0] if traj else None})
    exp = defaultdict(float)
    for e in turns:
        exp[(e["ol"], e["dl"])] = man_tot.get((e["ol"], NORM_MVT.get(e["mv"], e["mv"])), 0)
    keep = merge_turn_fragments(turns, 30.0, 40.0, expected_by_cell=exp, vol_factor=1.3)
    return keep, len(turns)


def build(out_db, start_hms, minutes):
    keep, n_turn = _bot_turn_keep_ids(start_hms, minutes)
    shutil.copy2(PROJ_DB, out_db)
    c = sqlite3.connect(out_db)
    cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall() if r[1] != "event_id"]
    cl = ",".join(cols)
    c.execute("ATTACH DATABASE ? AS bot", (BOT_DB,))
    with c:
        # keep bytetrack THROUGHS already in project.db; drop bytetrack turns
        c.execute("DELETE FROM vehicle_events WHERE camera_id=? AND NOT (movement='through')", (CAMERA,))
        idf = ",".join(str(i) for i in keep) or "-1"
        ins = c.execute(f"INSERT INTO vehicle_events ({cl}) SELECT {cl} FROM bot.vehicle_events "
                        f"WHERE camera_id=? AND movement IN ('left','right','u_turn') AND event_id IN ({idf})",
                        (CAMERA,)).rowcount
        # apply cam2 bank paths
        sug = json.loads(Path(BANK).read_text())
        c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (CAMERA,))
        now = datetime.now().isoformat()
        for p in sug.get("paths", []):
            c.execute("INSERT OR REPLACE INTO intersection_paths (camera_id,origin_leg_id,destination_leg_id,polyline,movement_label,supporting_count,source,created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (CAMERA, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                       p["movement_label"], p.get("supporting_count", 0), p.get("source", "data-driven"), now))
    c.execute("DETACH DATABASE bot")
    c.close()
    print(f"hybrid cam2: bytetrack throughs kept + BoT turns {n_turn}->{ins} merged -> {out_db}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--out-db", default=f"data/projects/{PROJECT}/_hybrid_tmp/cam2_hybrid.db")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    build(args.out_db, args.start_hms, args.minutes)
    if args.apply:
        ts = VIDEO_START.strftime("%Y%m%d")
        backup = Path(f"data/projects/{PROJECT}/backups/{ts}_pre_cam2_hybrid.db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJ_DB, backup)
        c = sqlite3.connect(PROJ_DB)
        cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall() if r[1] != "event_id"]
        cl = ",".join(cols)
        c.execute("ATTACH DATABASE ? AS h", (args.out_db,))
        with c:
            before = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (CAMERA,)).fetchone()[0]
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (CAMERA,))
            c.execute(f"INSERT INTO vehicle_events ({cl}) SELECT {cl} FROM h.vehicle_events WHERE camera_id=?", (CAMERA,))
            c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (CAMERA,))
            c.execute(f"INSERT INTO intersection_paths SELECT * FROM h.intersection_paths WHERE camera_id=?", (CAMERA,))
            after = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (CAMERA,)).fetchone()[0]
        c.execute("DETACH DATABASE h")
        c.close()
        print(f"[apply] cam2 events {before} -> {after}; bank applied. Backup {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
