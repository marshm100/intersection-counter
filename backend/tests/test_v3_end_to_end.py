"""v3 end-to-end integration test (Phase 10).

Exercises the full v3 chain so silent breaks in the seams are caught:
  bulk-upload -> save-labels (derive intersection + 2 cameras) -> calibrate
  legs per camera -> add trim -> process each camera through the REAL pipeline
  -> verify camera_id/trim_id propagation -> cross-camera dedup -> v3 Excel.

The pipeline's detector/tracker are mocked (no GPU/YOLO) to drive one clean
NB-through vehicle past each camera — the same proven crossing geometry as
test_integration. The two cameras see the SAME vehicle at the same wall-clock,
so cross-camera dedup must collapse them to one in the merged TMC while the
per-camera breakdown still shows both.
"""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import cv2
import numpy as np
import openpyxl
from fastapi.testclient import TestClient

from backend.app import app
from backend.database import get_connection, get_db_path
from backend.services.pipeline import ProcessingPipeline

client = TestClient(app)

# Same 4-leg geometry + crossing script test_integration proved yields exactly
# one NB-through event (640x480, NB tripwire at y=240, vehicle moving south).
_LEG_SEED = [
    ("Northbound", "NB", 0, [[0, 240], [640, 240]], 180.0),
    ("Southbound", "SB", 1, [[0, 440], [640, 440]], 0.0),
    ("Eastbound", "EB", 2, [[440, 0], [440, 480]], 270.0),
    ("Westbound", "WB", 3, [[200, 0], [200, 480]], 90.0),
]
_ABOVE_YS = [215, 225, 230]
_AFTER_YS = [250] + [265 + 15 * i for i in range(30)]
_ALL_YS = _ABOVE_YS + _AFTER_YS


def _make_detection(x, y, w=100, h=60, class_id=2, confidence=0.9):
    x1, y1, x2, y2 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
    return {
        "bbox": [x1, y1, x2, y2], "center": [float(x), float(y)],
        "class_id": class_id, "class_name": "car", "confidence": confidence,
        "bbox_width": float(w), "bbox_height": float(h), "bbox_area": float(w * h),
        "is_vehicle": class_id in (2, 3, 5, 7),
    }


def _make_video(path, frames=102):
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (640, 480))
    for _ in range(frames):
        w.write(np.zeros((480, 640, 3), dtype=np.uint8))
    w.release()


def _seed_legs(pid, camera_id):
    conn = get_connection(pid)
    try:
        for label, cd, so, oz, rh in _LEG_SEED:
            conn.execute(
                "INSERT INTO legs (camera_id, label, cardinal_direction, sort_order, "
                "origin_zone, reference_heading) VALUES (?,?,?,?,?,?)",
                (camera_id, label, cd, so, json.dumps(oz), rh),
            )
        conn.commit()
    finally:
        conn.close()


def _legs_for_camera(pid, camera_id):
    conn = get_connection(pid)
    conn.row_factory = sqlite3.Row
    try:
        legs = [dict(r) for r in conn.execute(
            "SELECT leg_id, label, cardinal_direction, origin_zone, reference_heading "
            "FROM legs WHERE camera_id=? ORDER BY sort_order", (camera_id,),
        ).fetchall()]
    finally:
        conn.close()
    for leg in legs:
        leg["origin_zone"] = json.loads(leg["origin_zone"])
    return legs


def _drive_camera(pid, db_path, video_row, legs, camera_id, trim_id):
    """Run the real ProcessingPipeline for one camera with a mocked detector
    driving the NB-through crossing. _v3 ids set exactly as the orchestrator does."""
    pipeline = ProcessingPipeline(
        project_id=pid, db_path=db_path, video_path=video_row["path"], legs=legs,
        fps=30.0, video_start_time=video_row["recording_start_datetime"],
        video_id=video_row["video_id"],
    )
    pipeline._v3_camera_id = camera_id
    pipeline._v3_trim_id = trim_id

    pipeline._preprocessor = MagicMock()
    pipeline._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

    seq = [[_make_detection(320, y)] for y in _ALL_YS]
    idx = [0]
    pipeline._detector = MagicMock()
    def _detect(frame):
        i = idx[0]; idx[0] += 1
        return seq[i] if i < len(seq) else []
    pipeline._detector.detect = _detect

    pipeline._tracker = MagicMock()
    pipeline._tracker.update = lambda dets, fn: [{**d, "track_id": 1} for d in dets]
    pipeline._tracker.get_state = MagicMock(return_value=b"")

    pipeline.process_video(frame_skip=3)


