"""v3 Phase 5 — aggregator + Excel export tests.

Bypasses pipeline + YOLO by writing synthetic vehicle_events rows directly
into the DB. Exercises dedup, aggregation, and the .xlsx exporter shape.
"""

import io
import json
import os
import shutil
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import openpyxl
import pytest
from fastapi.testclient import TestClient

from backend import database
from backend.app import app
from backend.services.v3_aggregator import aggregate_intersection_day
from backend.services.v3_excel_export import export_intersection_day_xlsx


client = TestClient(app)


def _make_video(dir_path: str, name: str) -> str:
    p = os.path.join(dir_path, name)
    w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 240))
    for _ in range(90):
        w.write(np.zeros((240, 320, 3), dtype=np.uint8))
    w.release()
    return p


def _insert_event(
    pid: str, *, video_id: int, camera_id: int, trim_id: int | None,
    leg_id: int, movement: str, timestamp_video: float = 1.0,
    detection_confidence: float = 0.9, rejected: int = 0,
) -> int:
    conn = database.get_connection(pid)
    try:
        cur = conn.execute(
            """INSERT INTO vehicle_events
               (video_id, camera_id, trim_id, vehicle_track_id,
                origin_leg_id, movement, trajectory_data,
                trajectory_confidence, vehicle_class, detection_confidence,
                timestamp_video, frame_number, rejected)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (video_id, camera_id, trim_id, 1, leg_id, movement, "[]",
             0.9, "car", detection_confidence,
             timestamp_video, int(timestamp_video * 30), rejected),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


def _insert_leg(pid: str, *, camera_id: int, label: str, cardinal: str,
                sort_order: int = 0) -> int:
    conn = database.get_connection(pid)
    try:
        cur = conn.execute(
            """INSERT INTO legs
               (camera_id, label, cardinal_direction, sort_order,
                origin_zone, reference_heading)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (camera_id, label, cardinal, sort_order, "[]", 0.0),
        )
        conn.commit()
        return int(cur.lastrowid)
    finally:
        conn.close()


@pytest.fixture()
def two_cam_intersection():
    """Project with 2 cameras at one intersection-day, each with one leg."""
    pid = client.post("/api/projects", json={"name": "v3-agg"}).json()["project_id"]
    tmpdir = tempfile.mkdtemp(prefix="v3_agg_")
    try:
        paths = [
            _make_video(tmpdir, "Cam1_01_20260514_080000 Main.mp4"),
            _make_video(tmpdir, "Cam2_01_20260514_080000 Main.mp4"),
        ]
        client.post(f"/api/projects/{pid}/videos/bulk", json={"paths": paths})
        body = client.post(f"/api/projects/{pid}/videos/save-labels").json()
        iid = body["intersections"][0]["intersection_id"]
        cams = client.get(f"/api/projects/{pid}/intersections/{iid}/cameras").json()
        cam_a, cam_b = cams[0]["camera_id"], cams[1]["camera_id"]
        leg_a = _insert_leg(pid, camera_id=cam_a, label="North", cardinal="N")
        leg_b = _insert_leg(pid, camera_id=cam_b, label="North", cardinal="N")
        vids = client.get(f"/api/projects/{pid}/videos").json()
        vid_a = next(v["video_id"] for v in vids if v["camera_id"] == cam_a)
        vid_b = next(v["video_id"] for v in vids if v["camera_id"] == cam_b)
        yield {"pid": pid, "iid": iid,
               "cam_a": cam_a, "cam_b": cam_b,
               "leg_a": leg_a, "leg_b": leg_b,
               "vid_a": vid_a, "vid_b": vid_b}
    finally:
        client.delete(f"/api/projects/{pid}")
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestAggregation:
    def test_no_events_returns_empty_matrix(self, two_cam_intersection):
        ctx = two_cam_intersection
        agg = aggregate_intersection_day(ctx["pid"], ctx["iid"])
        assert agg["tmc_matrix"] == []
        assert agg["totals"]["vehicles"] == 0

    def test_singleton_event_counted(self, two_cam_intersection):
        ctx = two_cam_intersection
        _insert_event(
            ctx["pid"],
            video_id=ctx["vid_a"], camera_id=ctx["cam_a"], trim_id=None,
            leg_id=ctx["leg_a"], movement="through", timestamp_video=1.0,
        )
        agg = aggregate_intersection_day(ctx["pid"], ctx["iid"])
        assert agg["totals"]["vehicles"] == 1
        assert agg["tmc_matrix"][0]["leg_label"] == "North"
        assert agg["tmc_matrix"][0]["through"] == 1

    def test_rejected_events_excluded(self, two_cam_intersection):
        ctx = two_cam_intersection
        _insert_event(
            ctx["pid"], video_id=ctx["vid_a"], camera_id=ctx["cam_a"],
            trim_id=None, leg_id=ctx["leg_a"], movement="through",
            timestamp_video=1.0, rejected=1,
        )
        agg = aggregate_intersection_day(ctx["pid"], ctx["iid"])
        assert agg["totals"]["vehicles"] == 0

    def test_parallel_overlap_deduplicates(self, two_cam_intersection):
        ctx = two_cam_intersection
        # Cam A and Cam B both see a left turn within 1 second of each other,
        # during their parallel-overlap window. Should count as 1.
        _insert_event(
            ctx["pid"], video_id=ctx["vid_a"], camera_id=ctx["cam_a"],
            trim_id=None, leg_id=ctx["leg_a"], movement="left",
            timestamp_video=1.0, detection_confidence=0.85,
        )
        _insert_event(
            ctx["pid"], video_id=ctx["vid_b"], camera_id=ctx["cam_b"],
            trim_id=None, leg_id=ctx["leg_b"], movement="left",
            timestamp_video=1.5, detection_confidence=0.95,
        )
        agg = aggregate_intersection_day(ctx["pid"], ctx["iid"])
        assert agg["totals"]["vehicles"] == 1
        assert agg["dedup_summary"]["merged"] == 1

    def test_per_camera_breakdown_shows_raw_counts(self, two_cam_intersection):
        """Per-camera sheet shows raw counts (not deduped) for QA."""
        ctx = two_cam_intersection
        _insert_event(ctx["pid"], video_id=ctx["vid_a"], camera_id=ctx["cam_a"],
                      trim_id=None, leg_id=ctx["leg_a"], movement="left",
                      timestamp_video=1.0, detection_confidence=0.85)
        _insert_event(ctx["pid"], video_id=ctx["vid_b"], camera_id=ctx["cam_b"],
                      trim_id=None, leg_id=ctx["leg_b"], movement="left",
                      timestamp_video=1.5, detection_confidence=0.95)
        agg = aggregate_intersection_day(ctx["pid"], ctx["iid"])
        # Each camera shows 1 raw event in the breakdown sheet
        for cam_block in agg["per_camera_breakdown"]:
            assert cam_block["raw_event_count"] == 1


