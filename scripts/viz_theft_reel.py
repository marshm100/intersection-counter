"""Theft reel for the operator's ruling (Phase B, 2026-09-13).

research_thefts.py says one tracker id sat on vehicle A (a yardstick chain),
then on vehicle B, while A went on being detected and B was already there.
Two readings: the id really moved between two cars (a TRACKER theft), or the
yardstick's chains swapped between two cars while the id stayed on one (a
YARDSTICK error). Only the video can tell. Each clip, full frame, never
cropped:
  ORANGE box + path = the tracker id in question (the whole clip)
  WHITE ring        = vehicle A, the car the id was on before
  CYAN ring         = vehicle B, the car the id is on after
  GREY boxes + ids  = the other tracker ids near either car
From 2.5 s before the switch to 2.5 s after it, every frame once (a sprite
sheet for the reel page); the switch frame is marked.
Picks: kind THEFT, at least a minute clear of the window ends, B's box >= 15 px,
per site one with A/B overlap <= 0.5 and one > 0.5 (evenly through the window).
Usage: .venv/Scripts/python.exe -X utf8 scripts/viz_theft_reel.py PROJ CAM VARIANT PREFIX [N_PER_BUCKET]
Writes screenshots/{PREFIX}_sprite_{n}.jpg and screenshots/{PREFIX}_index.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from research_tracker_break import base_variant  # noqa: E402

ORANGE, CYAN, GREY, BLACK, WHITE = (0, 140, 255), (255, 220, 0), (170, 170, 170), (0, 0, 0), (255, 255, 255)
W_OUT = 720
PAD_S = 2.5


def tbox(r):
    return (r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2)


def ring(im, box, col, sc):
    a, b, c, d = (int(q * sc) for q in box)
    cx, cy = (a + c) // 2, (b + d) // 2
    r = max(22, int(0.75 * (c - a)))
    cv2.circle(im, (cx, cy), r, BLACK, 5)
    cv2.circle(im, (cx, cy), r, col, 2)


def main() -> int:
    proj, cam, variant, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    n_per = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    events = json.loads(Path(f"runs/v2_week1/thefts_{proj}_{cam}_{variant}.json").read_text())
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    rows = np.asarray(load_dump(tracks_dir(parquet_path(proj, cam, chash, variant))))
    rows_f = rows[np.argsort(rows[:, 1], kind="stable")]
    uf, s_ = np.unique(rows_f[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows_f))
    fidx = dict(zip(uf.astype(int), zip(s_, e_)))

    pool = sorted((e for e in events if e["kind"] == "THEFT" and e["clear_of_ends"] and e["w"] >= 15),
                  key=lambda e: e["f_first_B"])
    picks = []
    for low_overlap in (True, False):
        sub = [e for e in pool if (e["iou_ab"] <= 0.5) == low_overlap]
        if sub:
            idx = np.linspace(0, len(sub) - 1, min(n_per, len(sub)) + 2)[1:-1].round().astype(int) \
                if len(sub) > n_per else np.arange(len(sub))
            picks += [sub[i] for i in idx]
    picks.sort(key=lambda e: e["f_first_B"])
    print(f"{proj} cam{cam} {variant}: {len(pool)} filmable thefts; filming {len(picks)}")

    cap = cv2.VideoCapture(vpath)
    index = []
    for n, e in enumerate(picks, 1):
        tid, A, B, fb = e["track"], e["A"], e["B"], e["f_first_B"]
        chA = {int(h[0]): h[1:5] for h in veh[A]}
        chB = {int(h[0]): h[1:5] for h in veh[B]}
        trk = rows[rows[:, 0] == tid]
        trk = trk[np.argsort(trk[:, 1])]
        f_lo, f_hi = int(fb - PAD_S * fps), int(fb + PAD_S * fps)
        frames = []
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        for fno in range(f_lo, f_hi + 1):
            ok, fr = cap.read()
            if not ok:
                break
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            near = [chA.get(fno), chB.get(fno)]
            refs = [b for b in near if b is not None]
            ab = fidx.get(fno)
            if ab is not None and refs:
                for r in rows_f[ab[0]:ab[1]]:
                    if int(r[0]) == tid:
                        continue
                    b = tbox(r)
                    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                    if any(abs(cx - (q[0] + q[2]) / 2) < 2.5 * (q[2] - q[0]) and
                           abs(cy - (q[1] + q[3]) / 2) < 2.5 * (q[2] - q[0]) for q in refs):
                        x1, y1, x2, y2 = (int(q * sc) for q in b)
                        cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 3)
                        cv2.rectangle(im, (x1, y1), (x2, y2), GREY, 1)
                        cv2.putText(im, str(int(r[0])), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, BLACK, 3)
                        cv2.putText(im, str(int(r[0])), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, GREY, 1)
            seen = trk[trk[:, 1] <= fno]
            if len(seen) >= 2:
                pth = (np.stack([seen[:, 2], seen[:, 3] + seen[:, 5] / 2.0], axis=1) * sc).astype(int)
                cv2.polylines(im, [pth], False, BLACK, 4)
                cv2.polylines(im, [pth], False, ORANGE, 2)
            cur = trk[trk[:, 1] == fno]
            if len(cur):
                x1, y1, x2, y2 = (int(q * sc) for q in tbox(cur[0]))
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 5)
                cv2.rectangle(im, (x1, y1), (x2, y2), ORANGE, 3)
                cv2.putText(im, str(tid), (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, BLACK, 4)
                cv2.putText(im, str(tid), (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, ORANGE, 1)
            if near[0] is not None:
                ring(im, near[0], WHITE, sc)
            if near[1] is not None:
                ring(im, near[1], CYAN, sc)
            cv2.rectangle(im, (0, 0), (W_OUT, 50), BLACK, -1)
            cv2.putText(im, f"#{n}  ORANGE = id {tid}   WHITE ring = car A (before)   CYAN ring = car B (after)",
                        (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.47, WHITE, 1)
            cv2.putText(im, f"f{fno}   {(fno - fb) / fps:+.1f}s from the switch", (8, 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            frames.append(im)
        fh, fw = frames[0].shape[:2]
        cols = 8
        sheet = np.zeros((((len(frames) + cols - 1) // cols) * fh, cols * fw, 3), dtype=np.uint8)
        for i, im in enumerate(frames):
            r_, c_ = divmod(i, cols)
            sheet[r_ * fh:(r_ + 1) * fh, c_ * fw:(c_ + 1) * fw] = im
        sprite = Path(f"screenshots/{prefix}_sprite_{n}.jpg")
        cv2.imwrite(str(sprite), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
        index.append({**e, "clip": n, "first_frame": f_lo, "frames": len(frames), "switch_index": fb - f_lo,
                      "fps": fps, "sprite": str(sprite), "w_px": fw, "h_px": fh, "cols": cols})
        print(f"  #{n} id {tid}: car {A} -> car {B} at f{fb} (overlap {e['iou_ab']}, stage {e.get('stage')}, "
              f"lost {e.get('was_lost')} age {e.get('age')}, swap {e['swap_with']}) -> {sprite}")
    Path(f"screenshots/{prefix}_index.json").write_text(json.dumps(index, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
