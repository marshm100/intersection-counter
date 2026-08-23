"""resolve_content_hash — pass-2 must replay a pass-1 dump when the source
video is gone (2026-08-22 machine transition: the corridor's videos stayed on
a company OneDrive). The hash is recoverable three ways; every one of them must
yield the SAME digest the video would have produced, or a replay would read a
different dump and silently change a measured score.
"""
from __future__ import annotations

import json

import pytest

from backend.services.detection_cache import (
    HASH_METHOD,
    compute_video_content_hash,
    resolve_content_hash,
)

HASH_A = "a" * 64
HASH_B = "b" * 64


def _make_cache(root, camera_id, content_hash, variants=("study_0700",),
                write_meta=True, meta_hash=None):
    d = root / str(camera_id) / content_hash
    d.mkdir(parents=True, exist_ok=True)
    for v in variants:
        (d / f"{v}.parquet").write_bytes(b"")
        if write_meta:
            (d / f"{v}.meta.json").write_text(json.dumps({
                "camera_id": camera_id,
                "content_hash": meta_hash or content_hash,
                "method": HASH_METHOD,
            }))
    return d


def _video(tmp_path, payload=b"some video bytes"):
    p = tmp_path / "clip.mp4"
    p.write_bytes(payload)
    return p


class TestPersistedHashWins:
    def test_persisted_hash_used_without_touching_the_file(self, tmp_path):
        """The recorded hash short-circuits — no file read, no cache needed."""
        got, method = resolve_content_hash(
            "proj", 2, tmp_path / "does-not-exist.mp4",
            persisted_hash=HASH_A, persisted_method=HASH_METHOD,
            root=tmp_path / "detections")
        assert got == HASH_A
        assert method == HASH_METHOD

    def test_stale_method_is_ignored(self, tmp_path):
        """A hash recorded under an older recipe must NOT be trusted; fall
        through to the file so the digest matches the current recipe."""
        vid = _video(tmp_path)
        expected, _ = compute_video_content_hash(vid)
        got, method = resolve_content_hash(
            "proj", 2, vid,
            persisted_hash=HASH_A, persisted_method="blake2b-OLD-v0",
            root=tmp_path / "detections")
        assert got == expected != HASH_A
        assert method == HASH_METHOD


class TestFilePath:
    def test_present_video_matches_compute_exactly(self, tmp_path):
        vid = _video(tmp_path)
        expected, _ = compute_video_content_hash(vid)
        got, method = resolve_content_hash(
            "proj", 2, vid, root=tmp_path / "detections")
        assert got == expected
        assert method == HASH_METHOD

    def test_size_and_frames_are_honored(self, tmp_path):
        """The offline path must not quietly change the recipe's inputs."""
        vid = _video(tmp_path)
        a, _ = resolve_content_hash("proj", 2, vid, file_size_bytes=10,
                                    total_frames=5, root=tmp_path / "d")
        b, _ = compute_video_content_hash(vid, file_size_bytes=10,
                                          total_frames=5)
        assert a == b


class TestOfflineCacheFallback:
    def test_single_cache_dir_resolves(self, tmp_path):
        root = tmp_path / "detections"
        _make_cache(root, 2, HASH_A)
        got, method = resolve_content_hash(
            "proj", 2, tmp_path / "gone.mp4", root=root)
        assert got == HASH_A
        assert "cache-resolved" in method

    def test_two_cache_dirs_refuses_to_guess(self, tmp_path):
        root = tmp_path / "detections"
        _make_cache(root, 2, HASH_A)
        _make_cache(root, 2, HASH_B)
        with pytest.raises(ValueError, match="cannot tell which"):
            resolve_content_hash("proj", 2, tmp_path / "gone.mp4", root=root)

    def test_sidecar_disagreement_refuses(self, tmp_path):
        """A meta.json naming a different hash than its directory means the
        cache was tampered with or copied wrong — never guess past that."""
        root = tmp_path / "detections"
        _make_cache(root, 2, HASH_A, meta_hash=HASH_B)
        with pytest.raises(ValueError, match="disagrees"):
            resolve_content_hash("proj", 2, tmp_path / "gone.mp4", root=root)

    def test_no_cache_at_all_raises_filenotfound(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            resolve_content_hash("proj", 2, tmp_path / "gone.mp4",
                                 root=tmp_path / "detections")

    def test_empty_camera_dir_raises_filenotfound(self, tmp_path):
        root = tmp_path / "detections"
        (root / "2").mkdir(parents=True)
        with pytest.raises(FileNotFoundError):
            resolve_content_hash("proj", 2, tmp_path / "gone.mp4", root=root)

    def test_missing_sidecars_still_resolve(self, tmp_path):
        """Sidecars are a cross-check, not a requirement."""
        root = tmp_path / "detections"
        _make_cache(root, 2, HASH_A, write_meta=False)
        got, _ = resolve_content_hash("proj", 2, tmp_path / "gone.mp4", root=root)
        assert got == HASH_A

    def test_loose_files_beside_cache_dirs_are_ignored(self, tmp_path):
        """The real corridor cache has a track_audit.json sitting next to the
        hash directories; it must not be mistaken for one."""
        root = tmp_path / "detections"
        _make_cache(root, 2, HASH_A)
        (root / "2" / "track_audit.json").write_text("{}")
        got, _ = resolve_content_hash("proj", 2, tmp_path / "gone.mp4", root=root)
        assert got == HASH_A
