"""Label-prep for the §3-D detector fine-tune (plan_detector_finetune_2026-07-16).

Builds a YOLO-format dataset directory from the detection CACHES (no
re-inference): stratified frames per (project, camera, variant) spec —
truck-heavy frames prioritized 50/50 with uniform-in-time — each with its
cached detections prefilled as class 0 `vehicle` proposal boxes. The
operator's 2–4 labeling hours become accept/fix + promoting semis to
class 1 `articulated`; everything prefills 0 so the prefill cannot bias
the articulated labels.

Usage:
  py scripts/prep_finetune_labels.py --out data/finetune_v1 ^
      --spec 97a7849a:2:study_0700 --spec 97a7849a:2:study_1600 ^
      --per-spec 60
Then label with any YOLO-format tool and train with
scripts/finetune_detector.py.
"""
from __future__ import annotations

import argparse
import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import (  # noqa: E402
    compute_video_content_hash, parquet_path,
)

TRUCKISH = (5, 7)          # bus/truck class ids — the articulated candidates
# Class 3 "medium" added for round v2 (plan_articulated_native VERDICT →
# labeling route): buses + single-unit trucks that are NOT ~2+ car lengths
# (bobtail, delivery/service trucks) — the Miovision Mediums bucket the v1
# taxonomy folded into class 0. v1 datasets predate it (their yaml lists
# 0–2; retraining across both sets must handle that — see the round doc).
NAMES = {0: "vehicle", 1: "articulated", 2: "long_single", 3: "medium"}


def _video_row(project: str, cam: int):
    conn = sqlite3.connect(f"data/projects/{project}/project.db")
    v = conn.execute(
        "SELECT path, file_size_bytes, total_frames, fps FROM videos "
        "WHERE camera_id=? ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
    conn.close()
    if v is None:
        raise SystemExit(f"{project}:{cam}: no video row")
    return v


def sample_frames(df: pd.DataFrame, n: int, seed: int,
                  mode: str = "mixed", min_gap: int = 250) -> list[int]:
    """mixed: 50% truck-heavy frames (by truckish-box count), 50%
    uniform-in-time. semis: rank frames by the WIDEST truckish box (long
    vehicles are wide boxes) and take the top n with a minimum frame gap so
    one slow semi does not fill the whole quota with near-duplicates."""
    rng = random.Random(seed)
    if mode == "semis":
        tr = df[df.class_id.isin(TRUCKISH)].copy()
        if tr.empty:
            return []
        tr["w"] = tr.bbox_x2 - tr.bbox_x1
        widest = tr.groupby("frame_idx")["w"].max().sort_values(ascending=False)
        picked: list[int] = []
        for f in widest.index:
            if all(abs(int(f) - q) >= min_gap for q in picked):
                picked.append(int(f))
            if len(picked) >= n:
                break
        rng.shuffle(picked)
        return picked
    per_frame = df.groupby("frame_idx")["class_id"].apply(
        lambda s: int((s.isin(TRUCKISH)).sum()))
    frames = sorted(per_frame.index)
    if not frames:
        return []
    heavy = [f for f, c in per_frame.sort_values(ascending=False).items()
             if c > 0][: max(1, n // 2)]
    rest = max(0, n - len(heavy))
    uniform = ([frames[int(i * (len(frames) - 1) / max(rest - 1, 1))]
                for i in range(rest)] if rest else [])
    picked = sorted(set(heavy) | set(uniform))
    rng.shuffle(picked)
    return picked[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--spec", action="append", required=True,
                    help="project:camera:variant (repeatable)")
    ap.add_argument("--per-spec", type=int, default=60)
    ap.add_argument("--val-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--mode", choices=("mixed", "semis"), default="mixed",
                    help="semis: top frames by widest truckish box (the "
                         "articulated-mining pass)")
    ap.add_argument("--exclude-dataset", default=None,
                    help="skip frames whose image stem already exists there")
    args = ap.parse_args()
    seen_stems = set()
    if args.exclude_dataset:
        for q in Path(args.exclude_dataset).glob("images/*/*.jpg"):
            seen_stems.add(q.stem)

    out = Path(args.out)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out / sub).mkdir(parents=True, exist_ok=True)

    rng = random.Random(args.seed)
    n_img = defaultdict(int)
    for spec in args.spec:
        project, cam_s, variant = spec.split(":")
        cam = int(cam_s)
        v = _video_row(project, cam)
        chash, _ = compute_video_content_hash(
            v[0], file_size_bytes=v[1], total_frames=v[2])
        pq = parquet_path(project, cam, chash, variant)
        if not Path(pq).exists():
            print(f"[skip] {spec}: no detection cache at {pq}")
            continue
        df = pd.read_parquet(pq)
        frames = sample_frames(df, args.per_spec, args.seed, mode=args.mode)
        cap = cv2.VideoCapture(v[0])
        W = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        H = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        wrote = 0
        for fidx in frames:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(fidx))
            ok, img = cap.read()
            if not ok:
                continue
            split = "val" if rng.random() < args.val_frac else "train"
            stem = f"{project[:8]}_c{cam}_{variant}_{int(fidx)}"
            if stem in seen_stems:
                continue
            cv2.imwrite(str(out / f"images/{split}/{stem}.jpg"), img,
                        [cv2.IMWRITE_JPEG_QUALITY, 92])
            rows = df[df.frame_idx == fidx]
            lines = []
            for _, r in rows.iterrows():
                cx = (r.bbox_x1 + r.bbox_x2) / 2.0 / W
                cy = (r.bbox_y1 + r.bbox_y2) / 2.0 / H
                bw = (r.bbox_x2 - r.bbox_x1) / W
                bh = (r.bbox_y2 - r.bbox_y1) / H
                if bw <= 0 or bh <= 0:
                    continue
                # prefill EVERYTHING as class 0 — the human promotes semis
                lines.append(f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f}")
            (out / f"labels/{split}/{stem}.txt").write_text(
                "\n".join(lines) + ("\n" if lines else ""))
            n_img[split] += 1
            wrote += 1
        cap.release()
        print(f"[ok] {spec}: {wrote} frames", flush=True)

    (out / "dataset.yaml").write_text(
        f"path: {out.resolve().as_posix()}\n"
        "train: images/train\nval: images/val\n"
        "names:\n" + "".join(f"  {k}: {v}\n" for k, v in sorted(NAMES.items())))
    (out / "README.md").write_text(
        "# Fine-tune labeling set\n\n"
        "Proposal boxes are prefilled as class 0 (vehicle) from the detection\n"
        "cache. Review each image in any YOLO-format labeling tool:\n"
        "fix/delete bad boxes, add missed vehicles, and PROMOTE articulated\n"
        "trucks (tractor+trailer) to class 1. Box trucks / buses stay class 0.\n"
        "Then train:  py scripts/finetune_detector.py --data "
        f"{(out / 'dataset.yaml').as_posix()}\n")
    print(f"dataset at {out}  (train {n_img['train']}, val {n_img['val']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
