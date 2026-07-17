"""Visualize the phantom turn attribution: legs + phantom trajectories on a frame.

Phantom SB-left (60) and NB-right (46) all get destination L24 (WB Private
Driveway). This overlays the 4 leg origins + heading arrows, the phantom
trajectories (SB-left red, NB-right blue), and faded real tracks (gray) so we can
SEE whether L24/L25 are mis-placed and why everything ending lower-right snaps to
L24. Usage:  py scripts/viz_phantoms.py
"""
from __future__ import annotations
import json, math, sqlite3, sys
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB = "data/projects/97a7849a/_hybrid_tmp/oc.db"
LEG_COL = {22: (0, 255, 255), 23: (0, 255, 0), 24: (0, 0, 255), 25: (255, 0, 255)}


def main() -> int:
    frame_idx = 252030
    c = sqlite3.connect(DB)
    vp = c.execute("SELECT path FROM videos WHERE camera_id=1 ORDER BY sort_order LIMIT 1").fetchone()[0]
    cap = cv2.VideoCapture(vp); cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read(); cap.release()
    if not ok: frame = np.zeros((480, 640, 3), np.uint8)

    # faded real tracks (sample)
    ov = frame.copy()
    for (tj,) in c.execute("SELECT trajectory_data FROM vehicle_events WHERE camera_id=1 AND rejected=0 LIMIT 1200"):
        if tj:
            cv2.polylines(ov, [np.array(json.loads(tj), np.int32)], False, (170, 170, 170), 1, cv2.LINE_AA)
    frame = cv2.addWeighted(ov, 0.3, frame, 0.7, 0)

    # phantom trajectories
    for ol, mv, col in [(22, "left", (0, 0, 255)), (23, "right", (255, 0, 0))]:
        for (tj,) in c.execute("SELECT trajectory_data FROM vehicle_events WHERE camera_id=1 AND rejected=0 AND origin_leg_id=? AND movement=?", (ol, mv)):
            if tj:
                cv2.polylines(frame, [np.array(json.loads(tj), np.int32)], False, col, 1, cv2.LINE_AA)

    # legs: origin dot + heading arrow + label
    for lid, lab, oz, ref in c.execute("SELECT leg_id,label,origin_zone,reference_heading FROM legs WHERE camera_id=1"):
        if not oz: continue
        ox, oy = json.loads(oz)[0]; col = LEG_COL.get(lid, (255, 255, 255))
        cv2.circle(frame, (int(ox), int(oy)), 7, col, -1)
        r = math.radians(ref); dx, dy = math.sin(r), -math.cos(r)
        cv2.arrowedLine(frame, (int(ox), int(oy)), (int(ox+dx*60), int(oy+dy*60)), col, 2, tipLength=0.3)
        cv2.putText(frame, f"L{lid} ref={ref:.0f}", (int(ox)+8, int(oy)-6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2, cv2.LINE_AA)
    c.close()
    cv2.putText(frame, "phantom SB-left=RED  NB-right=BLUE  (both dest L24)", (6, 472), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
    out = "screenshots/phantoms_7am.png"
    cv2.imwrite(out, frame); print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
