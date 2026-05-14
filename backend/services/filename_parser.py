"""Filename parser for traffic-camera clips.

Expected format (per v3 Implementation Plan):
    [Camera Number]_[Sequence]_[YYYYMMDD]_[HHMMSS] [Intersection name].ext

Examples:
    Cam1_03_20260514_080000 Main St & 5th Ave.mp4
    1_12_20260514_172030 Burnet Rd & 38th.mp4
    CamA_001_20260513_233015.mp4              (no intersection hint)

The intersection name in the filename is user-added and treated as advisory
only — the canonical intersection name is whatever the user enters in the
Videos tab. The other four fields (camera label, sequence, date, time) come
from the camera firmware and are trusted as the recording-start anchor.

Fallback when the filename doesn't match the expected pattern:
- camera_label = "Unknown"
- recording_start_datetime = file_mtime - duration  (best guess)
- intersection_hint = None
- parse_confidence < 1.0
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


# Anchored regex: cam + seq + date(YYYYMMDD) + time(HHMMSS) + optional name.
# Camera label tolerates letters and digits ("Cam1", "1", "CamA").
# Intersection hint captures anything after a single space, up to ext.
FILENAME_RE = re.compile(
    r"^(?P<cam>[A-Za-z0-9]+)_(?P<seq>\d+)_"
    r"(?P<date>\d{8})_(?P<time>\d{6})"
    r"(?:\s+(?P<intersection>.+?))?"
    r"\.(?P<ext>[A-Za-z0-9]+)$"
)


@dataclass
class ParsedFilename:
    """Result of parsing a single video filename.

    parse_confidence is 1.0 for a clean structured match, 0.0 for a complete
    fallback. The Videos-tab UI highlights rows with confidence < 0.5.
    """
    camera_label: str
    sequence: int | None
    recording_start_datetime: datetime
    intersection_hint: str | None
    parse_confidence: float
    raw_filename: str


def parse_filename(filename: str) -> ParsedFilename | None:
    """Parse a filename against the structured pattern. Returns None on no match.

    Caller should fall back to `parse_with_fallback` if they want a guaranteed
    result; this function is the strict-parse path used by tests.
    """
    base = os.path.basename(filename)
    m = FILENAME_RE.match(base)
    if not m:
        return None
    try:
        dt = datetime.strptime(
            f"{m['date']}{m['time']}", "%Y%m%d%H%M%S"
        )
    except ValueError:
        return None
    hint = m["intersection"].strip() if m["intersection"] else None
    return ParsedFilename(
        camera_label=m["cam"],
        sequence=int(m["seq"]),
        recording_start_datetime=dt,
        intersection_hint=hint or None,
        parse_confidence=1.0,
        raw_filename=base,
    )


def parse_with_fallback(
    file_path: str,
    duration_seconds: float | None = None,
) -> ParsedFilename:
    """Always return a ParsedFilename, even if the filename doesn't match.

    Fallback rules:
    - camera_label: "Unknown"
    - recording_start_datetime: file mtime - duration (recording-end as the
      anchor since cameras typically write the file when recording stops)
    - intersection_hint: None
    - parse_confidence: 0.0
    """
    parsed = parse_filename(file_path)
    if parsed is not None:
        return parsed

    base = os.path.basename(file_path)
    try:
        mtime = datetime.fromtimestamp(Path(file_path).stat().st_mtime)
    except (OSError, ValueError):
        mtime = datetime.now()
    estimated_start = mtime
    if duration_seconds is not None and duration_seconds > 0:
        estimated_start = mtime - timedelta(seconds=float(duration_seconds))

    return ParsedFilename(
        camera_label="Unknown",
        sequence=None,
        recording_start_datetime=estimated_start,
        intersection_hint=None,
        parse_confidence=0.0,
        raw_filename=base,
    )


def parsed_to_dict(p: ParsedFilename) -> dict:
    """Serialize ParsedFilename for HTTP response or DB write."""
    return {
        "camera_label": p.camera_label,
        "sequence": p.sequence,
        "recording_start_datetime": p.recording_start_datetime.isoformat(timespec="seconds"),
        "intersection_hint": p.intersection_hint,
        "parse_confidence": p.parse_confidence,
        "raw_filename": p.raw_filename,
    }
