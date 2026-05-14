"""Coverage / trim validation.

A trim is a wall-clock window the user wants processed (e.g. 07:00:00-09:00:00).
Each camera at an intersection-day produces a set of wall-clock coverage
intervals from its videos (recording_start_datetime + duration).

The validator answers:
  - Does the union of camera coverages fully contain the proposed trim?
  - If not, which sub-intervals of the trim have no video coverage?
  - For each second of the trim, which camera(s) cover it (used by the
    orchestrator to decide single-source vs parallel coverage)?

Pure interval algebra. No I/O. Unit-testable with synthetic data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class Interval:
    """Half-open wall-clock interval [start, end). Naive datetimes."""
    start: datetime
    end: datetime

    def __post_init__(self):
        if self.end <= self.start:
            raise ValueError(f"Interval end ({self.end}) must be after start ({self.start})")

    def duration_seconds(self) -> float:
        return (self.end - self.start).total_seconds()

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end

    def intersect(self, other: "Interval") -> "Interval | None":
        if not self.overlaps(other):
            return None
        s = max(self.start, other.start)
        e = min(self.end, other.end)
        return Interval(s, e)


@dataclass
class CameraCoverage:
    """All wall-clock intervals covered by one camera (from its videos)."""
    camera_id: int
    intervals: list[Interval]


@dataclass
class CoverageReport:
    """Per-trim breakdown of which cameras cover which sub-intervals.

    sub_intervals is sorted by start; each entry is the maximal sub-interval
    of the trim where the set of covering cameras is constant.
    gaps lists the sub-intervals of the trim with no camera coverage.
    """
    trim: Interval
    sub_intervals: list[tuple[Interval, list[int]]]   # camera_ids, sorted
    gaps: list[Interval]

    def is_fully_covered(self) -> bool:
        return not self.gaps


def _normalize(intervals: list[Interval]) -> list[Interval]:
    """Sort and merge overlapping intervals."""
    if not intervals:
        return []
    sorted_iv = sorted(intervals, key=lambda i: i.start)
    merged = [sorted_iv[0]]
    for iv in sorted_iv[1:]:
        last = merged[-1]
        if iv.start <= last.end:
            merged[-1] = Interval(last.start, max(last.end, iv.end))
        else:
            merged.append(iv)
    return merged


def video_to_coverage_interval(
    start_datetime: datetime, duration_seconds: float
) -> Interval:
    """Compute a video's wall-clock coverage from its start + duration."""
    return Interval(start_datetime, start_datetime + timedelta(seconds=float(duration_seconds)))


def wallclock_to_datetime(date_str: str, wallclock: str) -> datetime:
    """Combine YYYY-MM-DD + HH:MM:SS into a naive datetime."""
    return datetime.fromisoformat(f"{date_str}T{wallclock}")


def compute_coverage_report(
    cameras: list[CameraCoverage],
    trim: Interval,
) -> CoverageReport:
    """Walk the trim second by sub-interval, recording which cameras cover each.

    Uses a sweepline over interval endpoints clipped to the trim window.
    Output sub_intervals partition the trim exactly; gaps lists portions with
    zero coverage.
    """
    # Clip each camera's intervals to the trim window first.
    clipped: dict[int, list[Interval]] = {}
    for cam in cameras:
        kept = []
        for iv in cam.intervals:
            isect = iv.intersect(trim)
            if isect is not None:
                kept.append(isect)
        if kept:
            clipped[cam.camera_id] = _normalize(kept)

    # Build sweepline events: (time, +cam) on start, (time, -cam) on end.
    events: list[tuple[datetime, int, int]] = []   # (t, delta, camera_id)
    for cid, ivs in clipped.items():
        for iv in ivs:
            events.append((iv.start, +1, cid))
            events.append((iv.end, -1, cid))
    # Pin the trim boundaries so the partition spans the whole trim.
    events.append((trim.start, 0, 0))
    events.append((trim.end, 0, 0))
    events.sort(key=lambda e: (e[0], -e[1]))   # process starts before ends at same t

    # Sweep, emitting one sub-interval per distinct (active set) segment.
    active: set[int] = set()
    sub_intervals: list[tuple[Interval, list[int]]] = []
    gaps: list[Interval] = []
    prev_t = trim.start
    for t, delta, cid in events:
        if t > prev_t and prev_t >= trim.start and t <= trim.end:
            iv = Interval(prev_t, t)
            if active:
                sub_intervals.append((iv, sorted(active)))
            else:
                gaps.append(iv)
        if delta == +1:
            active.add(cid)
        elif delta == -1:
            active.discard(cid)
        prev_t = t

    return CoverageReport(trim=trim, sub_intervals=sub_intervals, gaps=gaps)


def union_intervals(intervals: list[Interval]) -> list[Interval]:
    """Public alias for the merge step — useful for computing total coverage."""
    return _normalize(intervals)


def find_overlap_regions(
    cameras: list[CameraCoverage],
) -> list[Interval]:
    """Return wall-clock intervals where 2+ cameras have simultaneous coverage.

    Used by the cross-camera dedup pass to know which segments need
    parallel-coverage reconciliation.
    """
    # Sweepline over starts/ends, counting active cameras.
    events: list[tuple[datetime, int]] = []
    for cam in cameras:
        for iv in cam.intervals:
            events.append((iv.start, +1))
            events.append((iv.end, -1))
    events.sort(key=lambda e: (e[0], -e[1]))

    regions: list[Interval] = []
    active = 0
    region_start: datetime | None = None
    for t, delta in events:
        was_overlap = active >= 2
        active += delta
        is_overlap = active >= 2
        if not was_overlap and is_overlap:
            region_start = t
        elif was_overlap and not is_overlap:
            if region_start is not None and t > region_start:
                regions.append(Interval(region_start, t))
            region_start = None
    return regions
