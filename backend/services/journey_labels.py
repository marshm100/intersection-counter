"""Journey labels: hand-labelled vehicle journeys on short clips (2026-09-30,
docs/research_tracking_2026-09-29.md phase 0).

The operator watches a 3-minute clip and, per vehicle, clicks it as it
crosses IN (entry leg) and as it crosses OUT (exit leg), with a class. That
per-vehicle truth lets scripts/eval_journeys.py score any tracker or linker
idea directly — broken, stolen, missed, double-counted, wrong movement —
instead of only through fleet 5/95 scores where errors cancel.
Dev-validation only; never read by the counting pipeline.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from backend.database import get_connection

CLASSES = ("car", "truck", "articulated", "bus", "motorcycle")
_LABEL_COLS = ("entry_leg_id", "entry_leg_label", "entry_frame", "entry_x",
               "entry_y", "exit_leg_id", "exit_leg_label", "exit_frame",
               "exit_x", "exit_y", "vehicle_class", "note")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_clip(project_id: str, clip_id: str, camera_id: int, video_id: int,
                start_frame: int, end_frame: int, fps: float,
                label: str = "") -> dict:
    """Define (or redefine the frames of) a clip. Labels are untouched."""
    if end_frame <= start_frame:
        raise ValueError("end_frame must be after start_frame")
    conn = get_connection(project_id)
    try:
        with conn:
            conn.execute(
                "INSERT INTO journey_clips (clip_id, camera_id, video_id, "
                "start_frame, end_frame, fps, label, created_at) "
                "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(clip_id) DO UPDATE SET "
                "camera_id=excluded.camera_id, video_id=excluded.video_id, "
                "start_frame=excluded.start_frame, end_frame=excluded.end_frame, "
                "fps=excluded.fps, label=excluded.label",
                (clip_id, camera_id, video_id, int(start_frame), int(end_frame),
                 float(fps), label, _now()))
    finally:
        conn.close()
    return get_clip(project_id, clip_id)


def get_clip(project_id: str, clip_id: str) -> dict | None:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM journey_clips WHERE clip_id=?",
                         (clip_id,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()


def list_clips(project_id: str) -> list[dict]:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM journey_labels l "
            "WHERE l.clip_id = c.clip_id) AS n_labels "
            "FROM journey_clips c ORDER BY c.camera_id, c.start_frame").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _validate(clip: dict, data: dict) -> dict:
    out = {k: data.get(k) for k in _LABEL_COLS}
    has_entry = out["entry_frame"] is not None
    has_exit = out["exit_frame"] is not None
    if not has_entry and not has_exit:
        raise ValueError("a journey needs an entry, an exit, or both")
    for side in ("entry", "exit"):
        if out[f"{side}_frame"] is None:
            for k in ("leg_id", "leg_label", "x", "y"):
                out[f"{side}_{k}"] = None
            continue
        f = int(out[f"{side}_frame"])
        if not clip["start_frame"] <= f <= clip["end_frame"]:
            raise ValueError(f"{side} frame {f} is outside the clip")
        out[f"{side}_frame"] = f
        if out[f"{side}_x"] is None or out[f"{side}_y"] is None:
            raise ValueError(f"{side} needs the clicked position")
    if has_entry and has_exit and out["exit_frame"] < out["entry_frame"]:
        raise ValueError("exit must come after entry")
    cls = (out["vehicle_class"] or "car").lower()
    if cls not in CLASSES:
        raise ValueError(f"class must be one of {', '.join(CLASSES)}")
    out["vehicle_class"] = cls
    out["note"] = out["note"] or ""
    return out


def add_label(project_id: str, clip_id: str, data: dict) -> dict:
    clip = get_clip(project_id, clip_id)
    if clip is None:
        raise LookupError("clip not found")
    row = _validate(clip, data)
    conn = get_connection(project_id)
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO journey_labels (clip_id, camera_id, video_id, "
                + ", ".join(_LABEL_COLS) + ", created_at) VALUES ("
                + ",".join("?" * (3 + len(_LABEL_COLS) + 1)) + ")",
                (clip_id, clip["camera_id"], clip["video_id"],
                 *[row[k] for k in _LABEL_COLS], _now()))
            label_id = cur.lastrowid
    finally:
        conn.close()
    return {"label_id": label_id, "clip_id": clip_id, **row}


def list_labels(project_id: str, clip_id: str) -> list[dict]:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM journey_labels WHERE clip_id=? "
            "ORDER BY COALESCE(entry_frame, exit_frame), label_id",
            (clip_id,)).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def delete_label(project_id: str, clip_id: str, label_id: int) -> bool:
    conn = get_connection(project_id)
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM journey_labels WHERE clip_id=? AND label_id=?",
                (clip_id, int(label_id)))
            return cur.rowcount > 0
    finally:
        conn.close()
