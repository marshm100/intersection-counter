"""Processing router — start, pause, resume, cancel, and status for the AI pipeline."""

import asyncio
import json
import logging
import queue
import threading
import time
from typing import Callable

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from backend.config import DEFAULT_FRAME_SKIP, PROJECTS_DIR
from backend.database import get_all_project_info, get_db_path, get_connection, set_project_info
from backend.services.checkpoint import CheckpointManager
from backend.services.frame_annotator import render_frame_preview
from backend.services.pipeline import ProcessingPipeline

logger = logging.getLogger(__name__)
router = APIRouter()

# Module-level state
_pipelines: dict[str, ProcessingPipeline] = {}
_progress: dict[str, dict] = {}
_preview_frames: dict[str, bytes] = {}
_threads: dict[str, threading.Thread] = {}
_preview_queues: dict[str, queue.Queue] = {}
_state_lock = threading.Lock()


def _make_placeholder_jpeg() -> bytes:
    """Return a black 640×360 JPEG with a 'Starting...' label."""
    img = np.zeros((360, 640, 3), dtype=np.uint8)
    cv2.putText(img, "Starting...", (230, 190),
                cv2.FONT_HERSHEY_SIMPLEX, 1.2, (100, 100, 100), 2, cv2.LINE_AA)
    _, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 50])
    return buf.tobytes()


