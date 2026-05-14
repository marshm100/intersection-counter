"""v3 multi-camera orchestrator.

Plans segment work for an intersection-day card. For each trim, computes
the (camera, video, start_offset, end_offset) tuples that the pipeline
should process. Validates coverage before planning so the user sees gap
errors up front instead of mid-run.

Pure planning logic. The actual pipeline invocation lives in the
processing router; this module just answers "what should be processed?"
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from backend.services.coverage import (
    CameraCoverage, Interval, compute_coverage_report,
    video_to_coverage_interval, wallclock_to_datetime,
)


@dataclass
class VideoSegment:
    """One processable slice of a single video.

    start_offset_seconds and end_offset_seconds are measured from the
    video's start frame (frame 0). The pipeline converts these to frame
    numbers via the video's FPS at run time.
    """
    video_id: int
    camera_id: int
    trim_id: int
    video_path: str
    fps: float
    duration_seconds: float
    recording_start_datetime: datetime
    start_offset_seconds: float
    end_offset_seconds: float

    @property
    def start_frame(self) -> int:
        return max(0, int(self.start_offset_seconds * self.fps))

    @property
    def end_frame(self) -> int:
        return int(self.end_offset_seconds * self.fps)


@dataclass
class PlanResult:
    """Outcome of planning processing for one intersection-day.

    `segments` is empty when there are coverage errors. Callers should
    inspect `errors` and refuse to start if non-empty.
    """
    segments: list[VideoSegment]
    errors: list[str]
    cameras_used: list[int]   # de-duped, sorted
    trims_used: list[int]


def _video_interval(video: dict) -> Interval | None:
    """Compute the wall-clock coverage interval of one video row."""
    start_str = video.get("recording_start_datetime") or video.get("recording_start_time")
    if not start_str:
        return None
    try:
        start = datetime.fromisoformat(start_str)
    except ValueError:
        return None
    dur = float(video.get("duration_seconds") or 0)
    if dur <= 0:
        return None
    return video_to_coverage_interval(start, dur)


def _camera_coverage_with_videos(
    camera_id: int, videos: list[dict],
) -> tuple[CameraCoverage, list[tuple[dict, Interval]]]:
    """Returns (CameraCoverage, [(video_dict, interval), ...])."""
    pairs: list[tuple[dict, Interval]] = []
    for v in videos:
        iv = _video_interval(v)
        if iv is not None:
            pairs.append((v, iv))
    cov = CameraCoverage(camera_id=camera_id, intervals=[p[1] for p in pairs])
    return cov, pairs


def plan_intersection_day(
    *,
    date_str: str,
    trims: list[dict],
    cameras_with_videos: list[tuple[dict, list[dict]]],
) -> PlanResult:
    """Plan processing for one intersection-day.

    Inputs:
      date_str: YYYY-MM-DD for the intersection-day.
      trims: list of trim dicts (trim_id, start_wallclock, end_wallclock).
      cameras_with_videos: list of (camera_dict, videos_list_for_that_camera).

    Returns:
      A PlanResult. errors is non-empty if any trim isn't fully covered.
      segments lists every (camera, video, trim) processing slice; the
      pipeline runs each one in turn.
    """
    if not trims:
        return PlanResult([], ["No trims defined. Add at least one trim window."], [], [])

    # Build per-camera coverage + per-video intervals once.
    camera_videos: dict[int, list[tuple[dict, Interval]]] = {}
    camera_coverages: list[CameraCoverage] = []
    for cam, vids in cameras_with_videos:
        cov, pairs = _camera_coverage_with_videos(cam["camera_id"], vids)
        if pairs:
            camera_videos[cam["camera_id"]] = pairs
            camera_coverages.append(cov)

    if not camera_coverages:
        return PlanResult([], ["No cameras with video coverage at this intersection."], [], [])

    errors: list[str] = []
    segments: list[VideoSegment] = []
    cameras_used: set[int] = set()
    trims_used: set[int] = set()

    for trim in trims:
        try:
            trim_iv = Interval(
                wallclock_to_datetime(date_str, trim["start_wallclock"]),
                wallclock_to_datetime(date_str, trim["end_wallclock"]),
            )
        except ValueError as e:
            errors.append(f"Trim {trim['trim_id']}: invalid times — {e}")
            continue

        report = compute_coverage_report(camera_coverages, trim_iv)
        if not report.is_fully_covered():
            gap_descs = [
                f"{g.start.time()}-{g.end.time()}"
                for g in report.gaps
            ]
            errors.append(
                f"Trim {trim['start_wallclock']}-{trim['end_wallclock']}: "
                f"no video coverage at {', '.join(gap_descs)}"
            )
            continue

        # For each (covered sub-interval, camera) pair, intersect with each
        # of that camera's videos and emit a VideoSegment per overlapping
        # video. This naturally handles parallel coverage (two cameras both
        # produce segments) and gap-filling (different cameras for adjacent
        # sub-intervals).
        for sub_iv, cam_ids in report.sub_intervals:
            for cid in cam_ids:
                for video_row, video_iv in camera_videos[cid]:
                    overlap = video_iv.intersect(sub_iv)
                    if overlap is None:
                        continue
                    start_offset = (overlap.start - video_iv.start).total_seconds()
                    end_offset = (overlap.end - video_iv.start).total_seconds()
                    if end_offset <= start_offset:
                        continue
                    segments.append(VideoSegment(
                        video_id=video_row["video_id"],
                        camera_id=cid,
                        trim_id=trim["trim_id"],
                        video_path=video_row["path"],
                        fps=float(video_row["fps"]),
                        duration_seconds=float(video_row["duration_seconds"]),
                        recording_start_datetime=video_iv.start,
                        start_offset_seconds=start_offset,
                        end_offset_seconds=end_offset,
                    ))
                    cameras_used.add(cid)
                    trims_used.add(trim["trim_id"])

    return PlanResult(
        segments=segments,
        errors=errors,
        cameras_used=sorted(cameras_used),
        trims_used=sorted(trims_used),
    )
