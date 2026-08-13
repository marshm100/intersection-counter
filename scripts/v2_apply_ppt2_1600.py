"""OPERATOR-ADJUDICATED APPLY — PPT-2 re-attribution, cam2 study_1600.
docs/plan_gate_ag2_2026-08-13.md (gate-passed candidate, operator "go
for it" 2026-08-13). Follows the audited _finish_apply sequence with
the shipped primitives: fresh record=True adjudication at apply time →
timestamped pre-apply backup + rotation → _apply_window_events. The
flag-queue rebuild is DEFERRED (it consumes pass-2 borderline rows a
re-attribution candidate does not carry; recorded in the apply doc).

Refuses to run while the server holds port 5000 (the 2026-08-10
precedent: applies happen against a quiesced DB).
"""
from __future__ import annotations

import shutil
import socket
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from backend.database import get_connection, get_db_path        # noqa: E402
from backend.services.apply_gate import adjudicate_apply        # noqa: E402
from backend.services.two_pass import (_apply_window_events,    # noqa: E402
                                       _rotate_backups,
                                       gate_census_inputs)

PROJECT = "97a7849a"
CAM = 2
VARIANT = "study_1600"
FPS = 25.0
F_LO, F_HI = 1439950, 1619950
CAND = Path("data/projects/97a7849a/_replay_scratch/ppt/ag2/"
            "p1_live_cam2_study_1600.db")


def window_sig(db, t_lo, t_hi):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    sig = Counter((int(t), o, d, m) for t, o, d, m in conn.execute(
        "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
        "movement FROM vehicle_events WHERE camera_id=? "
        "AND COALESCE(rejected,0)=0 AND timestamp_video >= ? "
        "AND timestamp_video < ?", (CAM, t_lo, t_hi)))
    conn.close()
    return sig


def main() -> int:
    t_lo, t_hi = F_LO / FPS, F_HI / FPS
    # ---- preconditions ------------------------------------------------------
    s = socket.socket()
    port_free = s.connect_ex(("127.0.0.1", 5000)) != 0
    s.close()
    if not port_free:
        print("ABORT: server still holds port 5000 — stop it first")
        return 1
    if not CAND.exists():
        print(f"ABORT: candidate missing: {CAND}")
        return 1
    proj = get_db_path(PROJECT)
    conn = sqlite3.connect(f"file:{proj}?mode=ro", uri=True)
    ncols = len(conn.execute("PRAGMA table_info(vehicle_events)").fetchall())
    n_live = conn.execute(
        "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? "
        "AND COALESCE(rejected,0)=0 AND timestamp_video >= ? "
        "AND timestamp_video < ?", (CAM, t_lo, t_hi)).fetchone()[0]
    conn.close()
    conn = sqlite3.connect(f"file:{CAND}?mode=ro", uri=True)
    ncols_c = len(conn.execute("PRAGMA table_info(vehicle_events)").fetchall())
    n_cand = conn.execute(
        "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? "
        "AND COALESCE(rejected,0)=0 AND timestamp_video >= ? "
        "AND timestamp_video < ?", (CAM, t_lo, t_hi)).fetchone()[0]
    conn.close()
    print(f"pre-checks: schema {ncols_c}=={ncols} cols; window kept "
          f"{n_cand}=={n_live}")
    if ncols_c != ncols or n_cand != n_live:
        print("ABORT: precondition failed")
        return 1

    # ---- fresh adjudication at apply time (record=True → audit trail) ------
    conn = get_connection(PROJECT)
    chash = conn.execute(
        "SELECT content_hash FROM videos WHERE camera_id=? "
        "ORDER BY sort_order LIMIT 1", (CAM,)).fetchone()[0]
    conn.close()
    census, confusion = gate_census_inputs(PROJECT, CAM, chash, VARIANT, FPS)
    v = adjudicate_apply(PROJECT, CAM, VARIANT, incumbent_db=proj,
                         candidate_db=CAND, t_lo=t_lo, t_hi=t_hi,
                         census=census, confusion=confusion, record=True,
                         mode="reattribution", fps=FPS)
    print(f"adjudication (recorded): {v['decision']} [{','.join(v['reasons'])}]")
    if v["decision"] != "apply":
        print("ABORT: gate did not pass at apply time")
        return 1

    # ---- backup + swap (the audited primitives) -----------------------------
    backup = proj.parent / "backups" / (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_pre_twopass_cam{CAM}.db")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(proj, backup)
    _rotate_backups(backup.parent)
    print(f"backup: {backup}")
    want = window_sig(CAND, t_lo, t_hi)
    _apply_window_events(proj, CAND, CAM, t_lo, t_hi)

    # ---- post-verify --------------------------------------------------------
    got = window_sig(proj, t_lo, t_hi)
    n_after = sum(got.values())
    others_ok = True
    conn = sqlite3.connect(f"file:{proj}?mode=ro", uri=True)
    for label, lo, hi, expect in (("study_0700", 629950 / FPS, 809950 / FPS,
                                   5815),
                                  ("study_1100", 989950 / FPS, 1169950 / FPS,
                                   4426)):
        n = conn.execute(
            "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? "
            "AND COALESCE(rejected,0)=0 AND timestamp_video >= ? "
            "AND timestamp_video < ?", (CAM, lo, hi)).fetchone()[0]
        ok = n == expect
        others_ok &= ok
        print(f"post-verify {label}: {n} (expect {expect}) "
              f"{'OK' if ok else 'CHANGED — INVESTIGATE'}")
    conn.close()
    print(f"post-verify {VARIANT}: kept={n_after} (expect {n_cand}) "
          f"multiset=={'MATCH' if got == want else 'MISMATCH'}")
    if got != want or n_after != n_cand or not others_ok:
        print(f"POST-VERIFY FAILED — restore from {backup}")
        return 1
    print("APPLIED: cam2 study_1600 re-attribution is live.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
