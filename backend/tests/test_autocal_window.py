"""Auto-cal sample-window resolution + bounded parallel concurrency
(2026-08-18 operator feature). The resolver is tested pure (video lookup
monkeypatched); the pool is tested with a stubbed collector — no YOLO."""
import sys
import threading
import time
import types

import pytest

from backend.services import auto_calibrator_v2 as ac


VIDEO_24H = {"video_id": 7, "path": "x.mp4", "duration_seconds": 86404.6,
             "recording_start_datetime": "2026-05-12T00:00:02"}


@pytest.fixture
def midnight_video(monkeypatch):
    monkeypatch.setattr(ac, "_resolve_video_path",
                        lambda p, c, v: ("x.mp4", 7))
    monkeypatch.setattr(ac, "get_video", lambda p, v: dict(VIDEO_24H))


class TestResolveSampleWindow:
    def test_default_is_7h_offset_15min_span(self, midnight_video):
        # duration default re-frozen 15 min (operator ruling 2026-08-19:
        # collection costs ~3 GPU-min per footage-min)
        w = ac.resolve_sample_window("p", 1)
        assert w["sample_start_sec"] == 7 * 3600
        assert w["sample_end_sec"] == 7 * 3600 + 15 * 60
        assert (w["start_clock"], w["end_clock"]) == ("07:00", "07:15")
        assert w["source"] == "default"

    def test_clock_form_resolves_against_recording_start(self, midnight_video):
        w = ac.resolve_sample_window("p", 1, start_hms="07:00",
                                     duration_min=660)
        # recording starts at 00:00:02 -> the 07:00 wall clock is 2 s
        # earlier in video-relative time
        assert w["sample_start_sec"] == 25198.0
        assert w["sample_end_sec"] == 25198.0 + 660 * 60
        assert w["source"] == "clock"

    def test_duration_bounds_are_hard_errors(self, midnight_video):
        with pytest.raises(ValueError, match="at least 15 minutes"):
            ac.resolve_sample_window("p", 1, start_hms="07:00",
                                     duration_min=10)
        with pytest.raises(ValueError, match="at most 15 hours"):
            ac.resolve_sample_window("p", 1, start_hms="07:00",
                                     duration_min=16 * 60)

    def test_end_clamps_to_footage(self, midnight_video):
        w = ac.resolve_sample_window("p", 1, start_hms="20:00",
                                     duration_min=10 * 60)
        assert w["sample_end_sec"] == pytest.approx(86404.6)

    def test_start_before_footage_is_an_error(self, monkeypatch):
        monkeypatch.setattr(ac, "_resolve_video_path",
                            lambda p, c, v: ("x.mp4", 7))
        monkeypatch.setattr(ac, "get_video", lambda p, v: {
            "video_id": 7, "duration_seconds": 7200.0,
            "recording_start_datetime": "2026-05-12T08:00:00"})
        with pytest.raises(ValueError, match="before the footage begins"):
            ac.resolve_sample_window("p", 1, start_hms="07:00",
                                     duration_min=60)

    def test_cross_midnight_wraps(self, monkeypatch):
        monkeypatch.setattr(ac, "_resolve_video_path",
                            lambda p, c, v: ("x.mp4", 7))
        monkeypatch.setattr(ac, "get_video", lambda p, v: {
            "video_id": 7, "duration_seconds": 10 * 3600.0,
            "recording_start_datetime": "2026-05-12T22:00:00"})
        w = ac.resolve_sample_window("p", 1, start_hms="01:00",
                                     duration_min=120)
        assert w["sample_start_sec"] == 3 * 3600.0
        assert w["start_clock"] == "01:00"

    def test_short_video_defaults_from_zero(self, monkeypatch):
        monkeypatch.setattr(ac, "_resolve_video_path",
                            lambda p, c, v: ("x.mp4", 7))
        monkeypatch.setattr(ac, "get_video", lambda p, v: {
            "video_id": 7, "duration_seconds": 2 * 3600.0,
            "recording_start_datetime": "2026-05-12T07:00:00"})
        w = ac.resolve_sample_window("p", 1)
        assert w["sample_start_sec"] == 0.0
        assert w["sample_end_sec"] == 15 * 60.0

    def test_video_below_minimum_is_an_error(self, monkeypatch):
        monkeypatch.setattr(ac, "_resolve_video_path",
                            lambda p, c, v: ("x.mp4", 7))
        monkeypatch.setattr(ac, "get_video", lambda p, v: {
            "video_id": 7, "duration_seconds": 600.0,
            "recording_start_datetime": "2026-05-12T07:00:00"})
        with pytest.raises(ValueError, match="15-minute minimum"):
            ac.resolve_sample_window("p", 1)


