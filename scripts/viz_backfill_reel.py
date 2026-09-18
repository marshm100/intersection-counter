"""Back-fill reel (2026-09-12, weak-box births, inheritance): is a track's
back-filled start the same car as the track it joins?

Picks tracks whose back-fill (the sidecar backfill.npy in the dump dir) is at
least MIN_BF frames long, evenly through the window, a minute clear of its
ends. Each clip is the full frame from 1 s before the back-filled start to
2 s after the birth, every frame once (a sprite sheet for the reel page):
  YELLOW box + path = the track's back-filled start (its weak early boxes)
  CYAN box + path   = the same track id after its birth
  GREY boxes        = other tracks within two box widths (a twin shows here)
Usage: .venv/Scripts/python.exe -X utf8 scripts/viz_backfill_reel.py PROJ CAM VARIANT PREFIX [N]
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

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

YELLOW, CYAN, GREY, BLACK, WHITE = (0, 230, 255), (255, 220, 0), (170, 170, 170), (0, 0, 0), (255, 255, 255)
W_OUT = 720
MIN_BF = 8


def box(r):
    return (r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2)


def main() -> int:
    proj, cam, variant, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    n_clips = int(sys.argv[5]) if len(sys.argv) > 5 else 3
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    d = tracks_dir(parquet_path(proj, cam, chash, variant))
    rows = np.array(load_dump(d), copy=True)
    bf = np.load(d / "backfill.npy").reshape(-1, 9)
    f_lo_w, f_hi_w = rows[:, 1].min() + 60 * fps, rows[:, 1].max() - 60 * fps
    by_tid: dict = {}
    for r in bf:
        by_tid.setdefault(int(r[0]), []).append(r)
    cands = []
    for tid, rs in by_tid.items():
        rs = np.asarray(rs)
        promo = int(rs[0, 8])
        if len(rs) >= MIN_BF and f_lo_w <= promo <= f_hi_w and np.median(rs[:, 4]) >= 12:
            cands.append((promo, tid, rs))
    cands.sort()
    idx = np.linspace(0, len(cands) - 1, min(n_clips, len(cands))).round().astype(int)
    picks = [cands[i] for i in idx]
    print(f"{proj} cam{cam} {variant}: {len(by_tid)} tracks with back-fill, {len(cands)} eligible; filming {len(picks)}")

    rows_f = rows[np.argsort(rows[:, 1], kind="stable")]
    uf, s_ = np.unique(rows_f[:, 1], return_index=True); e_ = np.append(s_[1:], len(rows_f))
    fidx = dict(zip(uf.astype(int), zip(s_, e_)))
    cap = cv2.VideoCapture(vpath)
    index = []
    for n, (promo, tid, rs) in enumerate(picks, 1):
        bf_frames = set(int(f) for f in rs[:, 1])
        f_start = int(rs[:, 1].min() - fps)
        f_end = int(promo + 2 * fps)
        trk = rows[rows[:, 0] == tid]
        trk = trk[np.argsort(trk[:, 1])]
        frames = []
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_start)
        for fno in range(f_start, f_end + 1):
            ok, fr = cap.read()
            if not ok:
                break
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            seen = trk[trk[:, 1] <= fno]
            me = trk[trk[:, 1] == fno]
            ref = box(me[0]) if len(me) else None
            ab = fidx.get(fno)
            if ab is not None and ref is not None:
                wref = ref[2] - ref[0]
                for r in rows_f[ab[0]:ab[1]]:
                    if int(r[0]) == tid:
                        continue
                    b = box(r)
                    if abs((b[0] + b[2]) / 2 - (ref[0] + ref[2]) / 2) < 2 * wref and abs((b[1] + b[3]) / 2 - (ref[1] + ref[3]) / 2) < 2 * wref:
                        x1, y1, x2, y2 = (int(q * sc) for q in b)
                        cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 3)
                        cv2.rectangle(im, (x1, y1), (x2, y2), GREY, 1)
            for part, col in ((seen[np.isin(seen[:, 1], list(bf_frames))], YELLOW),
                              (seen[~np.isin(seen[:, 1], list(bf_frames))], CYAN)):
                if len(part) >= 2:
                    pth = np.stack([part[:, 2], part[:, 3] + part[:, 5] / 2.0], axis=1) * sc
                    cv2.polylines(im, [pth.astype(int)], False, BLACK, 4)
                    cv2.polylines(im, [pth.astype(int)], False, col, 2)
            if ref is not None:
                col = YELLOW if fno in bf_frames else CYAN
                x1, y1, x2, y2 = (int(q * sc) for q in ref)
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 5)
                cv2.rectangle(im, (x1, y1), (x2, y2), col, 3)
                cxy = ((x1 + x2) // 2, (y1 + y2) // 2)
                rad = max(24, int(0.7 * (x2 - x1)))
                cv2.circle(im, cxy, rad, BLACK, 4)
                cv2.circle(im, cxy, rad, col, 2)
            cv2.rectangle(im, (0, 0), (W_OUT, 50), BLACK, -1)
            cv2.putText(im, f"#{n}  track {tid}   YELLOW = back-filled start   CYAN = after its birth",
                        (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            phase = "back-filled" if fno in bf_frames else ("after birth" if fno >= promo else "before the track")
            cv2.putText(im, f"f{fno}   {(fno - promo) / fps:+.1f}s from the birth   {phase}", (8, 42),
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
        index.append({"clip": n, "track": tid, "promoted_at": promo, "first_frame": f_start,
                      "frames": len(frames), "birth_index": promo - f_start, "bf_frames": len(bf_frames),
                      "bf_first": int(rs[:, 1].min()), "fps": fps, "sprite": str(sprite),
                      "w": fw, "h": fh, "cols": cols})
        print(f"  #{n} track {tid}: {len(bf_frames)} back-filled frames from f{int(rs[:, 1].min())}, born f{promo} -> {sprite}")
    Path(f"screenshots/{prefix}_index.json").write_text(json.dumps(index, indent=1))
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