class TestExcelExport:
    def test_exports_three_sheets(self, two_cam_intersection, tmp_path):
        ctx = two_cam_intersection
        _insert_event(ctx["pid"], video_id=ctx["vid_a"], camera_id=ctx["cam_a"],
                      trim_id=None, leg_id=ctx["leg_a"], movement="through",
                      timestamp_video=1.0)
        out = tmp_path / "out.xlsx"
        export_intersection_day_xlsx(ctx["pid"], ctx["iid"], out)
        assert out.exists()
        wb = openpyxl.load_workbook(out)
        assert "TMC Summary" in wb.sheetnames
        assert "Per-Camera Breakdown" in wb.sheetnames
        assert "Dedup Audit" in wb.sheetnames

    def test_summary_sheet_values(self, two_cam_intersection, tmp_path):
        ctx = two_cam_intersection
        _insert_event(ctx["pid"], video_id=ctx["vid_a"], camera_id=ctx["cam_a"],
                      trim_id=None, leg_id=ctx["leg_a"], movement="through",
                      timestamp_video=1.0)
        _insert_event(ctx["pid"], video_id=ctx["vid_a"], camera_id=ctx["cam_a"],
                      trim_id=None, leg_id=ctx["leg_a"], movement="left",
                      timestamp_video=1.5)
        out = tmp_path / "out.xlsx"
        export_intersection_day_xlsx(ctx["pid"], ctx["iid"], out)
        wb = openpyxl.load_workbook(out)
        ws = wb["TMC Summary"]
        # Header row at row 6 (after 4 metadata + 1 blank)
        # First data row at 7 — should have leg label North, through=1, left=1
        row = next(r for r in ws.iter_rows(values_only=True) if r and r[0] == "North")
        assert row[1] == 1   # Through
        assert row[2] == 1   # Left

    def test_export_endpoint_returns_xlsx(self, two_cam_intersection):
        ctx = two_cam_intersection
        _insert_event(ctx["pid"], video_id=ctx["vid_a"], camera_id=ctx["cam_a"],
                      trim_id=None, leg_id=ctx["leg_a"], movement="through",
                      timestamp_video=1.0)
        r = client.get(
            f"/api/projects/{ctx['pid']}/intersections/{ctx['iid']}/export/xlsx"
        )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        # Body should be a real xlsx (zip starts with PK)
        assert r.content[:2] == b"PK"
