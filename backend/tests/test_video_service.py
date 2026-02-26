import pytest
import shutil
import numpy as np
import cv2
from pathlib import Path

from backend.services.video_service import (
    get_video_info,
    get_frame_at_position,
    get_frame_at_time,
    extract_creation_time,
    _format_duration,
    _format_file_size,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
TEST_VIDEO = FIXTURES_DIR / "test_clip.mp4"
TEST_WIDTH = 320
TEST_HEIGHT = 240
TEST_FPS = 30
TEST_FRAMES = 90  # 3 seconds


@pytest.fixture(scope="module", autouse=True)
def create_test_video():
    """Generate a synthetic MP4: 320x240, 30fps, 90 frames with unique solid colors."""
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(TEST_VIDEO), fourcc, TEST_FPS, (TEST_WIDTH, TEST_HEIGHT))
    for i in range(TEST_FRAMES):
        # Unique color per frame based on index
        b = (i * 3) % 256
        g = (i * 7 + 50) % 256
        r = (i * 11 + 100) % 256
        frame = np.full((TEST_HEIGHT, TEST_WIDTH, 3), (b, g, r), dtype=np.uint8)
        writer.write(frame)
    writer.release()
    yield
    if FIXTURES_DIR.exists():
        shutil.rmtree(FIXTURES_DIR)


class TestGetVideoInfo:
    def test_returns_all_fields(self):
        info = get_video_info(str(TEST_VIDEO))
        expected_keys = [
            "path", "filename", "width", "height", "fps", "total_frames",
            "duration_seconds", "duration_formatted", "file_size_bytes",
            "file_size_formatted", "codec", "creation_time",
        ]
        for key in expected_keys:
            assert key in info, f"Missing key: {key}"

    def test_correct_dimensions(self):
        info = get_video_info(str(TEST_VIDEO))
        assert info["width"] == TEST_WIDTH
        assert info["height"] == TEST_HEIGHT

    def test_correct_fps(self):
        info = get_video_info(str(TEST_VIDEO))
        assert info["fps"] == TEST_FPS

    def test_correct_frame_count(self):
        info = get_video_info(str(TEST_VIDEO))
        assert info["total_frames"] == TEST_FRAMES

    def test_correct_duration(self):
        info = get_video_info(str(TEST_VIDEO))
        assert info["duration_seconds"] == 3.0

    def test_correct_filename(self):
        info = get_video_info(str(TEST_VIDEO))
        assert info["filename"] == "test_clip.mp4"

    def test_path_is_absolute(self):
        info = get_video_info(str(TEST_VIDEO))
        assert Path(info["path"]).is_absolute()

    def test_codec_is_nonempty_string(self):
        info = get_video_info(str(TEST_VIDEO))
        assert isinstance(info["codec"], str)
        assert len(info["codec"]) > 0

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            get_video_info("/nonexistent/video.mp4")

    def test_non_video_file(self):
        # Create a text file and try to open it as video
        txt_path = FIXTURES_DIR / "not_a_video.txt"
        txt_path.write_text("this is not a video")
        with pytest.raises(ValueError):
            get_video_info(str(txt_path))


class TestGetFrameAtPosition:
    def test_frame_zero_is_jpeg(self):
        data = get_frame_at_position(str(TEST_VIDEO), 0)
        assert data[:2] == b"\xff\xd8"

    def test_last_frame(self):
        data = get_frame_at_position(str(TEST_VIDEO), TEST_FRAMES - 1)
        assert data[:2] == b"\xff\xd8"

    def test_middle_frame(self):
        data = get_frame_at_position(str(TEST_VIDEO), 45)
        assert data[:2] == b"\xff\xd8"

    def test_frame_at_total_frames_raises(self):
        with pytest.raises(ValueError):
            get_frame_at_position(str(TEST_VIDEO), TEST_FRAMES)

    def test_frame_past_end_raises(self):
        with pytest.raises(ValueError):
            get_frame_at_position(str(TEST_VIDEO), TEST_FRAMES + 100)

    def test_negative_frame_raises(self):
        with pytest.raises(ValueError):
            get_frame_at_position(str(TEST_VIDEO), -1)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            get_frame_at_position("/nonexistent/video.mp4", 0)

    def test_different_frames_different_bytes(self):
        frame0 = get_frame_at_position(str(TEST_VIDEO), 0)
        frame45 = get_frame_at_position(str(TEST_VIDEO), 45)
        assert frame0 != frame45


class TestGetFrameAtTime:
    def test_time_zero(self):
        data = get_frame_at_time(str(TEST_VIDEO), 0.0)
        assert data[:2] == b"\xff\xd8"

    def test_time_one(self):
        data = get_frame_at_time(str(TEST_VIDEO), 1.0)
        assert data[:2] == b"\xff\xd8"

    def test_time_past_end_raises(self):
        with pytest.raises(ValueError):
            get_frame_at_time(str(TEST_VIDEO), 999.0)

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            get_frame_at_time("/nonexistent/video.mp4", 0.0)


class TestExtractCreationTime:
    def test_returns_string_or_none(self):
        result = extract_creation_time(str(TEST_VIDEO))
        assert result is None or isinstance(result, str)

    def test_nonexistent_file_returns_none(self):
        result = extract_creation_time("/nonexistent/video.mp4")
        assert result is None


class TestFormatDuration:
    def test_zero(self):
        assert _format_duration(0) == "00:00:00"

    def test_seconds_only(self):
        assert _format_duration(45) == "00:00:45"

    def test_minutes_and_seconds(self):
        assert _format_duration(125) == "00:02:05"

    def test_hours_minutes_seconds(self):
        assert _format_duration(3661) == "01:01:01"

    def test_large_hours(self):
        assert _format_duration(259200) == "72:00:00"


class TestFormatFileSize:
    def test_bytes(self):
        assert _format_file_size(500) == "500 B"

    def test_kilobytes(self):
        assert _format_file_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert _format_file_size(5242880) == "5.0 MB"

    def test_gigabytes(self):
        assert _format_file_size(1610612736) == "1.5 GB"
