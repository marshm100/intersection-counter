"""v3 Phase 4 — processing endpoints (preflight + status + cancel).

The /start endpoint kicks off real pipeline work in a thread, which is
slow and torch-dependent. We exercise it via preflight (pure planning,
no pipeline spawn) and verify the status/cancel surfaces respond correctly.
"""

import os
import shutil
import tempfile

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.app import app


client = TestClient(app)


def _make_video(dir_path: str, name: str, frames: int = 90) -> str:
    p = os.path.join(dir_path, name)
    w = cv2.VideoWriter(p, cv2.VideoWriter_fourcc(*"mp4v"), 30.0, (320, 240))
    for i in range(frames):
        w.write(np.full((240, 320, 3), 50 + i, dtype=np.uint8))
    w.release()
    return p


@pytest.fixture()
def configured_intersection():
    """Project with 2 cameras at an intersection-day and one valid trim."""
    pid = client.post("/api/projects", json={"name": "v3-proc"}).json()["project_id"]
    tmpdir = tempfile.mkdtemp(prefix="v3_proc_")
    try:
        paths = [
            _make_video(tmpdir, "Cam1_01_20260514_080000 Main St.mp4"),
            _make_video(tmpdir, "Cam2_01_20260514_080000 Main St.mp4"),
        ]
        client.post(f"/api/projects/{pid}/videos/bulk", json={"paths": paths})
        body = client.post(f"/api/projects/{pid}/videos/save-labels").json()
        iid = body["intersections"][0]["intersection_id"]
        # Add a trim well within coverage (videos run 08:00:00-08:00:03)
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "08:00:00", "end_wallclock": "08:00:02"},
        )
        yield pid, iid
    finally:
        client.delete(f"/api/projects/{pid}")
        shutil.rmtree(tmpdir, ignore_errors=True)


class TestPreflight:
    def test_preflight_ok_returns_segments(self, configured_intersection):
        pid, iid = configured_intersection
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/preflight")
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["errors"] == []
        # 2 cameras × 1 trim × 1 video each = 2 segments
        assert body["segment_count"] == 2
        assert sorted(body["cameras_used"]) and sorted(body["trims_used"])

    def test_preflight_reports_uncovered_trim(self, configured_intersection):
        pid, iid = configured_intersection
        # Add an uncovered trim
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "20:00:00", "end_wallclock": "21:00:00"},
        )
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/preflight")
        body = r.json()
        assert body["ok"] is False
        assert len(body["errors"]) >= 1
        assert "no video coverage" in body["errors"][0].lower()


class TestStartGuard:
    def test_start_refuses_on_coverage_error(self, configured_intersection):
        pid, iid = configured_intersection
        # Wipe the good trim, leave only a bad one
        trims = client.get(f"/api/projects/{pid}/intersections/{iid}/trims").json()
        for t in trims:
            client.delete(f"/api/projects/{pid}/intersections/{iid}/trims/{t['trim_id']}")
        client.post(
            f"/api/projects/{pid}/intersections/{iid}/trims",
            json={"start_wallclock": "20:00:00", "end_wallclock": "21:00:00"},
        )
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/start")
        assert r.status_code == 422
        assert "trim coverage errors" in str(r.json()["detail"])

    def test_start_refuses_with_no_trims(self, configured_intersection):
        pid, iid = configured_intersection
        # Wipe all trims so plan yields "no trims"
        trims = client.get(f"/api/projects/{pid}/intersections/{iid}/trims").json()
        for t in trims:
            client.delete(f"/api/projects/{pid}/intersections/{iid}/trims/{t['trim_id']}")
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/start")
        assert r.status_code == 422


class TestStatusBeforeStart:
    def test_idle_status(self, configured_intersection):
        pid, iid = configured_intersection
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/processing/status")
        assert r.status_code == 200
        assert r.json()["status"] == "idle"


