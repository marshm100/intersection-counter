"""Tests for the trim-coverage validator."""

from datetime import datetime, timedelta

import pytest

from backend.services.coverage import (
    CameraCoverage, Interval, compute_coverage_report,
    find_overlap_regions, union_intervals, video_to_coverage_interval,
    wallclock_to_datetime,
)


def _iv(h1, m1, s1, h2, m2, s2):
    """Quick 1970-01-01 interval helper for terse tests."""
    return Interval(
        datetime(1970, 1, 1, h1, m1, s1),
        datetime(1970, 1, 1, h2, m2, s2),
    )


class TestIntervalBasics:
    def test_overlap_detection(self):
        a = _iv(8, 0, 0, 10, 0, 0)
        b = _iv(9, 0, 0, 11, 0, 0)
        assert a.overlaps(b) is True

    def test_no_overlap(self):
        a = _iv(8, 0, 0, 10, 0, 0)
        b = _iv(10, 0, 0, 12, 0, 0)
        assert a.overlaps(b) is False

    def test_intersect(self):
        a = _iv(8, 0, 0, 10, 0, 0)
        b = _iv(9, 30, 0, 11, 0, 0)
        i = a.intersect(b)
        assert i == _iv(9, 30, 0, 10, 0, 0)

    def test_intersect_disjoint_returns_none(self):
        a = _iv(8, 0, 0, 9, 0, 0)
        b = _iv(10, 0, 0, 11, 0, 0)
        assert a.intersect(b) is None

    def test_invalid_interval_rejected(self):
        with pytest.raises(ValueError):
            _iv(10, 0, 0, 9, 0, 0)


class TestVideoCoverageHelpers:
    def test_video_to_interval_from_duration(self):
        start = datetime(2026, 5, 14, 8, 0, 0)
        iv = video_to_coverage_interval(start, 3600.0)
        assert iv.start == start
        assert iv.end == datetime(2026, 5, 14, 9, 0, 0)

    def test_wallclock_to_datetime(self):
        dt = wallclock_to_datetime("2026-05-14", "07:30:00")
        assert dt == datetime(2026, 5, 14, 7, 30, 0)


class TestUnion:
    def test_merge_overlapping(self):
        a = _iv(8, 0, 0, 10, 0, 0)
        b = _iv(9, 0, 0, 11, 0, 0)
        merged = union_intervals([a, b])
        assert merged == [_iv(8, 0, 0, 11, 0, 0)]

    def test_disjoint_stays_separate(self):
        a = _iv(8, 0, 0, 9, 0, 0)
        b = _iv(10, 0, 0, 11, 0, 0)
        merged = union_intervals([a, b])
        assert merged == [a, b]

    def test_touching_merges(self):
        # Half-open: end of A equals start of B → they touch → merge.
        a = _iv(8, 0, 0, 9, 0, 0)
        b = _iv(9, 0, 0, 10, 0, 0)
        merged = union_intervals([a, b])
        assert merged == [_iv(8, 0, 0, 10, 0, 0)]


