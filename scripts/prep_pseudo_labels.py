r"""Pseudo-labelled detector training set (2026-10-01, the next-phase plan step 3; plan
phase 4c). No operator labelling.

The production detections are a per-camera recipe (cam1/2 yolo26l @ 1280, cam3 the
site-trained yolo26s_ft2 @ 640, cam4/5 yolo26s @ 960) and no single stock model wins
everywhere: the large model is unsure at dawn, the 640/960 models lose cam1's small far
vehicles. This builds a training set that carries BOTH strengths:
  * every sampled frame is run through yolo26s_ft2 @ 640 (dawn confidence, the 4-class
    scheme) and yolo26l @ 1280 (small far vehicles), both with the head fix (one-to-many
    head, class-agnostic NMS 0.6);
  * the two box sets are merged (class-agnostic, IoU 0.6, highest confidence kept); a box's
    class is the site-trained model's when one of its boxes overlaps (IoU >= 0.5), else 0
    "vehicle";
  * a box is kept only when a TRACK supports it - a row of the production linked dump with
    IoU >= 0.3 belonging to a track at least 1 s long - or the detector is sure (conf >= 0.6).
    One-frame junk never becomes training truth.
HELD OUT of the training set: all of cam5 (a whole camera), every journey-label clip
(development and held-out, +-60 s), and FM 51 (another project).
Usage: .venv\\Scripts\\python.exe -X utf8 scripts/prep_pseudo_labels.py --out data/finetune_pl1
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_labels import list_clips  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ = "97a7849a"
WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"), (2, "study_1100"),
           (2, "study_1600"), (3, "study_0600"), (4, "study_0700"), (4, "study_1100"),
           (4, "study_1600")]                       # cam5 held out entirely
NAMES = {0: "vehicle", 1: "articulated", 2: "long_single", 3: "medium"}
HEAD = dict(end2end=False, agnostic_nms=True, iou=0.6)
COCO_VEHICLES = [2, 3, 5, 7]
MIN_TRACK_S, TRACK_IOU, SURE_CONF, CLASS_IOU, MERGE_IOU = 1.0, 0.3, 0.6, 0.5, 0.6


def iou(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """a: (n,4) xyxy, b: (m,4) xyxy -> (n,m) IoU."""
    if not len(a) or not len(b):
        return np.zeros((len(a), len(b)))
    x1 = np.maximum(a[:, None, 0], b[None, :, 0]); y1 = np.maximum(a[:, None, 1], b[None, :, 1])
    x2 = np.minimum(a[:, None, 2], b[None, :, 2]); y2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]); bb = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    return inter / np.maximum(aa[:, None] + bb[None, :] - inter, 1e-6)


def merge(ft_b, ft_c, ft_k, l_b, l_c):
    """Union of the two models' boxes, class-agnostic NMS; class from ft2 when it agrees."""
    boxes = np.vstack([ft_b, l_b]) if len(ft_b) or len(l_b) else np.zeros((0, 4))
    confs = np.concatenate([ft_c, l_c])
    order = np.argsort(-confs)
    keep = []
    for i in order:
        if not keep or iou(boxes[[i]], boxes[keep]).max() < MERGE_IOU:
            keep.append(i)
    kb, kc = boxes[keep], confs[keep]
    cls = np.zeros(len(kb), dtype=int)
    if len(ft_b) and len(kb):
        m = iou(kb, ft_b)
        j = m.argmax(axis=1)
        ok = m.max(axis=1) >= CLASS_IOU
        cls[ok] = ft_k[j[ok]]
    return kb, kc, cls