class TestFrameProgressSurfacing:
    """The chip needs frame_number/progress_pct/eta_seconds/fps_processing
    to render a meaningful liveness indicator and ETA. The v3 _on_frame
    callback writes these to _v3_jobs and /processing/status passes them
    through. This test seeds the in-memory job directly so we don't have
    to spawn a real pipeline."""

    def test_frame_progress_appears_in_status(self, configured_intersection):
        import backend.routers.intersections as router_mod
        pid, iid = configured_intersection
        key = (pid, iid)
        # Seed an in-memory job mimicking what _on_frame would produce
        # after one callback fires.
        try:
            with router_mod._v3_jobs_lock:
                router_mod._v3_jobs[key] = {
                    "status": "running",
                    "segment_count": 2,
                    "current_segment_index": 0,
                    "current_camera_id": None,
                    "current_trim_id": None,
                    "current_video_id": None,
                    "error": None, "warnings": [], "cancel_requested": False,
                    "frame_progress": {
                        "frame_number": 1234,
                        "total_frames": 9999,
                        "progress_pct": 12.34,
                        "fps_processing": 25.0,
                        "eta_seconds": 600,
                        "vehicle_count": 7,
                    },
                }

            r = client.get(f"/api/projects/{pid}/intersections/{iid}/processing/status")
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "running"
            fp = body.get("frame_progress")
            assert fp is not None
            assert fp["frame_number"] == 1234
            assert fp["eta_seconds"] == 600
            assert fp["fps_processing"] == 25.0
            assert fp["vehicle_count"] == 7
        finally:
            with router_mod._v3_jobs_lock:
                router_mod._v3_jobs.pop(key, None)


class TestStatusConfiguredFlag:
    """The 'configured' flag is what lets the chip switch from
    'Configure' to 'Start' — i.e. distinguish 'never set up' from
    'set up but not yet started'. Without it both states show the
    same 'Idle / Configure' affordance and the user's setup work
    looks lost on the Processing tab."""

    def test_configured_true_with_trim_coverage(self, configured_intersection):
        pid, iid = configured_intersection
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/processing/status")
        body = r.json()
        assert body["status"] == "idle"
        assert body["configured"] is True

    def test_configured_false_when_trims_removed(self, configured_intersection):
        pid, iid = configured_intersection
        # Wipe all trims so preflight fails → not configured.
        trims = client.get(f"/api/projects/{pid}/intersections/{iid}/trims").json()
        for t in trims:
            client.delete(f"/api/projects/{pid}/intersections/{iid}/trims/{t['trim_id']}")

        r = client.get(f"/api/projects/{pid}/intersections/{iid}/processing/status")
        body = r.json()
        assert body["status"] == "idle"
        assert body["configured"] is False


class TestCancelNoOpOnIdle:
    def test_cancel_when_idle_is_safe(self, configured_intersection):
        pid, iid = configured_intersection
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/cancel")
        # Always returns 200; cancellation only takes effect on a running job
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Resume-from-checkpoint flow: persisted run-state, healing, /resume,
# /reprocess. Avoids spawning the real pipeline thread by stubbing
# _run_v3_pipeline so we can assert on the kwargs it would have received.
# ---------------------------------------------------------------------------


class TestRunStateHelpers:
    def test_set_get_clear_run_state(self, configured_intersection):
        from backend.database import (
            clear_v3_run_state, get_v3_run_state, set_v3_run_state,
        )
        pid, iid = configured_intersection
        assert get_v3_run_state(pid, iid) is None

        set_v3_run_state(pid, iid, "running")
        st = get_v3_run_state(pid, iid)
        assert st is not None and st["status"] == "running"

        set_v3_run_state(pid, iid, "error", error_message="boom")
        st = get_v3_run_state(pid, iid)
        assert st["status"] == "error" and st["error_message"] == "boom"

        clear_v3_run_state(pid, iid)
        assert get_v3_run_state(pid, iid) is None

    def test_heal_running_to_interrupted(self, configured_intersection):
        from backend.database import (
            get_v3_run_state, heal_v3_running_to_interrupted, set_v3_run_state,
        )
        pid, iid = configured_intersection
        set_v3_run_state(pid, iid, "running")
        healed = heal_v3_running_to_interrupted(pid)
        assert iid in healed
        assert get_v3_run_state(pid, iid)["status"] == "interrupted"

    def test_heal_leaves_non_running_alone(self, configured_intersection):
        from backend.database import (
            get_v3_run_state, heal_v3_running_to_interrupted, set_v3_run_state,
        )
        pid, iid = configured_intersection
        set_v3_run_state(pid, iid, "complete")
        healed = heal_v3_running_to_interrupted(pid)
        assert healed == []
        assert get_v3_run_state(pid, iid)["status"] == "complete"


