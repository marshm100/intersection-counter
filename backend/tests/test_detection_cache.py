"""Unit tests for the detection cache (Attribution v2, Step 1).

Round-trips synthetic detections through the Parquet writer/reader and checks
the reconstructed dicts match the shape VehicleDetector._parse_results emits,
plus hash stability and cache hit/miss detection.
"""
import pyarrow.parquet as pq
import pytest

from backend.services.detection_cache import (
    DetectionCacheReader,
    DetectionCacheWriter,
    cache_exists,
    compute_video_content_hash,
    parquet_path,
    read_metadata,
    reconstruct_detection,
)


def _det(x1, y1, x2, y2, conf, cls):
    return {
        "bbox": [x1, y1, x2, y2],
        "center": [(x1 + x2) / 2, (y1 + y2) / 2],
        "class_id": cls,
        "confidence": conf,
        "bbox_width": x2 - x1,
        "bbox_height": y2 - y1,
        "bbox_area": (x2 - x1) * (y2 - y1),
        "is_vehicle": True,
    }


def test_round_trip_preserves_detections(tmp_path):
    path = tmp_path / "c.parquet"
    w = DetectionCacheWriter(pq_path=path, metadata={"model": "yolo26s", "imgsz": 960})
    frames = {
        0: [_det(10, 20, 50, 60, 0.9, 2), _det(100, 100, 140, 150, 0.5, 7)],
        2: [_det(11, 21, 51, 61, 0.88, 2)],   # note: frame 1 has no detections
        5: [],                                  # explicit empty frame -> writes nothing
    }
    for fi, dets in frames.items():
        w.add(fi, dets)
    n = w.close()
    assert n == 3  # 2 + 1 + 0

    reader = DetectionCacheReader(path)
    assert reader.total_detections == 3
    got = dict(reader.iter_frames())
    assert sorted(got.keys()) == [0, 2]      # empty frame 5 produced no rows
    assert len(got[0]) == 2 and len(got[2]) == 1
    d = got[0][0]
    # Reconstructed shape matches the detector's parse output.
    assert d["bbox"] == [10.0, 20.0, 50.0, 60.0]
    assert d["center"] == [30.0, 40.0]
    assert d["class_id"] == 2 and d["class_name"] == "car"
    assert d["confidence"] == pytest.approx(0.9, abs=1e-6)
    assert d["bbox_width"] == 40.0 and d["bbox_height"] == 40.0
    assert d["bbox_area"] == 1600.0 and d["is_vehicle"] is True


def test_frames_yielded_in_order(tmp_path):
    path = tmp_path / "c.parquet"
    w = DetectionCacheWriter(pq_path=path)
    for fi in (0, 1, 2, 3):
        w.add(fi, [_det(fi, fi, fi + 10, fi + 10, 0.7, 2)])
    w.close()
    order = [fi for fi, _ in DetectionCacheReader(path).iter_frames()]
    assert order == [0, 1, 2, 3]


def test_empty_cache_is_still_a_hit(tmp_path):
    path = tmp_path / "c.parquet"
    w = DetectionCacheWriter(pq_path=path)
    assert w.close() == 0
    assert cache_exists(path)
    assert read_metadata(path)["total_detections"] == 0
    assert list(DetectionCacheReader(path).iter_frames()) == []


def test_cache_exists_requires_sidecar(tmp_path):
    path = tmp_path / "c.parquet"
    assert not cache_exists(path)        # nothing written
    DetectionCacheWriter(pq_path=path).close()
    assert cache_exists(path)
    # Removing the sidecar makes it a miss even though the parquet remains.
    path.with_suffix(".meta.json").unlink()
    assert not cache_exists(path)


def test_flush_batches_preserve_data(tmp_path):
    # flush_rows below the row count exercises the multi-row-group write path.
    path = tmp_path / "c.parquet"
    w = DetectionCacheWriter(pq_path=path, flush_rows=3)
    for fi in range(10):
        w.add(fi, [_det(fi, 0, fi + 5, 5, 0.6, 2)])
    n = w.close()
    assert n == 10
    assert pq.ParquetFile(str(path)).metadata.num_row_groups > 1
    assert sum(len(d) for _, d in DetectionCacheReader(path).iter_frames()) == 10


def test_content_hash_stable_and_sensitive(tmp_path):
    vid = tmp_path / "v.mp4"
    vid.write_bytes(b"\x00\x01\x02\x03" * 1000)
    h1, method = compute_video_content_hash(vid, file_size_bytes=4000, total_frames=100)
    h2, _ = compute_video_content_hash(vid, file_size_bytes=4000, total_frames=100)
    assert h1 == h2                      # deterministic
    assert method == "blake2b-128m-v1"
    # Different declared frame count -> different hash (re-trim invalidates).
    h3, _ = compute_video_content_hash(vid, file_size_bytes=4000, total_frames=200)
    assert h3 != h1
    # Different declared size -> different hash (re-encode invalidates).
    h4, _ = compute_video_content_hash(vid, file_size_bytes=4001, total_frames=100)
    assert h4 != h1


def test_parquet_path_layout(tmp_path):
    p = parquet_path("proj1", 1, "abc123", root=tmp_path)
    assert p.parent.name == "abc123"
    assert p.parent.parent.name == "1"
    assert p.name == "balanced_960_skip1.parquet"


def test_reconstruct_detection_matches_parse_shape():
    d = reconstruct_detection(0, 10, 20, 50, 60, 0.9, 2)
    assert set(d) == {"bbox", "center", "class_id", "class_name", "confidence",
                      "bbox_width", "bbox_height", "bbox_area", "is_vehicle"}
