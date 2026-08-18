"""Phase 3 auto-calibration service.

Wraps the Phase 0 clustering logic (scripts/auto_calibrate.py) and adds:
  * background-job orchestration with progress + ETA reporting
  * DB persistence to calibration_suggestions
  * bounded parallel concurrency with a FIFO queue (AUTO_CAL_MAX_CONCURRENT)
  * operator sample-window resolution (wall-clock start + duration,
    15 min .. 15 h, default +7 h into footage for 11 h)
  * cancel support (running AND queued jobs)

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

from datetime import datetime

from backend.config import (
    AUTO_CAL_DEFAULT_DURATION_SEC,
    AUTO_CAL_DEFAULT_OFFSET_SEC,
    AUTO_CAL_MAX_CONCURRENT,
    AUTO_CAL_MAX_SAMPLE_SEC,
    AUTO_CAL_MIN_SAMPLE_SEC,
)
from backend.database import (
    get_video, list_videos_for_camera, save_calibration_suggestion,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Job state — module-level so workers survive across HTTP requests (and the
# operator can leave the page entirely). Keyed by camera_id: one live job
# per camera. Concurrency: a bounded pool (AUTO_CAL_MAX_CONCURRENT) with a
# FIFO wait queue — jobs beyond the pool report status "queued" with an
# accurate position and start automatically as slots free.
# ---------------------------------------------------------------------------

_JOBS: dict[int, dict] = {}
_JOBS_LOCK = threading.Lock()
_RUN_COND = threading.Condition()
_WAIT_FIFO: list[str] = []           # job_ids in arrival order
_RUNNING: set[str] = set()           # job_ids currently holding a slot


def _acquire_run_slot(camera_id: int, job_id: str) -> bool:
    """Block until this job reaches the FIFO head AND a pool slot is free.
    Publishes queue_position while waiting. Returns False if the job was
    cancelled or replaced (same camera re-enqueued) while queued."""
    with _RUN_COND:
        _WAIT_FIFO.append(job_id)
        while True:
            with _JOBS_LOCK:
                job = _JOBS.get(camera_id)
                stale = (job is None or job.get("job_id") != job_id
                         or job.get("cancel_requested"))
            if stale:
                _WAIT_FIFO.remove(job_id)
                _RUN_COND.notify_all()
                return False
            pos = _WAIT_FIFO.index(job_id)
            if pos == 0 and len(_RUNNING) < AUTO_CAL_MAX_CONCURRENT:
                _WAIT_FIFO.pop(0)
                _RUNNING.add(job_id)
                _RUN_COND.notify_all()   # wake #2 so it recomputes position
                return True
            _update_job(camera_id, status="queued", phase="queued",
                        queue_position=pos + 1,
                        running_now=len(_RUNNING))
            _RUN_COND.wait(timeout=1.0)


def _release_run_slot(job_id: str) -> None:
    with _RUN_COND:
        _RUNNING.discard(job_id)
        _RUN_COND.notify_all()


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


def get_all_statuses(project_id: str | None = None) -> list[dict]:
    """Every camera's latest job (this process lifetime) — the project-
    level jobs strip polls this so progress stays visible after the
    operator leaves the calibration editor."""
    with _JOBS_LOCK:
        out = []
        for job in _JOBS.values():
            if project_id and job.get("project_id") != project_id:
                continue
            j = dict(job)
            j.pop("preview_jpeg", None)
            out.append(j)
    out.sort(key=lambda j: j.get("updated_at") or 0, reverse=True)
    return out


def resolve_sample_window(
    project_id: str,
    camera_id: int,
    video_id: int | None = None,
    start_hms: str | None = None,
    duration_min: float | None = None,
    sample_start_sec: float | None = None,
    sample_end_sec: float | None = None,
) -> dict:
    """Turn the operator's request into a concrete video-relative sample
    window, validated against the footage.

    Three forms, in precedence order:
      * explicit sample_start_sec / sample_end_sec (API power users);
      * wall-clock start_hms ("HH:MM[:SS]") + duration_min — resolved
        against the video's recording_start_datetime (set at upload);
      * nothing — the default: +7 h into the footage for 11 h
        (07:00-18:00 on a midnight-start 24 h file).

    Duration is hard-bounded [15 min, 15 h]; the end is clamped to the
    footage. Raises ValueError with an operator-readable message."""
    path, vid = _resolve_video_path(project_id, camera_id, video_id)
    v = get_video(project_id, vid) or {}
    vdur = float(v.get("duration_seconds") or 0.0)
    if vdur < AUTO_CAL_MIN_SAMPLE_SEC:
        raise ValueError(
            f"video is only {vdur/60:.0f} min long — shorter than the "
            f"15-minute minimum sample")
    vstart_sod = None
    raw_start = v.get("recording_start_datetime")
    if raw_start:
        t = datetime.fromisoformat(str(raw_start))
        vstart_sod = t.hour * 3600 + t.minute * 60 + t.second

    def clock(off: float) -> str | None:
        if vstart_sod is None:
            return None
        s = (vstart_sod + off) % 86400
        return f"{int(s // 3600):02d}:{int(s % 3600 // 60):02d}"

    if duration_min is not None:
        d = float(duration_min) * 60.0
        if d < AUTO_CAL_MIN_SAMPLE_SEC:
            raise ValueError("sample duration must be at least 15 minutes")
        if d > AUTO_CAL_MAX_SAMPLE_SEC:
            raise ValueError("sample duration must be at most 15 hours")

    if sample_start_sec is not None or sample_end_sec is not None:
        s = float(sample_start_sec or 0.0)
        e = (float(sample_end_sec) if sample_end_sec is not None
             else s + (float(duration_min) * 60.0 if duration_min is not None
                       else AUTO_CAL_DEFAULT_DURATION_SEC))
        source = "explicit"
    elif start_hms is not None:
        if vstart_sod is None:
            raise ValueError(
                "video has no recording start time — set it on the Videos "
                "tab (upload normally fills it from the filename)")
        try:
            parts = [int(p) for p in str(start_hms).split(":")]
        except ValueError:
            raise ValueError(f"bad start time {start_hms!r} — use HH:MM")
        while len(parts) < 3:
            parts.append(0)
        req = parts[0] * 3600 + parts[1] * 60 + parts[2]
        s = float(req - vstart_sod)
        if s < 0:
            # Only a recording that actually crosses midnight can wrap.
            crosses = vdur > (86400 - vstart_sod)
            if crosses and s + 86400 < vdur:
                s += 86400.0
            else:
                raise ValueError(
                    f"{start_hms} is before the footage begins "
                    f"(recording starts at {clock(0)})")
        e = s + (float(duration_min) * 60.0 if duration_min is not None
                 else AUTO_CAL_DEFAULT_DURATION_SEC)
        source = "clock"
    else:
        s = (float(AUTO_CAL_DEFAULT_OFFSET_SEC)
             if vdur >= AUTO_CAL_DEFAULT_OFFSET_SEC + AUTO_CAL_MIN_SAMPLE_SEC
             else 0.0)
        e = s + AUTO_CAL_DEFAULT_DURATION_SEC
        source = "default"

    if s < 0:
        raise ValueError("sample start is before the video begins")
    if s >= vdur - 1:
        raise ValueError(
            f"sample start is past the end of the footage "
            f"({vdur/3600:.1f} h long)")
    e = min(e, vdur)
    if e - s > AUTO_CAL_MAX_SAMPLE_SEC:
        e = s + AUTO_CAL_MAX_SAMPLE_SEC
    if e - s < AUTO_CAL_MIN_SAMPLE_SEC:
        s = max(0.0, min(s, vdur - AUTO_CAL_MIN_SAMPLE_SEC))
        e = min(vdur, s + AUTO_CAL_MIN_SAMPLE_SEC)
    return {
        "video_id": vid,
        "sample_start_sec": round(s, 1),
        "sample_end_sec": round(e, 1),
        "start_clock": clock(s),
        "end_clock": clock(e),
        "source": source,
        "video_duration_sec": vdur,
        "video_start_clock": clock(0),
    }


def get_preview_jpeg(camera_id: int) -> bytes | None:
    """The latest live-perception frame (F2). Ephemeral — process
    lifetime only, single slot, overwritten ~1/s while a job runs."""
    with _JOBS_LOCK:
        job = _JOBS.get(camera_id)
        return job.get("preview_jpeg") if job else None


def _shape_sample_tracks(acc: dict, every: int = 3,
                         min_points: int = 8, max_points: int = 25000) -> list:
    """F3 stage B: shape the accumulated {tid: {frame: (x, y)}} into the
    persisted `sample_tracks` payload — every Nth frame per track, short
    tracks dropped, globally capped by total points (longest tracks kept
    first) so the suggestion JSON stays ~sub-MB."""
    shaped = []
    for tid, by_frame in acc.items():
        frames = sorted(by_frame)[::every]
        if len(frames) < min_points:
            continue
        shaped.append({"tid": int(tid),
                       "points": [[int(f), round(by_frame[f][0], 1),
                                   round(by_frame[f][1], 1)] for f in frames]})
    shaped.sort(key=lambda t: -len(t["points"]))
    out, total = [], 0
    for t in shaped:
        if total + len(t["points"]) > max_points:
            break
        out.append(t)
        total += len(t["points"])
    return out


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
    # Honest ETA: frames processed over wall time since the collect phase
    # began, smoothed (EMA) so the readout doesn't jitter; the remaining
    # frames divided by that rate is the estimate. The short cluster +
    # persist tail is covered by a small fixed pad.
    done = max(0, int(info.get("frame_no", 0)) - int(info.get("start_frame", 0)))
    total = max(1, int(info.get("end_frame", 1)) - int(info.get("start_frame", 0)))
    fields["frames_done"] = done
    fields["frames_total"] = total
    with _JOBS_LOCK:
        job = _JOBS.get(camera_id)
        if job is not None:
            t0 = job.get("collect_t0")
            if t0 and done > 0:
                inst = done / max(0.5, time.time() - t0)
                prev = job.get("proc_fps") or inst
                smooth = 0.7 * float(prev) + 0.3 * inst
                fields["proc_fps"] = round(smooth, 1)
                fields["eta_sec"] = int((total - done) / max(0.5, smooth)) + 10
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
    window: dict | None = None,
) -> str:
    """Start an auto-cal job in a background thread. Returns the job_id.
    Jobs run in a bounded pool (AUTO_CAL_MAX_CONCURRENT) with a FIFO
    queue — enqueue different cameras freely and they run in parallel;
    re-enqueueing the SAME camera replaces its pending/running job.

    sample_end_sec defaults to sample_start_sec + the 11 h default span.
    `window` (from resolve_sample_window) rides along for display."""
    job_id = uuid.uuid4().hex
    sample_end_sec = sample_end_sec or (
        sample_start_sec + AUTO_CAL_DEFAULT_DURATION_SEC)

    with _JOBS_LOCK:
        # If a job is already live on this camera, mark it cancelled and
        # start a new one — the engineer is asking for a fresh attempt.
        if camera_id in _JOBS and _JOBS[camera_id].get("status") in (
                "queued", "running"):
            _JOBS[camera_id]["cancel_requested"] = True
        _JOBS[camera_id] = {
            "job_id": job_id,
            "camera_id": camera_id,
            "project_id": project_id,
            "video_id": video_id,
            "status": "queued",
            "progress_pct": 0.0,
            "phase": "queued",
            "queue_position": None,
            "eta_sec": None,
            "proc_fps": None,
            "frames_done": 0,
            "frames_total": None,
            "started_at": None,
            "updated_at": time.time(),
            "sample_start_sec": sample_start_sec,
            "sample_end_sec": sample_end_sec,
            "start_clock": (window or {}).get("start_clock"),
            "end_clock": (window or {}).get("end_clock"),
            "cancel_requested": False,
            "error": None,
        }

    t = threading.Thread(
        target=_run_job,
        args=(project_id, camera_id, video_id, sample_start_sec,
              sample_end_sec, job_id),
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
    sample_start_sec: float, sample_end_sec: float, job_id: str,
) -> None:
    """Worker entry. Waits FIFO for a pool slot (status 'queued' with an
    accurate position while waiting), then runs. Each job builds its own
    detector instance, so pool members are independent. Writes the result
    to calibration_suggestions on success; populates status['error'] on
    fail."""
    if not _acquire_run_slot(camera_id, job_id):
        # Cancelled or replaced while waiting in the queue.
        with _JOBS_LOCK:
            job = _JOBS.get(camera_id)
            if job is not None and job.get("job_id") == job_id:
                job.update(status="cancelled", phase="cancelled",
                           updated_at=time.time())
        return
    try:
        _update_job(camera_id, status="running", phase="resolve_video",
                    started_at=time.time(), queue_position=0)

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
        _update_job(camera_id, phase="collect_trajectories", progress_pct=5.0,
                    collect_t0=time.time())
        # F3 stage B: accumulate frame-stamped sample tracks from the same
        # hook the preview rides (trails × trails_f are parallel slices).
        _track_acc: dict[int, dict[int, tuple]] = {}

        def _cb(info):
            for tid, pts in (info.get("trails") or {}).items():
                fs = (info.get("trails_f") or {}).get(tid) or []
                slot = _track_acc.setdefault(tid, {})
                for f, p in zip(fs, pts):
                    slot[int(f)] = p
            _render_preview(camera_id, info)

        traj_dir = Path(f"data/projects/{project_id}/_replay_scratch/autocal")
        traj_dir.mkdir(parents=True, exist_ok=True)
        traj_npz = traj_dir / (
            f"traj_cam{camera_id}_{int(sample_start_sec)}_"
            f"{int(sample_end_sec)}.npz")
        try:
            result = run_auto_cal(
                path,
                sample_start_sec=sample_start_sec,
                sample_end_sec=sample_end_sec,
                should_cancel=lambda: bool(
                    _JOBS.get(camera_id, {}).get("cancel_requested")),
                on_progress=_cb,
                save_trajectories_to=str(traj_npz),
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
        # F3 stage B: the studio's synced replay data (shape-additive —
        # readers of the suggestion payload ignore unknown keys).
        result["sample_tracks"] = _shape_sample_tracks(_track_acc)
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
        _release_run_slot(job_id)
