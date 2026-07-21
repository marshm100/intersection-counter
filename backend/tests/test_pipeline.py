"""Tests for the processing pipeline.

Uses mocked detector to avoid loading YOLO — tests pipeline logic only:
origin crossing, trajectory building, finalization, event writing.
"""

import json
import os
import pickle
import sqlite3
import tempfile
import threading

import cv2
import numpy as np
import pytest
from unittest.mock import MagicMock, PropertyMock, patch

from backend.database import SCHEMA
from backend.services.pipeline import ProcessingPipeline


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def pipeline_env():
    """Create a temp project dir with initialized DB, mock legs, and video."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "project.db")
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)

        # NB origin zone: horizontal line at y=800, right-to-left so
        # left side (+1) = interior (above line, toward intersection center)
        conn.execute(
            """INSERT INTO legs
               (label, cardinal_direction, sort_order, origin_zone, reference_heading)
               VALUES (?, ?, ?, ?, ?)""",
            ("Northbound", "NB", 1, json.dumps([[700, 800], [300, 800]]), 0.0),
        )
        # EB origin zone: vertical line at x=200, bottom-to-top so
        # left side (+1) = interior (right of line, toward center)
        conn.execute(
            """INSERT INTO legs
               (label, cardinal_direction, sort_order, origin_zone, reference_heading)
               VALUES (?, ?, ?, ?, ?)""",
            ("Eastbound", "EB", 2, json.dumps([[200, 700], [200, 300]]), 90.0),
        )
        conn.commit()
        conn.close()

        # Create a 30-frame synthetic video (640x480 @ 30fps)
        video_path = os.path.join(tmpdir, "test.mp4")
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(video_path, fourcc, 30.0, (640, 480))
        for _ in range(30):
            writer.write(np.zeros((480, 640, 3), dtype=np.uint8))
        writer.release()

        legs = [
            {
                "leg_id": 1,
                "label": "Northbound",
                "cardinal_direction": "NB",
                "origin_zone": [[700, 800], [300, 800]],
                "reference_heading": 0.0,
            },
            {
                "leg_id": 2,
                "label": "Eastbound",
                "cardinal_direction": "EB",
                "origin_zone": [[200, 700], [200, 300]],
                "reference_heading": 90.0,
            },
        ]

        yield {
            "db_path": db_path,
            "video_path": video_path,
            "legs": legs,
            "tmpdir": tmpdir,
        }


def _make_pipeline(env, video_start_time=None):
    """Create a pipeline without loading YOLO."""
    return ProcessingPipeline(
        project_id="test",
        db_path=env["db_path"],
        video_path=env["video_path"],
        legs=env["legs"],
        fps=30.0,
        video_start_time=video_start_time,
    )


def _make_detection(x, y, w=100, h=60, class_id=2, confidence=0.9):
    """Build a detection dict at center (x, y)."""
    x1, y1, x2, y2 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
    return {
        "bbox": [x1, y1, x2, y2],
        "center": [float(x), float(y)],
        "class_id": class_id,
        "class_name": "car",
        "confidence": confidence,
        "bbox_width": float(w),
        "bbox_height": float(h),
        "bbox_area": float(w * h),
        "is_vehicle": class_id in (2, 3, 5, 7),
    }


def _nb_through_detections(num_frames=20):
    """Vehicle enters from south (y=850), crosses NB zone at y=800, goes north.

    With frame_skip=1 and step=40 we get:
    y: 850, 810, 770, 730, … all the way to y=90.
    Crosses y=800 zone between frame 0 (y=850) and frame 1 (y=810).
    """
    frames = []
    for i in range(num_frames):
        y = 850 - i * 40
        frames.append([_make_detection(500, y)])
    return frames


def _count_vehicle_events(db_path):
    conn = sqlite3.connect(db_path)
    count = conn.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0]
    conn.close()
    return count


def _get_vehicle_events(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM vehicle_events").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# TestPipelineInit
# ---------------------------------------------------------------------------

class TestPipelineInit:
    def test_creates_successfully(self, pipeline_env):
        p = _make_pipeline(pipeline_env)
        assert p is not None
        # Detector should NOT be loaded yet
        assert p._detector is None

    def test_diagnostic_counters_initialized(self, pipeline_env):
        p = _make_pipeline(pipeline_env)
        assert p.n_tracks_total == 0
        assert p.n_crossed_enter == 0
        assert p.n_crossed_exit == 0
        assert p.n_insufficient_data == 0
        # Phase 1 polyline-path counters
        assert p.n_origin_via_polyline == 0
        assert p.n_destination_via_polyline == 0

    def test_paths_kwarg_defaults_empty(self, pipeline_env):
        """Pipelines without paths use the legacy tripwire+heading tiers
        and have an empty _paths list (auto-upgrade behavior)."""
        p = _make_pipeline(pipeline_env)
        assert p._paths == []

    def test_paths_kwarg_accepts_list(self, pipeline_env):
        """When paths are provided, the pipeline stores them for tier-0 use."""
        from backend.services.pipeline import ProcessingPipeline
        sample_paths = [
            {"path_id": 1, "camera_id": 1, "origin_leg_id": 1,
             "destination_leg_id": 2,
             "polyline": [[100, 800], [300, 600], [500, 400]],
             "movement_label": "through", "supporting_count": 50},
        ]
        p = ProcessingPipeline(
            project_id="test",
            db_path=pipeline_env["db_path"],
            video_path=pipeline_env["video_path"],
            legs=pipeline_env["legs"],
            fps=30.0,
            paths=sample_paths,
        )
        assert len(p._paths) == 1
        assert p._paths[0]["origin_leg_id"] == 1
        assert p.n_origin_via_polyline == 0   # counter starts at 0

    def _veto_pipeline(self, env, paths):
        """FM51-shaped miniature: horizontal main road y=500 (legs 1 W, 2 E),
        side stem leg 3 with its mouth just off the road at (300,450)."""
        from backend.services.pipeline import ProcessingPipeline
        legs = [
            {"leg_id": 1, "label": "W", "cardinal_direction": "W",
             "origin_zone": [[100, 500]], "reference_heading": 90.0},
            {"leg_id": 2, "label": "E", "cardinal_direction": "E",
             "origin_zone": [[700, 500]], "reference_heading": 270.0},
            {"leg_id": 3, "label": "S", "cardinal_direction": "S",
             "origin_zone": [[300, 450]], "reference_heading": 120.0},
        ]
        return ProcessingPipeline(
            project_id="test", db_path=env["db_path"],
            video_path=env["video_path"], legs=legs, fps=30.0, paths=paths)

    _MAIN_THROUGH = {"path_id": 1, "camera_id": 1, "origin_leg_id": 1,
                     "destination_leg_id": 2, "movement_label": "through",
                     "supporting_count": 30,
                     "polyline": [[0, 500], [800, 500]]}
    # a 3->2 path whose ENTRY SEGMENT hugs the main road (the far-field
    # compression geometry phase 0 measured at the FM51 stem)
    _STEM_RIGHT = {"path_id": 2, "camera_id": 1, "origin_leg_id": 3,
                   "destination_leg_id": 2, "movement_label": "right",
                   "supporting_count": 7,
                   "polyline": [[380, 495], [420, 498], [460, 500],
                                [520, 500], [600, 500]]}

    def test_origin_veto_geometry(self, pipeline_env, monkeypatch):
        """The frozen rule (plan_origin_veto): born ON another pair's
        through-road AND > D_MOUTH from the candidate's mouth."""
        import backend.services.pipeline as mod
        p = self._veto_pipeline(pipeline_env,
                                [self._MAIN_THROUGH, self._STEM_RIGHT])
        monkeypatch.setattr(mod, "ORIGIN_CLAIM_VETO_ENABLED", True)
        # mid-main-road birth: stem vetoed, the through pair's own legs never
        assert p._compute_origin_veto((390, 496)) == frozenset({3})
        # birth in the stem's mouth throat: protected regardless of the road
        assert p._compute_origin_veto((310, 455)) == frozenset()
        # birth off every road: no veto
        assert p._compute_origin_veto((390, 300)) == frozenset()
        # flag off: always empty
        monkeypatch.setattr(mod, "ORIGIN_CLAIM_VETO_ENABLED", False)
        assert p._compute_origin_veto((390, 496)) == frozenset()

    def test_origin_veto_no_through_pair_never_fires(self, pipeline_env,
                                                     monkeypatch):
        import backend.services.pipeline as mod
        monkeypatch.setattr(mod, "ORIGIN_CLAIM_VETO_ENABLED", True)
        p = self._veto_pipeline(pipeline_env, [self._STEM_RIGHT])
        assert p._compute_origin_veto((390, 496)) == frozenset()

    def test_origin_veto_redirects_the_claim(self, pipeline_env, monkeypatch):
        """The phase-0 steal, reproduced then fixed: a main-road birth whose
        prefix matches the stem path's entry segment claims the stem with the
        flag OFF; with the veto ON the claim falls through to the heading
        fallback and lands the true main-road origin."""
        import backend.services.pipeline as mod
        # the prefix rides the stem path's entry segment exactly (the
        # far-field grab geometry): birth (380,495) is 5 px off the main
        # through line and 92 px from the stem mouth. Steps stay small so
        # displacement < TRAJECTORY_MIN_DISTANCE_PX until tier-0's 4-point
        # threshold — the claim must be decided by the polyline tier, as the
        # real FM51 grabs were.
        pts = [(380, 495), (392, 496), (404, 497), (416, 498), (428, 499)]
        paths = [self._MAIN_THROUGH, self._STEM_RIGHT]

        p = self._veto_pipeline(pipeline_env, paths)
        for f, (x, y) in enumerate(pts):
            p._process_vehicle(9, _make_detection(x, y), f)
        assert p.active_vehicles[9]["origin_leg_id"] == 3   # the steal
        assert p.n_origin_vetoed == 0

        monkeypatch.setattr(mod, "ORIGIN_CLAIM_VETO_ENABLED", True)
        p2 = self._veto_pipeline(pipeline_env, paths)
        for f, (x, y) in enumerate(pts):
            p2._process_vehicle(9, _make_detection(x, y), f)
        v = p2.active_vehicles[9]
        assert v["origin_veto"] == frozenset({3})
        assert v["origin_leg_id"] == 1     # falls to the main-road path match
        assert p2.n_origin_vetoed == 1

    # --- PHASE 3: the rescue half + the rewrite-veto -----------------------

    def test_origin_rescue_direction_and_guards(self, pipeline_env, monkeypatch):
        """_origin_rescue picks the leg of the through-road the birth sits on by
        the SIGN of the birth motion along the road tangent. Polylines run
        origin->dest, so east motion on the horizontal main road (origin=W
        leg 1, dest=E leg 2) => origin leg 1; reversed => leg 2. This also
        asserts the origin->dest polyline orientation the sign rule rests on."""
        import backend.services.pipeline as mod
        monkeypatch.setattr(mod, "ORIGIN_CLAIM_VETO_ENABLED", True)
        p = self._veto_pipeline(pipeline_env,
                                [self._MAIN_THROUGH, self._STEM_RIGHT])
        # born ON the main road (y=500), moving EAST (+tangent) -> the W origin
        assert p._origin_rescue((390, 496), [(390, 496), (430, 498)]) == 1
        # moving WEST (anti-parallel) -> the reverse-through's leg = E (2)
        assert p._origin_rescue((410, 498), [(430, 498), (390, 496)]) == 2
        # exactly perpendicular to the road -> ambiguous
        assert p._origin_rescue((390, 496), [(390, 496), (390, 540)]) is None
        # sub-pixel motion -> not a real through
        assert p._origin_rescue((390, 496), [(390, 496), (390.5, 496)]) is None
        # off every through-road -> nothing to claim
        assert p._origin_rescue((390, 300), [(390, 300), (430, 300)]) is None
        # flag off -> never rescues
        monkeypatch.setattr(mod, "ORIGIN_CLAIM_VETO_ENABLED", False)
        assert p._origin_rescue((390, 496), [(390, 496), (430, 498)]) is None

    def test_origin_rescue_emits_event_else_drops(self, pipeline_env, monkeypatch):
        """An origin-less far-field through (the veto's -467 drop) is rescued to
        the main-road leg and emits an event with the flag ON; with the flag
        OFF the same track keeps the legacy insufficient_data drop."""
        import backend.services.pipeline as mod
        legs = [
            {"leg_id": 1, "label": "W", "cardinal_direction": "W",
             "origin_zone": [[100, 500]], "reference_heading": 90.0},
            {"leg_id": 2, "label": "E", "cardinal_direction": "E",
             "origin_zone": [[700, 500]], "reference_heading": 270.0},
        ]

        def _origin_less_vehicle():
            return {
                "origin_leg_id": None, "reference_heading": None,
                "origin_frame": None, "start_frame": 3,
                # straight east along y=500, covering most of the main polyline
                "trajectory": [(100 + i * 40, 500) for i in range(15)],
                "confidences": [0.9] * 15, "last_center": (660, 500),
                "class_id": 2, "class_name": "car",
                "bbox_width": 100.0, "bbox_height": 60.0, "bbox_area": 6000.0,
            }

        # Flag ON -> rescued, one event, origin = the W leg (moving east).
        monkeypatch.setattr(mod, "ORIGIN_CLAIM_VETO_ENABLED", True)
        p = ProcessingPipeline(
            project_id="test", db_path=pipeline_env["db_path"],
            video_path=pipeline_env["video_path"], legs=legs, fps=30.0,
            paths=[self._MAIN_THROUGH])
        p.active_vehicles[50] = _origin_less_vehicle()
        p._finalize_vehicle(50, frame_number=25)
        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        assert events[0]["origin_leg_id"] == 1
        assert p.n_origin_rescued == 1

        # Flag OFF -> no rescue, dropped as insufficient_data, no new event.
        monkeypatch.setattr(mod, "ORIGIN_CLAIM_VETO_ENABLED", False)
        p2 = ProcessingPipeline(
            project_id="test", db_path=pipeline_env["db_path"],
            video_path=pipeline_env["video_path"], legs=legs, fps=30.0,
            paths=[self._MAIN_THROUGH])
        p2.active_vehicles[51] = _origin_less_vehicle()
        before = _count_vehicle_events(pipeline_env["db_path"])
        p2._finalize_vehicle(51, frame_number=25)
        assert _count_vehicle_events(pipeline_env["db_path"]) == before
        assert p2.n_origin_rescued == 0
        assert p2.n_insufficient_data == 1

    def test_rewrite_veto_filters_vetoed_origin_paths(self, pipeline_env,
                                                      monkeypatch):
        """The finalize-time joint scorer must not see a path whose origin is a
        vetoed leg (the FM51 S-right 76->84 re-steal): candidate_paths drops
        the 3->2 stem path, so the scorer can only keep the claimed main-road
        origin."""
        import backend.services.pipeline as mod
        monkeypatch.setattr(mod, "ORIGIN_CLAIM_VETO_ENABLED", True)
        p = self._veto_pipeline(pipeline_env,
                                [self._MAIN_THROUGH, self._STEM_RIGHT])
        captured = {}

        def fake_joint(trajectory, candidate_paths, **kw):
            captured["origins"] = sorted(
                pp.get("origin_leg_id") for pp in candidate_paths)
            return {"destination_leg_id": None}   # no match -> softmax fallback

        monkeypatch.setattr(mod, "score_path_joint", fake_joint)
        p.active_vehicles[60] = {
            "origin_leg_id": 1, "reference_heading": 90.0, "origin_frame": 5,
            "origin_veto": frozenset({3}), "start_frame": 0,
            "trajectory": [(100 + i * 30, 500) for i in range(12)],
            "confidences": [0.9] * 12, "last_center": (430, 500),
            "class_id": 2, "class_name": "car",
            "bbox_width": 100.0, "bbox_height": 60.0, "bbox_area": 6000.0,
        }
        p._finalize_vehicle(60, frame_number=25)
        assert captured["origins"] == [1]           # the 3->2 stem path filtered
        assert p.n_origin_rewrite_vetoed == 1

    def test_tripwire_incremental_scan_catches_late_crossing(self, pipeline_env):
        """The incremental tripwire scan (2026-07-17 quadratic fix) must not
        lose segments: a track that lingers short of the line for many
        attempts and then crosses is assigned on the crossing segment.
        Geometry keeps total displacement under TRAJECTORY_MIN_DISTANCE_PX so
        the heading fallback stays silent — only the tripwire can assign."""
        p = _make_pipeline(pipeline_env)
        # leg 1 origin_zone is the line y=800 spanning x 300..700 (heading 0).
        for f in range(10):
            p._process_vehicle(42, _make_detection(500, 830 + (f % 2)), f)
        v = p.active_vehicles[42]
        assert v["origin_leg_id"] is None          # linger: nothing assigned
        assert v["tripwire_scanned"] == len(v["trajectory"])
        p._process_vehicle(42, _make_detection(500, 790), 10)   # crosses y=800
        assert v["origin_leg_id"] == 1
        assert v["origin_frame"] == 10

    def test_assign_origin_polyline_tier_fires(self, pipeline_env):
        """When a trajectory matches a path's entry segment, the polyline
        tier assigns origin and bumps the counter (without using the
        tripwire / heading fallbacks)."""
        from backend.services.pipeline import ProcessingPipeline
        # A trajectory that runs along a polyline going from south to north.
        sample_paths = [
            {"path_id": 1, "camera_id": 1, "origin_leg_id": 1,
             "destination_leg_id": 2,
             "polyline": [[500, 850], [500, 700], [500, 500], [500, 300],
                          [500, 100]],
             "movement_label": "through", "supporting_count": 100},
        ]
        p = ProcessingPipeline(
            project_id="test",
            db_path=pipeline_env["db_path"],
            video_path=pipeline_env["video_path"],
            legs=pipeline_env["legs"],
            fps=30.0,
            paths=sample_paths,
        )
        # Inject an active vehicle with a trajectory that matches the
        # polyline's entry segment. Then call _assign_origin directly.
        p.active_vehicles[42] = {
            "trajectory": [(500, 840), (500, 800), (500, 760), (500, 720)],
            "origin_leg_id": None,
            "reference_heading": None,
        }
        p._assign_origin(42, frame_number=5)
        v = p.active_vehicles[42]
        assert v["origin_leg_id"] == 1
        assert v.get("origin_polyline_path_id") == 1
        assert p.n_origin_via_polyline == 1

    def test_initial_counts_zero(self, pipeline_env):
        p = _make_pipeline(pipeline_env)
        assert p.vehicle_count == 0
        assert p.error_count == 0
        assert p.turn_counts == {
            1: {"through": 0, "left": 0, "right": 0, "uturn": 0},
            2: {"through": 0, "left": 0, "right": 0, "uturn": 0},
        }


