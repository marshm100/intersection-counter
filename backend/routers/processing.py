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

from backend.config import DEFAULT_FRAME_SKIP, MAX_CONCURRENT_PIPELINES, PROJECTS_DIR
from backend.database import (
    get_all_project_info, get_db_path, get_connection,
    list_videos, set_project_info,
)
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
_preview_viewers: dict[str, int] = {}  # project_id -> active stream connection count
_state_lock = threading.Lock()

# Batch processing queue
_batch_queue: list[str] = []
_batch_params: dict[str, dict] = {}  # project_id -> {frame_skip}


def _make_placeholder_jpeg() -> bytes:
    """Return a black 640×360 JPEG with a 'Starting...' label.

    Returns b"" on encode failure rather than raising — the placeholder is
    cosmetic, never load-bearing, and a failure here shouldn't prevent
    processing from starting.
    """
    try:
        img = np.zeros((360, 640, 3), dtype=np.uint8)
        cv2.putText(img, "Starting...", (230, 190),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.2, (100, 100, 100), 2, cv2.LINE_AA)
        result = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 50])
        if not result or len(result) < 2 or result[1] is None:
            return b""
        return result[1].tobytes()
    except Exception:
        return b""


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
# Startup: heal stale "processing" status left by killed pipelines
# ---------------------------------------------------------------------------

def _heal_stale_status():
    """Reset any 'processing' status to 'interrupted' on server start.

    When uvicorn reloads, all pipeline threads die but the DB still says
    'processing'. This marks them as 'interrupted' so the user can decide
    to resume or reprocess.
    """
    if not PROJECTS_DIR.exists():
        return
    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir() or not (d / "project.db").exists():
            continue
        try:
            conn = get_connection(d.name)
            row = conn.execute(
                "SELECT value FROM project_info WHERE key = 'status'"
            ).fetchone()
            if row and row[0] == "processing":
                conn.execute(
                    "UPDATE project_info SET value = 'interrupted' WHERE key = 'status'"
                )
                conn.commit()
                logger.info("Healed stale 'processing' status for project %s", d.name)
        except Exception:
            pass