def test_v3_full_chain_upload_to_excel_with_dedup():
    pid = client.post("/api/projects", json={"name": "v3-e2e"}).json()["project_id"]
    tmpdir = tempfile.mkdtemp(prefix="v3_e2e_")
    try:
        # --- bulk-upload two cameras of the same intersection-day ---
        paths = [
            str(Path(tmpdir) / "Cam1_01_20260514_080000 MainSt.mp4"),
            str(Path(tmpdir) / "Cam2_01_20260514_080000 MainSt.mp4"),
        ]
        for p in paths:
            _make_video(p)
        r = client.post(f"/api/projects/{pid}/videos/bulk", json={"paths": paths})
        assert r.status_code == 200, r.text
        body = client.post(f"/api/projects/{pid}/videos/save-labels").json()
        iid = body["intersections"][0]["intersection_id"]

        # --- cameras + per-camera calibration (legs) ---
        cams = client.get(f"/api/projects/{pid}/intersections/{iid}/cameras").json()
        assert len(cams) == 2, cams
        for c in cams:
            _seed_legs(pid, c["camera_id"])

        # --- one trim covering the clip window (08:00:00–08:00:03) ---
        tr = client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "08:00:00", "end_wallclock": "08:00:03"},
        )
        assert tr.status_code == 200, tr.text
        trim_id = tr.json()["trim_id"]

        # --- process each camera through the real pipeline ---
        db_path = str(get_db_path(pid))
        conn = get_connection(pid)
        conn.row_factory = sqlite3.Row
        try:
            videos = {r["camera_id"]: dict(r) for r in conn.execute(
                "SELECT video_id, camera_id, path, recording_start_datetime FROM videos "
                "WHERE camera_id IS NOT NULL"
            ).fetchall()}
        finally:
            conn.close()
        for c in cams:
            _drive_camera(pid, db_path, videos[c["camera_id"]],
                          _legs_for_camera(pid, c["camera_id"]), c["camera_id"], trim_id)

        # --- camera_id / trim_id propagation (the #1 audit risk) ---
        conn = get_connection(pid)
        conn.row_factory = sqlite3.Row
        try:
            events = [dict(r) for r in conn.execute("SELECT * FROM vehicle_events").fetchall()]
        finally:
            conn.close()
        assert len(events) == 2, f"expected 2 events (one/camera), got {len(events)}"
        assert sorted(e["camera_id"] for e in events) == sorted(c["camera_id"] for c in cams)
        assert all(e["trim_id"] == trim_id for e in events), "trim_id not propagated"
        assert all(e["movement"] == "through" for e in events)

        # --- aggregation + cross-camera dedup ---
        summary = client.get(
            f"/api/projects/{pid}/intersections/{iid}/summary").json()
        assert summary["dedup_summary"]["raw_total"] == 2
        assert summary["dedup_summary"]["merged"] == 1     # the duplicate collapsed
        assert summary["dedup_summary"]["kept"] == 1
        assert summary["totals"]["vehicles"] == 1          # merged TMC counts it once
        nb = [r for r in summary["tmc_matrix"] if r["leg_label"] == "Northbound"][0]
        assert nb["through"] == 1
        # Per-camera breakdown is RAW (un-deduped) — both cameras still show their hit.
        assert len(summary["per_camera_breakdown"]) == 2
        assert all(c["raw_event_count"] == 1 for c in summary["per_camera_breakdown"])

        # --- v3 Excel export: three sheets, downloadable ---
        x = client.get(f"/api/projects/{pid}/intersections/{iid}/export/xlsx")
        assert x.status_code == 200
        xlsx = Path(tmpdir) / "out.xlsx"
        xlsx.write_bytes(x.content)
        wb = openpyxl.load_workbook(str(xlsx))
        try:
            assert {"TMC Summary", "Per-Camera Breakdown", "Dedup Audit"} <= set(wb.sheetnames)
        finally:
            wb.close()
    finally:
        client.delete(f"/api/projects/{pid}")
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)