# ---------------------------------------------------------------------------
# TestPipelineProcessing (mocked detector)
# ---------------------------------------------------------------------------

class TestPipelineProcessing:
    def test_vehicle_crosses_origin_and_finalized(self, pipeline_env):
        """Vehicle crosses NB origin zone and goes straight → 1 event."""
        p = _make_pipeline(pipeline_env)
        mock_dets = _nb_through_detections(num_frames=20)
        frame_idx = [0]

        # Mock preprocessor (passthrough), detector (scripted), tracker (identity)
        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        def mock_detect(frame):
            idx = frame_idx[0]
            frame_idx[0] += 1
            return mock_dets[idx] if idx < len(mock_dets) else []
        p._detector.detect = mock_detect

        # Tracker that assigns consistent track_id=1
        call_count = [0]
        def mock_tracker_update(detections, frame_number):
            call_count[0] += 1
            results = []
            for d in detections:
                results.append({**d, "track_id": 1})
            return results

        p._tracker = MagicMock()
        p._tracker.update = mock_tracker_update
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1, start_frame=0)

        assert _count_vehicle_events(pipeline_env["db_path"]) >= 1
        events = _get_vehicle_events(pipeline_env["db_path"])
        assert events[0]["origin_leg_id"] == 1

    def test_vehicle_never_crosses_origin(self, pipeline_env):
        """Vehicle stays below origin zone → 0 events."""
        p = _make_pipeline(pipeline_env)
        # Vehicle moves southwest (heading ~225°) — doesn't match NB(0°) or EB(90°)
        mock_dets = [[_make_detection(500 - i * 2, 900 + i * 2)] for i in range(20)]
        frame_idx = [0]

        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        def mock_detect(frame):
            idx = frame_idx[0]
            frame_idx[0] += 1
            return mock_dets[idx] if idx < len(mock_dets) else []
        p._detector.detect = mock_detect

        p._tracker = MagicMock()
        p._tracker.update = lambda dets, fn: [{**d, "track_id": 1} for d in dets]
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1)
        assert _count_vehicle_events(pipeline_env["db_path"]) == 0

    def test_multiple_vehicles(self, pipeline_env):
        """Two vehicles crossing at different times → 2 events."""
        p = _make_pipeline(pipeline_env)

        # Vehicle A crosses first, then Vehicle B
        all_dets = []
        for i in range(20):
            frame_dets = []
            # Vehicle A: crosses NB zone
            ya = 850 - i * 40
            frame_dets.append(_make_detection(400, ya))
            # Vehicle B: crosses NB zone, offset in time
            if i >= 5:
                yb = 850 - (i - 5) * 40
                frame_dets.append(_make_detection(600, yb))
            all_dets.append(frame_dets)

        frame_idx = [0]
        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        def mock_detect(frame):
            idx = frame_idx[0]
            frame_idx[0] += 1
            return all_dets[idx] if idx < len(all_dets) else []
        p._detector.detect = mock_detect

        # Tracker assigns id based on x position
        p._tracker = MagicMock()
        def mock_update(dets, fn):
            results = []
            for d in dets:
                tid = 1 if d["center"][0] < 500 else 2
                results.append({**d, "track_id": tid})
            return results
        p._tracker.update = mock_update
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1)
        assert _count_vehicle_events(pipeline_env["db_path"]) >= 2

    def test_frame_error_continues(self, pipeline_env):
        """Detector exception on one frame → processing continues."""
        p = _make_pipeline(pipeline_env)
        call_count = [0]

        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        def mock_detect(frame):
            call_count[0] += 1
            if call_count[0] == 3:
                raise RuntimeError("Simulated detection error")
            return []
        p._detector.detect = mock_detect

        p._tracker = MagicMock()
        p._tracker.update = MagicMock(return_value=[])
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1)
        assert p.error_count >= 1
        # Processing didn't crash — more frames were processed after the error
        assert call_count[0] > 3

    def test_pause_saves_checkpoint(self, pipeline_env):
        """Pause signal → checkpoint saved to DB."""
        p = _make_pipeline(pipeline_env)

        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        call_count = [0]
        p._detector = MagicMock()
        def mock_detect(frame):
            call_count[0] += 1
            if call_count[0] >= 3:
                p.pause()
            return []
        p._detector.detect = mock_detect

        p._tracker = MagicMock()
        p._tracker.update = MagicMock(return_value=[])
        p._tracker.get_state = MagicMock(return_value=b"state")

        p.process_video(frame_skip=1)
        assert p._checkpoint_mgr.has_checkpoint() is True