def _preview_worker(project_id: str, q: queue.Queue) -> None:
    """Encode preview frames in a dedicated thread so the pipeline is never blocked."""
    while True:
        item = q.get()
        if item is None:   # sentinel → exit
            break
        # Drain queue — keep only the latest frame
        while True:
            try:
                newer = q.get_nowait()
                if newer is None:
                    item = None
                    break
                item = newer
            except queue.Empty:
                break
        if item is None:
            break
        raw_frame, tracks, origin_zones, legs, active_traj, finalized_traj = item
        try:
            jpeg = render_frame_preview(
                raw_frame, tracks, origin_zones, legs,
                active_trajectories=active_traj,
                finalized_trajectories=finalized_traj,
            )
        except Exception as e:
            logger.warning("Preview annotation error: %s", e)
            # Fallback: encode raw frame without annotations
            try:
                _, buf = cv2.imencode(".jpg", raw_frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                jpeg = buf.tobytes()
            except Exception:
                continue
        with _state_lock:
            _preview_frames[project_id] = jpeg


def _time_str_to_seconds(t: str) -> int | None:
    """Convert 'HH:MM' string to integer seconds. Returns None on invalid input."""
    try:
        parts = t.strip().split(":")
        if len(parts) != 2:
            return None
        h, m = int(parts[0]), int(parts[1])
        if h < 0 or h > 23 or m < 0 or m > 59:
            return None
        return h * 3600 + m * 60
    except (ValueError, AttributeError):
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_prerequisites(project_id: str) -> dict:
    """Load and validate everything needed to start a pipeline."""
    info = get_all_project_info(project_id)
    video_path = info.get("video_path")

    if not video_path:
        raise HTTPException(status_code=400, detail="No video path configured for this project.")

    import os
    if not os.path.isfile(video_path):
        raise HTTPException(status_code=400, detail=f"Video file not found on disk: {video_path}")

    conn = get_connection(project_id)
    try:
        conn.row_factory = __import__("sqlite3").Row
        legs_raw = [dict(row) for row in conn.execute(
            "SELECT * FROM legs ORDER BY sort_order"
        ).fetchall()]
        legs = []
        for leg in legs_raw:
            oz = leg.get("origin_zone")
            if isinstance(oz, str):
                leg["origin_zone"] = json.loads(oz)
            legs.append(leg)
    finally:
        conn.close()

    if not legs:
        raise HTTPException(status_code=400, detail="No legs configured for this project.")

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    return {
        "video_path": video_path,
        "video_start_time": info.get("video_start_time"),
        "legs": legs,
        "fps": fps,
        "total_frames": total_frames,
    }


def _make_progress_callback(project_id: str, legs: list[dict]) -> Callable:
    """Return a closure that stores progress data and queues preview encoding."""
    def callback(data: dict):
        raw_frame = data.pop("raw_frame", None)
        tracks = data.pop("tracks", None)
        origin_zones = data.pop("origin_zones", None)
        active_trajectories = data.pop("active_trajectories", None)
        finalized_trajectories = data.pop("finalized_trajectories", None)
        with _state_lock:
            _progress[project_id] = data
        if raw_frame is not None:
            q = _preview_queues.get(project_id)
            if q is not None:
                try:
                    q.put_nowait((
                        raw_frame, tracks or [], origin_zones or [], legs,
                        active_trajectories or {}, finalized_trajectories or [],
                    ))
                except queue.Full:
                    pass   # preview thread is behind — drop frame, that's fine
    return callback


def _run_pipeline(project_id: str, start_frame: int = 0, end_frame: int | None = None,
                   frame_skip: int = DEFAULT_FRAME_SKIP):
    """Thread target: run the pipeline, update status on finish."""
    try:
        with _state_lock:
            pipeline = _pipelines.get(project_id)
        if pipeline is None:
            return

        callback = _make_progress_callback(project_id, pipeline.legs)
        pipeline.process_video(
            frame_skip=frame_skip,
            start_frame=start_frame,
            end_frame=end_frame,
            callback=callback,
        )

        # Determine final status
        if pipeline.pause_requested.is_set():
            set_project_info(project_id, "status", "paused")
        else:
            set_project_info(project_id, "status", "complete")

    except Exception as exc:
        logger.error("Pipeline error for project %s: %s", project_id, exc)
        set_project_info(project_id, "status", "error")
    finally:
        # Stop the preview worker thread
        q = _preview_queues.pop(project_id, None)
        if q is not None:
            q.put(None)   # sentinel
        with _state_lock:
            _pipelines.pop(project_id, None)
            _threads.pop(project_id, None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class StartProcessingRequest(BaseModel):
    count_start_time: str | None = None  # "HH:MM" offset from video start; None = 00:00
    count_end_time:   str | None = None  # "HH:MM" offset from video start; None = end of video
    frame_skip: int | None = None        # 1-5; None = use DEFAULT_FRAME_SKIP


@router.post("/projects/{project_id}/processing/start")
def start_processing(project_id: str, req: StartProcessingRequest = StartProcessingRequest()):
    with _state_lock:
        if project_id in _pipelines:
            thread = _threads.get(project_id)
            if thread is not None and thread.is_alive():
                raise HTTPException(status_code=409, detail="Processing already running.")
            # Stale entry (thread dead or missing) — clean up and allow restart
            _pipelines.pop(project_id, None)
            _threads.pop(project_id, None)
            set_project_info(project_id, "status", "idle")

    prereqs = _load_prerequisites(project_id)
    db_path = str(get_db_path(project_id))
    fps = prereqs["fps"]
    if fps <= 0:
        raise HTTPException(status_code=422, detail="Video has invalid FPS (0 or negative). The file may be corrupt.")
    total_frames = prereqs["total_frames"]

    # Convert HH:MM time strings to frame numbers
    start_frame = 0
    if req.count_start_time:
        secs = _time_str_to_seconds(req.count_start_time)
        if secs is None:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid count_start_time '{req.count_start_time}'. Expected HH:MM format."
            )
        start_frame = int(secs * fps)
        if total_frames > 0:
            start_frame = max(0, min(start_frame, total_frames))

    end_frame = None
    if req.count_end_time:
        secs = _time_str_to_seconds(req.count_end_time)
        if secs is None:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid count_end_time '{req.count_end_time}'. Expected HH:MM format."
            )
        end_frame = int(secs * fps)
        if total_frames > 0:
            end_frame = max(start_frame + 1, min(end_frame, total_frames))

    if end_frame is not None and end_frame <= start_frame:
        raise HTTPException(status_code=422, detail="End time must be after start time.")

    # Resolve frame_skip
    frame_skip = req.frame_skip if req.frame_skip and 1 <= req.frame_skip <= 5 else DEFAULT_FRAME_SKIP

    # Persist window so resume can reuse it
    set_project_info(project_id, "count_start_time", req.count_start_time or "")
    set_project_info(project_id, "count_end_time",   req.count_end_time   or "")
    set_project_info(project_id, "frame_skip", str(frame_skip))
    set_project_info(project_id, "count_start_frame", str(start_frame))
    set_project_info(project_id, "count_end_frame",   str(end_frame) if end_frame is not None else "")

    pipeline = ProcessingPipeline(
        project_id=project_id,
        db_path=db_path,
        video_path=prereqs["video_path"],
        legs=prereqs["legs"],
        fps=fps,
        video_start_time=prereqs["video_start_time"],
    )

    placeholder = _make_placeholder_jpeg()
    preview_q: queue.Queue = queue.Queue(maxsize=2)
    with _state_lock:
        _pipelines[project_id] = pipeline
        _preview_frames[project_id] = placeholder
    _preview_queues[project_id] = preview_q

    set_project_info(project_id, "status", "processing")

    threading.Thread(
        target=_preview_worker, args=(project_id, preview_q), daemon=True
    ).start()

    thread = threading.Thread(
        target=_run_pipeline, args=(project_id, start_frame, end_frame, frame_skip), daemon=True
    )
    with _state_lock:
        _threads[project_id] = thread
    thread.start()

    return {"status": "ok"}


