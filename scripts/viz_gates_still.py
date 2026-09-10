"""One still per camera with the operator's drawn geometry overlaid
(2026-09-10, for his ruling on cam4 / cam5's gates).

  magenta solid   the gate the crossing law uses (build_gates)
  magenta dotted  its +25% extension (GATE_EXTENSION_MARGIN)
  cyan dot        the drawn mouth point
  label           leg cardinal at the gate's midpoint, arrow = inward

Writes screenshots/gates_cam{N}.png (full frame). Prints each gate's
endpoints and length so the numbers travel with the picture.
Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/viz_gates_still.py [CAM ...]
"""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import GATE_EXTENSION_MARGIN  # noqa: E402
from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.entry_gates import build_gates, extend_gates  # noqa: E402

PROJ = "97a7849a"
MAGENTA, CYAN, BLACK, WHITE = (255, 0, 220), (255, 220, 0), (0, 0, 0), (255, 255, 255)


def main() -> int:
    cams = [int(a) for a in sys.argv[1:]] or [1, 2, 3, 4, 5]
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    for cam in cams:
        vpath, fps = con.execute(
            "SELECT path, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
        legs = dict(con.execute(
            "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,)))
        geom = leg_geometry_for_camera(PROJ, cam)
        gates = build_gates(
            {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
            list_paths_for_camera(PROJ, cam),
            {lg: g.get("heading") for lg, g in geom.items()},
            leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})
        ext = extend_gates(gates, GATE_EXTENSION_MARGIN)
        cap = cv2.VideoCapture(vpath)
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * 0.35))     # mid-morning-ish
        ok, fr = cap.read()
        cap.release()
        if not ok:
            print(f"cam{cam}: no frame")
            continue
        print(f"\n=== cam{cam} ({fr.shape[1]}x{fr.shape[0]}, {fps:.0f} fps) ===")
        for lg, g in geom.items():
            if g.get("mouth"):
                mx_, my_ = int(g["mouth"][0]), int(g["mouth"][1])
                cv2.circle(fr, (mx_, my_), 9, BLACK, -1)
                cv2.circle(fr, (mx_, my_), 7, CYAN, -1)
        for lg, (p1, p2, inw) in gates.items():
            e1, e2 = ext[lg][:2]
            # dotted extension
            for seg in ((e1, p1), (p2, e2)):
                a, b = seg
                L = math.hypot(b[0] - a[0], b[1] - a[1])
                steps = max(1, int(L / 8))
                for k in range(0, steps, 2):
                    x0 = a[0] + (b[0] - a[0]) * k / steps
                    y0 = a[1] + (b[1] - a[1]) * k / steps
                    x1 = a[0] + (b[0] - a[0]) * (k + 1) / steps
                    y1 = a[1] + (b[1] - a[1]) * (k + 1) / steps
                    cv2.line(fr, (int(x0), int(y0)), (int(x1), int(y1)), MAGENTA, 2)
            a, b = (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1]))
            cv2.line(fr, a, b, BLACK, 6)
            cv2.line(fr, a, b, MAGENTA, 3)
            mx, my = (a[0] + b[0]) // 2, (a[1] + b[1]) // 2
            tip = (int(mx + inw[0] * 28), int(my + inw[1] * 28))
            cv2.arrowedLine(fr, (mx, my), tip, BLACK, 4, tipLength=0.4)
            cv2.arrowedLine(fr, (mx, my), tip, WHITE, 2, tipLength=0.4)
            label = str(legs.get(lg, lg))
            cv2.putText(fr, label, (mx - 8, my - 10), cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, BLACK, 4)
            cv2.putText(fr, label, (mx - 8, my - 10), cv2.FONT_HERSHEY_SIMPLEX,
                        0.9, MAGENTA, 2)
            L = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
            print(f"  gate {label:>2}: ({p1[0]:.0f},{p1[1]:.0f}) -> ({p2[0]:.0f},{p2[1]:.0f})"
                  f"  {L:.0f}px  inward ({inw[0]:+.2f},{inw[1]:+.2f})"
                  f"  mouth {'drawn' if geom.get(lg, {}).get('gate') else 'derived'}")
        cv2.rectangle(fr, (0, 0), (fr.shape[1], 26), BLACK, -1)
        cv2.putText(fr, f"cam{cam}  magenta=gate  dotted=+25%  cyan dot=mouth  arrow=inward",
                    (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, WHITE, 1)
        out = Path(f"screenshots/gates_cam{cam}.png")
        cv2.imwrite(str(out), fr)
        print(f"  -> {out} ({out.stat().st_size // 1024} KB)")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