def held_out_spans() -> dict:
    spans: dict = {}
    for c in list_clips(PROJ):
        pad = 60 * c["fps"]
        spans.setdefault(c["camera_id"], []).append((c["start_frame"] - pad, c["end_frame"] + pad))
    return spans


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--per-window", type=int, default=250)
    ap.add_argument("--dawn-extra", type=int, default=250,
                    help="extra frames from cam3's first two hours (dawn)")
    ap.add_argument("--val-frac", type=float, default=0.12)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args()
    from ultralytics import YOLO
    ft = YOLO("yolo26s_ft2.pt")
    lg = YOLO("yolo26l.pt")
    out = Path(args.out)
    for sub in ("images/train", "images/val", "labels/train", "labels/val"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    spans = held_out_spans()
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    stats = {"frames": 0, "boxes": 0, "dropped_unsupported": 0, "train": 0, "val": 0}
    for cam, window in WINDOWS:
        path, chash, fps = con.execute(
            "SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
        base = tracks_dir(parquet_path(PROJ, cam, chash, window))
        linked = sorted(base.parent.glob(f"lk*_{window}.tracks"),
                        key=lambda p: p.stat().st_mtime)
        rows = np.asarray(load_dump(linked[-1] if linked else base))
        meta = json.loads(parquet_path(PROJ, cam, chash, window).with_suffix(".meta.json").read_text())
        f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
        # track lengths (s) and the rows of tracks >= MIN_TRACK_S, by frame
        order = np.lexsort((rows[:, 1], rows[:, 0]))
        rs = rows[order]
        st = np.unique(rs[:, 0], return_index=True)[1]
        en = np.append(st[1:], len(rs))
        length_s = {int(rs[a, 0]): (rs[b - 1, 1] - rs[a, 1]) / fps for a, b in zip(st, en)}
        good = np.array([length_s[int(t)] >= MIN_TRACK_S for t in rows[:, 0]])
        byf: dict = {}
        for r in rows[good]:
            byf.setdefault(int(r[1]), []).append(r)
        bad = spans.get(cam, [])
        n = args.per_window + (args.dawn_extra if cam == 3 else 0)
        cand = [f for f in range(int(f0), int(f1), int(fps * 2))
                if not any(a <= f <= b for a, b in bad)]
        if cam == 3:      # weight dawn: half the frames from the first two hours
            dawn = [f for f in cand if f < f0 + 2 * 3600 * fps]
            rest = [f for f in cand if f >= f0 + 2 * 3600 * fps]
            frames = rng.sample(dawn, min(len(dawn), n // 2)) + rng.sample(rest, min(len(rest), n - n // 2))
        else:
            frames = rng.sample(cand, min(len(cand), n))
        cap = cv2.VideoCapture(path)
        H = cap.get(cv2.CAP_PROP_FRAME_HEIGHT); W = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        wrote = 0
        for fidx in sorted(frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(fidx))
            ok, img = cap.read()
            if not ok:
                continue
            r1 = ft(img, conf=0.25, imgsz=640, classes=[0, 1, 2, 3], verbose=False, **HEAD)[0]
            r2 = lg(img, conf=0.25, imgsz=1280, classes=COCO_VEHICLES, verbose=False, **HEAD)[0]
            fb = r1.boxes.xyxy.cpu().numpy(); fc = r1.boxes.conf.cpu().numpy()
            fk = r1.boxes.cls.cpu().numpy().astype(int)
            lb = r2.boxes.xyxy.cpu().numpy(); lc = r2.boxes.conf.cpu().numpy()
            kb, kc, kk = merge(fb, fc, fk, lb, lc)
            tr = byf.get(int(fidx), [])
            tb = (np.array([[r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2]
                            for r in tr]) if tr else np.zeros((0, 4)))
            sup = iou(kb, tb).max(axis=1) >= TRACK_IOU if len(tb) else np.zeros(len(kb), bool)
            keep = sup | (kc >= SURE_CONF)
            stats["dropped_unsupported"] += int((~keep).sum())
            split = "val" if rng.random() < args.val_frac else "train"
            stem = f"{PROJ[:8]}_c{cam}_{window}_{int(fidx)}"
            cv2.imwrite(str(out / f"images/{split}/{stem}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
            lines = [f"{k} {(b[0] + b[2]) / 2 / W:.6f} {(b[1] + b[3]) / 2 / H:.6f} "
                     f"{(b[2] - b[0]) / W:.6f} {(b[3] - b[1]) / H:.6f}"
                     for b, k in zip(kb[keep], kk[keep]) if b[2] > b[0] and b[3] > b[1]]
            (out / f"labels/{split}/{stem}.txt").write_text("\n".join(lines) + ("\n" if lines else ""))
            stats["frames"] += 1; stats["boxes"] += len(lines); stats[split] += 1
            wrote += 1
        cap.release()
        print(f"[ok] cam{cam} {window}: {wrote} frames", flush=True)
    (out / "dataset.yaml").write_text(
        f"path: {out.resolve().as_posix()}\ntrain: images/train\nval: images/val\n"
        "names:\n" + "".join(f"  {k}: {v}\n" for k, v in sorted(NAMES.items())))
    (out / "stats.json").write_text(json.dumps(stats, indent=1))
    print("done:", stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
