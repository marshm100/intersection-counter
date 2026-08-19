"""Dump-track slices for the review overlay (REVIEW-UI, 2026-08-19).

Serves per-frame tracker rows (frame, cx, cy, bw, bh) for a camera +
time range so the reviewer can draw live bounding boxes over the
video. The dump is a 100-400 MB frame-ordered rows.npy per variant;
this module mmaps it ONCE per (project, camera, variant) into a
module-level registry (the auto_calibrator_v2 pattern) and answers
range queries via searchsorted — no per-request full reads, and the
frame-order verification runs once per cache fill.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import numpy as np

from backend.services.pass2_replay import tracks_dir
from backend.services.two_pass import _camera_parquet

_CACHE: dict[tuple, dict] = {}
_LOCK = threading.Lock()
_MAX_ROWS_PER_REQUEST = 4000


def _resolve_variant(project_id: str, camera_id: int, variant: str | None,
                     t_lo: float | None = None,
                     t_hi: float | None = None) -> str | None:
    """Explicit variant, else the on-disk dump whose FRAME RANGE contains
    the requested time window (a camera has one dump per study window —
    newest-sidecar picking served the wrong hour), else the newest."""
    if variant:
        return variant
    det = Path(f"data/projects/{project_id}/detections/{camera_id}")
    dirs = sorted(det.glob("*/*.tracks"), key=lambda p: p.stat().st_mtime,
                  reverse=True)
    if not dirs:
        return None
    if t_lo is not None:
        mid = (float(t_lo) + float(t_hi or t_lo)) / 2.0
        matches = []
        for d in dirs:
            meta_p = d / "meta.json"
            if not meta_p.exists():
                continue
            try:
                meta = json.loads(meta_p.read_text())
                f_lo, f_hi = meta.get("frames") or (None, None)
                fps = float(meta.get("fps") or 25.0)
                if f_lo is not None and f_lo / fps <= mid < f_hi / fps:
                    matches.append(d.name.replace(".tracks", ""))
            except Exception:
                continue
        if matches:
            # base variants (study_1100) over experimental prefixes
            # (oc_/ft2_/v2c_...): the production dump has the shortest name
            return sorted(matches, key=len)[0]
    return dirs[0].name.replace(".tracks", "")


def _load(project_id: str, camera_id: int, variant: str):
    key = (project_id, camera_id, variant)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None:
        return hit
    tdir = Path(tracks_dir(_camera_parquet(project_id, camera_id, variant)))
    rows_p = tdir / "rows.npy"
    count_p = tdir / "count.txt"
    meta_p = tdir / "meta.json"
    if not rows_p.exists():
        return None
    n = int(count_p.read_text()) if count_p.exists() else None
    rows = np.load(rows_p, mmap_mode="r")
    if n is not None:
        rows = rows[:n]
    frames = np.asarray(rows[:, 1])
    ordered = bool((np.diff(frames) >= 0).all()) if len(frames) > 1 else True
    if not ordered:
        rows = np.asarray(rows)[np.argsort(frames, kind="stable")]
        frames = rows[:, 1]
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    entry = {"rows": rows, "frames": frames,
             "fps": float(meta.get("fps") or 25.0), "variant": variant}
    with _LOCK:
        _CACHE[key] = entry
    return entry


def tracks_in_range(project_id: str, camera_id: int, t_lo: float,
                    t_hi: float, variant: str | None = None) -> dict:
    """{'variant', 'fps', 'tracks': [{'tid', 'pts': [[t,cx,cy,bw,bh],..]}]}
    for dump rows with t_lo <= frame/fps < t_hi. Thinned to the request
    cap; pts are time-seconds so the frontend needs no fps math."""
    v = _resolve_variant(project_id, camera_id, variant, t_lo, t_hi)
    if v is None:
        return {"variant": None, "fps": None, "tracks": []}
    entry = _load(project_id, camera_id, v)
    if entry is None:
        return {"variant": v, "fps": None, "tracks": []}
    fps = entry["fps"]
    lo = np.searchsorted(entry["frames"], t_lo * fps, side="left")
    hi = np.searchsorted(entry["frames"], t_hi * fps, side="right")
    sl = np.asarray(entry["rows"][lo:hi])
    stride = max(1, int(np.ceil(len(sl) / _MAX_ROWS_PER_REQUEST)))
    sl = sl[::stride]
    by_tid: dict[int, list] = {}
    for r in sl:
        by_tid.setdefault(int(r[0]), []).append(
            [round(float(r[1]) / fps, 3), round(float(r[2]), 1),
             round(float(r[3]), 1), round(float(r[4]), 1),
             round(float(r[5]), 1)])
    return {"variant": v, "fps": fps,
            "tracks": [{"tid": t, "pts": p} for t, p in by_tid.items()
                       if len(p) >= 2]}