# ---------------------------------------------------------------------------
# TestPipelineCheckpointIntegration
# ---------------------------------------------------------------------------

class TestPipelineCheckpointIntegration:
    def test_resume_from_checkpoint(self, pipeline_env):
        """Save checkpoint, then restore counts and start_frame."""
        p = _make_pipeline(pipeline_env)
        p.vehicle_count = 10
        p.error_count = 1
        p.active_vehicles = {1: {"trajectory": [(100, 200)]}}

        p._save_checkpoint(frame_number=900, video_time=30.0)

        p2 = _make_pipeline(pipeline_env)
        start_frame = p2.resume_from_checkpoint()

        assert p2.vehicle_count == 10
        assert p2.error_count == 1
        # Rewind by 60s * 30fps = 1800 frames → max(0, 900-1800) = 0
        assert start_frame == 0

    def test_resume_restores_active_vehicles(self, pipeline_env):
        """Active vehicles dict is restored from checkpoint."""
        p = _make_pipeline(pipeline_env)
        p.active_vehicles = {
            5: {
                "origin_leg_id": 1,
                "trajectory": [(100, 200), (110, 190)],
                "confidences": [0.9, 0.85],
            }
        }
        p._save_checkpoint(frame_number=500, video_time=16.7)

        p2 = _make_pipeline(pipeline_env)
        p2.resume_from_checkpoint()
        assert 5 in p2.active_vehicles
        assert p2.active_vehicles[5]["origin_leg_id"] == 1
        assert len(p2.active_vehicles[5]["trajectory"]) == 2

    def test_detection_skip_runs_detection_on_every_nth_frame(self, pipeline_env):
        """Fast mode runs YOLO every Nth frame; the tracker fills in
        between via Kalman. This is what makes fast mode ~3x faster on
        CPU. Verifies the wiring by counting detector.detect() calls."""
        from unittest.mock import MagicMock
        p = ProcessingPipeline(
            project_id="test",
            db_path=pipeline_env["db_path"],
            video_path=pipeline_env["video_path"],
            legs=pipeline_env["legs"],
            fps=30.0,
            detection_skip=3,
        )
        # Mock the detector so we count calls without loading YOLO.
        mock_det = MagicMock()
        mock_det.detect = MagicMock(return_value=[])
        p._detector = mock_det
        # Mock tracker too (also lazy-loaded; would otherwise try to init
        # at first use).
        mock_tracker = MagicMock()
        mock_tracker.update = MagicMock(return_value=[])
        p._tracker = mock_tracker

        p.process_video(frame_skip=1)

        # The pipeline_env video is 30 frames. detection_skip=3 means
        # detection fires on frames 0, 3, 6, ..., 27 = 10 calls.
        assert mock_det.detect.call_count == 10

    def test_detection_skip_default_runs_every_frame(self, pipeline_env):
        """Accurate mode (default detection_skip=1) keeps current behavior
        of detecting on every frame."""
        from unittest.mock import MagicMock
        p = ProcessingPipeline(
            project_id="test",
            db_path=pipeline_env["db_path"],
            video_path=pipeline_env["video_path"],
            legs=pipeline_env["legs"],
            fps=30.0,
        )
        mock_det = MagicMock()
        mock_det.detect = MagicMock(return_value=[])
        p._detector = mock_det
        mock_tracker = MagicMock()
        mock_tracker.update = MagicMock(return_value=[])
        p._tracker = mock_tracker

        p.process_video(frame_skip=1)
        # 30 frames in the fixture video, detection runs on all of them.
        assert mock_det.detect.call_count == 30

    def test_resume_honours_start_frame_floor(self, pipeline_env):
        """The floor protects a prior segment's events when resuming a
        later segment in the same video. Without it, the 60-second rewind
        would dip below the segment boundary and the cleanup DELETE would
        wipe the prior segment."""
        # Save a checkpoint at frame 2500 (well within the would-be rewind
        # window of 60s * 30fps = 1800 frames → raw start = 700).
        p = _make_pipeline(pipeline_env)
        p.video_id = 1
        p._save_checkpoint(frame_number=2500, video_time=2500 / 30.0)

        # Seed two events on the same video_id: one at frame 500
        # (prior segment, must survive), one at frame 2400 (current
        # segment's overlap region, gets wiped).
        conn = sqlite3.connect(pipeline_env["db_path"])
        try:
            conn.execute(
                """INSERT INTO vehicle_events
                   (video_id, vehicle_track_id, origin_leg_id, movement,
                    trajectory_data, trajectory_confidence, vehicle_class,
                    detection_confidence, timestamp_video, frame_number)
                   VALUES (1, 1, 1, 'through', '[]', 0.9, 'car', 0.9, 0, 500)"""
            )
            conn.execute(
                """INSERT INTO vehicle_events
                   (video_id, vehicle_track_id, origin_leg_id, movement,
                    trajectory_data, trajectory_confidence, vehicle_class,
                    detection_confidence, timestamp_video, frame_number)
                   VALUES (1, 2, 1, 'through', '[]', 0.9, 'car', 0.9, 0, 2400)"""
            )
            conn.commit()
        finally:
            conn.close()

        p2 = _make_pipeline(pipeline_env)
        p2.video_id = 1
        # Floor = 2000 (the current segment's start). Resumed start should
        # clamp to 2000 (raw rewind would have given 700).
        start = p2.resume_from_checkpoint(start_frame_floor=2000)
        assert start == 2000

        conn = sqlite3.connect(pipeline_env["db_path"])
        try:
            rows = conn.execute(
                "SELECT frame_number FROM vehicle_events ORDER BY frame_number"
            ).fetchall()
        finally:
            conn.close()
        # Frame-500 event survives; frame-2400 (>= 2000 floor) is gone.
        assert [r[0] for r in rows] == [500]


