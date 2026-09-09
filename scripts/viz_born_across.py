"""Reel 1 for the operator (2026-09-09): BORN-ACROSS entries.

G-SM-1 iteration 2 counts a solo inward corner crossing when the OTHER
corner was already inside the gate on the track's first frame and had
no earlier crossing of it — the agent's inference from the census,
not yet his ruling. This films an even-spread sample of tracks whose
ENTRY exists only because of that clause, so he can rule whether they
are real entries.

Each clip: gate lines (magenta), the box + bottom-corner path coloured
by machine state (amber ENTERING / green OCCUPYING / blue EXITED), the
crossing corner marked, and a caption naming the entry gate and frame.
Writes screenshots/born_across_{n}_{tid}.gif and prints the ledger.

Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/viz_born_across.py [CAM VARIANT N]
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import CORNER_PAIR_WINDOW_S, CROSSING_TRUNCATION_S  # noqa: E402
from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import all_crossings, build_gates  # noqa: E402
from backend.services.entry_gates import pair_crossings  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
STATE_COL = {"ENTERING": (0, 215, 255), "OCCUPYING": (60, 255, 60),
             "EXITED": (255, 70, 20)}
MAGENTA, BLACK, WHITE = (255, 0, 220), (0, 0, 0), (255, 255, 255)
W_OUT, STEP = 480, 2


def main() -> int:
    cam = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    variant = sys.argv[2] if len(sys.argv) > 2 else "study_0700"
    n_want = int(sys.argv[3]) if len(sys.argv) > 3 else 5

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
    geom = leg_geometry_for_camera(PROJ, cam)
    gates = build_gates(
        {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
        list_paths_for_camera(PROJ, cam),
        {lg: g.get("heading") for lg, g in geom.items()},
        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})
    td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    win = CORNER_PAIR_WINDOW_S * fps
    trunc = CROSSING_TRUNCATION_S * fps

    # --- find every track whose entry exists ONLY by the born-across clause
    pop = []
    _tids, starts = np.unique(rows[:, 0], return_index=True)
    bounds = list(zip(starts, list(starts[1:]) + [len(rows)]))
    for a, b in bounds:
        trk = rows[a:b]
        if len(trk) < 5:
            continue
        corner = {}
        for sign, key in ((-1.0, "L"), (1.0, "R")):
            corner[key] = [(float(r[1]), float(r[2]) + sign * float(r[4]) / 2,
                            float(r[3]) + float(r[5]) / 2) for r in trk]
        cr = {k: all_crossings(v, gates, fps) for k, v in corner.items()}
        valid = pair_crossings(corner["L"], corner["R"], gates, fps)
        ins = [c for c in valid if c[2]]
        if not ins:
            continue
        c0 = ins[0]
        # paired?  (a same-gate inward crossing on both corners within win)
        paired = any(x[1] == c0[1] and abs(x[0] - c0[0]) <= win
                     for x in cr["L"] if x[2]) and any(
            x[1] == c0[1] and abs(x[0] - c0[0]) <= win for x in cr["R"] if x[2])
        if paired or (float(trk[-1, 1]) - c0[0]) <= trunc:
            continue
        which = "L" if any(abs(x[0] - c0[0]) < 1e-6 for x in cr["L"]) else "R"
        pop.append((int(trk[0, 0]), c0, which, trk, valid))
    pop.sort(key=lambda t: t[1][0])
    print(f"cam{cam} {variant}: {len(pop)} born-across entries")
    if not pop:
        return 0
    idx = [int(round(i * (len(pop) - 1) / max(n_want - 1, 1)))
           for i in range(min(n_want, len(pop)))]
    sample = [pop[i] for i in idx]

    cap = cv2.VideoCapture(vpath)
    for k, (tid, c0, which, trk, valid) in enumerate(sample, 1):
        f_entry = int(c0[0])
        f_lo = max(0, int(trk[0, 1]) - int(1.0 * fps))
        f_hi = min(int(trk[-1, 1]) + int(1.0 * fps), f_entry + int(8 * fps))
        w0, h0 = float(trk[0, 4]), float(trk[0, 5])
        exits = [c for c in valid if not c[2]]
        out_leg = legs.get(exits[0][1]) if exits else None
        print(f"  #{k} tid {tid}: born f{int(trk[0, 1])} box {w0:.0f}x{h0:.0f} "
              f"at ({trk[0, 2]:.0f},{trk[0, 3]:.0f}); {which} corner crosses "
              f"IN over {legs.get(c0[1])} @f{f_entry} "
              f"(+{(f_entry - trk[0, 1]) / fps:.1f}s after birth); "
              f"track {len(trk)} rows to f{int(trk[-1, 1])}; "
              f"exit {out_leg or 'none'}")
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        frames = []
        for fno in range(f_lo, f_hi):
            ok, fr = cap.read()
            if not ok:
                break
            if (fno - f_lo) % STEP:
                continue
            state = "ENTERING"
            for f, _lg, inward, _p in valid:
                if fno >= f:
                    state = "OCCUPYING" if inward else "EXITED"
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            for lg, (p1, p2, _nrm) in gates.items():
                a = (int(p1[0] * sc), int(p1[1] * sc))
                b = (int(p2[0] * sc), int(p2[1] * sc))
                cv2.line(im, a, b, BLACK, 5)
                cv2.line(im, a, b, MAGENTA, 2)
                cv2.putText(im, str(legs.get(lg, lg)),
                            ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2 - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, MAGENTA, 1)
            col = STATE_COL[state]
            cv2.rectangle(im, (0, 0), (W_OUT, 44), BLACK, -1)
            cv2.putText(im, f"#{k} tid {tid}  {state}", (8, 18),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, col, 2)
            cv2.putText(im, f"born-across: {which} corner IN over "
                        f"{legs.get(c0[1])} @f{f_entry}   f{fno}",
                        (8, 38), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
            seen = trk[trk[:, 1] <= fno]
            if len(seen) >= 2:
                for sign, cc in ((-1.0, (200, 200, 200)), (1.0, (200, 200, 200))):
                    pth = np.stack([seen[:, 2] + sign * seen[:, 4] / 2.0,
                                    seen[:, 3] + seen[:, 5] / 2.0], axis=1)
                    cv2.polylines(im, [(pth * sc).astype(int)], False, BLACK, 3)
                    cv2.polylines(im, [(pth * sc).astype(int)], False, cc, 1)
            if len(seen) and fno <= trk[-1, 1]:
                p = seen[-1]
                x1, x2 = int((p[2] - p[4] / 2) * sc), int((p[2] + p[4] / 2) * sc)
                y1, y2 = int((p[3] - p[5] / 2) * sc), int((p[3] + p[5] / 2) * sc)
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 4)
                cv2.rectangle(im, (x1, y1), (x2, y2), col, 2)
                cx = x1 if which == "L" else x2
                cv2.circle(im, (cx, y2), 6, BLACK, -1)
                cv2.circle(im, (cx, y2), 4, WHITE, -1)
                ox = x2 if which == "L" else x1
                cv2.circle(im, (ox, y2), 6, BLACK, -1)
                cv2.circle(im, (ox, y2), 4, (0, 255, 255), -1)
            frames.append(Image.fromarray(cv2.cvtColor(im, cv2.COLOR_BGR2RGB)))
        out = Path(f"screenshots/born_across_{k}_{tid}.gif")
        q = [f.quantize(96, dither=Image.Dither.NONE) for f in frames]
        q[0].save(out, save_all=True, append_images=q[1:], optimize=True,
                  duration=int(1000 * STEP / fps), loop=0)
        print(f"     -> {out} ({out.stat().st_size // 1024} KB, "
              f"{len(frames)} frames)")
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
