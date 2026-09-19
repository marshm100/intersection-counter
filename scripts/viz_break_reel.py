"""Break reel for the operator's ruling (plan ok-plan-it-out-breezy-kernighan.md, 2026-09-19).

research_breaks.py says: at frame f_n the vehicle's next real box was in the
tracker's input, nobody took it, and id A (in the pool, tracked or freshly
lost) ended the frame without it - a MISSED break, refused by a named gate.
The film checks the yardstick (is the box under the cyan ring the vehicle
the orange id was on?) and shows what the vehicle got next. Each clip, full
frame, never cropped:
  ORANGE box + path = id A (its dump track), the id that missed
  CYAN ring         = the next real box it missed (at f_n)
  MAGENTA dashed    = the tracker's PREDICTED box for id A at f_n
  YELLOW dashed     = id A's LAST OBSERVED box (where it last saw the car)
  WHITE box + id    = the id the vehicle got next (if any), from f_n on
  GREY boxes + ids  = other ids nearby
2.5 s either side of f_n, every frame once (a sprite sheet).
Picks: MISSED breaks of one gate-2 class (default: the site's most common),
>= 1 min clear of the window ends, the next box >= 15 px, one clip per id,
evenly through the window; N per site.
Usage: .venv/Scripts/python.exe -X utf8 scripts/viz_break_reel.py PROJ CAM VARIANT PREFIX [N] [GATE2]
Writes screenshots/{PREFIX}_sprite_{n}.jpg and screenshots/{PREFIX}_index.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from viz_theft_reel import ORANGE, CYAN, GREY, BLACK, WHITE, W_OUT, PAD_S, tbox, ring  # noqa: E402

MAGENTA, YELLOW = (255, 0, 255), (0, 230, 255)


def dashed_rect(im, box, col, sc, dash=6):
    x1, y1, x2, y2 = (int(q * sc) for q in box)
    pts = [((x1, y1), (x2, y1)), ((x2, y1), (x2, y2)), ((x2, y2), (x1, y2)), ((x1, y2), (x1, y1))]
    for (ax, ay), (bx, by) in pts:
        n = max(1, int(np.hypot(bx - ax, by - ay) // dash))
        for i in range(0, n, 2):
            p = (int(ax + (bx - ax) * i / n), int(ay + (by - ay) * i / n))
            q = (int(ax + (bx - ax) * min(n, i + 1) / n), int(ay + (by - ay) * min(n, i + 1) / n))
            cv2.line(im, p, q, BLACK, 3)
            cv2.line(im, p, q, col, 1)


def main() -> int:
    proj, cam, variant, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    n_pick = int(sys.argv[5]) if len(sys.argv) > 5 else 2
    gate = sys.argv[6] if len(sys.argv) > 6 else None
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    events = json.loads(Path(f"runs/v2_week1/breaks_{proj}_{cam}_{variant}.json").read_text())
    rows = np.asarray(load_dump(tracks_dir(parquet_path(proj, cam, chash, variant))))
    rows_f = rows[np.argsort(rows[:, 1], kind="stable")]
    uf, s_ = np.unique(rows_f[:, 1], return_index=True)
    e_ = np.append(s_[1:], len(rows_f))
    fidx = dict(zip(uf.astype(int), zip(s_, e_)))
    by_id = defaultdict(list)
    for r in rows:
        by_id[int(r[0])].append(r)

    missed = [e for e in events if e["cls"] == "MISSED"]
    if gate is None:
        gate = Counter(e["gate2"] for e in missed).most_common(1)[0][0]
    f_lo, f_hi = float(rows[:, 1].min()) + 60 * fps, float(rows[:, 1].max()) - 60 * fps
    pool = sorted((e for e in missed if e["gate2"] == gate and f_lo <= e["f_n"] <= f_hi and e["w_n"] >= 15),
                  key=lambda e: e["f_n"])
    picks, used = [], set()
    if pool:
        targets = np.linspace(0, len(pool) - 1, n_pick + 2)[1:-1]
        for t in targets:
            for i in sorted(range(len(pool)), key=lambda i: abs(i - t)):
                if pool[i]["A"] not in used:
                    picks.append(pool[i]); used.add(pool[i]["A"]); break
    picks.sort(key=lambda e: e["f_n"])
    print(f"{proj} cam{cam} {variant}: {len(missed)} MISSED, gate {gate}: {len(pool)} filmable; filming {len(picks)}")

    cap = cv2.VideoCapture(vpath)
    index = []
    for n, e in enumerate(picks, 1):
        tid, fn, nid = e["A"], e["f_n"], e.get("B")
        trk = np.asarray(sorted(by_id[tid], key=lambda r: r[1]))
        f_lo_, f_hi_ = int(fn - PAD_S * fps), int(fn + PAD_S * fps)
        frames = []
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo_)
        refs = [e["det_n"], e["pred"]]
        for fno in range(f_lo_, f_hi_ + 1):
            ok, fr = cap.read()
            if not ok:
                break
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            ab = fidx.get(fno)
            if ab is not None:
                for r in rows_f[ab[0]:ab[1]]:
                    if int(r[0]) == tid:
                        continue
                    b = tbox(r)
                    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                    if any(abs(cx - (q[0] + q[2]) / 2) < 2.5 * (q[2] - q[0]) and
                           abs(cy - (q[1] + q[3]) / 2) < 2.5 * (q[2] - q[0]) for q in refs):
                        x1, y1, x2, y2 = (int(q * sc) for q in b)
                        col = WHITE if (nid is not None and int(r[0]) == nid) else GREY
                        cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 3)
                        cv2.rectangle(im, (x1, y1), (x2, y2), col, 1)
                        cv2.putText(im, str(int(r[0])), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, BLACK, 3)
                        cv2.putText(im, str(int(r[0])), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1)
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
            if fno == fn:
                if e.get("obs"):
                    dashed_rect(im, e["obs"], YELLOW, sc)
                dashed_rect(im, e["pred"], MAGENTA, sc)
                ring(im, e["det_n"], CYAN, sc)
            cv2.rectangle(im, (0, 0), (W_OUT, 50), BLACK, -1)
            head = f"#{n}  ORANGE = id {tid}   CYAN ring = the box it missed   MAGENTA = its prediction   YELLOW = last seen"
            cv2.putText(im, head, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
            cv2.putText(im, f"f{fno}   {(fno - fn) / fps:+.1f}s from the miss   {gate}", (8, 42),
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
        index.append({**e, "clip": n, "first_frame": f_lo_, "frames": len(frames), "switch_index": fn - f_lo_,
                      "fps": fps, "sprite": str(sprite), "w_px": fw, "h_px": fh, "cols": cols})
        print(f"  #{n} id {tid} at f{fn}: {e['box']} box conf {e['conf_in']:.2f}, {'lost' if e['lost'] else 'tracked'} age {e['age']}, "
              f"gate {e['gate1']} / {e['gate2']}; IoU pred {e['iou_pred']} obs {e['iou_obs']}; "
              f"err pred {e['err_pred_w']} obs {e['err_obs_w']} widths; next id {nid} -> {sprite}")
    Path(f"screenshots/{prefix}_index.json").write_text(json.dumps(index, indent=1))
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
