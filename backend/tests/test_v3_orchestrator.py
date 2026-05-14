"""v3 Phase 4 — orchestrator planner tests.

Pure planning logic (no torch, no pipeline). Tests against synthetic
camera/video dicts shaped like database rows.
"""

from datetime import datetime, timedelta

import pytest

from backend.services.v3_orchestrator import (
    PlanResult, VideoSegment, plan_intersection_day,
)


def _video(vid: int, start_iso: str, duration_s: float, fps: float = 30.0) -> dict:
    return {
        "video_id": vid,
        "path": f"/data/{vid}.mp4",
        "fps": fps,
        "duration_seconds": duration_s,
        "recording_start_datetime": start_iso,
        "recording_start_time": None,
    }


def _camera(cid: int, label: str = "Cam") -> dict:
    return {"camera_id": cid, "label": label}


def _trim(tid: int, start: str, end: str) -> dict:
    return {"trim_id": tid, "start_wallclock": start, "end_wallclock": end,
            "sort_order": tid}


DATE = "2026-05-14"


class TestSimpleCases:
    def test_no_trims_returns_error(self):
        plan = plan_intersection_day(
            date_str=DATE, trims=[],
            cameras_with_videos=[(_camera(1), [_video(1, f"{DATE}T08:00:00", 3600)])],
        )
        assert plan.segments == []
        assert "No trims" in plan.errors[0]

    def test_no_videos_returns_error(self):
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[_trim(1, "08:00:00", "09:00:00")],
            cameras_with_videos=[(_camera(1), [])],
        )
        assert plan.segments == []
        assert "No cameras" in plan.errors[0]


class TestSingleCameraSingleTrim:
    def test_trim_within_one_video(self):
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[_trim(1, "08:30:00", "09:30:00")],
            cameras_with_videos=[(
                _camera(1), [_video(1, f"{DATE}T08:00:00", 7200)],
            )],
        )
        assert plan.errors == []
        assert len(plan.segments) == 1
        seg = plan.segments[0]
        assert seg.video_id == 1
        assert seg.camera_id == 1
        assert seg.trim_id == 1
        # Trim starts 30min into the video → offset = 1800s
        assert seg.start_offset_seconds == 1800
        # Trim is 60min long → end_offset = 5400
        assert seg.end_offset_seconds == 5400
        # Frame numbers derived from offset * fps
        assert seg.start_frame == int(1800 * 30)
        assert seg.end_frame == int(5400 * 30)

    def test_trim_outside_video_reports_gap(self):
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[_trim(1, "20:00:00", "21:00:00")],
            cameras_with_videos=[(
                _camera(1), [_video(1, f"{DATE}T08:00:00", 3600)],
            )],
        )
        assert plan.segments == []
        assert "no video coverage" in plan.errors[0]


class TestMultipleVideosOneCamera:
    def test_trim_spans_two_videos(self):
        """One camera with two sequential clips that together cover the trim."""
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[_trim(1, "08:00:00", "10:00:00")],
            cameras_with_videos=[(_camera(1), [
                _video(1, f"{DATE}T08:00:00", 3600),  # 8:00-9:00
                _video(2, f"{DATE}T09:00:00", 3600),  # 9:00-10:00
            ])],
        )
        assert plan.errors == []
        # Should produce a segment per video
        assert len(plan.segments) == 2
        # Both videos fully consumed
        s1 = next(s for s in plan.segments if s.video_id == 1)
        s2 = next(s for s in plan.segments if s.video_id == 2)
        assert s1.start_offset_seconds == 0 and s1.end_offset_seconds == 3600
        assert s2.start_offset_seconds == 0 and s2.end_offset_seconds == 3600

    def test_gap_between_two_videos_reports_error(self):
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[_trim(1, "08:00:00", "10:00:00")],
            cameras_with_videos=[(_camera(1), [
                _video(1, f"{DATE}T08:00:00", 1800),   # 8:00-8:30
                _video(2, f"{DATE}T09:30:00", 1800),   # 9:30-10:00 (gap!)
            ])],
        )
        assert plan.segments == []
        assert "no video coverage" in plan.errors[0]


class TestMultipleCameras:
    def test_two_cameras_parallel_each_get_segment(self):
        """Two cameras filming the same window → both produce segments
        for the same trim (parallel coverage)."""
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[_trim(1, "08:00:00", "09:00:00")],
            cameras_with_videos=[
                (_camera(1), [_video(1, f"{DATE}T08:00:00", 3600)]),
                (_camera(2), [_video(2, f"{DATE}T08:00:00", 3600)]),
            ],
        )
        assert plan.errors == []
        assert len(plan.segments) == 2
        assert {s.camera_id for s in plan.segments} == {1, 2}

    def test_gap_coverage_between_two_cameras(self):
        """Cam1 covers 8:00-8:30, Cam2 covers 8:30-9:00, trim is 8:00-9:00.
        Should produce one segment per camera, each over its own coverage."""
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[_trim(1, "08:00:00", "09:00:00")],
            cameras_with_videos=[
                (_camera(1), [_video(1, f"{DATE}T08:00:00", 1800)]),
                (_camera(2), [_video(2, f"{DATE}T08:30:00", 1800)]),
            ],
        )
        assert plan.errors == []
        assert len(plan.segments) == 2
        s1 = next(s for s in plan.segments if s.camera_id == 1)
        s2 = next(s for s in plan.segments if s.camera_id == 2)
        # Each segment covers its own half
        assert s1.end_offset_seconds == 1800
        assert s2.end_offset_seconds == 1800

    def test_multiple_trims_each_produce_segments(self):
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[
                _trim(1, "08:00:00", "09:00:00"),
                _trim(2, "16:00:00", "17:00:00"),
            ],
            cameras_with_videos=[(_camera(1), [
                _video(1, f"{DATE}T07:00:00", 12 * 3600),  # 7am-7pm
            ])],
        )
        assert plan.errors == []
        # One video × two trims = two segments
        assert len(plan.segments) == 2
        trim_ids = {s.trim_id for s in plan.segments}
        assert trim_ids == {1, 2}


class TestPlanResultMetadata:
    def test_cameras_used_and_trims_used_populated(self):
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[_trim(1, "08:00:00", "09:00:00")],
            cameras_with_videos=[
                (_camera(1), [_video(1, f"{DATE}T08:00:00", 3600)]),
                (_camera(5), [_video(2, f"{DATE}T08:00:00", 3600)]),
            ],
        )
        assert plan.cameras_used == [1, 5]
        assert plan.trims_used == [1]

    def test_invalid_trim_time_produces_error(self):
        plan = plan_intersection_day(
            date_str=DATE,
            trims=[_trim(1, "invalid", "09:00:00")],
            cameras_with_videos=[(_camera(1), [_video(1, f"{DATE}T08:00:00", 3600)])],
        )
        assert plan.segments == []
        assert any("invalid" in e.lower() or "trim" in e.lower() for e in plan.errors)
