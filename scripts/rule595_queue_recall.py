"""Queue-recall vs the 5/95-failing cell-bins (MASTER_PLAN §1c item (c),
operator-directed 2026-07-28).

THE question the customer standard raises: Miovision's ~100% compliance
includes their human-fix layer; ours is the flag queue + review UX. So —
of the cell-bins that FAIL the 5/95 rule on the production tables, what
fraction does the production queue actually SURFACE for review?

Match rule (a failing cell-bin is CAUGHT when any open flag on its
camera matches):
  - approach matches the cell's bound letter (or the flag has no
    approach = camera-wide), AND movement matches (or flag movement is
    None = approach-wide), AND
  - the flag's interval overlaps the bin (interval_*_seconds are video
    seconds; bins are wall-clock -> rec-offset conversion), OR its
    linked event's timestamp lands in the bin, OR the flag carries
    neither (cell/camera-scoped, e.g. S4) -> matches all bins.

Reported: recall overall + for BIG failures (|delta| >= 20 vehicles —
the ones that matter to a deliverable), + open-flag workload per camera.
Corridor only (FM51's project predates the current feeders; noted).
Evidence -> runs/3b_validation/rule595_queue_recall.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import triangulate_manual as T
from backend.services.spot_check import _rec_offset_seconds
from rule595_compliance import CORRIDOR, DAYLIGHT, score

PROJECT = "97a7849a"
OUT = Path("runs/3b_validation/rule595_queue_recall.json")
BIG = 20


def main() -> int:
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    result = {}
    for cam, hours in CORRIDOR.items():
        ours = T.load_ours(cam)
        mio = T.load_miovision(cam)
        if hours is None:
            minutes = [m for m in sorted(mio.keys())
                       if DAYLIGHT[0] <= m.hour < DAYLIGHT[1]]
        else:
            minutes = [dtime(h, m) for lo, hi in hours
                       for h in range(lo, hi) for m in range(60)]
        fails = [r for r in score(ours, mio, minutes) if not r["ok"]]

        rec = _rec_offset_seconds(PROJECT, cam) or 0
        flags = []
        for (kind, subtype, event_id, i0, i1, appr, mv) in conn.execute(
                "SELECT kind, subtype, event_id, interval_start_seconds, "
                "interval_end_seconds, approach, movement FROM review_flags "
                "WHERE camera_id=? AND (status IS NULL OR status NOT IN "
                "('resolved', 'dismissed'))", (cam,)):
            ev_ts = None
            if event_id is not None:
                row = conn.execute(
                    "SELECT timestamp_video FROM vehicle_events WHERE "
                    "event_id=?", (event_id,)).fetchone()
                ev_ts = row[0] if row else None
            flags.append({"subtype": subtype, "i0": i0, "i1": i1,
                          "appr": appr, "mv": mv, "ev_ts": ev_ts})

        def caught_by(f, bin_hm, cell):
            # vocabulary bridge: cells are "NB thru" (bound+B, short
            # movement); flags store approach='N', movement='through'.
            b_appr, b_mv = cell.split(" ", 1)
            b_appr = b_appr.rstrip("B")
            b_mv = {"thru": "through", "uturn": "u_turn"}.get(b_mv, b_mv)
            if f["appr"] and f["appr"] != b_appr:
                return False
            if f["mv"] and f["mv"] != b_mv:
                return False
            h, m = int(bin_hm[:2]), int(bin_hm[3:])
            wall0 = h * 3600 + m * 60
            v0, v1 = wall0 - rec, wall0 + 900 - rec       # bin in video secs
            if f["i0"] is not None and f["i1"] is not None:
                return f["i0"] < v1 and f["i1"] > v0
            if f["ev_ts"] is not None:
                return v0 <= f["ev_ts"] < v1
            return True                                    # cell/camera-scoped

        rows = []
        for r in fails:
            hits = [f["subtype"] for f in flags
                    if caught_by(f, r["bin"], r["cell"])]
            rows.append({**{k: r[k] for k in ("bin", "cell", "ours", "ref")},
                         "delta": r["ours"] - r["ref"],
                         "caught": bool(hits),
                         "subtypes": sorted(set(hits))[:4]})
        big = [r for r in rows if abs(r["delta"]) >= BIG]
        res = {
            "fails": len(rows),
            "caught": sum(1 for r in rows if r["caught"]),
            "recall_pct": round(100.0 * sum(1 for r in rows if r["caught"])
                                / len(rows), 1) if rows else None,
            "big_fails": len(big),
            "big_caught": sum(1 for r in big if r["caught"]),
            "big_recall_pct": round(100.0 * sum(1 for r in big if r["caught"])
                                    / len(big), 1) if big else None,
            "open_flags": len(flags),
            "missed_big": [{k: r[k] for k in ("bin", "cell", "ours", "ref")}
                           for r in big if not r["caught"]][:8],
        }
        result[f"cam{cam}"] = res
        print(f"[QR] cam{cam}: recall {res['recall_pct']}% "
              f"({res['caught']}/{res['fails']}), BIG {res['big_recall_pct']}% "
              f"({res['big_caught']}/{res['big_fails']}), "
              f"open flags {res['open_flags']}", flush=True)
        if res["missed_big"]:
            print(f"[QR]   missed BIG: {res['missed_big'][:3]}", flush=True)
    conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("QUEUE RECALL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
