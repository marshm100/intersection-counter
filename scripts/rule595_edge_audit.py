"""Step 1.3 — bin-edge audit (plan_595_standard_2026-07-28, Stage 1).

Question: are the window-edge 5/95 failures (17:45-class worst rows)
REAL peak variance, or manufactured by a clock offset between our event
timestamps (box-crossing on the recording clock) and Miovision's bin
clock? A systematic offset shifts vehicles across bin boundaries at high
flow — worst exactly at edges/peaks.

Method: sweep a global shift s in [-120, +120] s applied to OUR events
per camera; recompute 5/95 compliance at each s. A consistent optimum
with a material gain (> ~2 points) = clock artifact (fix = comparison-
layer offset + a recording-start correction note); a flat curve = the
failures are real variance.

Evidence -> runs/3b_validation/rule595_edge_audit.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import sqlite3

import triangulate_manual as T
from rule595_compliance import CORRIDOR, DAYLIGHT, score

PROJECT = "97a7849a"
SHIFTS = list(range(-120, 121, 15))
OUT = Path("runs/3b_validation/rule595_edge_audit.json")


def load_ours_shifted(cam: int, shift_s: float):
    """T.load_ours with a global +shift on event wall-clock."""
    c = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    leg_dir = {lid: T._CARD_TO_DIR.get((card or "").strip().upper())
               for lid, card in c.execute(
                   "SELECT leg_id,cardinal_direction FROM legs WHERE camera_id=?",
                   (cam,))}
    norm = {"through": "thru", "u_turn": "uturn"}
    out = defaultdict(lambda: defaultdict(int))
    for olid, mv, ts in c.execute(
            "SELECT origin_leg_id, movement, timestamp_real FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)):
        d = leg_dir.get(olid)
        if ts and d:
            t = datetime.fromisoformat(ts) + timedelta(seconds=shift_s)
            key = t.time().replace(second=0, microsecond=0)
            out[key][(d, norm.get(mv, mv))] += 1
    c.close()
    return out


def main() -> int:
    result = {}
    for cam, hours in CORRIDOR.items():
        mio = T.load_miovision(cam)
        if hours is None:
            minutes = [m for m in sorted(mio.keys())
                       if DAYLIGHT[0] <= m.hour < DAYLIGHT[1]]
        else:
            minutes = [dtime(h, m) for lo, hi in hours
                       for h in range(lo, hi) for m in range(60)]
        curve = {}
        for s in SHIFTS:
            ours = load_ours_shifted(cam, s)
            rows = score(ours, mio, minutes)
            ok = sum(1 for r in rows if r["ok"])
            curve[s] = round(100.0 * ok / len(rows), 1) if rows else None
        base = curve[0]
        best_s = max(curve, key=lambda k: (curve[k] or 0))
        result[f"cam{cam}"] = {"curve": curve, "base_pct": base,
                               "best_shift_s": best_s,
                               "best_pct": curve[best_s],
                               "gain": round((curve[best_s] or 0) - (base or 0), 1)}
        print(f"[EA] cam{cam}: base {base}% best {curve[best_s]}% at "
              f"{best_s:+d}s (gain {result[f'cam{cam}']['gain']})", flush=True)

    gains = [v["gain"] for v in result.values()]
    shifts = [v["best_shift_s"] for v in result.values()]
    verdict = ("CLOCK-ARTIFACT candidate" if any(g > 2.0 for g in gains)
               else "REAL variance (no material shift gain)")
    result["_verdict"] = {"verdict": verdict, "gains": gains,
                          "best_shifts": shifts}
    print(f"[EA] VERDICT: {verdict} (gains {gains}, shifts {shifts})",
          flush=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("EDGE AUDIT DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
