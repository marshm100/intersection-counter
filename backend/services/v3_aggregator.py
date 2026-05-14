"""v3 aggregator: groups counts per intersection-day with cross-camera dedup.

Reads events scoped to an intersection's cameras, applies the dedup pass
over parallel-overlap regions, then produces:
  - Per-leg × per-movement count matrix (one number per cell, merged across
    cameras and trims) — feeds the main TMC sheet.
  - Per-camera × per-leg × per-movement matrix — feeds the per-camera
    breakdown sheet.

Rejected events (vehicle_events.rejected = 1) are excluded everywhere.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from backend.database import get_connection, get_intersection, list_cameras, list_videos_for_camera
from backend.services.coverage import CameraCoverage, Interval, video_to_coverage_interval
from backend.services.dedup import EventForDedup, deduplicate


MOVEMENTS = ("through", "left", "right", "u_turn")


def _camera_coverages_for_intersection(project_id: str, intersection_id: int) -> list[CameraCoverage]:
    coverages: list[CameraCoverage] = []
    for cam in list_cameras(project_id, intersection_id):
        videos = list_videos_for_camera(project_id, cam["camera_id"])
        intervals: list[Interval] = []
        for v in videos:
            start_str = v.get("recording_start_datetime") or v.get("recording_start_time")
            if not start_str:
                continue
            try:
                start = datetime.fromisoformat(start_str)
            except ValueError:
                continue
            dur = float(v.get("duration_seconds") or 0)
            if dur <= 0:
                continue
            intervals.append(video_to_coverage_interval(start, dur))
        if intervals:
            coverages.append(CameraCoverage(camera_id=cam["camera_id"], intervals=intervals))
    return coverages


def _load_events_for_dedup(
    project_id: str, camera_ids: list[int],
) -> tuple[list[EventForDedup], dict[int, dict]]:
    """Pull vehicle_events with the joins needed to compute wall-clock time
    and leg labels.

    Returns:
      (events_for_dedup, event_row_by_id) — the second dict carries all the
      raw fields per event_id, used by the aggregator after we know which
      events survived dedup.
    """
    if not camera_ids:
        return [], {}
    placeholders = ",".join("?" * len(camera_ids))
    conn = get_connection(project_id)
    try:
        import sqlite3
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            f"""SELECT ve.event_id, ve.camera_id, ve.video_id, ve.trim_id,
                       ve.vehicle_track_id, ve.origin_leg_id, ve.movement,
                       ve.vehicle_class, ve.fhwa_class,
                       ve.detection_confidence, ve.trajectory_confidence,
                       ve.timestamp_video, ve.frame_number, ve.rejected,
                       l.label              AS leg_label,
                       l.cardinal_direction AS cardinal_direction,
                       v.recording_start_datetime AS video_start
                FROM vehicle_events ve
                LEFT JOIN legs   l ON ve.origin_leg_id = l.leg_id
                LEFT JOIN videos v ON ve.video_id      = v.video_id
                WHERE ve.camera_id IN ({placeholders}) AND ve.rejected = 0""",
            tuple(camera_ids),
        ).fetchall()
    finally:
        conn.close()

    events: list[EventForDedup] = []
    raw: dict[int, dict] = {}
    for r in rows:
        row = dict(r)
        raw[row["event_id"]] = row
        # Compute wall-clock time = video_start + timestamp_video
        video_start = row.get("video_start")
        if not video_start:
            continue
        try:
            wallclock = datetime.fromisoformat(video_start) + timedelta(
                seconds=float(row["timestamp_video"] or 0)
            )
        except ValueError:
            continue
        events.append(EventForDedup(
            event_id=row["event_id"],
            camera_id=row["camera_id"],
            leg_label=row.get("leg_label") or "",
            cardinal_direction=row.get("cardinal_direction") or "",
            movement=row.get("movement") or "",
            wallclock_time=wallclock,
            detection_confidence=float(row.get("detection_confidence") or 0),
            trajectory_confidence=float(row.get("trajectory_confidence") or 0),
        ))
    return events, raw


def aggregate_intersection_day(project_id: str, intersection_id: int) -> dict:
    """Produce the count matrices for one intersection-day, dedup applied.

    Returned shape:
      {
        "intersection": {...},
        "tmc_matrix": [
          {"leg_label": "North", "through": 312, "left": 180, ...},
          ...
        ],
        "per_camera_breakdown": [
          {"camera_id": 1, "camera_label": "Cam1",
           "matrix": [{"leg_label": "North", "through": ...}, ...]},
          ...
        ],
        "totals": {"vehicles": 4012},
        "dedup_summary": {"merged": 87, "kept": 4012},
      }
    """
    intersection = get_intersection(project_id, intersection_id)
    if intersection is None:
        return {"error": "Intersection not found"}

    cameras = list_cameras(project_id, intersection_id)
    camera_ids = [c["camera_id"] for c in cameras]
    cam_label_by_id = {c["camera_id"]: c["label"] for c in cameras}

    coverages = _camera_coverages_for_intersection(project_id, intersection_id)
    events_for_dedup, raw_by_id = _load_events_for_dedup(project_id, camera_ids)

    _kept_results, duplicate_ids = deduplicate(events_for_dedup, coverages)
    kept_rows = [raw_by_id[r["event_id"]]
                 for r in [_r.__dict__ for _r in _kept_results]
                 if r["event_id"] in raw_by_id]

    def _empty_row() -> dict[str, Any]:
        d: dict[str, Any] = {m: 0 for m in MOVEMENTS}
        d["other"] = 0
        d["total"] = 0
        return d

    # Merged TMC matrix (across all cameras, deduped)
    by_leg: dict[str, dict[str, Any]] = {}
    for row in kept_rows:
        leg = row.get("leg_label") or f"Leg {row['origin_leg_id']}"
        bucket = by_leg.setdefault(leg, {**_empty_row(), "leg_label": leg})
        movement = row.get("movement") or "other"
        if movement in MOVEMENTS:
            bucket[movement] += 1
        else:
            bucket["other"] += 1
        bucket["total"] += 1

    tmc_matrix = sorted(by_leg.values(), key=lambda r: r["leg_label"])

    # Per-camera breakdown (no dedup — shows raw per-camera counts; the
    # merged matrix is the source of truth, this is for QA / spot-checks).
    per_camera_breakdown: list[dict] = []
    for c in cameras:
        cam_rows = [r for r in raw_by_id.values() if r["camera_id"] == c["camera_id"]]
        by_leg_cam: dict[str, dict[str, Any]] = {}
        for row in cam_rows:
            leg = row.get("leg_label") or f"Leg {row['origin_leg_id']}"
            bucket = by_leg_cam.setdefault(leg, {**_empty_row(), "leg_label": leg})
            movement = row.get("movement") or "other"
            if movement in MOVEMENTS:
                bucket[movement] += 1
            else:
                bucket["other"] += 1
            bucket["total"] += 1
        per_camera_breakdown.append({
            "camera_id": c["camera_id"],
            "camera_label": c["label"],
            "matrix": sorted(by_leg_cam.values(), key=lambda r: r["leg_label"]),
            "raw_event_count": len(cam_rows),
        })

    return {
        "intersection": intersection,
        "tmc_matrix": tmc_matrix,
        "per_camera_breakdown": per_camera_breakdown,
        "totals": {"vehicles": sum(r["total"] for r in tmc_matrix)},
        "dedup_summary": {
            "merged": len(duplicate_ids),
            "kept": len(kept_rows),
            "raw_total": len(raw_by_id),
        },
    }
