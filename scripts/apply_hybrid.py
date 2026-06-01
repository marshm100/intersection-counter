"""Build (and optionally apply) the regime-hybrid for ANY corridor camera:
bytetrack THROUGHS (from project.db) + BoT-SORT merged TURNS (from the bank
retrack DB) + the camera's path bank. Camera-parameterized generalization of
apply_cam2_hybrid.py + cam2_hybrid_measure.py (the cam2 deadline build: best =
21.1%/38.4%). Picks the throughs tracker per camera by measurement upstream;
this combines the chosen throughs with volume-gated, merged BoT turns.

Prereqs (per camera N):
  - project.db has bytetrack events for cam N (from reprocess_camera.py)
  - the bank retrack DB exists: data/projects/<proj>/_hybrid_tmp/camN_bank.db
    (from apply_bank.py, no --apply) and evaluations/recal_camN.json

Usage:
  py scripts/apply_hybrid.py --camera 3                 # build hybrid DB + measure
  py scripts/apply_hybrid.py --camera 3 --apply         # + write to project.db (backup first)
"""
from __future__ import annotations
import argparse, json, shutil, sqlite3, subprocess, sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from groundtruth import VIDEO_START, NORM_MVT
from hybrid_ocbot import merge_turn_fragments
from od_accuracy import manual_per_minute, leg_idx

PROJECT = "97a7849a"
PROJ_DB = f"data/projects/{PROJECT}/project.db"


def _bot_turn_keep_ids(camera_id, bot_db, start_hms, minutes):
    """Load BoT turn events (from the bank retrack DB) with real event_id,
    volume-gated intra-turn merge, return the kept event_ids. The expected
    per-cell volume comes from the camera's Miovision manual movement totals."""
    start_sec = (datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{start_hms}") - VIDEO_START).total_seconds()
    mins = [datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{start_hms}") + timedelta(minutes=i)
            for i in range(int(minutes))]
    _, m_mv, _ = manual_per_minute(camera_id)
    inv = {idx: leg for leg, idx in leg_idx(camera_id).items()}   # approach idx -> our leg
    man_tot = defaultdict(float)                                   # (origin_leg, mvt) -> manual count
    for mn in mins:
        for (ii, mvt), n in m_mv.get(mn, {}).items():
            man_tot[(inv.get(ii), mvt)] += n
    c = sqlite3.connect(bot_db)
    rows = c.execute("SELECT event_id,origin_leg_id,destination_leg_id,movement,start_frame,frame_number,trajectory_data,timestamp_video "
                     "FROM vehicle_events WHERE camera_id=? AND rejected=0 AND movement IN ('left','right','u_turn')",
                     (camera_id,)).fetchall()
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


def build(camera_id, out_db, bot_db, bank, start_hms, minutes):
    keep, n_turn = _bot_turn_keep_ids(camera_id, bot_db, start_hms, minutes)
    shutil.copy2(PROJ_DB, out_db)
    c = sqlite3.connect(out_db)
    cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall() if r[1] != "event_id"]
    cl = ",".join(cols)
    c.execute("ATTACH DATABASE ? AS bot", (bot_db,))
    with c:
        # keep bytetrack THROUGHS already in project.db; drop bytetrack turns
        c.execute("DELETE FROM vehicle_events WHERE camera_id=? AND NOT (movement='through')", (camera_id,))
        idf = ",".join(str(i) for i in keep) or "-1"
        ins = c.execute(f"INSERT INTO vehicle_events ({cl}) SELECT {cl} FROM bot.vehicle_events "
                        f"WHERE camera_id=? AND movement IN ('left','right','u_turn') AND event_id IN ({idf})",
                        (camera_id,)).rowcount
        # apply bank paths
        sug = json.loads(Path(bank).read_text())
        c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (camera_id,))
        now = datetime.now().isoformat()
        for p in sug.get("paths", []):
            c.execute("INSERT OR REPLACE INTO intersection_paths (camera_id,origin_leg_id,destination_leg_id,polyline,movement_label,supporting_count,source,created_at) VALUES (?,?,?,?,?,?,?,?)",
                      (camera_id, p["origin_leg_id"], p["destination_leg_id"], json.dumps(p["polyline"]),
                       p["movement_label"], p.get("supporting_count", 0), p.get("source", "data-driven"), now))
    c.execute("DETACH DATABASE bot")
    c.close()
    print(f"hybrid cam{camera_id}: bytetrack throughs kept + BoT turns {n_turn}->{ins} merged -> {out_db}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--out-db", default=None)
    ap.add_argument("--bot-db", default=None)
    ap.add_argument("--bank", default=None)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    cam = args.camera
    out_db = args.out_db or f"data/projects/{PROJECT}/_hybrid_tmp/cam{cam}_hybrid.db"
    bot_db = args.bot_db or f"data/projects/{PROJECT}/_hybrid_tmp/cam{cam}_bank.db"
    bank = args.bank or f"evaluations/recal_cam{cam}.json"
    Path(out_db).parent.mkdir(parents=True, exist_ok=True)

    build(cam, out_db, bot_db, bank, args.start_hms, args.minutes)

    # measure the hybrid DB with the universal metric
    print()
    subprocess.run([sys.executable, "scripts/od_accuracy.py", "--camera", str(cam),
                    "--db", out_db, "--start-hms", args.start_hms,
                    "--minutes", str(args.minutes)], check=False)

    if args.apply:
        ts = VIDEO_START.strftime("%Y%m%d")
        backup = Path(f"data/projects/{PROJECT}/backups/{ts}_pre_cam{cam}_hybrid.db")
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(PROJ_DB, backup)
        c = sqlite3.connect(PROJ_DB)
        cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)").fetchall() if r[1] != "event_id"]
        cl = ",".join(cols)
        c.execute("ATTACH DATABASE ? AS h", (out_db,))
        with c:
            before = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (cam,)).fetchone()[0]
            c.execute("DELETE FROM vehicle_events WHERE camera_id=?", (cam,))
            c.execute(f"INSERT INTO vehicle_events ({cl}) SELECT {cl} FROM h.vehicle_events WHERE camera_id=?", (cam,))
            c.execute("DELETE FROM intersection_paths WHERE camera_id=?", (cam,))
            c.execute("INSERT INTO intersection_paths SELECT * FROM h.intersection_paths WHERE camera_id=?", (cam,))
            after = c.execute("SELECT COUNT(*) FROM vehicle_events WHERE camera_id=?", (cam,)).fetchone()[0]
        c.execute("DETACH DATABASE h")
        c.close()
        print(f"\n[apply] cam{cam} events {before} -> {after}; bank applied. Backup {backup}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
