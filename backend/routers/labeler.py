"""Labeling screen backend for the fine-tune dataset (§3-D,
plan_detector_finetune_2026-07-16).

Serves a YOLO-format dataset directory under data/ (built by
scripts/prep_finetune_labels.py) to the in-app labeling page
(/static/labeler.html) and persists edited labels back to the txt files —
no external labeling tool to install. The review ordering is truck-first
(widest prefilled box first) so articulated candidates surface early;
`reviewed.json` in the dataset dir tracks progress so sessions resume.
"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter()

_DATA_ROOT = (Path(__file__).resolve().parent.parent.parent / "data").resolve()
_SPLITS = ("train", "val")


def _dataset_dir(ds: str) -> Path:
    # name-only lookup under data/ — no path traversal by construction
    p = (_DATA_ROOT / Path(ds).name).resolve()
    if not str(p).startswith(str(_DATA_ROOT)) or not (p / "images").exists():
        raise HTTPException(status_code=404, detail="dataset not found")
    return p


def _read_boxes(txt: Path) -> list[list[float]]:
    if not txt.exists():
        return []
    out = []
    for line in txt.read_text().splitlines():
        parts = line.split()
        if len(parts) == 5:
            out.append([int(float(parts[0]))] + [float(x) for x in parts[1:]])
    return out


def _reviewed_path(root: Path) -> Path:
    return root / "reviewed.json"


def _load_reviewed(root: Path) -> set:
    p = _reviewed_path(root)
    try:
        return set(json.loads(p.read_text())) if p.exists() else set()
    except (ValueError, OSError):
        return set()


@router.get("/labeler/{ds}/manifest")
def labeler_manifest(ds: str):
    root = _dataset_dir(ds)
    reviewed = _load_reviewed(root)
    items = []
    for split in _SPLITS:
        for img in sorted((root / "images" / split).glob("*.jpg")):
            boxes = _read_boxes(root / "labels" / split / f"{img.stem}.txt")
            items.append({
                "split": split, "name": img.name,
                "boxes": boxes,
                "reviewed": f"{split}/{img.name}" in reviewed,
                # truck-first ordering proxy: widest prefilled box
                "_w": max((b[3] for b in boxes), default=0.0),
            })
    items.sort(key=lambda it: (-it["_w"]))
    for it in items:
        it.pop("_w")
    return {"dataset": ds, "items": items,
            "reviewed_count": len(reviewed), "total": len(items)}


@router.get("/labeler/{ds}/image/{split}/{name}")
def labeler_image(ds: str, split: str, name: str):
    root = _dataset_dir(ds)
    if split not in _SPLITS:
        raise HTTPException(status_code=404, detail="bad split")
    p = root / "images" / split / Path(name).name
    if not p.exists():
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(str(p), media_type="image/jpeg")


class LabelPayload(BaseModel):
    split: str
    name: str
    boxes: list[list[float]]
    reviewed: bool = True


@router.post("/labeler/{ds}/labels")
def labeler_save(ds: str, payload: LabelPayload):
    root = _dataset_dir(ds)
    if payload.split not in _SPLITS:
        raise HTTPException(status_code=404, detail="bad split")
    stem = Path(payload.name).stem
    txt = root / "labels" / payload.split / f"{stem}.txt"
    if not txt.parent.exists():
        raise HTTPException(status_code=404, detail="dataset labels missing")
    lines = []
    for b in payload.boxes:
        if len(b) != 5:
            raise HTTPException(status_code=422, detail="bad box")
        cls = int(b[0])
        if cls not in (0, 1):
            raise HTTPException(status_code=422, detail="class must be 0 or 1")
        cx, cy, w, h = (max(0.0, min(1.0, float(v))) for v in b[1:])
        if w <= 0 or h <= 0:
            continue
        lines.append(f"{cls} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}")
    txt.write_text("\n".join(lines) + ("\n" if lines else ""))
    reviewed = _load_reviewed(root)
    key = f"{payload.split}/{Path(payload.name).name}"
    if payload.reviewed:
        reviewed.add(key)
    else:
        reviewed.discard(key)
    _reviewed_path(root).write_text(json.dumps(sorted(reviewed)))
    return {"saved": key, "boxes": len(lines),
            "reviewed_count": len(reviewed)}
