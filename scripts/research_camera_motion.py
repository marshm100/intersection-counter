"""Does the camera itself move? (2026-09-29, cam2 diagnosis)

For each camera, samples N moments evenly through a window and measures the
global image shift (phase correlation on the grey frame, Hanning-windowed,
which registers the static background) between frame f and f+1 (per-frame
jitter) and between f and f + 1 s. A fixed camera shows ~0 px. Reports p50 /
p90 / p99 / max of the shift magnitude and the share of samples over 1 px.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_camera_motion.py [VARIANT] [N]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import parquet_path  # noqa: E402

PROJ = "97a7849a"


def grey(cap, f):
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
    ok, fr = cap.read()
    if not ok:
        return None
    return cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY).astype(np.float32)


def main() -> int:
    variant = sys.argv[1] if len(sys.argv) > 1 else "study_0700"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 150
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    for cam, path, chash, fps in con.execute("SELECT camera_id, path, content_hash, fps FROM videos ORDER BY camera_id"):
        v = variant if cam != 3 else "study_0600"
        pq = parquet_path(PROJ, cam, chash, v)
        meta = json.load(open(pq.with_suffix(".meta.json")))
        f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
        cap = cv2.VideoCapture(path)
        win = None
        one, sec = [], []
        for f in np.linspace(f0 + fps, f1 - 2 * fps, n).astype(int):
            a = grey(cap, f)
            b = grey(cap, f + 1)
            c = grey(cap, f + int(round(fps)))
            if a is None or b is None or c is None:
                continue
            if win is None:
                win = cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F)
            (dx, dy), _ = cv2.phaseCorrelate(a, b, win)
            one.append(float(np.hypot(dx, dy)))
            (dx, dy), _ = cv2.phaseCorrelate(a, c, win)
            sec.append(float(np.hypot(dx, dy)))
        cap.release()
        one, sec = np.array(one), np.array(sec)

        def s(x):
            return (f"p50 {np.percentile(x, 50):.2f} p90 {np.percentile(x, 90):.2f} p99 {np.percentile(x, 99):.2f} "
                    f"max {x.max():.2f} px, >1px {100 * (x > 1).mean():.0f}%")
        print(f"cam{cam} ({fps:g} fps, {len(one)} samples)  frame-to-frame: {s(one)}  |  over 1 s: {s(sec)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
