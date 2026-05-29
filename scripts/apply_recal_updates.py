"""Apply a direction-based recalibration suggestion (recalibrate_camera.py output).

Consumes the `recal_cam1.json` schema (top-level `updated_legs` + `paths`, with leg
ids ALREADY resolved) and writes it to the project DB. This is NOT the auto_cal
schema, so `apply_auto_cal.py` cannot consume it — hence a dedicated apply path.

CRITICAL — why this bypasses PUT /calibration/legs:
  Both PUT /calibration/legs handlers do a DESTRUCTIVE full replace
  (DELETE vehicle_events; DELETE legs; reinsert). With only ~112 surviving real
  trajectories for this camera and NO BACKUP, that path would be a second
  unrecoverable trajectory loss. Recalibration only changes origin_zone[0] +
  reference_heading on EXISTING leg rows, so we do a narrow in-place UPDATE that
  never touches `legs` membership or `vehicle_events`.

Re-attribution note: the surviving events keep their OLD attribution until an
explicit reprocess/replay — applying legs/paths does not re-snap stored events.
See docs/recalibration_plan_2026-05-27.md (Step 5).

Safety: dry-run by default; --apply makes a consistent VACUUM INTO backup of the
project DB before the first write.

Usage:
  py scripts/apply_recal_updates.py                       # dry-run (default)
  py scripts/apply_recal_updates.py --apply               # write
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import get_connection, get_db_path, list_paths_for_camera

VALID_MOVES = {"through", "left", "right", "u_turn"}

# Preservation invariant: a camera's events are those tagged with its camera_id
# OR (legacy, camera_id=NULL) carrying one of its leg_ids. Mirrors the catch-all
# in save_camera_calibration (backend/routers/calibration.py).
_EVENT_PREDICATE = (
    "camera_id = ? OR origin_leg_id IN (SELECT leg_id FROM legs WHERE camera_id = ?)"
)


def _count_events(conn: sqlite3.Connection, camera_id: int) -> int:
    return int(conn.execute(
        f"SELECT COUNT(*) FROM vehicle_events WHERE {_EVENT_PREDICATE}",
        (camera_id, camera_id),
    ).fetchone()[0])


def _load_legs(project_id: str, camera_id: int) -> dict[int, dict]:
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT leg_id, label, origin_zone, reference_heading "
            "FROM legs WHERE camera_id = ?", (camera_id,),
        ).fetchall()
    finally:
        conn.close()
    return {r[0]: {"label": r[1], "origin_zone": r[2], "reference_heading": r[3]}
            for r in rows}


def _backup_db(project_id: str, camera_id: int, expected_events: int) -> Path:
    """Checkpointed, VERIFIED single-file snapshot before any mutation.

    WAL+OneDrive on Windows can leave a VACUUM INTO silently short of committed
    rows still in the -wal file, so we (1) checkpoint(TRUNCATE) the live WAL into
    the main db first, (2) VACUUM INTO a fresh target, then (3) open the backup
    and assert it passes integrity_check AND holds exactly the events we expect.
    Raises on any failure — better to abort than apply against a bad backup.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
    bak_dir = get_db_path(project_id).parent / "backups"
    bak_dir.mkdir(parents=True, exist_ok=True)
    bak = bak_dir / f"project_{stamp}.db"
    if bak.exists():
        raise RuntimeError(f"backup target already exists: {bak}")

    src = get_connection(project_id)  # ensures schema/WAL on the live db
    try:
        src.execute("PRAGMA busy_timeout = 10000")
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        src.execute("VACUUM INTO ?", (str(bak),))
    finally:
        src.close()

    if not bak.exists():
        raise RuntimeError("VACUUM INTO reported success but no backup file exists")
    chk = sqlite3.connect(str(bak))
    try:
        integ = chk.execute("PRAGMA integrity_check").fetchone()[0]
        if integ != "ok":
            raise RuntimeError(f"backup failed integrity_check: {integ}")
        got = _count_events(chk, camera_id)
        if got != expected_events:
            raise RuntimeError(
                f"backup event count {got} != expected {expected_events} "
                "(WAL not fully captured?) — aborting before any mutation")
    finally:
        chk.close()
    return bak


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera-id", type=int, default=1)
    ap.add_argument("--suggestion", default="evaluations/recal_cam1.json")
    ap.add_argument("--apply", action="store_true",
                    help="actually write (default is dry-run)")
    ap.add_argument("--no-save-suggestion", action="store_true",
                    help="skip persisting the suggestion audit row")
    args = ap.parse_args()

    payload = json.loads(Path(args.suggestion).read_text())
    updated_legs = payload.get("updated_legs", [])
    paths = payload.get("paths", [])
    legs = _load_legs(args.project, args.camera_id)
    _c = get_connection(args.project)
    try:
        event_count_before = _count_events(_c, args.camera_id)
    finally:
        _c.close()

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"=== recal apply [{mode}] project={args.project} camera={args.camera_id} ===")
    print(f"suggestion: {len(updated_legs)} leg updates, {len(paths)} paths")
    print(f"current camera legs: {sorted(legs)}; vehicle_events: {event_count_before}\n")

    # --- Preflight: validate everything BEFORE any write -------------------
    errors: list[str] = []
    for ul in updated_legs:
        lid = ul["leg_id"]
        if lid not in legs:
            errors.append(f"updated leg {lid} does not exist for camera {args.camera_id}")
            continue
        old = legs[lid]
        old_origin = (json.loads(old["origin_zone"]) if old["origin_zone"] else None)
        if "origin_point" in ul:
            origin_change = f"origin {old_origin and old_origin[0]} -> {ul['origin_point']}"
        else:
            origin_change = f"origin {old_origin and old_origin[0]} (UNCHANGED, heading-only)"
        print(f"  leg L{lid} ({old.get('label') or ul.get('approach','?')}): "
              f"{origin_change}, heading {old['reference_heading']} -> {ul['reference_heading']}")

    valid_paths, skipped_paths = [], []
    for p in paths:
        o, d = p.get("origin_leg_id"), p.get("destination_leg_id")
        mv = p.get("movement_label")
        if d is None:
            skipped_paths.append((p, "destination_leg_id is None (column is NOT NULL)"))
        elif o not in legs or d not in legs:
            skipped_paths.append((p, f"leg id missing (o={o}, d={d})"))
        elif mv not in VALID_MOVES:
            skipped_paths.append((p, f"bad movement_label {mv!r}"))
        else:
            valid_paths.append(p)
    print()
    for p in valid_paths:
        print(f"  path L{p['origin_leg_id']}->L{p['destination_leg_id']} "
              f"{p['movement_label']:>7} n={p.get('supporting_count', 0)} "
              f"{len(p['polyline'])}pts")
    for p, why in skipped_paths:
        print(f"  SKIP path L{p.get('origin_leg_id')}->L{p.get('destination_leg_id')} "
              f"{p.get('movement_label')}: {why}")

    if errors:
        print("\nPREFLIGHT FAILED:")
        for e in errors:
            print(f"  - {e}")
        return 1
    if not valid_paths and not updated_legs:
        print("\nNothing to apply.")
        return 1

    existing_paths = list_paths_for_camera(args.project, args.camera_id)
    print(f"\nwould clear {len(existing_paths)} existing path(s), "
          f"write {len(valid_paths)} new (source=data-driven)")

    if not args.apply:
        print("\n[DRY-RUN] no changes written. Re-run with --apply to commit.")
        return 0

    # --- Apply -------------------------------------------------------------
    # Verified backup FIRST (raises and aborts before any mutation if unsound),
    # then the entire mutation in ONE transaction so a crash can never leave
    # legs moved with paths half-written. We inline the SQL (rather than calling
    # upsert_path / clear_paths_for_camera, which each open their own
    # connection) precisely so it is one atomic unit on one connection.
    print("\nPlease ensure no processing is running on this camera before applying.")
    bak = _backup_db(args.project, args.camera_id, event_count_before)
    print(f"verified backup -> {bak}")

    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection(args.project)
    try:
        conn.execute("PRAGMA busy_timeout = 10000")
        with conn:  # single atomic transaction
            for ul in updated_legs:
                if "origin_point" in ul:
                    # caller explicitly supplies a trusted origin -> update both
                    conn.execute(
                        "UPDATE legs SET origin_zone = ?, reference_heading = ? "
                        "WHERE leg_id = ? AND camera_id = ?",
                        (json.dumps([list(ul["origin_point"])]), ul["reference_heading"],
                         ul["leg_id"], args.camera_id))
                else:
                    # heading-only: keep the engineer-placed origin (the data-driven
                    # origin is unreliable at this camera — band-wide starts).
                    conn.execute(
                        "UPDATE legs SET reference_heading = ? "
                        "WHERE leg_id = ? AND camera_id = ?",
                        (ul["reference_heading"], ul["leg_id"], args.camera_id))
            n_cleared = conn.execute(
                "DELETE FROM intersection_paths WHERE camera_id = ?",
                (args.camera_id,)).rowcount
            for p in valid_paths:
                conn.execute(
                    "INSERT INTO intersection_paths "
                    "(camera_id, origin_leg_id, destination_leg_id, polyline, "
                    " movement_label, supporting_count, source, last_observed_at, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'data-driven', NULL, ?)",
                    (args.camera_id, p["origin_leg_id"], p["destination_leg_id"],
                     json.dumps(p["polyline"]), p["movement_label"],
                     p.get("supporting_count", 0), now))
            if not args.no_save_suggestion:
                meta = json.dumps({"applied_via": "scripts/apply_recal_updates.py",
                                   "backup": str(bak)})
                pj = json.dumps(payload)
                ex = conn.execute(
                    "SELECT suggestion_id FROM calibration_suggestions WHERE camera_id = ?",
                    (args.camera_id,)).fetchone()
                if ex:
                    conn.execute(
                        "UPDATE calibration_suggestions SET payload_json=?, status='applied', "
                        "generated_at=?, applied_at=?, job_metadata=? WHERE camera_id=?",
                        (pj, now, now, meta, args.camera_id))
                else:
                    conn.execute(
                        "INSERT INTO calibration_suggestions "
                        "(camera_id, payload_json, status, generated_at, applied_at, job_metadata) "
                        "VALUES (?, ?, 'applied', ?, ?, ?)",
                        (args.camera_id, pj, now, now, meta))
            event_count_after = _count_events(conn, args.camera_id)
            n_paths_after = conn.execute(
                "SELECT COUNT(*) FROM intersection_paths WHERE camera_id = ?",
                (args.camera_id,)).fetchone()[0]
            # Final guard INSIDE the txn: if events were touched, roll everything back.
            if event_count_after != event_count_before:
                raise RuntimeError(
                    f"vehicle_events changed {event_count_before}->{event_count_after}; "
                    "rolling back — nothing applied")
    finally:
        conn.close()

    for ul in updated_legs:
        what = "origin+heading" if "origin_point" in ul else "heading only (origin kept)"
        print(f"  updated L{ul['leg_id']}: {what}")
    print(f"  cleared {n_cleared} old path(s); wrote {len(valid_paths)} data-driven path(s)")
    if not args.no_save_suggestion:
        print("  saved suggestion audit row (status=applied)")
    print(f"\nvehicle_events: {event_count_before} -> {event_count_after} (PRESERVED)")
    print(f"intersection_paths now: {n_paths_after} rows  (backup: {bak})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
