"""Cross-camera vehicle deduplication.

When two cameras film the same intersection during a parallel-coverage
region, they often both detect the same physical vehicle. The aggregator
must count it once, not twice. When ONE camera misses a vehicle the other
caught (occlusion, lighting, blind spot), we want to count it from
whichever camera DID see it. That's the "gap fill" case.

The algorithm only deduplicates events that fall inside a parallel-overlap
region. Single-coverage events are always kept as-is.

Tunable constants (see config.py):
  DEDUP_TIME_WINDOW_SECONDS — ±window for matching events across cameras
  DEDUP_USE_CARDINAL_MATCH  — also require cardinal direction to match
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from backend.services.coverage import CameraCoverage, Interval, find_overlap_regions


DEFAULT_TIME_WINDOW_SECONDS = 5.0


@dataclass
class EventForDedup:
    """The slice of a vehicle_events row the dedup pass needs.

    Wall-clock timestamp is precomputed by the caller (it's
    video.recording_start_datetime + timestamp_video).
    """
    event_id: int
    camera_id: int
    leg_label: str
    cardinal_direction: str
    movement: str
    wallclock_time: datetime
    detection_confidence: float
    trajectory_confidence: float


@dataclass
class DedupResult:
    """One canonical kept event plus the events it merged in."""
    event_id: int
    camera_ids: list[int]   # all cameras that contributed (kept + merged)
    merged_event_ids: list[int] = field(default_factory=list)


def _is_in_overlap_region(event: EventForDedup, regions: list[Interval]) -> bool:
    for r in regions:
        if r.start <= event.wallclock_time < r.end:
            return True
    return False


def deduplicate(
    events: list[EventForDedup],
    camera_coverages: list[CameraCoverage],
    *,
    time_window_seconds: float = DEFAULT_TIME_WINDOW_SECONDS,
    use_cardinal: bool = True,
) -> tuple[list[DedupResult], set[int]]:
    """Run the dedup pass over an intersection-day's events.

    Returns:
      (kept_results, duplicate_event_ids)
      where kept_results is the list of canonical events with their merge
      attribution, and duplicate_event_ids is the set of event_ids that
      were merged INTO another event (and should not be counted by the
      aggregator).
    """
    overlap_regions = find_overlap_regions(camera_coverages)

    # Split events: those outside any overlap region pass through as singletons.
    in_overlap: list[EventForDedup] = []
    out_overlap: list[EventForDedup] = []
    for e in events:
        if overlap_regions and _is_in_overlap_region(e, overlap_regions):
            in_overlap.append(e)
        else:
            out_overlap.append(e)

    results: list[DedupResult] = []
    duplicates: set[int] = set()

    # Singletons (non-overlap) are kept as-is.
    for e in out_overlap:
        results.append(DedupResult(event_id=e.event_id, camera_ids=[e.camera_id]))

    # In-overlap events: group by (leg_label, movement [, cardinal]).
    def key(e: EventForDedup):
        if use_cardinal:
            return (e.leg_label, e.cardinal_direction, e.movement)
        return (e.leg_label, e.movement)

    in_overlap.sort(key=lambda e: (key(e), e.wallclock_time))

    # Bucket by key, then within each bucket sort by time and greedily
    # collapse events from different cameras within the time window.
    buckets: dict[tuple, list[EventForDedup]] = {}
    for e in in_overlap:
        buckets.setdefault(key(e), []).append(e)

    window = timedelta(seconds=float(time_window_seconds))
    for bucket in buckets.values():
        bucket.sort(key=lambda e: e.wallclock_time)
        # Each "kept" event starts a window; subsequent events from a
        # DIFFERENT camera within `window` get merged into it.
        i = 0
        while i < len(bucket):
            anchor = bucket[i]
            merged_ids: list[int] = []
            contributing_cams: set[int] = {anchor.camera_id}
            j = i + 1
            while j < len(bucket):
                cand = bucket[j]
                if cand.wallclock_time - anchor.wallclock_time > window:
                    break
                # Same camera: don't dedup (these are two distinct vehicles
                # from the same camera within the window).
                if cand.camera_id == anchor.camera_id:
                    j += 1
                    continue
                # Different camera, within window: collapse cand into anchor.
                # Higher-confidence wins as the canonical event; otherwise
                # the earlier one (anchor) stays.
                if (cand.detection_confidence > anchor.detection_confidence
                        and cand.camera_id not in contributing_cams):
                    # Swap: cand becomes the canonical event.
                    merged_ids.append(anchor.event_id)
                    duplicates.add(anchor.event_id)
                    anchor = cand
                else:
                    merged_ids.append(cand.event_id)
                    duplicates.add(cand.event_id)
                contributing_cams.add(cand.camera_id)
                # Remove the merged event from the bucket so the next
                # outer iteration doesn't re-examine it.
                bucket.pop(j)
            results.append(DedupResult(
                event_id=anchor.event_id,
                camera_ids=sorted(contributing_cams),
                merged_event_ids=merged_ids,
            ))
            i += 1

    return results, duplicates
