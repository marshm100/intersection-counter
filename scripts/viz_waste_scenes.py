"""Waste-scene renderer: manifest -> animated GIFs for the operator's
diagnosis reel (find_waste_examples.py picks the scenes).

Per scene: 3-6 s clip, every 3rd frame, live colored box + trail per
arm tid, white dashed ghost trail for production tids, drawn gates
magenta, ASCII caption strip. Pillow assembles the GIF.

Usage:
  py -X utf8 scripts/viz_waste_scenes.py [--only N]
Writes screenshots/waste_scene_<n>.gif
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import cv2
import numpy as np
from PIL import Image

from backend.database import leg_geometry_for_camera
from backend.services.detection_cache import parquet_path
from backend.services.pass2_replay import load_dump, tracks_dir

PROJ, CAM, FPS = "97a7849a", 2, 25.0
STEP = 4                     # every 4th frame -> 6.25 fps playback
COLORS = [(80, 220, 80), (60, 60, 230), (0, 165, 255), (255, 200, 0)]
CNAMES = ["GREEN", "RED", "ORANGE", "CYAN"]


def rows_by_tid(variant, chash):
    td = tracks_dir(parquet_path(PROJ, CAM, chash, variant))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.load(Path(td) / "rows.npy", mmap_mode="r")[:n]
    return rows


def tid_rows(rows, tid):
    sel = rows[rows[:, 0] == float(tid)]
    return sel[np.argsort(sel[:, 1])]


def render_span(arm_rows_list):
    """Clamp to 3-6 s centered on the primary track's busiest motion."""
    pr = arm_rows_list[0]
    f0, f1 = pr[0, 1], pr[-1, 1]
    if f1 - f0 <= 6 * FPS:
        lo, hi = f0, f1
    else:
        # sliding 5 s window of max displacement
        best, best_d = f0, -1.0
        fs = pr[:, 1]
        for i in range(len(pr)):
            j = np.searchsorted(fs, fs[i] + 5 * FPS)
            if j >= len(pr):
                break
            d = np.hypot(pr[j, 2] - pr[i, 2], pr[j, 3] - pr[i, 3])
            if d > best_d:
                best_d, best = d, fs[i]
        lo, hi = best, best + 5 * FPS
    if hi - lo < 3 * FPS:
        pad = (3 * FPS - (hi - lo)) / 2
        lo, hi = lo - pad, hi + pad
    return int(lo - 12), int(hi + 12)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", type=int, default=None)
    args = ap.parse_args()

    man = json.loads(Path("runs/v2_week1/waste_scenes_0700.json").read_text())
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash = con.execute(
        "SELECT path, content_hash FROM videos WHERE camera_id=?",
        (CAM,)).fetchone()
    con.close()
    gates = [g["gate"] for g in
             leg_geometry_for_camera(PROJ, CAM).values() if g.get("gate")]
    arm_rows = rows_by_tid.__wrapped__ if False else rows_by_tid(
        "idc_study_0700", chash)
    prod_rows = rows_by_tid("study_0700", chash)

    total = 0
    for n, sc in enumerate(man["scenes"], 1):
        if args.only and n != args.only:
            continue
        arls = [tid_rows(arm_rows, t) for t in sc["arm_tids"]]
        prls = [tid_rows(prod_rows, t) for t in sc.get("prod_tids", [])]
        lo, hi = render_span(arls)
        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, lo))
        frames = []
        for f in range(max(0, lo), hi + 1):
            ok, img = cap.read()
            if not ok:
                break
            if (f - lo) % STEP:
                continue
            for g1, g2 in gates:
                cv2.line(img, (int(g1[0]), int(g1[1])),
                         (int(g2[0]), int(g2[1])), (255, 0, 255), 1,
                         cv2.LINE_AA)
            for pr in prls:                       # production ghost
                past = pr[pr[:, 1] <= f][-60:]
                for a, b in zip(past[::4], past[4::4]):
                    cv2.line(img, (int(a[2]), int(a[3])),
                             (int(b[2]), int(b[3])), (255, 255, 255), 1,
                             cv2.LINE_AA)
            for k, ar in enumerate(arls):
                col = COLORS[k % 4]
                past = ar[ar[:, 1] <= f]
                if len(past) > 1:
                    trail = past[-90:]
                    cv2.polylines(img, [trail[:, 2:4].astype(np.int32)],
                                  False, col, 2, cv2.LINE_AA)
                live = past[-1] if len(past) and f - past[-1, 1] <= 3 else None
                if live is not None:
                    cx, cy, bw, bh = live[2], live[3], live[4], live[5]
                    cv2.rectangle(img, (int(cx - bw / 2), int(cy - bh / 2)),
                                  (int(cx + bw / 2), int(cy + bh / 2)),
                                  col, 2)
            strip = np.zeros((44, img.shape[1], 3), np.uint8)
            head = f"SCENE {n}  [{sc['klass']}]  {sc['cell']}"
            if sc["event_ids"]:
                head += "  events " + ",".join(
                    f"#{e}" for e in sc["event_ids"])
            legend = "  ".join(
                f"{CNAMES[k % 4]}=track {t}"
                for k, t in enumerate(sc["arm_tids"]))
            if sc.get("prod_tids"):
                legend += "  WHITE=production track"
            cv2.putText(strip, head, (8, 17), cv2.FONT_HERSHEY_SIMPLEX,
                        0.45, (230, 230, 230), 1, cv2.LINE_AA)
            cv2.putText(strip, legend, (8, 36), cv2.FONT_HERSHEY_SIMPLEX,
                        0.42, (180, 180, 180), 1, cv2.LINE_AA)
            frames.append(np.vstack([img, strip]))
        cap.release()
        if not frames:
            print(f"scene {n}: NO FRAMES ({lo}-{hi})")
            continue
        w = 400
        pil = []
        for fr in frames[:36]:
            h = int(fr.shape[0] * w / fr.shape[1])
            fr = cv2.resize(fr, (w, h), interpolation=cv2.INTER_AREA)
            pil.append(Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
                       .quantize(colors=64, dither=Image.Dither.NONE))
        out = Path(f"screenshots/waste_scene_{n}.gif")
        pil[0].save(out, save_all=True, append_images=pil[1:],
                    duration=160, loop=0, optimize=True)
        kb = out.stat().st_size // 1024
        total += kb
        print(f"scene {n}: {len(frames)} frames, {kb} KB -> {out}")
    print(f"total {total} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
