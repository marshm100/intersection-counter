"""Detection cache (Attribution v2, Step 1).

Persists raw YOLO detections to Parquet keyed by (camera_id, video_content_hash)
so the expensive detection pass runs ONCE and every downstream experiment —
tracker swaps (ByteTrack <-> OC-SORT), attribution re-runs, parameter sweeps —
consumes the cached detections instead of re-decoding + re-inferring the video.
This is what turns a multi-hour reprocess into a minutes-long "retrack" loop.

Design (see docs/implementation_plan_accuracy_2026-05-27.md section 3):
  - Cache lives at the POST-YOLO, PRE-TRACKER layer, so trackers can be swapped
    against identical detection input.
  - Layout: data/projects/<project_id>/detections/<camera_id>/<hash>/<variant>.parquet
    with a JSON sidecar of provenance metadata.
  - One Parquet row = one detection on one detection-frame.
  - Streamed on read (never load the whole file) to respect the 8 GB target.

The reader reconstructs the exact detection-dict shape that
VehicleDetector._parse_results emits, so the tracker is agnostic to whether
detections came live or from cache.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from backend.config import VEHICLE_CLASSES

# Bump when the hash recipe changes so old caches invalidate cleanly.
HASH_METHOD = "blake2b-128m-v1"
_HASH_PREFIX_BYTES = 128 * 1024 * 1024  # 128 MiB
DEFAULT_VARIANT = "balanced_960_skip1"

# Parquet column order / types. bbox stored as four float32 corners; the rest of
# the detection dict is derived on read (center, width/height/area, class_name).
_SCHEMA = pa.schema([
    ("frame_idx", pa.uint32()),
    ("bbox_x1", pa.float32()),
    ("bbox_y1", pa.float32()),
    ("bbox_x2", pa.float32()),
    ("bbox_y2", pa.float32()),
    ("confidence", pa.float32()),
    ("class_id", pa.uint8()),
])

_ALL_CLASSES = VEHICLE_CLASSES


def compute_video_content_hash(
    video_path: str | Path,
    *,
    file_size_bytes: int | None = None,
    total_frames: int | None = None,
) -> tuple[str, str]:
    """Stable content hash for a video file.

    blake2b over file_size + total_frames + the first 128 MiB of bytes. Hashing
    the whole file would be far too slow on an 11-hour video; the header window
    plus size + frame count is collision-safe at our scale. file_size_bytes /
    total_frames are read from the videos row when available (avoids a stat).

    Returns (hex_digest, method_tag).
    """
    p = Path(video_path)
    if file_size_bytes is None:
        file_size_bytes = p.stat().st_size
    h = hashlib.blake2b(digest_size=32)
    h.update(str(int(file_size_bytes)).encode())
    h.update(b"|")
    h.update(str(int(total_frames or 0)).encode())
    h.update(b"|")
    with open(p, "rb") as f:
        remaining = _HASH_PREFIX_BYTES
        while remaining > 0:
            chunk = f.read(min(1024 * 1024, remaining))
            if not chunk:
                break
            h.update(chunk)
            remaining -= len(chunk)
    return h.hexdigest(), HASH_METHOD


def cache_dir(project_id: str, camera_id: int, content_hash: str, root: Path | None = None) -> Path:
    base = root if root is not None else Path("data/projects") / project_id / "detections"
    return base / str(camera_id) / content_hash


def parquet_path(project_id: str, camera_id: int, content_hash: str,
                 variant: str = DEFAULT_VARIANT, root: Path | None = None) -> Path:
    return cache_dir(project_id, camera_id, content_hash, root) / f"{variant}.parquet"


def _meta_path(pq_path: Path) -> Path:
    return pq_path.with_suffix(".meta.json")


def reconstruct_detection(frame_idx: int, x1: float, y1: float, x2: float, y2: float,
                          confidence: float, class_id: int) -> dict:
    """Rebuild the detection dict shape VehicleDetector._parse_results emits."""
    w = float(x2 - x1)
    h = float(y2 - y1)
    return {
        "bbox": [float(x1), float(y1), float(x2), float(y2)],
        "center": [float((x1 + x2) / 2), float((y1 + y2) / 2)],
        "class_id": int(class_id),
        "class_name": _ALL_CLASSES.get(int(class_id), f"class_{int(class_id)}"),
        "confidence": float(confidence),
        "bbox_width": w,
        "bbox_height": h,
        "bbox_area": w * h,
        "is_vehicle": int(class_id) in VEHICLE_CLASSES,
    }


@dataclass
class DetectionCacheWriter:
    """Accumulates per-frame detections and writes a single Parquet file + sidecar.

    Write-through usage: call add(frame_idx, detections) for each detection frame
    during a normal run, then close(). Rows buffer in memory in column arrays;
    for an 11-hour run (~24 M rows) that is well under 1 GB before flush, but
    flush_rows lets very long runs spill in row-group batches.
    """
    pq_path: Path
    metadata: dict = field(default_factory=dict)
    flush_rows: int = 2_000_000
    _cols: dict = field(default_factory=lambda: {k: [] for k in
                        ("frame_idx", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2",
                         "confidence", "class_id")})
    _writer: pq.ParquetWriter | None = field(default=None, init=False)
    _n: int = field(default=0, init=False)

    def add(self, frame_idx: int, detections: list[dict]) -> None:
        for d in detections:
            x1, y1, x2, y2 = d["bbox"]
            self._cols["frame_idx"].append(int(frame_idx))
            self._cols["bbox_x1"].append(float(x1))
            self._cols["bbox_y1"].append(float(y1))
            self._cols["bbox_x2"].append(float(x2))
            self._cols["bbox_y2"].append(float(y2))
            self._cols["confidence"].append(float(d["confidence"]))
            self._cols["class_id"].append(int(d["class_id"]))
            self._n += 1
        if len(self._cols["frame_idx"]) >= self.flush_rows:
            self._flush()

    def _flush(self) -> None:
        if not self._cols["frame_idx"]:
            return
        table = pa.table(self._cols, schema=_SCHEMA)
        if self._writer is None:
            self.pq_path.parent.mkdir(parents=True, exist_ok=True)
            self._writer = pq.ParquetWriter(str(self.pq_path), _SCHEMA, compression="zstd")
        self._writer.write_table(table)
        for v in self._cols.values():
            v.clear()

    def close(self) -> int:
        """Flush remaining rows, close the writer, write the metadata sidecar.
        Returns the total number of detections written."""
        self._flush()
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        else:
            # No detections at all — still emit an empty file so a cache hit is
            # distinguishable from a miss.
            self.pq_path.parent.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.table(
                {k: [] for k in self._cols}, schema=_SCHEMA), str(self.pq_path),
                compression="zstd")
        meta = {**self.metadata, "method": HASH_METHOD, "total_detections": self._n}
        _meta_path(self.pq_path).write_text(json.dumps(meta, indent=2))
        return self._n


class DetectionCacheReader:
    """Streams cached detections per frame, reconstructing detection dicts.

    iter_frames() yields (frame_idx, [detection_dict, ...]) in ascending frame
    order, materialising one row group at a time so an 11-hour cache never has
    to be fully resident.
    """

    def __init__(self, pq_path: Path):
        self.pq_path = Path(pq_path)
        self._pf = pq.ParquetFile(str(self.pq_path))

    @property
    def total_detections(self) -> int:
        return self._pf.metadata.num_rows

    def iter_frames(self) -> Iterator[tuple[int, list[dict]]]:
        pending_idx: int | None = None
        pending: list[dict] = []
        for batch in self._pf.iter_batches():
            d = batch.to_pydict()
            for k in range(len(d["frame_idx"])):
                fi = int(d["frame_idx"][k])
                det = reconstruct_detection(
                    fi, d["bbox_x1"][k], d["bbox_y1"][k], d["bbox_x2"][k],
                    d["bbox_y2"][k], d["confidence"][k], d["class_id"][k],
                )
                if pending_idx is None:
                    pending_idx = fi
                if fi != pending_idx:
                    yield pending_idx, pending
                    pending_idx, pending = fi, []
                pending.append(det)
        if pending_idx is not None:
            yield pending_idx, pending


def cache_exists(pq_path: Path) -> bool:
    """A cache hit requires both the Parquet file and its metadata sidecar."""
    pq_path = Path(pq_path)
    return pq_path.exists() and _meta_path(pq_path).exists()


def read_metadata(pq_path: Path) -> dict | None:
    mp = _meta_path(Path(pq_path))
    if not mp.exists():
        return None
    return json.loads(mp.read_text())
