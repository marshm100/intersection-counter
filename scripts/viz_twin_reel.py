"""Twin reel for the operator's ruling (2026-09-19, research_twins.py).

A twin = two tracker ids on one yardstick chain at the same time. The census
sorts them by the geometry at the newborn's birth: NESTED (one box >= 0.9
inside the other - the detector's double box, born below the 0.6-IoU stacked
guard because the sizes differ), STACKED (IoU 0.3-0.6), TOUCHING (0.1-0.3),
BESIDE (IoU < 0.1, ~1.5 holder widths away - a neighbour that the chain later
shares, or a theft). The film says which are one vehicle. Each clip, full
frame, never cropped:
  ORANGE box + path = the NEWBORN id, from its birth frame on
  WHITE box + id    = the HOLDER, the id already on the vehicle
  CYAN ring         = the chain's box at the birth frame (the yardstick's vehicle)
  GREY boxes + ids  = other ids nearby
1 s before the birth to 4 s after it (the twin's life is what matters).
Picks per site: N of the NESTED class and N of the BESIDE class, evenly through
the window, >= 1 min from the ends, the holder's box >= 15 px, one clip per
vehicle.
Usage: .venv/Scripts/python.exe -X utf8 scripts/viz_twin_reel.py PROJ CAM VARIANT PREFIX [N]
Writes screenshots/{PREFIX}_sprite_{n}.jpg and screenshots/{PREFIX}_index.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from research_tracker_break import base_variant  # noqa: E402
from viz_theft_reel import ORANGE, CYAN, GREY, BLACK, WHITE, W_OUT, tbox, ring  # noqa: E402

PRE_S, POST_S = 1.0, 4.0


def geo(e):
    c = max(e["cov_young_in_old"], e["cov_old_in_young"])
    if c >= 0.9:
        return "nested"
    if e["iou"] >= 0.3:
        return "stacked"
    if e["iou"] >= 0.1:
        return "touching"
    return "beside"


def main() -> int:
    proj, cam, variant, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    n_per = int(sys.argv[5]) if len(sys.argv) > 5 else 1
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    events = json.loads(Path(f"runs/v2_week1/twins_{proj}_{cam}_{variant}.json").read_text())
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    rows = np.asarray(load_dump(tracks_dir(parquet_path(proj, cam, chash, variant))))
    rows_f = rows[np.argsort(rows[:, 1], kind="stable")]
    uf, s_ = np.unique(rows_f[:, 1], return_index=True)
    e_ = np.append(s_[1:], len(rows_f))
    fidx = dict(zip(uf.astype(int), zip(s_, e_)))
    by_id = defaultdict(list)
    for r in rows:
        by_id[int(r[0])].append(r)

    picks, used = [], set()
    for cls in ("nested", "beside"):
        pool = sorted((e for e in events if geo(e) == cls and e["clear_of_ends"] and e["w_old"] >= 15),
                      key=lambda e: e["birth"])
        if not pool:
            continue
        targets = np.linspace(0, len(pool) - 1, n_per + 2)[1:-1]
        for t in targets:
            for i in sorted(range(len(pool)), key=lambda i: abs(i - t)):
                if pool[i]["veh"] not in used:
                    picks.append((cls, pool[i])); used.add(pool[i]["veh"]); break
    picks.sort(key=lambda p: p[1]["birth"])
    print(f"{proj} cam{cam} {variant}: {len(events)} twins; filming {len(picks)}")

    cap = cv2.VideoCapture(vpath)
    index = []
    for n, (cls, e) in enumerate(picks, 1):
        young, old, fb = e["young"], e["old"], e["birth"]
        trk = np.asarray(sorted(by_id[young], key=lambda r: r[1]))
        chain = {int(h[0]): h[1:5] for h in veh[e["veh"]]}
        f_lo, f_hi = int(fb - PRE_S * fps), int(fb + POST_S * fps)
        frames = []
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        refs = [e["young_box"], e["old_box"]]
        for fno in range(f_lo, f_hi + 1):
            ok, fr = cap.read()
            if not ok:
                break
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            ab = fidx.get(fno)
            if ab is not None:
                for r in rows_f[ab[0]:ab[1]]:
                    if int(r[0]) == young:
                        continue
                    b = tbox(r)
                    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                    if int(r[0]) == old or any(abs(cx - (q[0] + q[2]) / 2) < 2.5 * (q[2] - q[0]) and
                                               abs(cy - (q[1] + q[3]) / 2) < 2.5 * (q[2] - q[0]) for q in refs):
                        x1, y1, x2, y2 = (int(q * sc) for q in b)
                        col = WHITE if int(r[0]) == old else GREY
                        cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 3 if col is GREY else 4)
                        cv2.rectangle(im, (x1, y1), (x2, y2), col, 1 if col is GREY else 2)
                        cv2.putText(im, str(int(r[0])), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, BLACK, 3)
                        cv2.putText(im, str(int(r[0])), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1)
            seen = trk[(trk[:, 1] <= fno) & (trk[:, 1] >= fb)]
            if len(seen) >= 2:
                pth = (np.stack([seen[:, 2], seen[:, 3] + seen[:, 5] / 2.0], axis=1) * sc).astype(int)
                cv2.polylines(im, [pth], False, BLACK, 4)
                cv2.polylines(im, [pth], False, ORANGE, 2)
            cur = trk[trk[:, 1] == fno]
            if len(cur) and fno >= fb:
                x1, y1, x2, y2 = (int(q * sc) for q in tbox(cur[0]))
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 5)
                cv2.rectangle(im, (x1, y1), (x2, y2), ORANGE, 3)
                cv2.putText(im, str(young), (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, BLACK, 4)
                cv2.putText(im, str(young), (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, ORANGE, 1)
            if fno == fb and fb in chain:
                ring(im, chain[fb], CYAN, sc)
            cv2.rectangle(im, (0, 0), (W_OUT, 50), BLACK, -1)
            cv2.putText(im, f"#{n}  ORANGE = newborn id {young}   WHITE = holder id {old}   CYAN ring = the vehicle (chain) at the birth",
                        (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
            cv2.putText(im, f"f{fno}   {(fno - fb) / fps:+.1f}s from the birth   {cls}", (8, 42),
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
        index.append({**e, "geo": cls, "clip": n, "first_frame": f_lo, "frames": len(frames), "switch_index": fb - f_lo,
                      "fps": fps, "sprite": str(sprite), "w_px": fw, "h_px": fh, "cols": cols})
        print(f"  #{n} {cls}: newborn {young} (conf {e['conf_young']}, life {e['young_life']} f) on holder {old} at f{fb}: "
              f"IoU {e['iou']}, cov {max(e['cov_young_in_old'], e['cov_old_in_young'])}, offset {e['offset_w']} w; "
              f"twin {e['twin_frames']} f; survivor {e['survivor']} -> {sprite}")
    Path(f"screenshots/{prefix}_index.json").write_text(json.dumps(index, indent=1))
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