# ---------------------------------------------------------------------------
# TestVehicleEventWriting
# ---------------------------------------------------------------------------

class TestVehicleEventWriting:
    def test_event_fields_complete(self, pipeline_env):
        """After finalization, all vehicle_events columns are populated."""
        p = _make_pipeline(pipeline_env)

        # Manually set up a vehicle that crossed origin and has a trajectory
        p.active_vehicles[99] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
        }

        p._finalize_vehicle(99, frame_number=25)

        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        e = events[0]
        assert e["vehicle_track_id"] == 99
        assert e["origin_leg_id"] == 1
        assert e["movement"] in ("through", "left", "right", "uturn")
        assert e["vehicle_class"] is not None
        assert e["detection_confidence"] == pytest.approx(0.9)
        assert e["frame_number"] == 25

    def test_event_fields_movement_uturn(self, pipeline_env):
        """movement column may be 'u_turn' (underscore) — accept both spellings."""
        p = _make_pipeline(pipeline_env)
        p.active_vehicles[99] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
        }
        p._finalize_vehicle(99, frame_number=25)
        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        assert events[0]["movement"] in ("through", "left", "right", "u_turn", "uturn")

    def test_native_articulated_votes_promote(self, pipeline_env):
        """plan_articulated_native: >= NATIVE_ARTICULATED_MIN_FRAMES class-8
        detections make the track articulated (FHWA 9) even when it was BORN
        as a plain vehicle — far-field semis detect as class 0/2 before the
        trailer resolves, so class-at-birth alone would under-call them."""
        p = _make_pipeline(pipeline_env)
        p.active_vehicles[7] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
            "n_native_articulated": 2,
        }
        p._finalize_vehicle(7, frame_number=25)
        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        assert events[0]["vehicle_class"] == "multi_unit_truck"
        assert events[0]["fhwa_class"] == 9

    def test_native_articulated_flicker_demotes(self, pipeline_env):
        """A single class-8 frame (below the vote floor) never flips the
        class: a born-8 track demotes to the validated COCO-truck path."""
        p = _make_pipeline(pipeline_env)
        p.active_vehicles[8] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 8,
            "class_name": "articulated_truck",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
            "n_native_articulated": 1,
        }
        p._finalize_vehicle(8, frame_number=25)
        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        # aspect 100/60 = 1.67 -> the truck branch's single_unit bucket
        assert events[0]["vehicle_class"] == "single_unit_truck"
        assert events[0]["fhwa_class"] == 5

    def test_native_articulated_votes_accumulate(self, pipeline_env):
        """_process_vehicle counts class-8 detections on the track."""
        p = _make_pipeline(pipeline_env)
        p._process_vehicle(11, _make_detection(500, 780, class_id=2), 1)
        p._process_vehicle(11, _make_detection(500, 760, class_id=8), 2)
        p._process_vehicle(11, _make_detection(500, 740, class_id=8), 3)
        assert p.active_vehicles[11]["n_native_articulated"] == 2

    def test_native_single_unit_votes_promote(self, pipeline_env):
        """plan_finetune_v2_retrain: >= NATIVE_SINGLE_UNIT_MIN_FRAMES id-9
        detections make the track single_unit_truck / FHWA 5 (-> Mediums)
        even when born as a plain vehicle, aspect branch bypassed."""
        p = _make_pipeline(pipeline_env)
        p.active_vehicles[12] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
            "n_native_single_unit": 2,
        }
        p._finalize_vehicle(12, frame_number=25)
        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        assert events[0]["vehicle_class"] == "single_unit_truck"
        assert events[0]["fhwa_class"] == 5

    def test_native_single_unit_flicker_demotes_artic_precedes(self, pipeline_env):
        """A single id-9 frame (below the floor) never flips the class:
        born-9 demotes to the COCO-truck aspect path. And when BOTH floors
        are met, articulated wins (the rarer, more specific class)."""
        p = _make_pipeline(pipeline_env)
        base = {
            "origin_leg_id": 1, "reference_heading": 0.0, "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20, "last_center": (500, 400),
            "class_name": "single_unit_truck",
            "bbox_width": 100.0, "bbox_height": 60.0, "bbox_area": 6000.0,
        }
        p.active_vehicles[13] = {**base, "class_id": 9,
                                 "n_native_single_unit": 1}
        p._finalize_vehicle(13, frame_number=25)
        p.active_vehicles[14] = {**base, "class_id": 2,
                                 "n_native_single_unit": 3,
                                 "n_native_articulated": 2}
        p._finalize_vehicle(14, frame_number=25)
        events = {e["vehicle_track_id"]: e
                  for e in _get_vehicle_events(pipeline_env["db_path"])}
        # aspect 100/60 = 1.67 -> the truck branch's single_unit bucket, but
        # via the DEMOTED coco path (fhwa 5 same value; the class_id took the
        # truck branch, not the native bypass — asserted by the born-9 demote
        # not crashing plus the artic-precedence case below)
        assert events[13]["vehicle_class"] == "single_unit_truck"
        assert events[13]["fhwa_class"] == 5
        assert events[14]["vehicle_class"] == "multi_unit_truck"
        assert events[14]["fhwa_class"] == 9

    def test_classifier_factors_persisted(self, pipeline_env):
        """Phase A instrumentation for bug #5: the classifier's decision
        factors (net_heading_change, cumulative_curvature, straightness,
        path_distance, num_points) must land on every event so a
        misclassification can be audited later. Without these, debugging
        the through-bias requires re-running detection from scratch."""
        p = _make_pipeline(pipeline_env)
        p.active_vehicles[42] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
        }
        p._finalize_vehicle(42, frame_number=25)

        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        e = events[0]
        # All five classifier factors must be populated (not NULL) for a
        # successfully-classified track.
        assert e["classifier_net_heading_change"] is not None
        assert e["classifier_cumulative_curvature"] is not None
        assert e["classifier_path_straightness"] is not None
        assert e["classifier_path_distance"] is not None
        assert e["classifier_num_points"] is not None
        # Sanity bounds on the values (catch wiring errors that would
        # otherwise let nonsense through).
        assert -180 <= e["classifier_net_heading_change"] <= 180
        assert 0 <= e["classifier_path_straightness"] <= 1
        assert e["classifier_path_distance"] > 0
        assert e["classifier_num_points"] == 20

    def test_timestamp_real_computed(self, pipeline_env):
        """When video_start_time is set, timestamp_real is computed."""
        p = _make_pipeline(pipeline_env, video_start_time="2024-06-15T08:00:00")

        p.active_vehicles[50] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
        }

        p._finalize_vehicle(50, frame_number=900)

        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        assert events[0]["timestamp_real"] is not None
        assert "2024-06-15" in events[0]["timestamp_real"]


