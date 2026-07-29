"""Stage 5.1C — backfill echo_suspect flags into the CURRENT production
queue (plan_stage5_phantom_2026-07-29, 5.1C; the queue must not be
rebuilt — S5 loss — so the S6 feeder's output is INSERTED).

Per corridor camera:
  tier C (production census event-join valid): cells from the
    footage-rating census (same source the runtime feeder uses).
  tier B (legacy table, join refused — cam4/cam5 class): cells from the
    phase-0 REPLAY censuses (runs/cam5_wall/chain_census_97a7_c{N}.json,
    single-cell excess keys summed across windows), basis recorded per
    flag. The pool exists on both tracking bases; the flag points at a
    (cell), not at events, so the pointer is basis-robust.

Idempotent: a camera with open echo_suspect flags is skipped.
  python scripts/echo_suspect_backfill.py            insert
  python scripts/echo_suspect_backfill.py --revert   delete all echo_suspect
Evidence -> printed table; the gate re-run is scripts/rule595_phantom_inventory.py.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.database import insert_flags
from backend.services.cardinals import bound_approach
from backend.services.flag_feeders import ECHO_CELL_MIN_EXCESS
from backend.services.footage_rating import rate_camera
import cam5_wall_phase0 as P0

PROJECT = "97a7849a"
PHASE0 = {c: Path(f"runs/cam5_wall/chain_census_97a7_c{c}.json")
          for c in (1, 2, 3, 4, 5)}
_MVFULL = {"thru": "through", "uturn": "u_turn"}


def phase0_cells(cam: int) -> list[dict]:
    """Same-cell pools from the phase-0 replay census (single-cell keys
    of excess_by_cellpair_top, summed across windows)."""
    d = json.loads(PHASE0[cam].read_text())
    pool: Counter = Counter()
    for w in d.values():
        for key, n in w.get("excess_by_cellpair_top", {}).items():
            cells = key.split("+")
            if len(cells) == 1:
                o, dd = (int(x) for x in cells[0].split(">"))
                pool[(o, dd)] += n
    return [{"origin_leg_id": o, "destination_leg_id": dd, "excess": n}
            for (o, dd), n in sorted(pool.items(), key=lambda kv: -kv[1])]


def main() -> int:
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    conn.row_factory = sqlite3.Row
    if "--revert" in sys.argv:
        with conn:
            n = conn.execute("DELETE FROM review_flags WHERE "
                             "subtype='echo_suspect'").rowcount
        conn.close()
        print(f"[EB] reverted: deleted {n} echo_suspect flags")
        return 0

    card = {r["leg_id"]: (r["cardinal_direction"] or "").strip().upper()
            for r in conn.execute("SELECT leg_id, cardinal_direction FROM legs")}
    label = {r["leg_id"]: r["label"] for r in conn.execute(
        "SELECT leg_id, label FROM legs")}
    cams = {r["camera_id"]: r["intersection_id"] for r in conn.execute(
        "SELECT camera_id, intersection_id FROM cameras")}

    for cam, iid in sorted(cams.items()):
        already = conn.execute(
            "SELECT COUNT(*) FROM review_flags WHERE camera_id=? AND "
            "subtype='echo_suspect' AND status='open'", (cam,)).fetchone()[0]
        if already:
            print(f"[EB] cam{cam}: {already} open echo_suspect flags exist — skip")
            continue
        census = rate_camera(PROJECT, cam)["metrics"]["census"]
        if census and census.get("event_join_valid"):
            cells = census.get("echo_cells", [])
            basis = "production_chain_census"
        else:
            cells = phase0_cells(cam)
            basis = "phase0_replay_census"
        flags = []
        for c in cells:
            if c["excess"] < ECHO_CELL_MIN_EXCESS:
                continue
            o, d = c["origin_leg_id"], c["destination_leg_id"]
            mv = c.get("movement")
            if mv is None:
                nm = P0._cell_name(card, o, d)
                if nm is None:
                    continue
                mv = _MVFULL.get(nm[1], nm[1])
            ap = bound_approach(card.get(o, ""))
            flags.append({
                "kind": "suspected_gap", "subtype": "echo_suspect",
                "camera_id": cam, "approach": ap, "movement": mv,
                "impact": float(c["excess"]),
                "reason": (f"{ap}B {mv} ({label.get(o, o)} -> "
                           f"{label.get(d, d)}): about {int(c['excess'])} "
                           f"counts this day repeat the same vehicle "
                           f"(track-fragment echo) — this movement can "
                           f"read HIGHER than reality. Review its failing "
                           f"bins; reject the duplicate events."),
                "evidence": {"origin_leg_id": o, "destination_leg_id": d,
                             "same_cell_excess": c["excess"], "basis": basis},
                "batch_key": None,
            })
        insert_flags(PROJECT, iid, flags)
        print(f"[EB] cam{cam} [{basis}]: inserted {len(flags)} — " +
              "; ".join(f"{f['approach']}B {f['movement']} "
                        f"({int(f['impact'])})" for f in flags), flush=True)
    conn.close()
    print("ECHO BACKFILL DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
