"""OPERATOR-ADJUDICATED APPLY — generalized re-attribution apply
(docs/plan_gate_ag2_2026-08-13.md; the audited _finish_apply sequence:
fresh record=True adjudication under the validated reattribution mode →
timestamped pre-apply backup + rotation → _apply_window_events → exact
post-verify). Refuses to run while the server holds port 5000. The
flag-queue rebuild is deferred (recorded in the apply docs).

Usage:
  py -X utf8 scripts/v2_apply_reattr.py --camera 2 --variant v2c_study_1100 \
      --f-lo 989950 --f-hi 1169950 --fps 25 \
      --candidate <db> [--verify-window LABEL:LO:HI:COUNT ...]
"""
from __future__ import annotations

import argparse
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


def window_sig(db, cam, t_lo, t_hi):
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    sig = Counter((int(t), o, d, m) for t, o, d, m in conn.execute(
        "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
        "movement FROM vehicle_events WHERE camera_id=? "
        "AND COALESCE(rejected,0)=0 AND timestamp_video >= ? "
        "AND timestamp_video < ?", (cam, t_lo, t_hi)))
    conn.close()
    return sig


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True,
                    help="dump variant for census + integrity (the "
                         "candidate's TRACK-ID SPACE, e.g. v2c_study_1100 "
                         "for an applied-artifact window)")
    ap.add_argument("--f-lo", type=int, required=True)
    ap.add_argument("--f-hi", type=int, required=True)
    ap.add_argument("--fps", type=float, required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--verify-window", action="append", default=[],
                    help="LABEL:T_LO:T_HI:EXPECTED_COUNT — other windows "
                         "that must be untouched")
    args = ap.parse_args()
    cam = args.camera
    t_lo, t_hi = args.f_lo / args.fps, args.f_hi / args.fps
    cand = Path(args.candidate)

    s = socket.socket()
    port_free = s.connect_ex(("127.0.0.1", 5000)) != 0
    s.close()
    if not port_free:
        print("ABORT: server still holds port 5000 — stop it first")
        return 1
    if not cand.exists():
        print(f"ABORT: candidate missing: {cand}")
        return 1
    proj = get_db_path(PROJECT)
    for db, name in ((proj, "live"), (cand, "candidate")):
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        n = len(conn.execute("PRAGMA table_info(vehicle_events)").fetchall())
        conn.close()
        if name == "live":
            ncols = n
        elif n != ncols:
            print(f"ABORT: schema mismatch {n} != {ncols}")
            return 1
    n_live = sum(window_sig(proj, cam, t_lo, t_hi).values())
    n_cand = sum(window_sig(cand, cam, t_lo, t_hi).values())
    print(f"pre-checks: schema {ncols} cols both; window kept "
          f"{n_cand}=={n_live}")
    if n_cand != n_live:
        print("ABORT: kept-mass precondition failed")
        return 1

    conn = get_connection(PROJECT)
    chash = conn.execute(
        "SELECT content_hash FROM videos WHERE camera_id=? "
        "ORDER BY sort_order LIMIT 1", (cam,)).fetchone()[0]
    conn.close()
    census, confusion = gate_census_inputs(PROJECT, cam, chash,
                                           args.variant, args.fps)
    v = adjudicate_apply(PROJECT, cam, args.variant, incumbent_db=proj,
                         candidate_db=cand, t_lo=t_lo, t_hi=t_hi,
                         census=census, confusion=confusion, record=True,
                         mode="reattribution", fps=args.fps)
    print(f"adjudication (recorded): {v['decision']} "
          f"[{','.join(v['reasons'])}]")
    if v["decision"] != "apply":
        print("ABORT: gate did not pass at apply time")
        return 1

    backup = proj.parent / "backups" / (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_pre_twopass_cam{cam}.db")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(proj, backup)
    _rotate_backups(backup.parent)
    print(f"backup: {backup}")
    want = window_sig(cand, cam, t_lo, t_hi)
    _apply_window_events(proj, cand, cam, t_lo, t_hi)

    got = window_sig(proj, cam, t_lo, t_hi)
    ok = got == want and sum(got.values()) == n_cand
    print(f"post-verify window: kept={sum(got.values())} (expect {n_cand}) "
          f"multiset=={'MATCH' if got == want else 'MISMATCH'}")
    conn = sqlite3.connect(f"file:{proj}?mode=ro", uri=True)
    for spec in args.verify_window:
        label, lo, hi, expect = spec.split(":")
        n = conn.execute(
            "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? "
            "AND COALESCE(rejected,0)=0 AND timestamp_video >= ? "
            "AND timestamp_video < ?",
            (cam, float(lo), float(hi))).fetchone()[0]
        this_ok = n == int(expect)
        ok &= this_ok
        print(f"post-verify {label}: {n} (expect {expect}) "
              f"{'OK' if this_ok else 'CHANGED — INVESTIGATE'}")
    conn.close()
    if not ok:
        print(f"POST-VERIFY FAILED — restore from {backup}")
        return 1
    print("APPLIED.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