class TestCoverageReport:
    def test_single_camera_full_coverage(self):
        trim = _iv(7, 0, 0, 9, 0, 0)
        cam = CameraCoverage(camera_id=1, intervals=[_iv(6, 0, 0, 10, 0, 0)])
        report = compute_coverage_report([cam], trim)
        assert report.is_fully_covered()
        assert report.gaps == []
        assert len(report.sub_intervals) == 1
        iv, cams = report.sub_intervals[0]
        assert iv == trim
        assert cams == [1]

    def test_uncovered_trim_has_full_gap(self):
        trim = _iv(7, 0, 0, 9, 0, 0)
        cam = CameraCoverage(camera_id=1, intervals=[_iv(10, 0, 0, 11, 0, 0)])
        report = compute_coverage_report([cam], trim)
        assert not report.is_fully_covered()
        assert report.gaps == [trim]
        assert report.sub_intervals == []

    def test_partial_coverage_gap_in_middle(self):
        trim = _iv(7, 0, 0, 9, 0, 0)
        # Camera covers 7:00-8:00, gap 8:00-8:30, camera 8:30-9:00
        cam = CameraCoverage(camera_id=1, intervals=[
            _iv(7, 0, 0, 8, 0, 0),
            _iv(8, 30, 0, 9, 0, 0),
        ])
        report = compute_coverage_report([cam], trim)
        assert not report.is_fully_covered()
        assert report.gaps == [_iv(8, 0, 0, 8, 30, 0)]

    def test_two_cameras_gap_coverage(self):
        """Camera A 7:00-8:00, Camera B 8:00-9:00. Together cover the trim."""
        trim = _iv(7, 0, 0, 9, 0, 0)
        cam_a = CameraCoverage(1, [_iv(7, 0, 0, 8, 0, 0)])
        cam_b = CameraCoverage(2, [_iv(8, 0, 0, 9, 0, 0)])
        report = compute_coverage_report([cam_a, cam_b], trim)
        assert report.is_fully_covered()
        assert len(report.sub_intervals) == 2
        assert report.sub_intervals[0][1] == [1]
        assert report.sub_intervals[1][1] == [2]

    def test_two_cameras_parallel_coverage(self):
        """Both cameras film 7:00-9:00 → trim is parallel-covered throughout."""
        trim = _iv(7, 0, 0, 9, 0, 0)
        cam_a = CameraCoverage(1, [_iv(7, 0, 0, 9, 0, 0)])
        cam_b = CameraCoverage(2, [_iv(7, 0, 0, 9, 0, 0)])
        report = compute_coverage_report([cam_a, cam_b], trim)
        assert report.is_fully_covered()
        assert len(report.sub_intervals) == 1
        assert report.sub_intervals[0][1] == [1, 2]

    def test_mixed_coverage(self):
        """A covers 7-8, B covers 7:30-9. Trim 7-9 has 3 sub-intervals:
        7:00-7:30 (A only), 7:30-8:00 (both), 8:00-9:00 (B only)."""
        trim = _iv(7, 0, 0, 9, 0, 0)
        cam_a = CameraCoverage(1, [_iv(7, 0, 0, 8, 0, 0)])
        cam_b = CameraCoverage(2, [_iv(7, 30, 0, 9, 0, 0)])
        report = compute_coverage_report([cam_a, cam_b], trim)
        assert report.is_fully_covered()
        assert len(report.sub_intervals) == 3
        # First sub: A only
        assert report.sub_intervals[0][1] == [1]
        # Middle: both
        assert report.sub_intervals[1][1] == [1, 2]
        # Last: B only
        assert report.sub_intervals[2][1] == [2]

    def test_coverage_outside_trim_doesnt_count(self):
        trim = _iv(7, 0, 0, 9, 0, 0)
        # Camera covers 9-10 entirely outside the trim
        cam = CameraCoverage(1, [_iv(9, 0, 0, 10, 0, 0)])
        report = compute_coverage_report([cam], trim)
        assert not report.is_fully_covered()
        assert report.gaps == [trim]


class TestFindOverlapRegions:
    def test_no_overlap(self):
        cams = [
            CameraCoverage(1, [_iv(7, 0, 0, 8, 0, 0)]),
            CameraCoverage(2, [_iv(8, 0, 0, 9, 0, 0)]),
        ]
        assert find_overlap_regions(cams) == []

    def test_full_overlap(self):
        cams = [
            CameraCoverage(1, [_iv(7, 0, 0, 9, 0, 0)]),
            CameraCoverage(2, [_iv(7, 0, 0, 9, 0, 0)]),
        ]
        regions = find_overlap_regions(cams)
        assert regions == [_iv(7, 0, 0, 9, 0, 0)]

    def test_partial_overlap(self):
        cams = [
            CameraCoverage(1, [_iv(7, 0, 0, 8, 30, 0)]),
            CameraCoverage(2, [_iv(8, 0, 0, 9, 0, 0)]),
        ]
        regions = find_overlap_regions(cams)
        assert regions == [_iv(8, 0, 0, 8, 30, 0)]

    def test_three_cameras_pairs(self):
        # 1: 7-9, 2: 8-10, 3: 9-11. Overlaps: 1+2 at 8-9, 2+3 at 9-10.
        cams = [
            CameraCoverage(1, [_iv(7, 0, 0, 9, 0, 0)]),
            CameraCoverage(2, [_iv(8, 0, 0, 10, 0, 0)]),
            CameraCoverage(3, [_iv(9, 0, 0, 11, 0, 0)]),
        ]
        regions = find_overlap_regions(cams)
        # Continuous overlap from 8:00 to 10:00 (always >=2 cameras)
        assert regions == [_iv(8, 0, 0, 10, 0, 0)]
