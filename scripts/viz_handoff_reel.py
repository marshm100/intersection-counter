"""Hand-off reel for the operator's ruling (2026-09-12, tracker engineering).

The yardstick (a greedy linker over the raw detections) says one vehicle's
chain continues while the tracker's id changes at a frame. Two readings:
  - the chain is right (one car the whole time) and the tracker's id
    really changed on that car -> a TRACKER break to engineer against;
  - the chain itself jumped to another car -> a YARDSTICK error.
Only the video can tell. Each clip shows, on the full frame, never cropped:
  WHITE ring + box  = the vehicle as the yardstick follows it (every frame)
  ORANGE box + path = the tracker's id on it BEFORE the hand-off
  CYAN box + path   = the tracker's id on it AFTER the hand-off
                      (drawn from its own start, so a takeover shows where
                      that id was before it reached this car)
The hand-off frame is held for one second under a HAND-OFF banner.

Usage: .venv/Scripts/python.exe -X utf8 scripts/viz_handoff_reel.py PROJ CAM VARIANT PREFIX [N_PER_KIND]
Writes screenshots/{PREFIX}_{n}.webm and screenshots/{PREFIX}_index.json
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

ORANGE, CYAN, BLACK, WHITE = (0, 140, 255), (255, 220, 0), (0, 0, 0), (255, 255, 255)
W_OUT = int(os.environ.get("REEL_WIDTH", "720"))
PAD_S = 2.5
HOLD_S = 1.0


def iou(a, b):
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    if inter <= 0:
        return 0.0
    return inter / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter)


def tbox(r):
    return (r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2)


def main() -> int:
    proj, cam, variant, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    n_per = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    base = "l1_study_" if "l1_study_" in variant else "study_"
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base}{variant.split('study_')[-1]}.json").read_text())
    rows = np.asarray(load_dump(tracks_dir(parquet_path(proj, cam, chash, variant))))
    rows_f = rows[np.argsort(rows[:, 1], kind="stable")]
    uf, s_ = np.unique(rows_f[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows_f))
    fidx = dict(zip(uf.astype(int), zip(s_, e_)))
    rows_t = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    ut, st_ = np.unique(rows_t[:, 0], return_index=True); en_ = np.append(st_[1:], len(rows_t))
    seg = {int(t): rows_t[a:b] for t, a, b in zip(ut, st_, en_)}

    # stay a minute clear of the window's ends (tracker warm-up at the start,
    # the cut at the end)
    w_lo, w_hi = float(rows[:, 1].min()) + 60 * fps, float(rows[:, 1].max()) - 60 * fps
    found = {"neighbour takeover": [], "fresh birth": []}
    for vi, v in enumerate(veh):
        cover = []
        for (f, a, b, c, d, s) in v:
            best = (0.0, None)
            ab = fidx.get(f)
            if ab is not None:
                for r in rows_f[ab[0]:ab[1]]:
                    x = iou((a, b, c, d), tbox(r))
                    if x > best[0]:
                        best = (x, int(r[0]))
            cover.append(best[1] if best[0] >= 0.1 else None)
        for k in range(len(v) - 1):
            A, B = cover[k], cover[k + 1]
            if A is None or B is None or A == B:
                continue
            fB = seg[B][:, 1].astype(int)
            f_next = v[k + 1][0]
            if fB[0] == f_next:
                kind = "fresh birth"
            else:
                prev = fB[fB < f_next]
                if not len(prev) or f_next - prev[-1] != 1:
                    continue
                # exclude twins (B already stacked on this car on the frame before)
                rb = seg[B][seg[B][:, 1] == v[k][0]]
                if len(rb) and iou(tbox(rb[0]), tuple(v[k][1:5])) >= 0.5:
                    continue
                kind = "neighbour takeover"
            if (v[k + 1][3] - v[k + 1][1]) < 15 or not (w_lo <= f_next <= w_hi):
                continue
            found[kind].append((vi, k, A, B, f_next))
            break   # one hand-off per vehicle

    picks = []
    for kind, lst in found.items():
        if not lst:
            continue
        idx = np.linspace(0, len(lst) - 1, min(n_per, len(lst))).round().astype(int)
        picks += [(kind, *lst[i]) for i in idx]
    print(f"{proj} cam{cam} {variant}: neighbour takeovers {len(found['neighbour takeover'])}, "
          f"fresh births {len(found['fresh birth'])}; filming {len(picks)}")

    cap = cv2.VideoCapture(vpath)
    Path("screenshots").mkdir(exist_ok=True)
    index = []
    for n, (kind, vi, k, A, B, f_h) in enumerate(picks, 1):
        v = veh[vi]
        chain = {int(h[0]): h[1:5] for h in v}
        # a full PAD_S either side even where the chain has ended: the viewer
        # must see what happens to the cars after the hand-off
        f_lo = int(f_h - PAD_S * fps)
        f_hi = int(f_h + PAD_S * fps)
        TA, TB = seg[A], seg[B]
        frames = []
        plain = []          # each frame once (the page player), hand-off index recorded
        h_idx = None
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        for fno in range(f_lo, f_hi + 1):
            ok, fr = cap.read()
            if not ok:
                break
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            for trk, col in ((TA, ORANGE), (TB, CYAN)):
                seen = trk[trk[:, 1] <= fno]
                if len(seen) >= 2:
                    pth = np.stack([seen[:, 2], seen[:, 3] + seen[:, 5] / 2.0], axis=1) * sc
                    cv2.polylines(im, [pth.astype(int)], False, BLACK, 4)
                    cv2.polylines(im, [pth.astype(int)], False, col, 2)
                cur = trk[trk[:, 1] == fno]
                if len(cur):
                    x1, y1, x2, y2 = (int(q * sc) for q in tbox(cur[0]))
                    cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 5)
                    cv2.rectangle(im, (x1, y1), (x2, y2), col, 3)
            if fno in chain:
                a, b, c, d = (int(q * sc) for q in chain[fno])
                cx, cy = (a + c) // 2, (b + d) // 2
                cv2.rectangle(im, (a, b), (c, d), WHITE, 1)
                r = max(24, int(0.7 * (c - a)))
                cv2.circle(im, (cx, cy), r, BLACK, 5)
                cv2.circle(im, (cx, cy), r, WHITE, 2)
            cv2.rectangle(im, (0, 0), (W_OUT, 50), BLACK, -1)
            cv2.putText(im, f"#{n}  WHITE ring = the car   ORANGE = id {A} (before)   CYAN = id {B} (after)",
                        (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            cv2.putText(im, f"{kind}   f{fno}   {(fno - f_h) / fps:+.1f}s from the hand-off", (8, 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            if fno == f_h:
                banner = im.copy()
                cv2.rectangle(banner, (0, im.shape[0] - 40), (W_OUT, im.shape[0]), BLACK, -1)
                cv2.putText(banner, "HAND-OFF: the tracker's id changes on the white-ringed car here",
                            (8, im.shape[0] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 2)
                frames.extend([banner] * int(HOLD_S * fps))
                h_idx = len(plain)
                plain.append(banner)
            else:
                frames.append(im)
                plain.append(im)
        out = Path(f"screenshots/{prefix}_{n}.webm")
        h, w = frames[0].shape[:2]
        vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"VP80"), fps, (w, h))
        for f in frames:
            vw.write(f)
        vw.release()
        # sprite sheet for the review page: every frame once, 8 across
        fh, fw = plain[0].shape[:2]
        cols = 8
        rows_n = (len(plain) + cols - 1) // cols
        sheet = np.zeros((rows_n * fh, cols * fw, 3), dtype=np.uint8)
        for i, im in enumerate(plain):
            r_, c_ = divmod(i, cols)
            sheet[r_ * fh:(r_ + 1) * fh, c_ * fw:(c_ + 1) * fw] = im
        sprite = Path(f"screenshots/{prefix}_sprite_{n}.jpg")
        cv2.imwrite(str(sprite), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
        index.append({"clip": n, "kind": kind, "vehicle": vi, "id_before": A, "id_after": B,
                      "handoff_frame": f_h, "file": str(out), "sprite": str(sprite),
                      "frames": len(plain), "cols": cols, "w": fw, "h": fh, "fps": fps,
                      "handoff_index": h_idx, "first_frame": f_lo})
        print(f"  #{n} {kind}: id {A} -> {B} at f{f_h} -> {out} ({out.stat().st_size // 1024} KB, {len(frames)} frames)")
    Path(f"screenshots/{prefix}_index.json").write_text(json.dumps(index, indent=1))
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
