"""Still: the five cam5 'rights booked as S->N through' over the gate lines (2026-09-11).

The operator ruled the counted (cyan) tracks of the fragment reel are
right turns; the state machine booked four of them S->N gate-full
(IN over S, OUT over N) and one posterior. This still draws each
track's bottom-centre path over the frame with the four gate lines,
births as dots, and its valid crossings as rings, so he can see WHERE
they exit and which line is (not) in their way.
Usage: .venv\Scripts\python.exe -X utf8 scripts/viz_cam5_right_paths.py OUT.png TID [TID...]
"""
from __future__ import annotations
import sqlite3, sys
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.database import leg_geometry_for_camera, list_paths_for_camera
from backend.services.detection_cache import parquet_path
from backend.services.entry_gates import build_gates, pair_crossings
from backend.services.pass2_replay import load_dump, tracks_dir
PROJ, cam, variant = "97a7849a", 5, "l1_study_1600"
out, tids = Path(sys.argv[1]), [int(t) for t in sys.argv[2:]]
con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,)))
geom = leg_geometry_for_camera(PROJ, cam)
gates = build_gates({lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")}, list_paths_for_camera(PROJ, cam),
                    {lg: g.get("heading") for lg, g in geom.items()}, leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})
rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
cap = cv2.VideoCapture(vpath); cap.set(cv2.CAP_PROP_POS_FRAMES, int(rows[rows[:, 0] == float(tids[0])][0, 1])); ok, fr = cap.read(); cap.release()
S = 2; im = cv2.resize(fr, (fr.shape[1] * S, fr.shape[0] * S))
COLS = [(255, 220, 0), (0, 200, 255), (80, 255, 80), (255, 120, 255), (60, 120, 255)]
for lg, (p1, p2, inw) in gates.items():
    a, b = (int(p1[0] * S), int(p1[1] * S)), (int(p2[0] * S), int(p2[1] * S))
    cv2.line(im, a, b, (0, 0, 0), 8); cv2.line(im, a, b, (255, 0, 220), 4)
    m = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
    cv2.putText(im, legs[lg], (m[0] - 10, m[1] - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 0), 6)
    cv2.putText(im, legs[lg], (m[0] - 10, m[1] - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 0, 220), 3)
    # inward arrow at the midpoint
    cv2.arrowedLine(im, m, (int(m[0] + inw[0] * 40), int(m[1] + inw[1] * 40)), (255, 0, 220), 3, tipLength=0.4)
for k, t in enumerate(tids):
    trk = rows[rows[:, 0] == float(t)]; trk = trk[np.argsort(trk[:, 1])]
    col = COLS[k % len(COLS)]
    pth = (np.stack([trk[:, 2], trk[:, 3] + trk[:, 5] / 2], 1) * S).astype(int)
    cv2.polylines(im, [pth], False, (0, 0, 0), 6); cv2.polylines(im, [pth], False, col, 3)
    cv2.circle(im, tuple(pth[0]), 9, (0, 0, 0), -1); cv2.circle(im, tuple(pth[0]), 7, col, -1)
    # last box
    p = trk[-1]; x1, y1, x2, y2 = int((p[2] - p[4] / 2) * S), int((p[3] - p[5] / 2) * S), int((p[2] + p[4] / 2) * S), int((p[3] + p[5] / 2) * S)
    cv2.rectangle(im, (x1, y1), (x2, y2), col, 2)
    corner = {}
    for sign, key in ((-1.0, "L"), (1.0, "R")):
        corner[key] = [(float(r[1]), float(r[2]) + sign * float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
    for f, lg, inw, pt in pair_crossings(corner["L"], corner["R"], gates, fps):
        c = (int(pt[0] * S), int(pt[1] * S))
        cv2.circle(im, c, 14, (0, 0, 0), 4); cv2.circle(im, c, 14, col, 2)
        cv2.putText(im, ("IN " if inw else "OUT ") + legs[lg], (c[0] + 16, c[1] + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 4)
        cv2.putText(im, ("IN " if inw else "OUT ") + legs[lg], (c[0] + 16, c[1] + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7, col, 2)
    cv2.putText(im, f"clip {k + 1}: {t}", (12, 40 + 34 * k), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 6)
    cv2.putText(im, f"clip {k + 1}: {t}", (12, 40 + 34 * k), cv2.FONT_HERSHEY_SIMPLEX, 1.0, col, 2)
out.parent.mkdir(parents=True, exist_ok=True); cv2.imwrite(str(out), im); print("->", out, im.shape)
