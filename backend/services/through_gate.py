"""Bank-gated through filter — FM51 audit #4 (2026-07-06).

Reject events labelled movement='through' whose (origin,dest) is NOT a real
through-pair in the bank (a bank path with movement='through' AND supporting_count
>= min_support). A through connects OPPOSING legs; a "through" from a T-stem is
geometrically impossible and is typically a short fragment of a main-road through
vehicle whose origin was mis-read onto the adjacent side road — a DUPLICATE of an
already-counted vehicle, so we REJECT (not reassign — reassigning would over-count
the main road). Blind: the bank encodes the site's own real through-movements; a
4-way rejects nothing. Post-processing pass, dry-run by default.

See memory project_per_approach_attribution_2026_06_30 (FM51 #4 diagnosis).
"""
from __future__ import annotations
import sqlite3

from backend.config import THROUGH_GATE_MIN_SUPPORT
from backend.database import get_db_path, list_paths_for_camera


_TURNS = ("left", "right", "u_turn")


def bank_turn_pairs(paths, min_support: int = 1) -> set:
    """{(origin_leg, dest_leg)} that the bank POSITIVELY labels as a TURN (a path
    with movement in left/right/u_turn and support >= min_support). Because
    intersection_paths is UNIQUE per (camera, origin, dest), one bank path defines
    a pair's movement — so a turn here means a 'through' event for that pair is a
    mis-classification. We key off the POSITIVE turn signal (not 'absent from the
    through set') so real throughs whose bank path is channel-drawn/support-0 are
    never touched — a 4-way rejects nothing."""
    return {(p.get("origin_leg_id"), p.get("destination_leg_id"))
            for p in paths
            if p.get("movement_label") in _TURNS
            and (p.get("supporting_count") or 0) >= min_support
            and p.get("origin_leg_id") is not None
            and p.get("destination_leg_id") is not None}


def is_invalid_through(movement, origin, dest, turn_pairs) -> bool:
    """True when a 'through' event runs between a pair the bank knows is a TURN."""
    if movement != "through" or origin is None or dest is None:
        return False
    return (origin, dest) in turn_pairs


def reject_invalid_throughs(project_id: str, camera_id: int, *, apply: bool = False,
                            min_support: int | None = None) -> dict:
    """Mark rejected=1 on this camera's 'through' events whose (origin,dest) is not a
    real bank through-pair. Dry-run by default; apply=True writes. Returns counts."""
    min_support = THROUGH_GATE_MIN_SUPPORT if min_support is None else min_support
    turn_pairs = bank_turn_pairs(list_paths_for_camera(project_id, camera_id), min_support)
    conn = sqlite3.connect(str(get_db_path(project_id)), timeout=10)
    rows = conn.execute(
        "SELECT rowid, origin_leg_id, destination_leg_id FROM vehicle_events "
        "WHERE camera_id=? AND movement='through' AND COALESCE(rejected,0)=0",
        (camera_id,)).fetchall()
    bogus = [rid for rid, o, d in rows if is_invalid_through("through", o, d, turn_pairs)]
    result = {"through_events": len(rows), "bank_turn_pairs": len(turn_pairs),
              "rejected": len(bogus), "applied": False}
    if apply and bogus:
        conn.executemany("UPDATE vehicle_events SET rejected=1 WHERE rowid=?",
                         [(i,) for i in bogus])
        conn.commit()
        result["applied"] = True
    conn.close()
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Reject geometrically-invalid 'through' events")
    ap.add_argument("--project", required=True)
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--apply", action="store_true", help="write (default: dry-run)")
    a = ap.parse_args()
    print(reject_invalid_throughs(a.project, a.camera, apply=a.apply))