@router.post("/projects/{project_id}/processing/pause")
def pause_processing(project_id: str):
    with _state_lock:
        pipeline = _pipelines.get(project_id)

    if pipeline is None:
        raise HTTPException(status_code=400, detail="No processing is running.")

    pipeline.pause()
    set_project_info(project_id, "status", "paused")
    return {"status": "ok"}


@router.post("/projects/{project_id}/processing/resume")
def resume_processing(project_id: str):
    db_path = str(get_db_path(project_id))
    ckpt_mgr = CheckpointManager(db_path)

    if not ckpt_mgr.has_checkpoint():
        raise HTTPException(status_code=400, detail="No checkpoint to resume from.")

    with _state_lock:
        if project_id in _pipelines:
            thread = _threads.get(project_id)
            if thread is not None and thread.is_alive():
                raise HTTPException(status_code=409, detail="Processing already running.")
            # Stale entry (thread dead or missing) — clean up and allow restart
            _pipelines.pop(project_id, None)
            _threads.pop(project_id, None)

    prereqs = _load_prerequisites(project_id)

    pipeline = ProcessingPipeline(
        project_id=project_id,
        db_path=db_path,
        video_path=prereqs["video_path"],
        legs=prereqs["legs"],
        fps=prereqs["fps"],
        video_start_time=prereqs["video_start_time"],
    )

    start_frame = pipeline.resume_from_checkpoint()

    # Restore the original count window end frame and frame_skip
    info = get_all_project_info(project_id)
    end_frame_str = info.get("count_end_frame", "")
    end_frame = int(end_frame_str) if end_frame_str else None
    frame_skip_str = info.get("frame_skip", "")
    frame_skip = int(frame_skip_str) if frame_skip_str else DEFAULT_FRAME_SKIP

    placeholder = _make_placeholder_jpeg()
    preview_q: queue.Queue = queue.Queue(maxsize=2)
    with _state_lock:
        _pipelines[project_id] = pipeline
        _preview_frames[project_id] = placeholder
    _preview_queues[project_id] = preview_q

    set_project_info(project_id, "status", "processing")

    threading.Thread(
        target=_preview_worker, args=(project_id, preview_q), daemon=True
    ).start()

    thread = threading.Thread(
        target=_run_pipeline, args=(project_id, start_frame, end_frame, frame_skip), daemon=True
    )
    with _state_lock:
        _threads[project_id] = thread
    thread.start()

    return {"status": "ok", "start_frame": start_frame}


def stop_pipeline(project_id: str) -> None:
    """Stop a running pipeline and clean up module-level state for *project_id*.

    Idempotent — safe to call even when no pipeline is running.
    """
    with _state_lock:
        pipeline = _pipelines.get(project_id)
        thread = _threads.get(project_id)

    if pipeline is not None:
        pipeline.pause()
        if thread is not None:
            thread.join(timeout=5)

    q = _preview_queues.pop(project_id, None)
    if q is not None:
        q.put(None)   # sentinel — stop preview worker

    with _state_lock:
        _pipelines.pop(project_id, None)
        _threads.pop(project_id, None)
        _progress.pop(project_id, None)
        _preview_frames.pop(project_id, None)


@router.post("/projects/{project_id}/processing/cancel")
def cancel_processing(project_id: str):
    """Idempotent cancel: pause if running, clear checkpoint, reset to idle."""
    stop_pipeline(project_id)

    db_path = str(get_db_path(project_id))
    CheckpointManager(db_path).clear_checkpoint()

    set_project_info(project_id, "status", "idle")
    return {"status": "ok"}


