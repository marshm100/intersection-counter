import cv2
import json
import subprocess
from pathlib import Path


def _format_duration(seconds: float) -> str:
    """Format seconds as 'HH:MM:SS'."""
    total = int(seconds)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _format_file_size(size_bytes: int) -> str:
    """Format bytes as human-readable string."""
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f} GB"
    if size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes} B"


def extract_creation_time(video_path: str) -> str | None:
    """Extract creation time from video metadata using ffprobe.

    Returns ISO datetime string if found, None otherwise.
    Gracefully returns None if ffprobe is not installed or fails.
    """
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                str(video_path),
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        tags = data.get("format", {}).get("tags", {})
        for key in ("creation_time", "date", "com.apple.quicktime.creationdate"):
            if key in tags:
                return tags[key]
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired, json.JSONDecodeError, Exception):
        return None


def get_video_info(video_path: str) -> dict:
    """Open video with cv2, extract and return metadata dict."""
    path = Path(video_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open file as video: {video_path}")

    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = round(cap.get(cv2.CAP_PROP_FPS), 2)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
        codec = "".join(
            chr((fourcc_int >> (8 * i)) & 0xFF)
            for i in range(4)
            if ((fourcc_int >> (8 * i)) & 0xFF) != 0
        )

        duration_seconds = round(total_frames / fps, 2) if fps > 0 else 0.0
        file_size = path.stat().st_size
        creation_time = extract_creation_time(str(path))

        return {
            "path": str(path),
            "filename": path.name,
            "width": width,
            "height": height,
            "fps": fps,
            "total_frames": total_frames,
            "duration_seconds": duration_seconds,
            "duration_formatted": _format_duration(duration_seconds),
            "file_size_bytes": file_size,
            "file_size_formatted": _format_file_size(file_size),
            "codec": codec,
            "creation_time": creation_time,
        }
    finally:
        cap.release()


def get_frame_at_position(video_path: str, frame_number: int) -> bytes:
    """Open video, seek to frame_number, read one frame, return JPEG bytes.

    Always opens/closes per call — no persistent VideoCapture objects.
    """
    path = Path(video_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    if frame_number < 0:
        raise ValueError(f"frame_number must be >= 0, got {frame_number}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open file as video: {video_path}")

    try:
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if frame_number >= total_frames:
            raise ValueError(
                f"frame_number {frame_number} >= total_frames {total_frames}"
            )

        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_number)
        ret, frame = cap.read()
        if not ret or frame is None:
            raise ValueError(f"Failed to read frame {frame_number}")

        success, buf = cv2.imencode(".jpg", frame)
        if not success:
            raise ValueError(f"Failed to encode frame {frame_number} as JPEG")

        return buf.tobytes()
    finally:
        cap.release()


def get_frame_at_time(video_path: str, seconds: float) -> bytes:
    """Convert seconds to frame number using fps, delegate to get_frame_at_position."""
    path = Path(video_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Video file not found: {video_path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError(f"Cannot open file as video: {video_path}")

    try:
        fps = cap.get(cv2.CAP_PROP_FPS)
    finally:
        cap.release()

    frame_number = int(seconds * fps)
    return get_frame_at_position(video_path, frame_number)