# ---------------------------------------------------------------------------
# TestPipelineEdgeCases
# ---------------------------------------------------------------------------

class TestTurnCounts:
    def test_turn_counts_incremented_on_finalize(self, pipeline_env):
        """_finalize_vehicle increments turn_counts for a valid vehicle."""
        p = _make_pipeline(pipeline_env)
        p.active_vehicles[99] = {
            "origin_leg_id": 1,
            "reference_heading": 0.0,
            "origin_frame": 5,
            "trajectory": [(500, 780 - i * 20) for i in range(20)],
            "confidences": [0.9] * 20,
            "last_center": (500, 400),
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
        }

        p._finalize_vehicle(99, frame_number=25)

        events = _get_vehicle_events(pipeline_env["db_path"])
        assert len(events) == 1
        movement = events[0]["movement"]

        # Exactly one turn type should have been incremented in leg 1
        leg_counts = p.turn_counts[1]
        total = sum(leg_counts.values())
        assert total == 1
        if movement in leg_counts:
            assert leg_counts[movement] == 1

    def test_turn_counts_in_callback(self, pipeline_env):
        """turn_counts key appears in the progress callback payload."""
        p = _make_pipeline(pipeline_env)
        mock_dets = _nb_through_detections(num_frames=20)
        frame_idx = [0]

        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        def mock_detect(frame):
            idx = frame_idx[0]
            frame_idx[0] += 1
            return mock_dets[idx] if idx < len(mock_dets) else []
        p._detector.detect = mock_detect

        p._tracker = MagicMock()
        p._tracker.update = lambda dets, fn: [{**d, "track_id": 1} for d in dets]
        p._tracker.get_state = MagicMock(return_value=b"")

        payloads = []
        p.process_video(frame_skip=1, callback=lambda d: payloads.append(d))

        assert len(payloads) > 0
        for payload in payloads:
            assert "turn_counts" in payload
            tc = payload["turn_counts"]
            # Keys are stringified leg IDs
            assert "1" in tc
            assert "2" in tc
            for leg_id, leg_data in tc.items():
                assert "label" in leg_data
                assert "cardinal" in leg_data
                assert "counts" in leg_data
                assert set(leg_data["counts"].keys()) == {"through", "left", "right", "uturn"}


