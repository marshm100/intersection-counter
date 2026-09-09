"""Film named tracks under the journey state machine (G-SM-1 reels).

For each track: gate lines (magenta, labelled), the box + both bottom-
corner paths, the machine state (amber ENTERING / green OCCUPYING /
blue EXITED) from pair_crossings(), and a printed ledger of EVERY raw
per-corner crossing with whether the machine kept it — so the operator
can see exactly which crossing was refused and why it matters.

Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/viz_pair_reel.py CAM VARIANT PREFIX TID [TID...]
Writes screenshots/{PREFIX}_{n}_{tid}.gif
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import all_crossings, build_gates  # noqa: E402
from backend.services.entry_gates import classify_pair, pair_crossings  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
STATE_COL = {"ENTERING": (0, 215, 255), "OCCUPYING": (60, 255, 60),
             "EXITED": (255, 70, 20)}
MAGENTA, BLACK, WHITE = (255, 0, 220), (0, 0, 0), (255, 255, 255)
W_OUT = int(__import__("os").environ.get("REEL_WIDTH", "480"))
MAX_S = float(__import__("os").environ.get("REEL_MAX_S", "40"))
RENDER_FPS = float(__import__("os").environ.get("REEL_FPS", "10"))


def main() -> int:
    cam, variant, prefix = int(sys.argv[1]), sys.argv[2], sys.argv[3]
    tids = [int(t) for t in sys.argv[4:]]
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=?",
        (cam,)).fetchone()
    legs = dict(con.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (cam,)))
    con.close()
    fps = float(fps)
    step = max(1, int(round(fps / RENDER_FPS)))   # rendered fps
    geom = leg_geometry_for_camera(PROJ, cam)
    gates = build_gates(
        {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
        list_paths_for_camera(PROJ, cam),
        {lg: g.get("heading") for lg, g in geom.items()},
        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})
    td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
    card = lambda lg: legs.get(lg, f"L{lg}")  # noqa: E731

    # REEL_CROP=1: crop to the gates' bounding box (+margin) before
    # scaling, so far-field boxes stay legible and the GIF stays small
    crop = None
    if __import__("os").environ.get("REEL_CROP", "0") == "1":
        xs = [p[0] for g in gates.values() for p in g[:2]]
        ys = [p[1] for g in gates.values() for p in g[:2]]
        mx, my = (max(xs) - min(xs)) * 0.18, (max(ys) - min(ys)) * 0.25
        crop = (int(max(0, min(xs) - mx)), int(max(0, min(ys) - my)),
                int(max(xs) + mx), int(max(ys) + my))

    cap = cv2.VideoCapture(vpath)
    for k, tid in enumerate(tids, 1):
        trk = rows[rows[:, 0] == float(tid)]
        trk = trk[np.argsort(trk[:, 1])]
        if not len(trk):
            print(f"tid {tid}: no track")
            continue
        corner = {}
        for sign, key in ((-1.0, "L"), (1.0, "R")):
            corner[key] = [(float(r[1]), float(r[2]) + sign * float(r[4]) / 2,
                            float(r[3]) + float(r[5]) / 2) for r in trk]
        raw = {key: all_crossings(v, gates, fps) for key, v in corner.items()}
        valid = pair_crossings(corner["L"], corner["R"], gates, fps)
        o, d, fo, fd, _op, _dp, tag = classify_pair(corner["L"], corner["R"],
                                                    gates, fps)
        vset = {(round(c[0], 1), c[1], c[2]) for c in valid}
        print(f"\n#{k} tid {tid}: f{int(trk[0, 1])}-{int(trk[-1, 1])} "
              f"({len(trk)} rows, {(trk[-1, 1] - trk[0, 1]) / fps:.1f}s), "
              f"box at birth {trk[0, 4]:.0f}x{trk[0, 5]:.0f}")
        events = []
        for key in ("L", "R"):
            for f, lg, inward, _p in raw[key]:
                events.append((f, key, lg, inward))
        for f, key, lg, inward in sorted(events):
            kept = any(abs(vf - f) < 0.6 and vl == lg and vi == inward
                       for vf, vl, vi in vset)
            print(f"     f{int(f):>8} {key} corner {'IN ' if inward else 'OUT'} "
                  f"over {card(lg)}   {'KEPT' if kept else 'refused'}")
        for f, lg, inward, _p in valid:
            print(f"     valid @f{int(f)} {'IN ' if inward else 'OUT'} {card(lg)}")
        machine = (f"{card(o)} -> {card(d)}" if tag == "full"
                   else f"{tag} ({card(o) if o else ''}{card(d) if d else ''})")
        print(f"     machine: {machine}")

        f_lo = max(0, int(trk[0, 1]) - int(1.0 * fps))
        f_hi = min(int(trk[-1, 1]) + int(1.0 * fps), f_lo + int(MAX_S * fps))
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        frames = []
        for fno in range(f_lo, f_hi):
            ok, fr = cap.read()
            if not ok:
                break
            if (fno - f_lo) % step:
                continue
            state = "ENTERING"
            for f, _lg, inward, _p in valid:
                if fno >= f:
                    state = "OCCUPYING" if inward else "EXITED"
            ox = oy = 0
            if crop:
                x0, y0, x1c, y1c = crop
                fr = fr[y0:min(y1c, fr.shape[0]), x0:min(x1c, fr.shape[1])]
                ox, oy = x0, y0
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            for lg, (p1, p2, _nrm) in gates.items():
                a = (int((p1[0] - ox) * sc), int((p1[1] - oy) * sc))
                b = (int((p2[0] - ox) * sc), int((p2[1] - oy) * sc))
                cv2.line(im, a, b, BLACK, 5)
                cv2.line(im, a, b, MAGENTA, 2)
                cv2.putText(im, str(card(lg)),
                            ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, MAGENTA, 1)
            col = STATE_COL[state]
            cv2.rectangle(im, (0, 0), (W_OUT, 44), BLACK, -1)
            cv2.putText(im, f"#{k} tid {tid}  {state}", (8, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
            cv2.putText(im, f"machine: {machine}   f{fno}  "
                        f"{(fno - trk[0, 1]) / fps:+.1f}s",
                        (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
            seen = trk[trk[:, 1] <= fno]
            if len(seen) >= 2:
                for sign in (-1.0, 1.0):
                    pth = np.stack([seen[:, 2] + sign * seen[:, 4] / 2.0 - ox,
                                    seen[:, 3] + seen[:, 5] / 2.0 - oy], axis=1)
                    cv2.polylines(im, [(pth * sc).astype(int)], False, BLACK, 3)
                    cv2.polylines(im, [(pth * sc).astype(int)], False,
                                  (210, 210, 210), 1)
            if len(seen) and fno <= trk[-1, 1]:
                p = seen[-1]
                x1, x2 = (int((p[2] - p[4] / 2 - ox) * sc),
                          int((p[2] + p[4] / 2 - ox) * sc))
                y1, y2 = (int((p[3] - p[5] / 2 - oy) * sc),
                          int((p[3] + p[5] / 2 - oy) * sc))
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 4)
                cv2.rectangle(im, (x1, y1), (x2, y2), col, 2)
                for cx in (x1, x2):
                    cv2.circle(im, (cx, y2), 5, BLACK, -1)
                    cv2.circle(im, (cx, y2), 3, WHITE, -1)
            frames.append(Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)))
        out = Path(f"screenshots/{prefix}_{k}_{tid}.gif")
        q = [f.quantize(int(__import__("os").environ.get("REEL_COLORS", "96")),
                        dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * step / fps), loop=0)
        print(f"     -> {out} ({out.stat().st_size // 1024} KB, {len(frames)} frames)")
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
