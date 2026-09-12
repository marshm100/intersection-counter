"""Film a floor-removed track together with its sequential partner (2026-09-11).

Arm d15 (100 px floor) removed ~75 px tracks that, on cam5, were
overcounts and, on cam1, were real turns. Every one has a surviving
event born or dying at the same spot within seconds. This reel shows
the pair on the full frame so the operator can rule whether they are
ONE vehicle fractured (the removed track is a duplicate) or TWO
vehicles in a queue (the removed track was a real count).

Orange = the removed track (its box and bottom-centre path), cyan =
the surviving counted track. Banner names both and the gap. WebM VP8,
full frame, never cropped (operator ruling 2026-09-09).

Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/viz_fragment_pair_reel.py CAM VARIANT PREFIX A:B [A:B...]
Writes screenshots/{PREFIX}_{n}_{A}_{B}.webm
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import leg_geometry_for_camera, list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ = "97a7849a"
ORANGE, CYAN, MAGENTA, BLACK, WHITE = (0, 140, 255), (255, 220, 0), (255, 0, 220), (0, 0, 0), (255, 255, 255)
W_OUT = int(os.environ.get("REEL_WIDTH", "720"))
MAX_S = float(os.environ.get("REEL_MAX_S", "40"))
RENDER_FPS = float(os.environ.get("REEL_FPS", "10"))
PAD_S = 1.5


def main() -> int:
    cam, variant, prefix = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    pairs = [tuple(int(x) for x in a.split(":")) for a in sys.argv[4:]]
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,)))
    con.close()
    fps = float(fps)
    step = max(1, int(round(fps / RENDER_FPS)))
    geom = leg_geometry_for_camera(PROJ, cam)
    gates = build_gates({lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")}, list_paths_for_camera(PROJ, cam),
                        {lg: g.get("heading") for lg, g in geom.items()},
                        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})
    rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
    cap = cv2.VideoCapture(vpath)
    Path("screenshots").mkdir(exist_ok=True)
    for k, (ta, tb) in enumerate(pairs, 1):
        A = rows[rows[:, 0] == float(ta)]; A = A[np.argsort(A[:, 1])]
        B = rows[rows[:, 0] == float(tb)]; B = B[np.argsort(B[:, 1])]
        if not len(A) or not len(B):
            print(f"pair {ta}:{tb}: missing track"); continue
        first, last = (A, B) if A[0, 1] <= B[0, 1] else (B, A)
        gap = (last[0, 1] - first[-1, 1]) / fps
        # one segment when the pair is close; two segments (first track,
        # a gap card, second track) when the gap would blow the clip cap
        seg1 = (max(0, int(first[0, 1] - PAD_S * fps)), int(first[-1, 1] + PAD_S * fps))
        seg2 = (max(0, int(last[0, 1] - PAD_S * fps)), int(last[-1, 1] + PAD_S * fps))
        if seg2[1] - seg1[0] <= MAX_S * fps:
            segments = [(seg1[0], seg2[1])]
        else:
            segments = [seg1, seg2]
        f_lo = segments[0][0]
        f_hi = segments[-1][1]
        print(f"#{k} removed {ta} f{int(A[0,1])}-{int(A[-1,1])} ({(A[-1,1]-A[0,1])/fps:.1f}s, box {np.median(A[:,4]):.0f}x{np.median(A[:,5]):.0f})"
              f"  survivor {tb} f{int(B[0,1])}-{int(B[-1,1])} ({(B[-1,1]-B[0,1])/fps:.1f}s)  gap {gap:+.1f}s  clip f{f_lo}-{f_hi}")
        frames = []
        plan = []
        for si, (s0, s1) in enumerate(segments):
            if si:
                plan.append(("card", s0))
            plan.extend(("frame", f) for f in range(s0, s1))
        cap.set(cv2.CAP_PROP_POS_FRAMES, segments[0][0])
        next_frame = segments[0][0]
        for kind, fno in plan:
            if kind == "card":
                cap.set(cv2.CAP_PROP_POS_FRAMES, fno); next_frame = fno
                for _ in range(int(RENDER_FPS)):
                    card = np.zeros_like(frames[-1])
                    cv2.putText(card, f"... {gap:.1f} s later ...", (W_OUT // 3, card.shape[0] // 2),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.0, WHITE, 2)
                    frames.append(card)
                continue
            ok, fr = cap.read()
            next_frame += 1
            if not ok:
                break
            if (fno - segments[0][0]) % step:
                continue
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            for lg, (p1, p2, _n) in gates.items():
                a = (int(p1[0] * sc), int(p1[1] * sc)); b = (int(p2[0] * sc), int(p2[1] * sc))
                cv2.line(im, a, b, BLACK, 5); cv2.line(im, a, b, MAGENTA, 2)
                cv2.putText(im, str(legs.get(lg, lg)), ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, MAGENTA, 2)
            for trk, col in ((B, CYAN), (A, ORANGE)):
                seen = trk[trk[:, 1] <= fno]
                if len(seen) >= 2:
                    pth = np.stack([seen[:, 2], seen[:, 3] + seen[:, 5] / 2.0], axis=1) * sc
                    cv2.polylines(im, [pth.astype(int)], False, BLACK, 4)
                    cv2.polylines(im, [pth.astype(int)], False, col, 2)
                if len(seen) and fno <= trk[-1, 1]:
                    p = seen[-1]
                    x1, x2 = int((p[2] - p[4] / 2) * sc), int((p[2] + p[4] / 2) * sc)
                    y1, y2 = int((p[3] - p[5] / 2) * sc), int((p[3] + p[5] / 2) * sc)
                    cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 5)
                    cv2.rectangle(im, (x1, y1), (x2, y2), col, 3)
                    # a big ring so a 12 px far-field box can be found on the full frame
                    cv2.circle(im, ((x1 + x2) // 2, (y1 + y2) // 2), 26, BLACK, 4)
                    cv2.circle(im, ((x1 + x2) // 2, (y1 + y2) // 2), 26, col, 2)
            cv2.rectangle(im, (0, 0), (W_OUT, 50), BLACK, -1)
            cv2.putText(im, f"#{k}  ORANGE = removed track {ta}   CYAN = counted track {tb}   gap {gap:+.1f}s",
                        (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, WHITE, 2)
            live = []
            if A[0, 1] <= fno <= A[-1, 1]: live.append("orange LIVE")
            if B[0, 1] <= fno <= B[-1, 1]: live.append("cyan LIVE")
            cv2.putText(im, f"f{fno}  {(fno - f_lo) / fps:+.1f}s   {'  '.join(live)}", (8, 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            frames.append(im)
        out = Path(f"screenshots/{prefix}_{k}_{ta}_{tb}.webm")
        h, w = frames[0].shape[:2]
        vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"VP80"), fps / step, (w, h))
        for f in frames:
            vw.write(f)
        vw.release()
        print(f"     -> {out} ({out.stat().st_size // 1024} KB, {len(frames)} frames)")
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
