"""Detection-gap reel: the SB-right deficit corridor with EVERYTHING the
system has overlaid — every arm track boxed, every raw detection dotted.
A moving vehicle with NO marking = invisible to the detector (the
operator's 50-70% claim); a yellow-dot-only vehicle = detected but never
tracked (birth failure). Operator instrument ruling applied: high-
contrast colors only, black-outlined; nothing that reads as concrete.

Picks the two 15 s windows of the 8:00-8:15 bin (Mio 69 SB-right, we
counted 33) with the most uncovered detections in the SB-right zone.

Usage:  py -X utf8 scripts/viz_detection_gap.py
Writes screenshots/detgap_clip_{1,2}.gif
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import cv2
import numpy as np
import pandas as pd
from PIL import Image

from backend.services.detection_cache import parquet_path
from backend.services.pass2_replay import load_dump, tracks_dir
from detector_zone_recall import load_curves, in_zone

PROJ, CAM, FPS = "97a7849a", 2, 25.0
BIN_LO, BIN_HI = 720000, 742500        # 8:00-8:15 video frames
STEP, W = 4, 400
BLUE, YELLOW, BLACK = (255, 70, 20), (0, 215, 255), (0, 0, 0)


def main() -> int:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash = con.execute(
        "SELECT path, content_hash FROM videos WHERE camera_id=?",
        (CAM,)).fetchone()
    con.close()

    td = tracks_dir(parquet_path(PROJ, CAM, chash, "idc_study_0700"))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.load(Path(td) / "rows.npy", mmap_mode="r")[:n]
    sel = (rows[:, 1] >= BIN_LO) & (rows[:, 1] < BIN_HI)
    trk = np.asarray(rows[sel])

    df = pd.read_parquet(parquet_path(PROJ, CAM, chash, "idc_study_0700"))
    df = df[(df.frame_idx >= BIN_LO) & (df.frame_idx < BIN_HI)
            & (df.confidence >= 0.25)].copy()
    df["cx"] = (df.bbox_x1 + df.bbox_x2) / 2
    df["cy"] = (df.bbox_y1 + df.bbox_y2) / 2

    curves = load_curves(CAM, "channel", [72])          # SB-right zone
    mask, _ = in_zone(pd.DataFrame(
        {"bbox_x1": df.bbox_x1, "bbox_x2": df.bbox_x2,
         "bbox_y1": df.bbox_y1, "bbox_y2": df.bbox_y2,
         "confidence": df.confidence}), curves, 40.0)
    zdf = df[mask]

    # uncovered = zone det with no track point within 40 px same frame
    trk_by_f = {}
    for r in trk:
        trk_by_f.setdefault(int(r[1]), []).append((r[2], r[3]))
    unc = []
    for f, x, y in zip(zdf.frame_idx.astype(int), zdf.cx, zdf.cy):
        pts = trk_by_f.get(f, [])
        if not pts or min(np.hypot(px - x, py - y)
                          for px, py in pts) > 40:
            unc.append(f)
    unc = np.array(unc)
    win = int(15 * FPS)
    best = []
    for lo in range(BIN_LO, BIN_HI - win, win // 2):
        c = int(((unc >= lo) & (unc < lo + win)).sum())
        best.append((c, lo))
    best.sort(reverse=True)
    picks = [best[0][1]]
    for c, lo in best[1:]:
        if all(abs(lo - p) >= win for p in picks):
            picks.append(lo)
            break
    print("clip windows:", [(p, f"{best_c}uncov") for (best_c, p) in
                            [(c, l) for c, l in best if l in picks]])

    det_by_f = {}
    for f, x, y in zip(df.frame_idx.astype(int), df.cx, df.cy):
        det_by_f.setdefault(f, []).append((x, y))

    for ci, lo in enumerate(picks, 1):
        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, lo)
        frames = []
        for f in range(lo, lo + win):
            ok, img = cap.read()
            if not ok:
                break
            if (f - lo) % STEP:
                continue
            for cur in curves:                     # the SB-right corridor
                cv2.polylines(img, [cur.astype(np.int32)], False,
                              (200, 0, 200), 1, cv2.LINE_AA)
            live = trk[(trk[:, 1] <= f) & (trk[:, 1] > f - 3)]
            for r in live:
                cx, cy, bw, bh = r[2], r[3], r[4], r[5]
                p1 = (int(cx - bw / 2), int(cy - bh / 2))
                p2 = (int(cx + bw / 2), int(cy + bh / 2))
                cv2.rectangle(img, p1, p2, BLACK, 3)
                cv2.rectangle(img, p1, p2, BLUE, 1)
            pts = det_by_f.get(f, [])
            lp = {(r[2], r[3]) for r in live}
            for x, y in pts:
                if lp and min(np.hypot(a - x, b - y) for a, b in lp) <= 40:
                    continue
                cv2.circle(img, (int(x), int(y)), 5, BLACK, -1)
                cv2.circle(img, (int(x), int(y)), 3, YELLOW, -1)
            strip = np.zeros((44, img.shape[1], 3), np.uint8)
            cv2.putText(strip, f"CLIP {ci}  8:00-8:15 bin  SB-right: "
                        f"Miovision 69, we counted 33",
                        (8, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (230, 230, 230), 1, cv2.LINE_AA)
            cv2.putText(strip, "BLUE box = tracked   YELLOW dot = detected,"
                        " never tracked   nothing = invisible to us",
                        (8, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                        (180, 180, 180), 1, cv2.LINE_AA)
            frames.append(np.vstack([img, strip]))
        cap.release()
        pil = []
        for fr in frames:
            h = int(fr.shape[0] * W / fr.shape[1])
            fr = cv2.resize(fr, (W, h), interpolation=cv2.INTER_AREA)
            pil.append(Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
                       .quantize(colors=64, dither=Image.Dither.NONE))
        out = Path(f"screenshots/detgap_clip_{ci}.gif")
        pil[0].save(out, save_all=True, append_images=pil[1:],
                    duration=160, loop=0, optimize=True)
        print(f"clip {ci}: {len(pil)} frames, "
              f"{out.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
