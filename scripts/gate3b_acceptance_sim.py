"""§3-B residual — acceptance-layer composition simulation
(plan_3b_validation_2026-07-28, "still owed" item; closed 2026-07-28).

The phase-0 matrix validated the SPOT layer; this composes the full
`acceptance()` verdict (corridor consistency × reverse balance × the
stratified spot rule) on a SCRATCH COPY of the corridor project with
simulated-perfect spot counts inserted per the phase-0 protocol
(stratified windows, seed 97, extend-to-certify). project.db untouched.

Expectations (from the phase-0 record): no intersection composes to a
false "ship"; cam5's intersection stays review-or-worse (its windows
carry binding approach rows); cam3's stays review/fail (night segments/
claim scope). Evidence -> runs/3b_validation/acceptance_sim.json
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.database import get_connection
from backend.services.spot_check import (
    _processed_segments, _rec_offset_seconds, acceptance, compare_spot_count,
    propose_windows)
import gate3b_phase0 as G0
import triangulate_manual as T

SRC = Path("data/projects/97a7849a/project.db")
SIM_PID = "3bsim_tmp"
SIM_DIR = Path(f"data/projects/{SIM_PID}")
OUT = Path("runs/3b_validation/acceptance_sim.json")
SEED = 97
MINUTES = 30.0


def main() -> int:
    SIM_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SRC, SIM_DIR / "project.db")
    try:
        conn = get_connection(SIM_PID)
        cams = {cid: iid for cid, iid in conn.execute(
            "SELECT camera_id, intersection_id FROM cameras")}
        conn.close()

        # Insert simulated-perfect spot counts per the phase-0 protocol.
        inserted = {}
        for cam in sorted(cams):
            mio = T.load_miovision(cam)
            rec = _rec_offset_seconds(SIM_PID, cam)
            pw = propose_windows(SIM_PID, cam, minutes=MINUTES, seed=SEED)
            rows = []
            for w in pw.get("windows", []):
                start, dur = w["start_seconds"], w["duration_seconds"]
                seg_end = w["segment"][1]
                manual = G0.gt_manual_counts(mio, rec, start, dur)
                rep = compare_spot_count(SIM_PID, cam, start, dur, manual)
                while (rep["verdict"] == "review" and rep["total"]["manual"]
                       and rep["total"]["rel_err"] is not None
                       and abs(rep["total"]["rel_err"]) <= 0.05
                       and "extend the count" in rep["note"]
                       and dur < 3600.0 and start + dur < seg_end - 60.0):
                    dur = min(dur + 900.0, 3600.0, seg_end - start)
                    manual = G0.gt_manual_counts(mio, rec, start, dur)
                    rep = compare_spot_count(SIM_PID, cam, start, dur, manual)
                conn = get_connection(SIM_PID)
                with conn:
                    conn.execute(
                        "INSERT INTO spot_counts (camera_id, start_seconds, "
                        "duration_seconds, manual_counts, notes, created_at) "
                        "VALUES (?, ?, ?, ?, 'acceptance-sim', '2026-07-28')",
                        (cam, start, dur, json.dumps(manual)))
                conn.close()
                rows.append({"segment": w["segment_index"], "start": start,
                             "dur": dur, "verdict": rep["verdict"]})
            inserted[cam] = rows
            print(f"[A] cam{cam}: {len(rows)} spot rows "
                  f"({[r['verdict'] for r in rows]})", flush=True)

        # Compose acceptance per intersection (shared volume cache).
        cache: dict = {}
        composed = {}
        for cam, iid in sorted(cams.items()):
            acc = acceptance(SIM_PID, iid, _cache=cache)
            items = {i["item"]: i["verdict"] for i in acc["items"]}
            composed[iid] = {"camera": cam, "items": items,
                             "overall": acc.get("overall")}
            print(f"[A] intersection {iid} (cam{cam}): {items} "
                  f"overall={composed[iid]['overall']}", flush=True)

        false_ship = [iid for iid, c in composed.items()
                      if c["overall"] == "ship" and c["camera"] in (3, 5)]
        result = {"seed": SEED, "spot_rows": inserted, "composed": composed,
                  "false_ship_intersections": false_ship}
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(result, indent=1))
        print(f"[A] false-ship on GT-fail cameras: {false_ship}", flush=True)
        print(f"wrote {OUT}", flush=True)
        print("ACCEPTANCE SIM DONE", flush=True)
        return 0
    finally:
        shutil.rmtree(SIM_DIR, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