class TestStatusDBFallback:
    def test_status_reads_db_when_no_in_memory_job(self, configured_intersection):
        from backend.database import set_v3_run_state
        pid, iid = configured_intersection
        set_v3_run_state(pid, iid, "interrupted")
        r = client.get(f"/api/projects/{pid}/intersections/{iid}/processing/status")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "interrupted"
        # No checkpoint was seeded, so has_checkpoint should be False.
        assert body.get("has_checkpoint") is False


class TestStartGuardOnActiveState:
    def test_start_refused_when_interrupted(self, configured_intersection):
        from backend.database import set_v3_run_state
        pid, iid = configured_intersection
        set_v3_run_state(pid, iid, "interrupted")
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/start")
        assert r.status_code == 409
        detail = r.json()["detail"]
        assert detail["status"] == "interrupted"
        # Message should steer the user to Continue/Restart from beginning
        assert "Continue" in detail["message"]
        assert "Restart from beginning" in detail["message"]


def _seed_checkpoint(pid: str, *, video_id: int, camera_id: int,
                     trim_id: int, frame_number: int):
    """Helper: write a checkpoint row directly. Avoids spinning up a real
    pipeline just to populate it."""
    from backend.database import get_db_path
    from backend.services.checkpoint import CheckpointManager
    cp = CheckpointManager(str(get_db_path(pid)))
    cp.save_checkpoint(
        frame_number=frame_number,
        timestamp_video=frame_number / 30.0,
        tracker_state=b"",
        active_trajectories=b"",
        vehicle_count=0,
        error_count=0,
        current_video_id=video_id,
        current_camera_id=camera_id,
        current_trim_id=trim_id,
    )


class TestResume:
    def test_resume_refuses_when_not_interrupted(self, configured_intersection):
        pid, iid = configured_intersection
        # No run-state row at all → "idle" state, can't resume
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/resume")
        assert r.status_code == 400
        assert "not in 'interrupted'" in r.json()["detail"]

    def test_resume_refuses_when_no_checkpoint(self, configured_intersection):
        from backend.database import set_v3_run_state
        pid, iid = configured_intersection
        set_v3_run_state(pid, iid, "interrupted")
        # No checkpoint seeded.
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/resume")
        assert r.status_code == 400
        assert "No checkpoint" in r.json()["detail"]

    def test_resume_refuses_when_checkpoint_doesnt_match_plan(
        self, configured_intersection, monkeypatch,
    ):
        from backend.database import set_v3_run_state
        pid, iid = configured_intersection
        set_v3_run_state(pid, iid, "interrupted")
        # Seed a checkpoint pointing at a video that isn't in the plan.
        _seed_checkpoint(
            pid, video_id=99999, camera_id=99999,
            trim_id=99999, frame_number=42,
        )
        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/resume")
        assert r.status_code == 422
        detail = r.json()["detail"]
        assert "doesn't match" in detail["message"]
        assert detail["checkpoint"]["video_id"] == 99999

    def test_resume_spawns_pipeline_at_matched_segment(
        self, configured_intersection, monkeypatch,
    ):
        from backend.database import set_v3_run_state
        import backend.routers.intersections as router_mod
        pid, iid = configured_intersection

        # Capture _run_v3_pipeline kwargs so the test doesn't actually run
        # the heavy pipeline. The thread.start() in the endpoint will call
        # this stub instead of the real one.
        captured: list[dict] = []

        def stub(*args, **kwargs):
            captured.append({"args": args, "kwargs": kwargs})

        monkeypatch.setattr(router_mod, "_run_v3_pipeline", stub)

        # Get the planned segments so we can target one specifically.
        plan = client.post(
            f"/api/projects/{pid}/intersections/{iid}/processing/preflight"
        ).json()
        assert plan["ok"] and plan["segment_count"] >= 1
        target_seg = plan["segments"][0]

        # Seed checkpoint inside that segment's frame range.
        mid = target_seg["start_frame"] + max(
            1, (target_seg["end_frame"] - target_seg["start_frame"]) // 2,
        )
        _seed_checkpoint(
            pid,
            video_id=target_seg["video_id"],
            camera_id=target_seg["camera_id"],
            trim_id=target_seg["trim_id"],
            frame_number=mid,
        )
        set_v3_run_state(pid, iid, "interrupted")

        r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/resume")
        assert r.status_code == 200, r.json()
        body = r.json()
        assert body["resumed_from_segment"] == 0
        assert body["resumed_from_frame"] == mid

        # The thread spawned by /resume calls our stub. Allow a brief moment
        # for the thread to start; the stub is synchronous and fast.
        import time
        for _ in range(50):
            if captured:
                break
            time.sleep(0.02)
        assert captured, "thread never fired the _run_v3_pipeline stub"
        kwargs = captured[0]["kwargs"]
        assert kwargs["start_segment_index"] == 0
        assert kwargs["resume_first_segment"] is True


