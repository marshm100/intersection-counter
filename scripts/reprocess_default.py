"""REPROCESS THE FLEET UNDER THE DEFAULT (operator go 2026-09-10).

G-DEF-1 passed and the four rules now default ON in backend/config.py.
This applies the default to all 12 production windows so the live
standings ARE the default's. No environment flags are set — that is
the point. Flow per window = the ship flow (named pre-ship backup once;
force_once disposition; run_pass2(apply=True) through the apply gate,
which takes its own backup and rebuilds the worklist). Afterwards:
event counts per window compared with the G-DEF-1 d1 arm (they must
match — same code, same dumps, same flags), and health sidecars
rewritten for all 12.

Refuses to run if any of the four rules is not ON in the process.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.config as cfg  # noqa: E402

RULES = ("GATE_GROUND_ANCHOR", "STRAIGHT_FRAGMENT_RULE",
         "GATE_EVIDENCE_EITHER_CORNER", "JOURNEY_STATE_MACHINE",
         "STRAIGHT_FRAGMENT_INCLUDE_PATH_FITS")
assert all(getattr(cfg, r) for r in RULES), "the default is not ON in config"
import os  # noqa: E402
assert not any(os.environ.get(r) for r in RULES), \
    "env overrides set — the reprocess must run on the DEFAULT alone"

from backend.config import PROJECTS_DIR  # noqa: E402
from backend.database import get_db_path, set_disposition  # noqa: E402
from backend.services.study_health import window_health  # noqa: E402
from backend.services.two_pass import run_pass2  # noqa: E402

P = "97a7849a"
WINDOWS = [(1, "study_0700"), (1, "study_1600"),
           (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
           (3, "study_0600"),
           (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]
NOTE = "operator go 2026-09-10: reprocess under THE DEFAULT (G-DEF-1 PASS)"
ARM = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")


def main() -> int:
    proj_db = Path(get_db_path(P))
    con = sqlite3.connect(proj_db)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = proj_db.parent / "backups" / f"project_{ts}_pre_default_reprocess_gdef4.db"
    shutil.copy2(proj_db, backup)
    print(f"pre-reprocess backup: {backup} ({backup.stat().st_size // 2**20} MB)",
          flush=True)
    print(f"rules ON: {', '.join(RULES)}; env overrides: none", flush=True)

    workdir = Path(PROJECTS_DIR) / P / "two_pass"
    rows = []
    for cam, variant in WINDOWS:
        t = time.time()
        set_disposition(P, cam, variant, "force_once", NOTE)
        res = run_pass2(P, cam, variant=variant, workdir=workdir, apply=True)
        rep = res.get("replay") or {}
        act = res.get("evidence_activation") or {}
        gate = res.get("apply_gate") or {}
        arm_events = None
        st = ARM / "arm" / f"twopass_cam{cam}_{variant}.stats.json"
        # the d1 arm's working DB is the last one written for this window
        d1 = ARM / f"d7_cam{cam}_{variant}.db"
        if d1.exists():
            c = sqlite3.connect(f"file:{d1}?mode=ro", uri=True)
            arm_events = c.execute(
                "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? AND rejected=0",
                (cam,)).fetchone()[0]
            c.close()
        print(f"cam{cam} {variant}: applied={res.get('applied')} "
              f"gate={gate.get('decision')} ({','.join(gate.get('reasons', []))}) "
              f"events={rep.get('events')} (d1 arm db rows {arm_events}) "
              f"dropped={rep.get('insufficient_data')} cov={act.get('coverage')} "
              f"{'ON' if act.get('activated') else 'OFF'}  ({time.time() - t:.0f}s)",
              flush=True)
        rows.append((cam, variant, res.get("applied"), rep.get("events"), arm_events))
        if not res.get("applied"):
            print("STOP: window did not apply", flush=True)
            return 1

    print("\nHEALTH sidecars (all 12):", flush=True)
    for cam, variant in WINDOWS:
        h = window_health(P, cam, variant, write=True)
        print(f"  cam{cam} {variant}: {h.get('verdict') if h else 'no signals'}",
              flush=True)
    print("\nDONE. Standings are now the default's; re-score with "
          "scripts/v2_score_dev.py on the d1_*.db files (production column).",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