@router.get("/projects/{project_id}/processing/status")
def processing_status(project_id: str):
    db_path = str(get_db_path(project_id))
    info = get_all_project_info(project_id)
    status = info.get("status", "idle")

    with _state_lock:
        is_running = project_id in _pipelines
        progress = _progress.get(project_id)

    has_checkpoint = CheckpointManager(db_path).has_checkpoint()

    # Auto-heal: DB says "processing" but no pipeline is running → crashed
    if status == "processing" and not is_running:
        status = "error"
        set_project_info(project_id, "status", "error")

    return {
        "status": status,
        "is_running": is_running,
        "has_checkpoint": has_checkpoint,
        "progress": progress,
        "count_start_time": info.get("count_start_time", ""),
        "count_end_time": info.get("count_end_time", ""),
    }


@router.get("/projects/{project_id}/processing/preview-stream")
async def processing_preview_stream(project_id: str):
    """MJPEG stream: yields latest JPEG frame every ~40 ms (≤25 fps).
    Closes automatically ~2 s after processing stops."""
    async def generate():
        last_sent: bytes | None = None
        idle_since: float | None = None

        while True:
            frame: bytes | None = _preview_frames.get(project_id)
            is_running: bool = project_id in _pipelines

            if frame is not None and frame is not last_sent:
                last_sent = frame
                idle_since = None
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                )

            if not is_running:
                if idle_since is None:
                    idle_since = time.time()
                elif time.time() - idle_since > 2.0:
                    break

            await asyncio.sleep(0.04)   # 25 fps cap

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-cache, no-store"},
    )


@router.get("/projects/{project_id}/processing/preview-frame")
def processing_preview_frame(project_id: str):
    with _state_lock:
        jpeg = _preview_frames.get(project_id)
    if jpeg is None:
        raise HTTPException(status_code=404, detail="No preview available yet.")
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, no-cache"},
    )


@router.get("/projects/{project_id}/review-frame")
def review_frame(project_id: str, frame: int = 0, show_trajectories: bool = True):
    """Return a JPEG of a specific video frame with optional trajectory overlays."""
    import sqlite3 as _sqlite3

    info = get_all_project_info(project_id)
    video_path = info.get("video_path")
    if not video_path:
        raise HTTPException(status_code=400, detail="No video path configured.")

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise HTTPException(status_code=500, detail="Cannot open video file.")

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        frame_num = max(0, min(frame, total_frames - 1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_num)
        ret, img = cap.read()
        if not ret or img is None:
            raise HTTPException(status_code=500, detail="Could not read frame.")
    finally:
        cap.release()

    # Load legs and origin zones from DB
    conn = get_connection(project_id)
    try:
        conn.row_factory = _sqlite3.Row
        legs_raw = [dict(row) for row in conn.execute(
            "SELECT * FROM legs ORDER BY sort_order"
        ).fetchall()]
        legs = []
        origin_zones = []
        for leg in legs_raw:
            oz = leg.get("origin_zone")
            if isinstance(oz, str):
                leg["origin_zone"] = json.loads(oz)
            legs.append(leg)
            origin_zones.append(leg.get("origin_zone", []))

        finalized_trajectories = []
        if show_trajectories:
            rows = conn.execute(
                """SELECT trajectory_data, movement, origin_leg_id, start_frame, frame_number
                   FROM vehicle_events
                   WHERE start_frame IS NOT NULL
                     AND start_frame <= ? AND frame_number >= ?""",
                (frame_num, frame_num),
            ).fetchall()
            for row in rows:
                traj = json.loads(row["trajectory_data"])
                total_pts = len(traj)
                duration = row["frame_number"] - row["start_frame"]
                if duration > 0 and total_pts > 1:
                    progress = (frame_num - row["start_frame"]) / duration
                    pts_to_show = max(2, int(total_pts * min(1.0, progress)))
                    visible_traj = traj[:pts_to_show]
                else:
                    visible_traj = traj
                finalized_trajectories.append({
                    "trajectory": visible_traj,
                    "movement": row["movement"],
                    "origin_leg_id": row["origin_leg_id"],
                })
    finally:
        conn.close()

    jpeg = render_frame_preview(
        img, [], origin_zones, legs,
        finalized_trajectories=finalized_trajectories if show_trajectories else None,
    )
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store, no-cache"},
    )