class TestBoundedParallelPool:
    def test_two_run_third_queues_fifo(self, monkeypatch):
        """Three cameras enqueued: at most AUTO_CAL_MAX_CONCURRENT (2) run
        at once; the third reports queued with a position, then runs when
        a slot frees. Completion states land for all three."""
        peak = {"n": 0}
        running_now = {"n": 0}
        gate = threading.Event()
        lock = threading.Lock()

        def fake_run(path, sample_start_sec, sample_end_sec,
                     should_cancel=None, on_progress=None, **kwargs):
            with lock:
                running_now["n"] += 1
                peak["n"] = max(peak["n"], running_now["n"])
            gate.wait(timeout=5.0)
            with lock:
                running_now["n"] -= 1
            return {"leg_zones": [], "paths": [], "stats": {}}

        stub = types.ModuleType("scripts.auto_calibrate")
        stub.run = fake_run
        stub.AutoCalCancelled = type("AutoCalCancelled", (Exception,), {})
        monkeypatch.setitem(sys.modules, "scripts.auto_calibrate", stub)
        monkeypatch.setattr(ac, "_resolve_video_path",
                            lambda p, c, v: ("x.mp4", 7))
        monkeypatch.setattr(ac, "save_calibration_suggestion",
                            lambda *a, **k: None)
        monkeypatch.setattr(ac, "AUTO_CAL_MAX_CONCURRENT", 2)
        monkeypatch.setattr(ac, "_JOBS", {})

        for cam in (101, 102, 103):
            ac.enqueue("p", cam, video_id=7, sample_start_sec=0,
                       sample_end_sec=900)

        # Wait for BOTH pool slots to be occupied before opening the
        # gate — otherwise a slow thread start lets job 1 time out of
        # the stub before job 2 arrives and peak never reaches 2
        # (scheduling flake observed on Windows).
        deadline = time.time() + 5.0
        while time.time() < deadline and running_now["n"] < 2:
            time.sleep(0.05)
        assert running_now["n"] == 2, "two jobs never ran concurrently"

        deadline = time.time() + 5.0
        third_queued = False
        while time.time() < deadline:
            s = ac.get_status(103)
            if s and s["status"] == "queued" and s.get("queue_position"):
                third_queued = True
                break
            time.sleep(0.05)
        assert third_queued, "third job never reported a queue position"
        assert peak["n"] <= 2

        gate.set()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            done = [ac.get_status(c) for c in (101, 102, 103)]
            if all(s and s["status"] == "complete" for s in done):
                break
            time.sleep(0.05)
        assert all(ac.get_status(c)["status"] == "complete"
                   for c in (101, 102, 103))
        assert peak["n"] == 2, "pool never actually ran two in parallel"

    def test_cancel_while_queued(self, monkeypatch):
        gate = threading.Event()

        def fake_run(path, sample_start_sec, sample_end_sec,
                     should_cancel=None, on_progress=None, **kwargs):
            gate.wait(timeout=5.0)
            return {"leg_zones": [], "paths": [], "stats": {}}

        stub = types.ModuleType("scripts.auto_calibrate")
        stub.run = fake_run
        stub.AutoCalCancelled = type("AutoCalCancelled", (Exception,), {})
        monkeypatch.setitem(sys.modules, "scripts.auto_calibrate", stub)
        monkeypatch.setattr(ac, "_resolve_video_path",
                            lambda p, c, v: ("x.mp4", 7))
        monkeypatch.setattr(ac, "save_calibration_suggestion",
                            lambda *a, **k: None)
        monkeypatch.setattr(ac, "AUTO_CAL_MAX_CONCURRENT", 1)
        monkeypatch.setattr(ac, "_JOBS", {})

        ac.enqueue("p", 201, video_id=7, sample_start_sec=0,
                   sample_end_sec=900)
        ac.enqueue("p", 202, video_id=7, sample_start_sec=0,
                   sample_end_sec=900)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            s = ac.get_status(202)
            if s and s["status"] == "queued" and s.get("queue_position"):
                break
            time.sleep(0.05)
        assert ac.cancel(202)
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if ac.get_status(202)["status"] == "cancelled":
                break
            time.sleep(0.05)
        assert ac.get_status(202)["status"] == "cancelled"
        gate.set()
        deadline = time.time() + 5.0
        while time.time() < deadline:
            if ac.get_status(201)["status"] == "complete":
                break
            time.sleep(0.05)
        assert ac.get_status(201)["status"] == "complete"
