"""Phase 3 auto-calibration service.

Wraps the Phase 0 clustering logic (scripts/auto_calibrate.py) and adds:
  * background-job orchestration with progress reporting
  * DB persistence to calibration_suggestions
  * single-job concurrency (CPU+memory budget)
  * cancel support

The Phase 0 script is the canonical implementation of the clustering
algorithm; this module imports its `run()` function and the helpers it
needs. Doing it this way keeps one source of truth — improvements to
the clustering land in one place, the CLI script and the production
service both pick them up.

Public API:
  AutoCalibratorJob.enqueue(project_id, camera_id, video_id, sample_seconds)
      -> job_id (str)
  AutoCalibratorJob.get_status(camera_id) -> dict
  AutoCalibratorJob.cancel(camera_id) -> bool

The worker writes the suggestion JSON into calibration_suggestions when
done. The router then exposes GET/apply/reject endpoints on top of that.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
import traceback
import uuid
from pathlib import Path

# Defer adding the project root to sys.path until import-time. The
# script lives at <repo>/scripts/auto_calibrate.py; backend code
# imports it lazily inside _run_job so module-level imports of this
# file don't require torch/ultralytics to be importable at import-time
# (matters for tests that don't need full YOLO infrastructure).

from backend.database import (
    get_video, list_videos_for_camera, save_calibration_suggestion,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job state — module-level so the worker survives across HTTP requests.
# Keyed by camera_id. Single concurrency: at most one auto-cal job runs at
# a time across the whole process (CPU/memory budget; auto-cal competes
# with the live processing pipeline for the same resources).
# ---------------------------------------------------------------------------

_JOBS: dict[int, dict] = {}
_JOBS_LOCK = threading.Lock()
_SINGLETON_LOCK = threading.Lock()   # held while ANY job is actually running


def _update_job(camera_id: int, **fields) -> None:
    with _JOBS_LOCK:
        if camera_id in _JOBS:
            _JOBS[camera_id].update(fields)
            _JOBS[camera_id]["updated_at"] = time.time()


def get_status(camera_id: int) -> dict | None:
    with _JOBS_LOCK:
        job = _JOBS.get(camera_id)
        if not job:
            return None
        out = dict(job)
        # JPEG bytes are served by the preview endpoint, never in JSON.
        out.pop("preview_jpeg", None)
        return out


def get_preview_jpeg(camera_id: int) -> bytes | None:
    """The latest live-perception frame (F2). Ephemeral — process
    lifetime only, single slot, overwritten ~1/s while a job runs."""
    with _JOBS_LOCK:
        job = _JOBS.get(camera_id)
        return job.get("preview_jpeg") if job else None


def _render_preview(camera_id: int, info: dict) -> None:
    """F2 live-perception callback (plan_f2_livecal_2026-07-28): honest
    progress + a small annotated JPEG into the job slot. Runs ~1/s on
    the worker thread; the collector's hook guard swallows failures, so
    a preview problem can never kill calibration."""
    import cv2
    frame = info.get("frame")
    if frame is None:
        return
    img = frame.copy()
    for t in info.get("tracked", []):
        bb = t.get("bbox")
        if bb:
            x1, y1, x2, y2 = (int(v) for v in bb)
            cv2.rectangle(img, (x1, y1), (x2, y2), (80, 220, 80), 2)
    for pts in (info.get("trails") or {}).values():
        for a, b in zip(pts, pts[1:]):
            cv2.line(img, (int(a[0]), int(a[1])),
                     (int(b[0]), int(b[1])), (60, 160, 255), 2)
    h, w = img.shape[:2]
    if w > 640:
        img = cv2.resize(img, (640, int(h * 640 / w)))
    ok, buf = cv2.imencode(".jpg", img,
                           [int(cv2.IMWRITE_JPEG_QUALITY), 70])
    fields = {
        "progress_pct": round(5.0 + 85.0 * float(info.get("progress", 0.0)), 1),
        "active_tracks": info.get("active", 0),
        "finished_tracks": info.get("finished", 0),
    }
    if ok:
        fields["preview_jpeg"] = buf.tobytes()
    with _JOBS_LOCK:
        job = _JOBS.get(camera_id)
        if job is not None:
            job.update(fields)
            job["preview_seq"] = int(job.get("preview_seq", 0)) + 1
            job["updated_at"] = time.time()


def cancel(camera_id: int) -> bool:
    with _JOBS_LOCK:
        job = _JOBS.get(camera_id)
        if not job:
            return False
        job["cancel_requested"] = True
        return True


def enqueue(
    project_id: str,
    camera_id: int,
    video_id: int | None = None,
    sample_start_sec: float = 0.0,
    sample_end_sec: float | None = None,
) -> str:
    """Start an auto-cal job in a background thread. Returns the job_id.
    Only one job runs at a time globally; subsequent enqueues replace the
    pending job for that camera (we don't queue multiple per-camera).

    sample_end_sec defaults to sample_start_sec + 15 min."""
    job_id = uuid.uuid4().hex
    sample_end_sec = sample_end_sec or (sample_start_sec + 15 * 60)

    with _JOBS_LOCK:
        # If a job is already running on this camera, mark it cancelled and
        # start a new one — the engineer is asking for a fresh attempt.
        if camera_id in _JOBS and _JOBS[camera_id].get("status") == "running":
            _JOBS[camera_id]["cancel_requested"] = True
        _JOBS[camera_id] = {
            "job_id": job_id,
            "camera_id": camera_id,
            "project_id": project_id,
            "video_id": video_id,
            "status": "queued",
            "progress_pct": 0.0,
            "phase": "queued",
            "started_at": None,
            "updated_at": time.time(),
            "sample_start_sec": sample_start_sec,
            "sample_end_sec": sample_end_sec,
            "cancel_requested": False,
            "error": None,
        }

    t = threading.Thread(
        target=_run_job,
        args=(project_id, camera_id, video_id, sample_start_sec, sample_end_sec),
        daemon=True,
        name=f"auto-cal-{camera_id}",
    )
    t.start()
    return job_id


def _resolve_video_path(project_id: str, camera_id: int, video_id: int | None) -> tuple[str, int]:
    """Look up the video file to run auto-cal on. Returns (path, video_id).
    If video_id is None, pick the first video attached to the camera."""
    if video_id is not None:
        v = get_video(project_id, video_id)
        if v is None:
            raise ValueError(f"video {video_id} not found in project {project_id}")
        return v["path"], video_id
    vids = list_videos_for_camera(project_id, camera_id)
    if not vids:
        raise ValueError(f"camera {camera_id} has no videos attached")
    return vids[0]["path"], vids[0]["video_id"]


def _run_job(
    project_id: str, camera_id: int, video_id: int | None,
    sample_start_sec: float, sample_end_sec: float,
) -> None:
    """Worker entry. Acquires the singleton lock so we never run two
    auto-cals (or one auto-cal alongside a live pipeline thread — they'd
    fight for the GIL + YOLO model + memory). Writes the result to
    calibration_suggestions on success; populates status['error'] on fail."""
    # Wait (briefly) for the singleton — engineer may have queued a job
    # while a previous one finishes its tail.
    acquired = _SINGLETON_LOCK.acquire(blocking=True, timeout=5.0)
    if not acquired:
        _update_job(camera_id, status="error",
                    error="Another auto-cal job is already running.")
        return
    try:
        _update_job(camera_id, status="running", phase="resolve_video",
                    started_at=time.time())

        path, vid = _resolve_video_path(project_id, camera_id, video_id)
        _update_job(camera_id, video_id=vid)

        # Lazy import: pulls in YOLO via VehicleDetector.
        repo_root = Path(__file__).resolve().parent.parent.parent
        sys.path.insert(0, str(repo_root))
        from scripts.auto_calibrate import run as run_auto_cal, AutoCalCancelled

        # The trajectory-collection pass is the long phase. We pass a
        # should_cancel callback so a Cancel request is honored mid-pass
        # (it polls cancel_requested every ~30 frames) instead of only
        # after the whole window finishes.
        _update_job(camera_id, phase="collect_trajectories", progress_pct=5.0)
        try:
            result = run_auto_cal(
                path,
                sample_start_sec=sample_start_sec,
                sample_end_sec=sample_end_sec,
                should_cancel=lambda: bool(
                    _JOBS.get(camera_id, {}).get("cancel_requested")),
                on_progress=lambda info: _render_preview(camera_id, info),
            )
        except AutoCalCancelled:
            _update_job(camera_id, status="cancelled", phase="done",
                        progress_pct=100.0)
            return
        if _JOBS[camera_id].get("cancel_requested"):
            _update_job(camera_id, status="cancelled", phase="done",
                        progress_pct=100.0)
            return

        _update_job(camera_id, phase="persist", progress_pct=95.0)
        # Drop the full video_path off the JSON we persist — keep the
        # JSON small + portable. Add summary metadata to job_metadata.
        result.pop("video_path", None)
        meta = {
            "video_id": vid,
            "video_path": path,
            "sample_window_sec": [sample_start_sec, sample_end_sec],
            "stats": result.get("stats", {}),
        }
        save_calibration_suggestion(project_id, camera_id, result,
                                    job_metadata=meta)
        _update_job(camera_id, status="complete", phase="done",
                    progress_pct=100.0,
                    n_leg_zones=len(result.get("leg_zones", [])),
                    n_paths=len(result.get("paths", [])))
        logger.info("auto-cal complete for camera=%s: %d zones, %d paths",
                    camera_id, len(result.get("leg_zones", [])),
                    len(result.get("paths", [])))
    except Exception as e:
        logger.exception("auto-cal job for camera=%s failed", camera_id)
        _update_job(camera_id, status="error",
                    error=f"{type(e).__name__}: {e}",
                    traceback=traceback.format_exc()[-2000:])
    finally:
        _SINGLETON_LOCK.release()