class TestPipelineEdgeCases:
    def test_empty_video(self, pipeline_env):
        """total_frames=0 → pipeline exits gracefully, no error, 0 events written."""
        p = _make_pipeline(pipeline_env)
        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)
        p._detector = MagicMock()
        p._detector.detect = MagicMock(return_value=[])
        p._tracker = MagicMock()
        p._tracker.update = MagicMock(return_value=[])
        p._tracker.get_state = MagicMock(return_value=b"")

        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.return_value = 0  # CAP_PROP_FRAME_COUNT = 0
        mock_cap.read.return_value = (False, None)

        with patch('backend.services.pipeline.cv2.VideoCapture', return_value=mock_cap):
            p.process_video(frame_skip=1)

        assert _count_vehicle_events(pipeline_env["db_path"]) == 0
        assert p.error_count == 0

    def test_no_detections_entire_video(self, pipeline_env):
        """Detector returns [] every frame → 0 events, no crash."""
        p = _make_pipeline(pipeline_env)
        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)
        p._detector = MagicMock()
        p._detector.detect = MagicMock(return_value=[])
        p._tracker = MagicMock()
        p._tracker.update = MagicMock(return_value=[])
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1)

        assert _count_vehicle_events(pipeline_env["db_path"]) == 0
        assert p.error_count == 0

    def test_vehicle_one_point_trajectory_not_counted(self, pipeline_env):
        """A vehicle detected on only ONE frame (then never again) cannot be
        classified — trajectory has fewer points than TRAJECTORY_MIN_POINTS,
        so no event is written. (Two-point trajectories DO get counted now —
        the previous behavior of dropping them was a throttling artifact.)"""
        p = _make_pipeline(pipeline_env)

        mock_dets = [
            [_make_detection(500, 770)],  # frame 0: single detection
            [],                            # frame 1+: vehicle never reappears
        ]
        mock_dets += [[] for _ in range(200)]  # extend past grace period

        frame_idx = [0]
        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)
        p._detector = MagicMock()

        def mock_detect(frame):
            idx = frame_idx[0]
            frame_idx[0] += 1
            return mock_dets[idx] if idx < len(mock_dets) else []

        p._detector.detect = mock_detect
        p._tracker = MagicMock()
        p._tracker.update = lambda dets, fn: [{**d, "track_id": 1} for d in dets]
        p._tracker.get_state = MagicMock(return_value=b"")

        p.process_video(frame_skip=1)

        assert _count_vehicle_events(pipeline_env["db_path"]) == 0


