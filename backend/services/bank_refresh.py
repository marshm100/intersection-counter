"""Bank refresh — teach the flow priors the current truth.

Charter: docs/plan_study_health_2026-08-28.md:63-67; gate
docs/plan_bank_refresh_2026-09-06.md (G-BR-1). The priors on
intersection_paths (supporting_count + sample_window_seconds) were
bootstrapped in June while the pipeline undercounted; the shipped
basis now exceeds some of them 30-70x. This module re-derives them
FROM THE SHIPPED BASIS (vehicle_events rejected=0) — never by
re-running the GT-free builder (wholesale swaps measured
catastrophic twice: docs/bank_coverage_audit_2026-07-09.md).

THE ONE NON-DESTRUCTIVE WRITER: every existing intersection_paths
writer replaces whole rows (apply_bank.py DELETE+reinsert). This
module UPDATEs ONLY the two prior columns on existing rows —
polyline, movement_label, source, expected_speed are never touched.
Cells with shipped traffic but no bank row are reported, never
created (a prior needs a polyline row; geometry synthesis is
chartered, out of scope).
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path


def _connect(project_id: str, db_path: str | Path | None) -> sqlite3.Connection:
    if db_path is not None:
        return sqlite3.connect(str(db_path))
    from backend.database import get_connection
    return get_connection(project_id)


def shipped_cell_counts(conn: sqlite3.Connection,
                        camera_id: int) -> dict[tuple[int, int], int]:
    """Shipped-basis count per (origin_leg_id, destination_leg_id).

    rejected=0 IS the shipped basis (there is no 'counted' column).
    Events without both legs resolved carry no cell and are skipped.
    """
    return {(int(o), int(d)): int(n) for o, d, n in conn.execute(
        "SELECT origin_leg_id, destination_leg_id, COUNT(*) "
        "FROM vehicle_events WHERE camera_id = ? AND rejected = 0 "
        "AND origin_leg_id IS NOT NULL AND destination_leg_id IS NOT NULL "
        "GROUP BY origin_leg_id, destination_leg_id", (camera_id,))}


def study_window_seconds(conn: sqlite3.Connection, camera_id: int) -> float:
    """Total shipped-study duration for the camera's intersection.

    Summed from the trims table — event->trim linkage is unreliable
    (production has thousands of NULL trim_ids), the trims themselves
    are the authority on what was studied.
    """
    row = conn.execute("SELECT intersection_id FROM cameras "
                       "WHERE camera_id = ?", (camera_id,)).fetchone()
    if row is None:
        return 0.0
    total = 0.0
    for start, end in conn.execute(
            "SELECT start_wallclock, end_wallclock FROM trims "
            "WHERE intersection_id = ?", (row[0],)):
        try:
            t0 = datetime.strptime(start, "%H:%M:%S")
            t1 = datetime.strptime(end, "%H:%M:%S")
        except ValueError:
            t0 = datetime.strptime(start, "%H:%M")
            t1 = datetime.strptime(end, "%H:%M")
        total += (t1 - t0).total_seconds()
    return total


def refresh_bank(project_id: str, camera_id: int, *,
                 db_path: str | Path | None = None,
                 write: bool = False,
                 sidecar_dir: str | Path | None = None) -> dict:
    """Compute (and optionally write) the refreshed priors for one camera.

    Returns {"rows": [per-row before/after], "no_row_cells": [...],
    "window_seconds": float, "written": bool}. With write=True the
    narrow UPDATE runs in one transaction and a rollback sidecar
    (bank_refresh_rollback_cam{N}.json) records the exact old values
    next to the DB (or in sidecar_dir).
    """
    conn = _connect(project_id, db_path)
    try:
        counts = shipped_cell_counts(conn, camera_id)
        window_s = study_window_seconds(conn, camera_id)
        rows = []
        for pid_, o, d, mv, sc, sw in conn.execute(
                "SELECT path_id, origin_leg_id, destination_leg_id, "
                "movement_label, supporting_count, sample_window_seconds "
                "FROM intersection_paths WHERE camera_id = ? "
                "ORDER BY origin_leg_id, destination_leg_id", (camera_id,)):
            new_n = counts.get((int(o), int(d)), 0)
            rows.append({"path_id": int(pid_), "origin_leg_id": int(o),
                         "destination_leg_id": int(d), "movement": mv,
                         "old_count": int(sc), "old_window_s": sw,
                         "new_count": int(new_n), "new_window_s": window_s})
        banked = {(r["origin_leg_id"], r["destination_leg_id"]) for r in rows}
        no_row = [{"origin_leg_id": o, "destination_leg_id": d, "counted": n}
                  for (o, d), n in sorted(counts.items()) if (o, d) not in banked]

        written = False
        if write and rows and window_s > 0:
            sd = Path(sidecar_dir) if sidecar_dir else (
                Path(db_path).parent if db_path else
                Path(f"data/projects/{project_id}"))
            sd.mkdir(parents=True, exist_ok=True)
            (sd / f"bank_refresh_rollback_cam{camera_id}.json").write_text(
                json.dumps({"camera_id": camera_id,
                            "refreshed_at": datetime.now().isoformat(),
                            "rows": [{"path_id": r["path_id"],
                                      "supporting_count": r["old_count"],
                                      "sample_window_seconds": r["old_window_s"]}
                                     for r in rows]}, indent=2))
            with conn:
                for r in rows:
                    conn.execute(
                        "UPDATE intersection_paths SET supporting_count = ?, "
                        "sample_window_seconds = ? WHERE path_id = ?",
                        (r["new_count"], window_s, r["path_id"]))
            written = True
        return {"rows": rows, "no_row_cells": no_row,
                "window_seconds": window_s, "written": written}
    finally:
        conn.close()


def rollback_bank(project_id: str, camera_id: int, *,
                  db_path: str | Path | None = None,
                  sidecar_dir: str | Path | None = None) -> int:
    """Restore the exact pre-refresh values from the rollback sidecar."""
    sd = Path(sidecar_dir) if sidecar_dir else (
        Path(db_path).parent if db_path else Path(f"data/projects/{project_id}"))
    payload = json.loads(
        (sd / f"bank_refresh_rollback_cam{camera_id}.json").read_text())
    conn = _connect(project_id, db_path)
    try:
        with conn:
            for r in payload["rows"]:
                conn.execute(
                    "UPDATE intersection_paths SET supporting_count = ?, "
                    "sample_window_seconds = ? WHERE path_id = ?",
                    (r["supporting_count"], r["sample_window_seconds"],
                     r["path_id"]))
        return len(payload["rows"])
    finally:
        conn.close()
