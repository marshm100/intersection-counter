"""Processing router — start, pause, resume, cancel, and status for the AI pipeline."""

import logging
import threading
from typing import Callable

import cv2
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.config import DEFAULT_FRAME_SKIP, PROJECTS_DIR
from backend.database import get_all_project_info, get_db_path, get_connection, set_project_info
from backend.services.checkpoint import CheckpointManager
from backend.services.pipeline import ProcessingPipeline

logger = logging.getLogger(__name__)
router = APIRouter()

# Module-level state
_pipelines: dict[str, ProcessingPipeline] = {}
_progress: dict[str, dict] = {}
_threads: dict[str, threading.Thread] = {}
_state_lock = threading.Lock()


def _time_str_to_seconds(t: str) -> int:
    """Convert 'HH:MM' string to integer seconds."""
    parts = t.strip().split(":")
    return int(parts[0]) * 3600 + int(parts[1]) * 60


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
        legs = [dict(row) for row in conn.execute(
            "SELECT * FROM legs ORDER BY sort_order"
        ).fetchall()]
    finally:
        conn.close()

    if not legs:
        raise HTTPException(status_code=400, detail="No legs configured for this project.")

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    cap.release()

    return {
        "video_path": video_path,
        "video_start_time": info.get("video_start_time"),
        "legs": legs,
        "fps": fps,
    }


def _make_progress_callback(project_id: str) -> Callable:
    """Return a closure that stores progress data under _state_lock."""
    def callback(data: dict):
        with _state_lock:
            _progress[project_id] = data
    return callback


def _run_pipeline(project_id: str, start_frame: int = 0, end_frame: int | None = None):
    """Thread target: run the pipeline, update status on finish."""
    try:
        with _state_lock:
            pipeline = _pipelines.get(project_id)
        if pipeline is None:
            return

        callback = _make_progress_callback(project_id)
        pipeline.process_video(
            frame_skip=DEFAULT_FRAME_SKIP,
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
        with _state_lock:
            _pipelines.pop(project_id, None)
            _threads.pop(project_id, None)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class StartProcessingRequest(BaseModel):
    count_start_time: str | None = None  # "HH:MM" offset from video start; None = 00:00
    count_end_time:   str | None = None  # "HH:MM" offset from video start; None = end of video


@router.post("/projects/{project_id}/processing/start")
def start_processing(project_id: str, req: StartProcessingRequest = StartProcessingRequest()):
    with _state_lock:
        if project_id in _pipelines:
            raise HTTPException(status_code=409, detail="Processing already running.")

    prereqs = _load_prerequisites(project_id)
    db_path = str(get_db_path(project_id))
    fps = prereqs["fps"]
    info = get_all_project_info(project_id)
    total_frames = int(info.get("video_total_frames", 0))

    # Convert HH:MM time strings to frame numbers
    start_frame = 0
    if req.count_start_time:
        start_frame = int(_time_str_to_seconds(req.count_start_time) * fps)
        start_frame = max(0, min(start_frame, total_frames))

    end_frame = None
    if req.count_end_time:
        end_frame = int(_time_str_to_seconds(req.count_end_time) * fps)
        end_frame = max(start_frame + 1, min(end_frame, total_frames))

    # Persist window so resume can reuse it
    set_project_info(project_id, "count_start_time", req.count_start_time or "")
    set_project_info(project_id, "count_end_time",   req.count_end_time   or "")
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

    with _state_lock:
        _pipelines[project_id] = pipeline

    set_project_info(project_id, "status", "processing")

    thread = threading.Thread(
        target=_run_pipeline, args=(project_id, start_frame, end_frame), daemon=True
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
            raise HTTPException(status_code=409, detail="Processing already running.")

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

    # Restore the original count window end frame
    info = get_all_project_info(project_id)
    end_frame_str = info.get("count_end_frame", "")
    end_frame = int(end_frame_str) if end_frame_str else None

    with _state_lock:
        _pipelines[project_id] = pipeline

    set_project_info(project_id, "status", "processing")

    thread = threading.Thread(
        target=_run_pipeline, args=(project_id, start_frame, end_frame), daemon=True
    )
    with _state_lock:
        _threads[project_id] = thread
    thread.start()

    return {"status": "ok", "start_frame": start_frame}


@router.post("/projects/{project_id}/processing/cancel")
def cancel_processing(project_id: str):
    """Idempotent cancel: pause if running, clear checkpoint, reset to idle."""
    with _state_lock:
        pipeline = _pipelines.get(project_id)
        thread = _threads.get(project_id)

    if pipeline is not None:
        pipeline.pause()
        if thread is not None:
            thread.join(timeout=5)

    db_path = str(get_db_path(project_id))
    CheckpointManager(db_path).clear_checkpoint()

    with _state_lock:
        _pipelines.pop(project_id, None)
        _threads.pop(project_id, None)
        _progress.pop(project_id, None)

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

    return {
        "status": status,
        "is_running": is_running,
        "has_checkpoint": has_checkpoint,
        "progress": progress,
        "count_start_time": info.get("count_start_time", ""),
        "count_end_time": info.get("count_end_time", ""),
    }