# ---------------------------------------------------------------------------
# TestOriginCounterFix
# ---------------------------------------------------------------------------

class TestOriginCounterFix:
    def test_n_crossed_exit_not_inflated(self, pipeline_env):
        """n_crossed_exit increments only once per vehicle, not on every re-attempt."""
        p = _make_pipeline(pipeline_env)

        # Vehicle moving east-to-west — heading ~270° which won't match NB(0) or EB(90)
        # within 90°. So origin assignment will fail.
        p.active_vehicles[42] = {
            "origin_leg_id": None,
            "reference_heading": None,
            "origin_frame": None,
            "origin_attempt_failed": False,
            "start_frame": 0,
            "trajectory": [],
            "confidences": [],
            "class_id": 2,
            "class_name": "car",
            "bbox_width": 100.0,
            "bbox_height": 60.0,
            "bbox_area": 6000.0,
        }

        # Simulate 30 points moving southwest (heading ~225°, doesn't match NB=0 or EB=90)
        for i in range(30):
            det = _make_detection(500 - i * 20, 400 + i * 20)
            det["track_id"] = 42
            p._process_vehicle(42, det, frame_number=i)

        # Origin assignment runs at frames 5, 10, 15, 20, 25 — all fail.
        # Without the fix, n_crossed_exit would be 5. With the fix, it's 1.
        assert p.n_crossed_exit == 1


# ---------------------------------------------------------------------------
# TestFatalErrorHandling
# ---------------------------------------------------------------------------

class TestFatalErrorHandling:
    def test_fatal_error_not_swallowed(self, pipeline_env):
        """MemoryError during frame processing is re-raised, not swallowed."""
        p = _make_pipeline(pipeline_env)

        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        p._detector.detect = MagicMock(side_effect=MemoryError("out of memory"))

        p._tracker = MagicMock()
        p._tracker.update = MagicMock(return_value=[])
        p._tracker.get_state = MagicMock(return_value=b"")

        with pytest.raises(MemoryError):
            p.process_video(frame_skip=1)

    def test_consecutive_errors_abort(self, pipeline_env):
        """RuntimeError on every frame → pipeline aborts after MAX_CONSECUTIVE_ERRORS."""
        from backend.services.pipeline import MAX_CONSECUTIVE_ERRORS

        p = _make_pipeline(pipeline_env)

        p._preprocessor = MagicMock()
        p._preprocessor.preprocess = MagicMock(side_effect=lambda f: f)

        p._detector = MagicMock()
        p._detector.detect = MagicMock(side_effect=RuntimeError("bad frame"))

        p._tracker = MagicMock()
        p._tracker.update = MagicMock(return_value=[])
        p._tracker.get_state = MagicMock(return_value=b"")

        # Mock a video with more frames than MAX_CONSECUTIVE_ERRORS
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = True
        mock_cap.get.return_value = MAX_CONSECUTIVE_ERRORS + 10
        read_count = [0]
        def mock_read():
            read_count[0] += 1
            if read_count[0] <= MAX_CONSECUTIVE_ERRORS + 10:
                return True, np.zeros((480, 640, 3), dtype=np.uint8)
            return False, None
        mock_cap.read = mock_read

        with patch('backend.services.pipeline.cv2.VideoCapture', return_value=mock_cap):
            with pytest.raises(RuntimeError, match="consecutive"):
                p.process_video(frame_skip=1)


# ---------------------------------------------------------------------------
# Detection cache: retrack-from-cache seam + write-through (Attribution v2 Step 1)
# ---------------------------------------------------------------------------

def test_process_cached_replays_schedule_with_empty_fill(pipeline_env, tmp_path):
    """process_cached must drive _ingest_detections on the full detection-frame
    schedule, supplying [] for frames the cache has no rows for (so the tracker
    Kalman cadence matches a live run)."""
    from backend.services.detection_cache import (
        DetectionCacheReader, DetectionCacheWriter,
    )
    pipe = _make_pipeline(pipeline_env)
    calls = []
    pipe._ingest_detections = lambda dets, fn: calls.append((fn, len(dets)))

    path = tmp_path / "c.parquet"
    w = DetectionCacheWriter(pq_path=path)
    w.add(0, [_make_detection(100, 100), _make_detection(200, 200)])
    w.add(2, [_make_detection(150, 150)])   # frame 1 absent
    w.add(5, [_make_detection(300, 300)])   # frames 3,4 absent
    w.close()

    pipe.process_cached(DetectionCacheReader(path), 0, 6, detection_skip=1)
    assert calls == [(0, 2), (1, 0), (2, 1), (3, 0), (4, 0), (5, 1)]


def test_process_cached_respects_detection_skip(pipeline_env, tmp_path):
    from backend.services.detection_cache import (
        DetectionCacheReader, DetectionCacheWriter,
    )
    pipe = _make_pipeline(pipeline_env)
    calls = []
    pipe._ingest_detections = lambda dets, fn: calls.append(fn)

    path = tmp_path / "c.parquet"
    w = DetectionCacheWriter(pq_path=path)
    for fi in (0, 2, 4):
        w.add(fi, [_make_detection(100, 100)])
    w.close()

    pipe.process_cached(DetectionCacheReader(path), 0, 6, detection_skip=2)
    assert calls == [0, 2, 4]   # only frames where frame % 2 == 0


