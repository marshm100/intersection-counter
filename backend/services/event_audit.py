"""The event audit (2026-10-01): the operator judges a stratified sample of the
software's COUNTED events on the video (see database.AUDIT_SCHEMA).

Items are written by scripts/audit_sample.py; the page /static/audit.html
plays each one with its track drawn and posts one verdict. The latest answer
per item stands. scripts/audit_report.py turns answers into precision per
camera x stratum. Dev-validation only; never read by the counting pipeline.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from backend.database import get_connection

VERDICTS = ("correct", "wrong_movement", "not_intersection", "double", "unsure")
_ITEM_COLS = ("batch", "camera_id", "video_id", "window", "vehicle_track_id", "stratum",
              "claimed_origin_leg_id", "claimed_dest_leg_id", "claimed_movement",
              "claim_detail", "start_frame", "end_frame", "fps", "track_json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_item(project_id: str, item: dict) -> int:
    row = dict(item)
    if not isinstance(row.get("track_json"), str):
        row["track_json"] = json.dumps(row.get("track_json") or [])
    row.setdefault("claim_detail", "")
    conn = get_connection(project_id)
    try:
        with conn:
            cur = conn.execute(
                f"INSERT INTO audit_items ({', '.join(_ITEM_COLS)}, created_at) "
                f"VALUES ({', '.join('?' * len(_ITEM_COLS))}, ?)",
                tuple(row.get(k) for k in _ITEM_COLS) + (_now(),))
            return int(cur.lastrowid)
    finally:
        conn.close()


def _latest_answers(conn) -> dict:
    conn.row_factory = sqlite3.Row
    q = ("SELECT a.* FROM audit_answers a JOIN (SELECT item_id, MAX(answer_id) m "
         "FROM audit_answers GROUP BY item_id) x ON a.answer_id = x.m")
    return {r["item_id"]: dict(r) for r in conn.execute(q)}


def list_items(project_id: str, batch: str | None = None) -> list[dict]:
    """Items without their track (light), each with its latest answer or None."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        q = ("SELECT item_id, batch, camera_id, video_id, window, vehicle_track_id, stratum, "
             "claimed_origin_leg_id, claimed_dest_leg_id, claimed_movement, claim_detail, "
             "start_frame, end_frame, fps FROM audit_items")
        cur = (conn.execute(q + " WHERE batch=? ORDER BY item_id", (batch,)) if batch
               else conn.execute(q + " ORDER BY item_id"))
        rows = [dict(r) for r in cur]
        ans = _latest_answers(conn)
        for r in rows:
            r["answer"] = ans.get(r["item_id"])
        return rows
    finally:
        conn.close()


def get_item(project_id: str, item_id: int) -> dict | None:
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        r = conn.execute("SELECT * FROM audit_items WHERE item_id=?", (item_id,)).fetchone()
        if r is None:
            return None
        item = dict(r)
        item["track"] = json.loads(item.pop("track_json") or "[]")
        item["answer"] = _latest_answers(conn).get(item_id)
        return item
    finally:
        conn.close()


def answer_item(project_id: str, item_id: int, verdict: str,
                true_origin_leg_id: int | None = None,
                true_dest_leg_id: int | None = None, note: str = "") -> dict:
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    if verdict == "wrong_movement" and (true_origin_leg_id is None or true_dest_leg_id is None):
        raise ValueError("a wrong movement needs the true origin and destination legs")
    if get_item(project_id, item_id) is None:
        raise KeyError(item_id)
    conn = get_connection(project_id)
    try:
        with conn:
            conn.execute(
                "INSERT INTO audit_answers (item_id, verdict, true_origin_leg_id, "
                "true_dest_leg_id, note, created_at) VALUES (?,?,?,?,?,?)",
                (item_id, verdict, true_origin_leg_id, true_dest_leg_id, note or "", _now()))
    finally:
        conn.close()
    return get_item(project_id, item_id)["answer"]
