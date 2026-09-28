"""Exit-only reel for the operator's ruling (2026-09-27, cam4 SB-through diagnosis).

cam4's southbound-through excess is EXIT-ONLY tracks: first seen partway
through the box on the southbound line, then seen leaving south, origin
guessed by the posterior. Most are ALONE at birth (no other track within
1.5 box). The film says which they are: a real car whose earlier track was
lost (a correct count), or surplus.

Each clip, full frame, never cropped, as an MP4 at half speed:
  ORANGE box + path = the exit-only track, from its birth on
  GREY boxes + ids  = other tracks nearby (within 4 box widths)
  MAGENTA lines     = the gate lines
3 s before the birth (was this car already being tracked?) to the track's
end + 1 s, capped at 12 s.
Picks: counted, unrejected exit-only N-origin throughs, alone at birth, box
>= 15 px, >= 1 min from the window ends, evenly spread through the window.
Usage: .venv/Scripts/python.exe -X utf8 scripts/viz_exit_only_reel.py CAM VARIANT STEM N
Writes screenshots/exitonly_cam{CAM}_{VARIANT}_{n}.mp4 and an index JSON.
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
ORANGE, GREY, BLACK, WHITE, MAGENTA = (0, 140, 255), (170, 170, 170), (0, 0, 0), (255, 255, 255), (255, 0, 255)
W_OUT = 960
PRE_S, POST_S, MAX_S = 3.0, 1.0, 12.0


def box(r):
    return (r[2] - r[4] / 2, r[3] - r[5] / 2, r[2] + r[4] / 2, r[3] + r[5] / 2)


def main() -> int:
    cam, variant, stem = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    n_clips = int(sys.argv[4]) if len(sys.argv) > 4 else 2
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE camera_id=?",
                                    (cam,)).fetchone()
    fps = float(fps)
    legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,)))
    north = [k for k, v in legs.items() if v == "N"][0]
    gates = {legs.get(lid): g["gate"] for lid, g in leg_geometry_for_camera(PROJ, cam).items() if g["gate"]}
    rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
    by_id = defaultdict(list)
    for r in rows:
        by_id[int(r[0])].append(r)
    by_id = {k: np.asarray(sorted(v, key=lambda r: r[1])) for k, v in by_id.items()}
    rows_f = rows[np.argsort(rows[:, 1], kind="stable")]
    uf, s_ = np.unique(rows_f[:, 1], return_index=True)
    fidx = dict(zip(uf.astype(int), zip(s_, np.append(s_[1:], len(rows_f)))))
    tag = f"vl3_{variant}" if cam in (4, 5) else variant
    d = sqlite3.connect(f"file:{BASE / f'{stem}_cam{cam}_{tag}.db'}?mode=ro", uri=True)
    ftag = {(v, t): g for v, t, g in d.execute("SELECT video_id, vehicle_track_id, gate_tag FROM track_fates")}
    f_min, f_max = float(rows[:, 1].min()), float(rows[:, 1].max())
    pool = []
    for v, t in d.execute("SELECT video_id, vehicle_track_id FROM vehicle_events WHERE camera_id=? AND "
                          "origin_leg_id=? AND movement='through' AND COALESCE(rejected,0)=0", (cam, north)):
        if ftag.get((v, t)) != "exit_only" or t not in by_id:
            continue
        trk = by_id[t]
        b0 = trk[0]
        if b0[4] < 15 or b0[1] < f_min + 60 * fps or trk[-1][1] > f_max - 60 * fps:
            continue
        ab = fidx.get(int(b0[1]))
        alone = True
        if ab is not None:
            for r in rows_f[ab[0]:ab[1]]:
                if int(r[0]) != t and math.hypot(r[2] - b0[2], r[3] - b0[3]) <= 1.5 * b0[4]:
                    alone = False
                    break
        if alone:
            pool.append(t)
    pool.sort(key=lambda t: by_id[t][0][1])
    picks = [pool[int(i)] for i in np.linspace(0, len(pool) - 1, n_clips + 2)[1:-1]] if pool else []
    print(f"cam{cam} {variant}: {len(pool)} lone exit-only SB throughs; filming {picks}")

    cap = cv2.VideoCapture(vpath)
    index = []
    for n, t in enumerate(picks, 1):
        trk = by_id[t]
        fb, fe = int(trk[0][1]), int(trk[-1][1])
        f_lo = int(fb - PRE_S * fps)
        f_hi = min(int(fe + POST_S * fps), int(f_lo + MAX_S * fps))
        out = Path(f"screenshots/exitonly_cam{cam}_{variant}_{n}.mp4")
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        writer = None
        for fno in range(f_lo, f_hi + 1):
            ok, fr = cap.read()
            if not ok:
                break
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            for name, g in gates.items():
                pts = (np.asarray(g, dtype=float) * sc).astype(int)
                cv2.polylines(im, [pts], False, MAGENTA, 2)
                cv2.putText(im, name, tuple(pts[len(pts) // 2]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, MAGENTA, 2)
            ref = trk[min(max(fno - fb, 0), len(trk) - 1)]
            ab = fidx.get(fno)
            if ab is not None:
                for r in rows_f[ab[0]:ab[1]]:
                    if int(r[0]) == t or math.hypot(r[2] - ref[2], r[3] - ref[3]) > 4 * max(ref[4], 15):
                        continue
                    x1, y1, x2, y2 = (int(q * sc) for q in box(r))
                    cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 3)
                    cv2.rectangle(im, (x1, y1), (x2, y2), GREY, 1)
                    cv2.putText(im, str(int(r[0])), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, GREY, 1)
            seen = trk[(trk[:, 1] <= fno)]
            if len(seen) >= 2:
                pth = (seen[:, 2:4] * sc).astype(int)
                cv2.polylines(im, [pth], False, BLACK, 4)
                cv2.polylines(im, [pth], False, ORANGE, 2)
            cur = trk[trk[:, 1] == fno]
            if len(cur):
                x1, y1, x2, y2 = (int(q * sc) for q in box(cur[0]))
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 5)
                cv2.rectangle(im, (x1, y1), (x2, y2), ORANGE, 3)
            cv2.rectangle(im, (0, 0), (W_OUT, 54), BLACK, -1)
            cv2.putText(im, f"#{n}  ORANGE = track {t}, counted as a southbound through (first seen mid-box)",
                        (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            cv2.putText(im, f"{(fno - fb) / fps:+.1f}s from when it is first seen   |   real car counted once, "
                            f"or already counted / not a car?", (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            if writer is None:
                h, w = im.shape[:2]
                writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps / 2.0, (w, h))
            writer.write(im)
        if writer is not None:
            writer.release()
        index.append({"clip": n, "track": t, "birth_frame": fb, "end_frame": fe,
                      "birth_xy": [round(float(trk[0][2])), round(float(trk[0][3]))],
                      "box_px": round(float(trk[0][4])), "file": str(out)})
        print(f"  #{n}: track {t} first seen f{fb} at {index[-1]['birth_xy']}, box {index[-1]['box_px']} px, "
              f"life {(fe - fb) / fps:.1f}s -> {out}")
    cap.release()
    Path(f"screenshots/exitonly_cam{cam}_{variant}_index.json").write_text(json.dumps(index, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