_heal_stale_status()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _probe_video(path: str) -> dict:
    """Use OpenCV to read fps + total_frames from a video file on disk."""
    import os
    if not os.path.isfile(path):
        raise HTTPException(status_code=400, detail=f"Video file not found on disk: {path}")
    cap = cv2.VideoCapture(path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return {"fps": fps, "total_frames": total_frames}


def _collect_videos_to_process(project_id: str, info: dict) -> list[dict]:
    """Return the ordered list of videos this run will process.

    Multi-video mode (videos table has rows): use those rows in sort_order.
    Legacy mode (no rows but project_info has video_path): synthesize a
    single-entry list with video_id=None so events get NULL video_id.
    """
    rows = list_videos(project_id)
    if rows:
        return [
            {
                "video_id": r["video_id"],
                "path": r["path"],
                "filename": r["filename"],
                "fps": float(r["fps"]),
                "total_frames": int(r["total_frames"]),
                "video_start_time": r.get("recording_start_time") or info.get("video_start_time"),
            }
            for r in rows
        ]

    # Legacy fallback
    video_path = info.get("video_path")
    if not video_path:
        return []
    probed = _probe_video(video_path)
    return [{
        "video_id": None,
        "path": video_path,
        "filename": info.get("video_filename") or video_path,
        "fps": probed["fps"],
        "total_frames": probed["total_frames"],
        "video_start_time": info.get("video_start_time"),
    }]


def _load_prerequisites(project_id: str) -> dict:
    """Load and validate everything needed to start a pipeline.

    Returns a dict with `videos` (ordered list, length >= 1) and `legs`.
    Also surfaces convenience fields for single-video callers: `video_path`,
    `fps`, `total_frames`, `video_start_time` — these reflect the FIRST
    video in the list and are kept for callers that haven't yet adopted
    the multi-video shape.
    """
    info = get_all_project_info(project_id)
    videos = _collect_videos_to_process(project_id, info)

    if not videos:
        raise HTTPException(status_code=400, detail="No video configured for this project.")

    for v in videos:
        import os
        if not os.path.isfile(v["path"]):
            raise HTTPException(
                status_code=400,
                detail=f"Video file not found on disk: {v['path']}",
            )

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

    first = videos[0]
    return {
        "videos": videos,
        "legs": legs,
        # Legacy convenience fields (first video) — keep until callers migrate
        "video_path": first["path"],
        "video_start_time": first["video_start_time"],
        "fps": first["fps"],
        "total_frames": first["total_frames"],
    }


def _make_progress_callback(
    project_id: str,
    legs: list[dict],
    video_index: int = 0,
    total_videos: int = 1,
    video_filename: str | None = None,
) -> Callable:
    """Return a closure that stores progress data and queues preview encoding.

    When the project spans multiple videos, video_index/total_videos/video_filename
    are injected into the progress payload so the UI can show "Video 2 of 3 — …".
    """
    def callback(data: dict):
        raw_frame = data.pop("raw_frame", None)
        tracks = data.pop("tracks", None)
        origin_zones = data.pop("origin_zones", None)
        active_trajectories = data.pop("active_trajectories", None)
        finalized_trajectories = data.pop("finalized_trajectories", None)
        if total_videos > 1:
            data["video_index"] = video_index
            data["total_videos"] = total_videos
            if video_filename:
                data["video_filename"] = video_filename
        with _state_lock:
            _progress[project_id] = data
        if raw_frame is not None and _preview_viewers.get(project_id, 0) > 0:
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


def _start_next_queued() -> None:
    """Start next queued project if under the concurrency limit. Called from _run_pipeline's finally block."""
    with _state_lock:
        active = sum(1 for t in _threads.values() if t.is_alive())
        while _batch_queue and active < MAX_CONCURRENT_PIPELINES:
            next_id = _batch_queue.pop(0)
            params = _batch_params.pop(next_id, {})
            # Verify project dir still exists (user might have deleted it while queued)
            project_dir = PROJECTS_DIR / next_id
            if not project_dir.exists():
                continue
            active += 1
            # Release lock before starting (start_processing acquires it internally)
            break
        else:
            return

    # Start outside the lock
    try:
        frame_skip = params.get("frame_skip")
        req = StartProcessingRequest(frame_skip=frame_skip)
        start_processing(next_id, req)
        logger.info("Batch queue: auto-started project %s", next_id)
    except Exception as e:
        logger.error("Batch queue: failed to start project %s: %s", next_id, e)
        set_project_info(next_id, "status", "error")
        # Try next in queue
        _start_next_queued()


def _run_pipeline(
    project_id: str,
    videos: list[dict],
    legs: list[dict],
    start_frame: int = 0,
    end_frame: int | None = None,
    frame_skip: int = DEFAULT_FRAME_SKIP,
    resume_video_id: int | None = None,
):
    """Thread target: orchestrate the pipeline across one or more videos.

    Single-video projects: identical behavior to v1 (start_frame/end_frame
    define the time window).
    Multi-video projects: process each video in turn, fully. The time-window
    args apply only to the first video and only when len(videos)==1.

    Pause: signals the current ProcessingPipeline; on the next save_checkpoint
    the loop sees pause_requested and exits cleanly. Resume looks up
    `resume_video_id` to know which video to pick up on.
    """
    db_path = str(get_db_path(project_id))
    pause_was_set = False

    try:
        # Find the starting index when resuming mid-batch.
        start_idx = 0
        if resume_video_id is not None:
            for i, v in enumerate(videos):
                if v["video_id"] == resume_video_id:
                    start_idx = i
                    break

        for idx in range(start_idx, len(videos)):
            v = videos[idx]
            is_first = idx == start_idx

            pipeline = ProcessingPipeline(
                project_id=project_id,
                db_path=db_path,
                video_path=v["path"],
                legs=legs,
                fps=v["fps"],
                video_start_time=v.get("video_start_time"),
                video_id=v["video_id"],
            )

            # Time windows only apply when there's exactly one video. For
            # multi-video runs we process each video end-to-end.
            if len(videos) == 1 and is_first:
                this_start, this_end = start_frame, end_frame
            else:
                this_start, this_end = 0, None

            # Resume from checkpoint only for the first video in a resumed run.
            if is_first and resume_video_id is not None:
                this_start = pipeline.resume_from_checkpoint()

            with _state_lock:
                _pipelines[project_id] = pipeline

            callback = _make_progress_callback(
                project_id, legs,
                video_index=idx,
                total_videos=len(videos),
                video_filename=v.get("filename"),
            )

            pipeline.process_video(
                frame_skip=frame_skip,
                start_frame=this_start,
                end_frame=this_end,
                callback=callback,
            )

            if pipeline.pause_requested.is_set():
                pause_was_set = True
                break

        if pause_was_set:
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
        # Auto-start next queued project
        _start_next_queued()


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
    videos = prereqs["videos"]
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

    # The orchestrator creates the first ProcessingPipeline; we just set up the
    # placeholder and preview infrastructure here.
    placeholder = _make_placeholder_jpeg()
    preview_q: queue.Queue = queue.Queue(maxsize=2)
    with _state_lock:
        _preview_frames[project_id] = placeholder
    _preview_queues[project_id] = preview_q

    set_project_info(project_id, "status", "processing")

    threading.Thread(
        target=_preview_worker, args=(project_id, preview_q), daemon=True
    ).start()

    thread = threading.Thread(
        target=_run_pipeline,
        kwargs={
            "project_id": project_id,
            "videos": videos,
            "legs": prereqs["legs"],
            "start_frame": start_frame,
            "end_frame": end_frame,
            "frame_skip": frame_skip,
        },
        daemon=True,
    )
    with _state_lock:
        _threads[project_id] = thread
    thread.start()

    return {"status": "ok", "videos": len(videos)}


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
    # Stop any existing pipeline first (handles stale threads from prior runs)
    stop_pipeline(project_id)

    db_path = str(get_db_path(project_id))
    ckpt_mgr = CheckpointManager(db_path)

    if not ckpt_mgr.has_checkpoint():
        raise HTTPException(status_code=400, detail="No checkpoint to resume from.")

    prereqs = _load_prerequisites(project_id)
    videos = prereqs["videos"]

    checkpoint = ckpt_mgr.load_checkpoint()
    resume_video_id = checkpoint.get("current_video_id") if checkpoint else None

    # If checkpoint has no current_video_id (pre-multi-video DBs), assume
    # we're resuming the first/only video.
    if resume_video_id is None and len(videos) == 1:
        resume_video_id = videos[0]["video_id"]

    # Restore the original count window end frame and frame_skip
    info = get_all_project_info(project_id)
    end_frame_str = info.get("count_end_frame", "")
    end_frame = int(end_frame_str) if end_frame_str else None
    frame_skip_str = info.get("frame_skip", "")
    frame_skip = int(frame_skip_str) if frame_skip_str else DEFAULT_FRAME_SKIP

    placeholder = _make_placeholder_jpeg()
    preview_q: queue.Queue = queue.Queue(maxsize=2)
    with _state_lock:
        _preview_frames[project_id] = placeholder
    _preview_queues[project_id] = preview_q

    set_project_info(project_id, "status", "processing")

    threading.Thread(
        target=_preview_worker, args=(project_id, preview_q), daemon=True
    ).start()

    thread = threading.Thread(
        target=_run_pipeline,
        kwargs={
            "project_id": project_id,
            "videos": videos,
            "legs": prereqs["legs"],
            "start_frame": 0,
            "end_frame": end_frame,
            "frame_skip": frame_skip,
            "resume_video_id": resume_video_id,
        },
        daemon=True,
    )
    with _state_lock:
        _threads[project_id] = thread
    thread.start()

    return {"status": "ok", "resume_video_id": resume_video_id}


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


@router.post("/projects/{project_id}/processing/reprocess")
def reprocess(project_id: str):
    """Clear all results and checkpoint so the user can start fresh with new algorithms."""
    stop_pipeline(project_id)

    conn = get_connection(project_id)
    try:
        with conn:
            conn.execute("DELETE FROM vehicle_events")
            conn.execute("DELETE FROM low_confidence_segments")
            conn.execute("DELETE FROM checkpoint")
    finally:
        conn.close()

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

    # Auto-heal: DB says "processing" but no pipeline is running → interrupted
    if status == "processing" and not is_running:
        status = "interrupted"
        set_project_info(project_id, "status", "interrupted")

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
    """MJPEG stream: yields latest JPEG frame every ~33 ms (≤30 fps).
    Closes automatically ~2 s after processing stops."""
    async def generate():
        with _state_lock:
            _preview_viewers[project_id] = _preview_viewers.get(project_id, 0) + 1
        try:
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

                await asyncio.sleep(0.033)  # 30 fps cap
        finally:
            with _state_lock:
                count = _preview_viewers.get(project_id, 1) - 1
                if count <= 0:
                    _preview_viewers.pop(project_id, None)
                else:
                    _preview_viewers[project_id] = count

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


# ---------------------------------------------------------------------------
# Batch processing endpoints
# ---------------------------------------------------------------------------

class BatchStartRequest(BaseModel):
    project_ids: list[str]
    frame_skip: int | None = None


@router.post("/processing/batch-start")
def batch_start(req: BatchStartRequest):
    """Start processing for multiple projects with a concurrency limit."""
    started: list[str] = []
    queued: list[str] = []
    skipped: list[dict] = []

    frame_skip = req.frame_skip if req.frame_skip and 1 <= req.frame_skip <= 5 else DEFAULT_FRAME_SKIP

    for pid in req.project_ids:
        project_dir = PROJECTS_DIR / pid
        if not project_dir.exists():
            skipped.append({"project_id": pid, "reason": "Project not found"})
            continue

        # Check has video and legs
        info = get_all_project_info(pid)
        if not info.get("video_path"):
            skipped.append({"project_id": pid, "reason": "No video configured"})
            continue

        conn = get_connection(pid)
        try:
            leg_count = conn.execute("SELECT COUNT(*) FROM legs").fetchone()[0]
        finally:
            conn.close()
        if leg_count == 0:
            skipped.append({"project_id": pid, "reason": "No legs configured (needs calibration)"})
            continue

        # Already running?
        with _state_lock:
            if pid in _pipelines:
                thread = _threads.get(pid)
                if thread is not None and thread.is_alive():
                    skipped.append({"project_id": pid, "reason": "Already processing"})
                    continue

        status = info.get("status", "")
        if status in ("complete",):
            skipped.append({"project_id": pid, "reason": "Already complete"})
            continue

        # Check concurrency limit
        with _state_lock:
            active = sum(1 for t in _threads.values() if t.is_alive())

        if active < MAX_CONCURRENT_PIPELINES:
            try:
                start_req = StartProcessingRequest(frame_skip=frame_skip)
                start_processing(pid, start_req)
                started.append(pid)
            except Exception as e:
                skipped.append({"project_id": pid, "reason": str(e)})
        else:
            _batch_queue.append(pid)
            _batch_params[pid] = {"frame_skip": frame_skip}
            set_project_info(pid, "status", "queued")
            queued.append(pid)

    return {"started": started, "queued": queued, "skipped": skipped}


@router.get("/processing/batch-status")
def batch_status():
    """Return status and progress for all projects in one call."""
    projects = []
    if not PROJECTS_DIR.exists():
        return {"projects": projects, "queue_length": len(_batch_queue), "active_count": 0}

    for d in PROJECTS_DIR.iterdir():
        if not d.is_dir() or not (d / "project.db").exists():
            continue
        try:
            info = get_all_project_info(d.name)
        except Exception:
            continue

        status = info.get("status", "idle")
        with _state_lock:
            is_running = d.name in _pipelines
            progress = _progress.get(d.name)

        # Auto-heal
        if status == "processing" and not is_running:
            status = "interrupted"
            set_project_info(d.name, "status", "interrupted")

        queue_pos = None
        if d.name in _batch_queue:
            queue_pos = _batch_queue.index(d.name) + 1

        entry = {
            "project_id": d.name,
            "name": info.get("project_name", ""),
            "status": status,
            "progress_pct": 0.0,
            "queue_position": queue_pos,
        }
        if progress:
            entry["progress_pct"] = progress.get("progress_pct", 0.0)
            entry["vehicle_count"] = progress.get("vehicle_count", 0)
            entry["fps"] = progress.get("fps", 0.0)

        projects.append(entry)

    with _state_lock:
        active_count = sum(1 for t in _threads.values() if t.is_alive())

    return {"projects": projects, "queue_length": len(_batch_queue), "active_count": active_count}