def test_write_through_persists_detections(pipeline_env, tmp_path):
    """When a cache writer is attached, _process_single_frame persists each
    frame's detections without altering tracking behaviour."""
    from backend.services.detection_cache import (
        DetectionCacheReader, DetectionCacheWriter,
    )
    pipe = _make_pipeline(pipeline_env)
    # Stub the heavy collaborators so no YOLO loads and no video is decoded.
    pipe._preprocessor = MagicMock()
    pipe._preprocessor.preprocess.side_effect = lambda f: f
    pipe._detector = MagicMock()
    pipe._detector.detect.return_value = [_make_detection(120, 130)]
    pipe._ingest_detections = lambda dets, fn: None   # isolate write-through

    path = tmp_path / "c.parquet"
    writer = DetectionCacheWriter(pq_path=path)
    pipe._detection_cache_writer = writer
    pipe._process_single_frame(np.zeros((480, 640, 3), dtype=np.uint8), 7)
    writer.close()

    frames = dict(DetectionCacheReader(path).iter_frames())
    assert list(frames.keys()) == [7]
    assert frames[7][0]["center"] == [120.0, 130.0]


# ---------------------------------------------------------------------------
# Step 0 detection audit instrumentation (Attribution v2 P2.C)
# ---------------------------------------------------------------------------

def _track(tid, x, y, w=50, h=60, area=None):
    x1, y1, x2, y2 = x - w / 2, y - h / 2, x + w / 2, y + h / 2
    return {"track_id": tid, "bbox": [x1, y1, x2, y2], "center": [float(x), float(y)],
            "bbox_area": float(area if area is not None else w * h)}


def test_audit_distinguishes_real_hits_from_coasted(pipeline_env):
    pipe = _make_pipeline(pipeline_env)
    pipe._audit_mode = True
    det = _make_detection(120, 130, w=50, h=60)        # input YOLO box
    trk = _track(1, 120, 130, w=50, h=60)              # output track at same place

    pipe._audit_update([det], [trk], 0)                # real hit
    pipe._audit_update([], [trk], 1)                   # coasted (no detections)
    pipe._audit_update([], [trk], 2)                   # coasted again -> gap grows
    pipe._audit_update([det], [trk], 3)               # real hit again (gap resets)

    rec = pipe._audit_tracks[1]
    assert rec["real_yolo_hits"] == 2
    assert rec["n_output_frames"] == 4
    assert rec["max_coasted_gap"] == 2
    assert rec["first_real_hit_frame"] == 0


def test_audit_no_match_when_iou_too_low(pipeline_env):
    pipe = _make_pipeline(pipeline_env)
    pipe._audit_mode = True
    det = _make_detection(120, 130, w=50, h=60)
    far = _track(1, 600, 400, w=50, h=60)              # output track nowhere near det
    pipe._audit_update([det], [far], 0)
    assert pipe._audit_tracks[1]["real_yolo_hits"] == 0   # emitted box didn't belong to it


def test_audit_emit_records_dropped_tracks(pipeline_env):
    pipe = _make_pipeline(pipeline_env)
    pipe._audit_mode = True
    trk = _track(7, 120, 130)
    pipe._audit_update([], [trk], 0)                   # coasted only -> never a real hit
    # A track dropped with no origin must still produce an audit record.
    pipe._audit_emit(7, {"trajectory": [[120, 130]], "origin_leg_id": None})
    assert len(pipe._audit_records) == 1
    r = pipe._audit_records[0]
    assert r["track_id"] == 7 and r["real_yolo_hits"] == 0
    assert r["origin_assigned"] is False and r["final_points"] == 1


def test_audit_report_classify():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "audit_rep", os.path.join(os.path.dirname(__file__), "..", "..",
                                  "scripts", "audit_detection_vs_association.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.classify({"real_yolo_hits": 0, "final_points": 5, "max_coasted_gap": 0,
                       "origin_assigned": True}) == "never_emitted"
    assert m.classify({"real_yolo_hits": 5, "final_points": 1, "max_coasted_gap": 0,
                       "origin_assigned": True}) == "emitted_fragmented"
    assert m.classify({"real_yolo_hits": 5, "final_points": 30, "max_coasted_gap": 0,
                       "origin_assigned": True}) == "ok"


class TestPerCameraKnobs:
    """Per-camera detection/tracking knobs flow through the pipeline:
    NMS from calibration, tracker buffers via VehicleTracker's explicit params
    (not backend_kwargs), with explicit constructor args taking precedence."""

    def _pipeline(self, env, **kw):
        from backend.services.pipeline import ProcessingPipeline
        return ProcessingPipeline(
            project_id="test", db_path=env["db_path"],
            video_path=env["video_path"], legs=env["legs"], fps=30.0, **kw,
        )

    def test_nms_threshold_honored_from_calibration(self, pipeline_env, monkeypatch):
        import backend.services.pipeline as plmod
        captured = {}
        monkeypatch.setattr(plmod, "_class_agnostic_nms",
                            lambda dets, iou: (captured.__setitem__("iou", iou), dets)[1])
        p = self._pipeline(pipeline_env, calibration_params={"pre_track_nms_iou": 0.5})
        p._ingest_detections([_make_detection(400, 400), _make_detection(420, 410)], 1)
        assert captured.get("iou") == 0.5

    def test_nms_off_by_default(self, pipeline_env, monkeypatch):
        import backend.services.pipeline as plmod
        captured = {"called": False}
        def _spy(dets, iou):
            captured["called"] = True
            return dets
        monkeypatch.setattr(plmod, "_class_agnostic_nms", _spy)
        # No calibration override and global PRE_TRACK_NMS_IOU defaults to None.
        p = self._pipeline(pipeline_env)
        p._ingest_detections([_make_detection(400, 400), _make_detection(420, 410)], 1)
        assert captured["called"] is False

    def test_tracker_knobs_from_calibration(self, pipeline_env):
        p = self._pipeline(pipeline_env, calibration_params={
            "tracker_lost_buffer": 60, "tracker_match_threshold": 0.7,
            "tracker_activation_threshold": 0.4})
        init = p.tracker._backend._init_kwargs
        assert init["track_buffer"] == 60
        assert init["match_thresh"] == 0.7
        assert init["track_thresh"] == 0.4

    def test_calibration_override_beats_explicit(self, pipeline_env):
        # A per-camera calibration OVERRIDE wins over an explicit arg, because
        # callers pass the MODE DEFAULT as the explicit arg and a real per-camera
        # tune must beat it. (A sweep that needs to force a value injects it into
        # calibration_params, which is exactly this winning path.)
        p = self._pipeline(pipeline_env, tracker_match_threshold=0.8,
                           calibration_params={"tracker_match_threshold": 0.9})
        assert p.tracker._backend._init_kwargs["match_thresh"] == 0.9

    def test_explicit_used_when_no_calibration_override(self, pipeline_env):
        # No per-camera override (key absent / None) -> the explicit arg (mode
        # default or a deliberate sweep value like retrack_to_db's activation) drives.
        p = self._pipeline(pipeline_env, tracker_match_threshold=0.65,
                           calibration_params={"tracker_match_threshold": None})
        assert p.tracker._backend._init_kwargs["match_thresh"] == 0.65