class TestReprocess:
    def test_reprocess_clears_events_checkpoint_and_state(
        self, configured_intersection,
    ):
        from backend.database import (
            get_connection, get_db_path, get_v3_run_state, set_v3_run_state,
        )
        from backend.services.checkpoint import CheckpointManager
        pid, iid = configured_intersection

        # Seed a vehicle_event tied to a trim of this intersection.
        trims = client.get(f"/api/projects/{pid}/intersections/{iid}/trims").json()
        trim_id = trims[0]["trim_id"]

        plan = client.post(
            f"/api/projects/{pid}/intersections/{iid}/processing/preflight"
        ).json()
        seg = plan["segments"][0]

        # The fixture skips calibration, so no legs exist yet. Create one
        # tied to the segment's camera so the FK on vehicle_events.origin_leg_id
        # is satisfiable. Reprocess wipes by trim_id and camera_id, not by
        # leg, so the seeded event will still be deleted.
        conn = get_connection(pid)
        try:
            cur = conn.execute(
                """INSERT INTO legs
                   (camera_id, label, cardinal_direction, sort_order,
                    origin_zone, reference_heading)
                   VALUES (?, 'N', 'NB', 0, '[[0,0],[1,1]]', 0.0)""",
                (seg["camera_id"],),
            )
            leg_id = int(cur.lastrowid)
            conn.execute(
                """INSERT INTO vehicle_events
                   (video_id, camera_id, trim_id, vehicle_track_id,
                    origin_leg_id, movement, trajectory_data,
                    trajectory_confidence, vehicle_class, detection_confidence,
                    timestamp_video, frame_number)
                   VALUES (?, ?, ?, 1, ?, 'through', '[]', 0.9, 'car', 0.9, 0.0, 0)""",
                (seg["video_id"], seg["camera_id"], trim_id, leg_id),
            )
            conn.commit()
            before = conn.execute(
                "SELECT COUNT(*) FROM vehicle_events WHERE trim_id = ?",
                (trim_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        assert before == 1

        # Seed checkpoint + run-state.
        _seed_checkpoint(
            pid,
            video_id=seg["video_id"],
            camera_id=seg["camera_id"],
            trim_id=trim_id,
            frame_number=10,
        )
        set_v3_run_state(pid, iid, "interrupted")

        r = client.post(
            f"/api/projects/{pid}/intersections/{iid}/processing/reprocess"
        )
        assert r.status_code == 200

        conn = get_connection(pid)
        try:
            after = conn.execute(
                "SELECT COUNT(*) FROM vehicle_events WHERE trim_id = ?",
                (trim_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        assert after == 0
        assert not CheckpointManager(str(get_db_path(pid))).has_checkpoint()
        assert get_v3_run_state(pid, iid) is None


class TestConcurrencyCap:
    """MAX_CONCURRENT_PIPELINES enforced across intersection-days: at capacity a
    start is held 'queued' (no thread), and promoted when a slot frees."""

    def _fill(self, rm, n):
        keys = []
        with rm._v3_jobs_lock:
            for i in range(n):
                k = (f"_capfill_{i}", 999)
                rm._v3_jobs[k] = {"status": "running", "_started": True}
                keys.append(k)
        return keys

    def _drop(self, rm, *keys):
        with rm._v3_jobs_lock:
            for k in keys:
                rm._v3_jobs.pop(k, None)

    def test_start_queues_when_at_capacity(self, configured_intersection):
        import backend.routers.intersections as rm
        from backend.config import MAX_CONCURRENT_PIPELINES
        from backend.database import clear_v3_run_state
        pid, iid = configured_intersection
        fill = self._fill(rm, MAX_CONCURRENT_PIPELINES)
        try:
            r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/start")
            assert r.status_code == 200, r.text
            assert r.json().get("queued_for_slot") is True
            with rm._v3_jobs_lock:
                job = rm._v3_jobs[(pid, iid)]
                assert job["status"] == "queued"
                assert job["_started"] is False  # no thread spawned
        finally:
            self._drop(rm, *fill, (pid, iid))
            clear_v3_run_state(pid, iid)

    def test_promote_starts_queued_when_slot_frees(self, configured_intersection, monkeypatch):
        import time
        import backend.routers.intersections as rm
        captured = []
        def stub(p, i, segs, **k):
            with rm._v3_jobs_lock:
                if (p, i) in rm._v3_jobs:
                    rm._v3_jobs[(p, i)]["status"] = "running"
            captured.append((p, i))
        monkeypatch.setattr(rm, "_run_v3_pipeline", stub)
        pid, iid = configured_intersection
        # Isolate the shared in-memory job map so the active count is exactly the
        # one running slot below (other tests may leave residue in _v3_jobs).
        with rm._v3_jobs_lock:
            saved = dict(rm._v3_jobs)
            rm._v3_jobs.clear()
            rm._v3_jobs[("_one", 999)] = {"status": "running", "_started": True}  # 1/2 slots
            rm._v3_jobs[(pid, iid)] = {"status": "queued", "_started": False, "_segments": ["seg"]}
        try:
            rm._v3_promote_queued()
            time.sleep(0.2)
            assert (pid, iid) in captured
            with rm._v3_jobs_lock:
                assert rm._v3_jobs[(pid, iid)]["_started"] is True
        finally:
            with rm._v3_jobs_lock:
                rm._v3_jobs.clear()
                rm._v3_jobs.update(saved)

    def test_promote_is_noop_when_full(self, configured_intersection, monkeypatch):
        import backend.routers.intersections as rm
        from backend.config import MAX_CONCURRENT_PIPELINES
        captured = []
        monkeypatch.setattr(rm, "_run_v3_pipeline", lambda *a, **k: captured.append(a))
        pid, iid = configured_intersection
        fill = self._fill(rm, MAX_CONCURRENT_PIPELINES)
        with rm._v3_jobs_lock:
            rm._v3_jobs[(pid, iid)] = {"status": "queued", "_started": False, "_segments": ["seg"]}
        try:
            rm._v3_promote_queued()
            assert captured == []
            with rm._v3_jobs_lock:
                assert rm._v3_jobs[(pid, iid)]["_started"] is False
        finally:
            self._drop(rm, *fill, (pid, iid))

    def test_cancel_drops_a_queued_job(self, configured_intersection):
        import backend.routers.intersections as rm
        from backend.database import set_v3_run_state, clear_v3_run_state
        pid, iid = configured_intersection
        with rm._v3_jobs_lock:
            rm._v3_jobs[(pid, iid)] = {"status": "queued", "_started": False, "_segments": ["seg"]}
        set_v3_run_state(pid, iid, "queued")
        try:
            r = client.post(f"/api/projects/{pid}/intersections/{iid}/processing/cancel")
            assert r.status_code == 200
            assert r.json()["status"] == "cancelled"
            with rm._v3_jobs_lock:
                assert rm._v3_jobs[(pid, iid)]["status"] == "cancelled"
        finally:
            self._drop(rm, (pid, iid))
            clear_v3_run_state(pid, iid)
