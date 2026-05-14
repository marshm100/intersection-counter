"""Tests for the filename parser."""

import os
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from backend.services.filename_parser import (
    parse_filename, parse_with_fallback, parsed_to_dict,
)


class TestStructuredMatch:
    def test_typical_camera_name(self):
        p = parse_filename("Cam1_03_20260514_080000 Main St & 5th Ave.mp4")
        assert p is not None
        assert p.camera_label == "Cam1"
        assert p.sequence == 3
        assert p.recording_start_datetime == datetime(2026, 5, 14, 8, 0, 0)
        assert p.intersection_hint == "Main St & 5th Ave"
        assert p.parse_confidence == 1.0

    def test_numeric_only_camera(self):
        p = parse_filename("1_12_20260514_172030 Burnet Rd.mp4")
        assert p is not None
        assert p.camera_label == "1"
        assert p.sequence == 12

    def test_alpha_camera_label(self):
        p = parse_filename("CamA_001_20260513_233015 Downtown.mp4")
        assert p is not None
        assert p.camera_label == "CamA"

    def test_no_intersection_hint(self):
        p = parse_filename("CamA_001_20260513_233015.mp4")
        assert p is not None
        assert p.intersection_hint is None
        assert p.parse_confidence == 1.0

    def test_multiword_intersection(self):
        p = parse_filename("Cam1_03_20260514_080000 East 6th and Congress Ave NB.mp4")
        assert p is not None
        assert p.intersection_hint == "East 6th and Congress Ave NB"

    def test_uppercase_extension(self):
        p = parse_filename("Cam1_03_20260514_080000.MP4")
        assert p is not None
        assert p.recording_start_datetime.hour == 8

    def test_path_prefix_is_stripped(self):
        p = parse_filename("/data/videos/Cam1_03_20260514_080000.mp4")
        assert p is not None
        assert p.camera_label == "Cam1"


class TestNonMatching:
    def test_random_filename_returns_none(self):
        assert parse_filename("DSC00123.mp4") is None

    def test_missing_time_component(self):
        assert parse_filename("Cam1_03_20260514.mp4") is None

    def test_invalid_date_returns_none(self):
        # Month 13 doesn't exist
        assert parse_filename("Cam1_03_20261314_080000.mp4") is None

    def test_invalid_time_returns_none(self):
        # Hour 25 doesn't exist
        assert parse_filename("Cam1_03_20260514_250000.mp4") is None

    def test_no_extension(self):
        assert parse_filename("Cam1_03_20260514_080000") is None

    def test_wrong_separator(self):
        assert parse_filename("Cam1-03-20260514-080000.mp4") is None


class TestFallback:
    def test_fallback_returns_unknown_with_zero_confidence(self, tmp_path):
        f = tmp_path / "DSC00123.mp4"
        f.write_bytes(b"x")
        p = parse_with_fallback(str(f), duration_seconds=60.0)
        assert p.camera_label == "Unknown"
        assert p.sequence is None
        assert p.intersection_hint is None
        assert p.parse_confidence == 0.0
        assert p.raw_filename == "DSC00123.mp4"

    def test_fallback_subtracts_duration_from_mtime(self, tmp_path):
        f = tmp_path / "weird_name.mp4"
        f.write_bytes(b"x")
        mtime = datetime.fromtimestamp(f.stat().st_mtime)
        p = parse_with_fallback(str(f), duration_seconds=120.0)
        delta = mtime - p.recording_start_datetime
        # Should be roughly 120s, allow small float jitter
        assert 119 <= delta.total_seconds() <= 121

    def test_structured_filename_uses_structured_parse(self, tmp_path):
        f = tmp_path / "Cam1_03_20260514_080000.mp4"
        f.write_bytes(b"x")
        p = parse_with_fallback(str(f), duration_seconds=120.0)
        # Structured parse wins over fallback
        assert p.camera_label == "Cam1"
        assert p.parse_confidence == 1.0
        assert p.recording_start_datetime == datetime(2026, 5, 14, 8, 0, 0)


class TestSerialization:
    def test_to_dict_round_trip_shape(self):
        p = parse_filename("Cam1_03_20260514_080000 Main St.mp4")
        d = parsed_to_dict(p)
        assert d["camera_label"] == "Cam1"
        assert d["sequence"] == 3
        assert d["recording_start_datetime"].startswith("2026-05-14T08:00:00")
        assert d["intersection_hint"] == "Main St"
        assert d["parse_confidence"] == 1.0
        assert d["raw_filename"] == "Cam1_03_20260514_080000 Main St.mp4"
