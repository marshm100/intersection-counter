"""SHIP G-SM-1 iteration 3 to production (operator go 2026-09-09: "Sure").

Windows: cam1 study_0700, cam2 study_0700, cam2 study_1100, cam3
study_0600 — the four that passed their declared gate on the sm3 arm.
Flow = the cam1-0700 (09-07) and cam1-1600 (09-08) ships:
  1. named pre-ship backup of project.db (WAL checkpointed first);
  2. per window: disposition force_once (operator go), then
     run_pass2(apply=True) through the apply gate, which takes its own
     pre_twopass backup, swaps the window's events in, rebuilds the
     flag queue (worklist);
  3. isolation: every camera's vehicle_events OUTSIDE the shipped
     hours must hash identical to the pre-ship backup; cam4/cam5
     entirely;
  4. health sidecars rewritten for the four windows.
Requires the shipped flag set in the environment:
  GATE_GROUND_ANCHOR=1 STRAIGHT_FRAGMENT_RULE=1 GATE_EVIDENCE_EITHER_CORNER=1
  JOURNEY_STATE_MACHINE=1
"""
from __future__ import annotations

import hashlib
import shutil
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import (GATE_EVIDENCE_EITHER_CORNER,  # noqa: E402
                            GATE_GROUND_ANCHOR, JOURNEY_STATE_MACHINE,
                            PROJECTS_DIR, STRAIGHT_FRAGMENT_RULE)

assert (GATE_GROUND_ANCHOR and STRAIGHT_FRAGMENT_RULE
        and GATE_EVIDENCE_EITHER_CORNER and JOURNEY_STATE_MACHINE), "flags not armed"

from backend.database import get_db_path, set_disposition  # noqa: E402
from backend.services.study_health import window_health  # noqa: E402
from backend.services.two_pass import run_pass2  # noqa: E402

P = "97a7849a"
SHIP = [(1, "study_0700"), (2, "study_0700"), (2, "study_1100"),
        (3, "study_0600")]
HOURS = {"study_0700": (7, 9), "study_1100": (11, 13),
         "study_1600": (16, 18), "study_0600": (6, 20)}
NOTE = "operator go 2026-09-09 (G-SM-1 iteration 3, sm3 arm)"


def rows_hash(db: Path, cam: int, exclude: list[tuple[int, int]]) -> tuple[str, int, int]:
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = con.execute(
        "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, movement,"
        " timestamp_real, frame_number, rejected FROM vehicle_events"
        " WHERE camera_id=? ORDER BY event_id", (cam,)).fetchall()
    con.close()
    keep, inside = [], 0
    for r in rows:
        ts = r[4] or ""
        hour = int(ts[11:13]) if len(ts) >= 13 else -1
        if any(lo <= hour < hi for lo, hi in exclude):
            inside += 1
            continue
        keep.append(r)
    h = hashlib.md5(repr(keep).encode()).hexdigest()
    return h, len(keep), inside


def main() -> int:
    proj_db = Path(get_db_path(P))
    con = sqlite3.connect(proj_db)
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.close()
    ts = datetime.now().strftime("%Y%m%dT%H%M%S")
    backup = proj_db.parent / "backups" / f"project_{ts}_pre_ship_gsm1.db"
    shutil.copy2(proj_db, backup)
    print(f"pre-ship backup: {backup} ({backup.stat().st_size // 2**20} MB)",
          flush=True)

    workdir = Path(PROJECTS_DIR) / P / "two_pass"
    for cam, variant in SHIP:
        t = time.time()
        set_disposition(P, cam, variant, "force_once", NOTE)
        res = run_pass2(P, cam, variant=variant, workdir=workdir, apply=True)
        rep = res.get("replay") or {}
        act = res.get("evidence_activation") or {}
        gate = res.get("apply_gate") or {}
        print(f"cam{cam} {variant}: applied={res.get('applied')} "
              f"gate={gate.get('decision')} ({','.join(gate.get('reasons', []))}) "
              f"events={rep.get('events')} dropped={rep.get('insufficient_data')} "
              f"cov={act.get('coverage')} {'ON' if act.get('activated') else 'OFF'} "
              f"backup={Path(res.get('backup', '')).name} "
              f"flags={res.get('flags')}  ({time.time() - t:.0f}s)", flush=True)
        if not res.get("applied"):
            print("STOP: window did not apply", flush=True)
            return 1

    print("\nISOLATION vs pre-ship backup (vehicle_events outside shipped hours):")
    shipped = {}
    for cam, variant in SHIP:
        shipped.setdefault(cam, []).append(HOURS[variant])
    ok = True
    for cam in (1, 2, 3, 4, 5):
        ex = shipped.get(cam, [])
        h0, n0, in0 = rows_hash(backup, cam, ex)
        h1, n1, in1 = rows_hash(proj_db, cam, ex)
        same = (h0 == h1)
        ok = ok and same
        print(f"  cam{cam}: outside-hours rows {n0} -> {n1} "
              f"{'IDENTICAL' if same else 'CHANGED  <-- BREACH'}; "
              f"shipped-hours rows {in0} -> {in1}")
    print("isolation:", "PASS" if ok else "FAIL")

    print("\nHEALTH sidecars:")
    for cam, variant in SHIP:
        h = window_health(P, cam, variant, write=True)
        if h is None:
            print(f"  cam{cam} {variant}: no signals")
            continue
        verdict = {k: v for k, v in h.items()
                   if k in ("verdict", "colour", "color", "grade", "status")}
        print(f"  cam{cam} {variant}: {verdict}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
