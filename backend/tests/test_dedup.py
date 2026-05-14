"""Tests for cross-camera deduplication."""

from datetime import datetime, timedelta

from backend.services.coverage import CameraCoverage, Interval
from backend.services.dedup import EventForDedup, deduplicate


def _ev(eid, cam, leg, mov, time_iso, conf=0.9):
    return EventForDedup(
        event_id=eid, camera_id=cam, leg_label=leg, cardinal_direction="N",
        movement=mov, wallclock_time=datetime.fromisoformat(time_iso),
        detection_confidence=conf, trajectory_confidence=0.9,
    )


def _parallel_cameras(start_iso, end_iso, cam_ids=(1, 2)):
    """Two cameras both covering the same interval = parallel coverage."""
    iv = Interval(datetime.fromisoformat(start_iso),
                  datetime.fromisoformat(end_iso))
    return [CameraCoverage(camera_id=c, intervals=[iv]) for c in cam_ids]


class TestNoOverlapPassthrough:
    def test_singletons_outside_overlap_kept(self):
        # One camera, no parallel coverage → nothing to dedup
        cov = [CameraCoverage(1, [Interval(
            datetime.fromisoformat("2026-05-14T08:00:00"),
            datetime.fromisoformat("2026-05-14T09:00:00"),
        )])]
        events = [
            _ev(1, 1, "North", "through", "2026-05-14T08:00:05"),
            _ev(2, 1, "North", "left", "2026-05-14T08:00:10"),
        ]
        results, dups = deduplicate(events, cov)
        assert dups == set()
        assert len(results) == 2


class TestParallelCoverage:
    def test_two_cameras_same_vehicle_collapsed(self):
        cov = _parallel_cameras("2026-05-14T08:00:00", "2026-05-14T09:00:00")
        events = [
            _ev(1, 1, "North", "through", "2026-05-14T08:00:05", conf=0.85),
            _ev(2, 2, "North", "through", "2026-05-14T08:00:06", conf=0.90),
        ]
        results, dups = deduplicate(events, cov)
        # Higher-conf event 2 wins; event 1 marked duplicate.
        assert len(results) == 1
        assert results[0].event_id == 2
        assert dups == {1}
        assert sorted(results[0].camera_ids) == [1, 2]

    def test_outside_time_window_kept_separately(self):
        cov = _parallel_cameras("2026-05-14T08:00:00", "2026-05-14T09:00:00")
        events = [
            _ev(1, 1, "North", "through", "2026-05-14T08:00:00"),
            _ev(2, 2, "North", "through", "2026-05-14T08:00:20"),
        ]
        results, dups = deduplicate(events, cov, time_window_seconds=5.0)
        assert dups == set()
        assert len(results) == 2

    def test_different_movement_not_merged(self):
        cov = _parallel_cameras("2026-05-14T08:00:00", "2026-05-14T09:00:00")
        events = [
            _ev(1, 1, "North", "through", "2026-05-14T08:00:05"),
            _ev(2, 2, "North", "left",    "2026-05-14T08:00:06"),
        ]
        results, dups = deduplicate(events, cov)
        assert dups == set()
        assert len(results) == 2

    def test_different_leg_not_merged(self):
        cov = _parallel_cameras("2026-05-14T08:00:00", "2026-05-14T09:00:00")
        events = [
            _ev(1, 1, "North", "through", "2026-05-14T08:00:05"),
            _ev(2, 2, "South", "through", "2026-05-14T08:00:06"),
        ]
        results, dups = deduplicate(events, cov)
        assert dups == set()
        assert len(results) == 2

    def test_same_camera_not_merged(self):
        """Same camera × two close events = two distinct vehicles. Don't dedup."""
        cov = _parallel_cameras("2026-05-14T08:00:00", "2026-05-14T09:00:00")
        events = [
            _ev(1, 1, "North", "through", "2026-05-14T08:00:05"),
            _ev(2, 1, "North", "through", "2026-05-14T08:00:06"),
        ]
        results, dups = deduplicate(events, cov)
        assert dups == set()
        assert len(results) == 2


class TestGapFill:
    def test_unmatched_event_in_overlap_still_counts(self):
        """Camera 2 missed a vehicle Camera 1 saw → keep Camera 1's event."""
        cov = _parallel_cameras("2026-05-14T08:00:00", "2026-05-14T09:00:00")
        events = [
            _ev(1, 1, "North", "through", "2026-05-14T08:00:05"),
            # No matching event from Camera 2 within window
        ]
        results, dups = deduplicate(events, cov)
        assert dups == set()
        assert len(results) == 1
        assert results[0].event_id == 1


class TestThreeCameras:
    def test_three_cameras_one_vehicle(self):
        iv = Interval(datetime.fromisoformat("2026-05-14T08:00:00"),
                      datetime.fromisoformat("2026-05-14T09:00:00"))
        cov = [CameraCoverage(c, [iv]) for c in (1, 2, 3)]
        events = [
            _ev(1, 1, "North", "through", "2026-05-14T08:00:05", conf=0.80),
            _ev(2, 2, "North", "through", "2026-05-14T08:00:06", conf=0.95),
            _ev(3, 3, "North", "through", "2026-05-14T08:00:07", conf=0.85),
        ]
        results, dups = deduplicate(events, cov)
        # All three collapse into one
        assert len(results) == 1
        # Camera 2 wins (highest confidence)
        assert results[0].event_id == 2
        assert sorted(results[0].camera_ids) == [1, 2, 3]
        assert dups == {1, 3}


class TestCardinalToggle:
    def test_cardinal_required_blocks_merge(self):
        """If `use_cardinal=True` and two cameras label the leg differently
        (different cardinal_direction), don't merge them."""
        cov = _parallel_cameras("2026-05-14T08:00:00", "2026-05-14T09:00:00")
        e1 = EventForDedup(1, 1, "North", "N", "through",
                           datetime.fromisoformat("2026-05-14T08:00:05"), 0.9, 0.9)
        e2 = EventForDedup(2, 2, "North", "S", "through",
                           datetime.fromisoformat("2026-05-14T08:00:06"), 0.9, 0.9)
        results, dups = deduplicate([e1, e2], cov, use_cardinal=True)
        assert dups == set()
        assert len(results) == 2

    def test_cardinal_disabled_allows_merge(self):
        cov = _parallel_cameras("2026-05-14T08:00:00", "2026-05-14T09:00:00")
        e1 = EventForDedup(1, 1, "North", "N", "through",
                           datetime.fromisoformat("2026-05-14T08:00:05"), 0.9, 0.9)
        e2 = EventForDedup(2, 2, "North", "S", "through",
                           datetime.fromisoformat("2026-05-14T08:00:06"), 0.9, 0.9)
        results, dups = deduplicate([e1, e2], cov, use_cardinal=False)
        # Match on leg+movement only → they collapse. With equal confidence
        # the earlier anchor (event 1) wins, so event 2 is the duplicate.
        assert len(results) == 1
        assert dups == {2}
