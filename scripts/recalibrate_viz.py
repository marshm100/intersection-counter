"""Recalibration visual gate (Phase 3, step 4) — MANDATORY engineer review.

Overlays the data-driven recalibration suggestion on a real video frame so the
engineer can confirm, in a glance, that the new through polylines follow where
the cars actually drive and the recalibrated leg headings make sense. The
data-only signal is confounded by the mid-turn-entry problem, so this human gate
is required before applying. See docs/recalibration_plan_2026-05-27.md.

Renders: faded sample trajectories (gray), the suggestion's path polylines
(colored by movement), recalibrated leg origins + reference_heading arrows, and a
panel of manual vs assigned counts.

Usage:
  py scripts/recalibrate_viz.py --frame 251980
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from groundtruth import ALL_MVT, db_processed_window
from recalibrate_camera import APPROACH_TO_LEG, manual_for_window
from replay_attribution_changes import PROJECT_DB, load_events

MOVE_COLOR = {"through": (0, 200, 0), "left": (255, 120, 0),
              "right": (0, 140, 255), "u_turn": (200, 0, 200)}


def _video_path():
    c = sqlite3.connect(str(PROJECT_DB))
    p = c.execute("SELECT path FROM videos WHERE camera_id=1 ORDER BY sort_order LIMIT 1").fetchone()[0]
    c.close()
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suggestion", default="evaluations/recal_cam1.json")
    ap.add_argument("--frame", type=int, default=251980)  # 07:00:00 @ 10fps
    ap.add_argument("--out", default="screenshots/recal_cam1_7am.png")
    args = ap.parse_args()

    sug = json.loads(Path(args.suggestion).read_text())

    cap = cv2.VideoCapture(_video_path())
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        # fall back to a black canvas sized from the suggestion polylines
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
    h, w = frame.shape[:2]
    canvas = frame.copy()

    # faded sample trajectories
    c = sqlite3.connect(str(PROJECT_DB))
    trajs = [e["trajectory"] for e in load_events(c) if e["trajectory"] and len(e["trajectory"]) >= 4]
    c.close()
    overlay = canvas.copy()
    for t in trajs:
        pts = np.array(t, dtype=np.int32)
        cv2.polylines(overlay, [pts], False, (180, 180, 180), 1, cv2.LINE_AA)
    canvas = cv2.addWeighted(overlay, 0.35, canvas, 0.65, 0)

    # suggestion path polylines, colored by movement, thick
    for p in sug["paths"]:
        col = MOVE_COLOR.get(p["movement_label"], (255, 255, 255))
        pts = np.array(p["polyline"], dtype=np.int32)
        cv2.polylines(canvas, [pts], False, col, 3, cv2.LINE_AA)
        mid = pts[len(pts) // 2]
        cv2.putText(canvas, f"L{p['origin_leg_id']} {p['movement_label']} n={p['supporting_count']}",
                    (int(mid[0]) + 4, int(mid[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 2, cv2.LINE_AA)

    # recalibrated leg origins + heading arrows
    for lg in sug["updated_legs"]:
        ox, oy = lg["origin_point"]
        cv2.circle(canvas, (int(ox), int(oy)), 6, (0, 255, 255), -1)
        r = math.radians(lg["reference_heading"])
        dx, dy = math.sin(r), -math.cos(r)
        cv2.arrowedLine(canvas, (int(ox), int(oy)),
                        (int(ox + dx * 55), int(oy + dy * 55)), (0, 255, 255), 2, tipLength=0.3)
        cv2.putText(canvas, f"L{lg['leg_id']} {lg.get('approach','')} ref={lg['reference_heading']:.0f}",
                    (int(ox) + 8, int(oy) - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

    # manual vs assigned panel
    window = db_processed_window()
    manual = manual_for_window(window)
    assigned = {}
    for p in sug["paths"]:
        appr = next((a for a, l in APPROACH_TO_LEG.items() if l == p["origin_leg_id"]), "?")
        mv = {"through": "thru", "u_turn": "uturn"}.get(p["movement_label"], p["movement_label"])
        assigned[(appr, mv)] = assigned.get((appr, mv), 0) + p["supporting_count"]
    panel = [f"window {window[0]:.0f}-{window[1]:.0f}s   axis {sug.get('arterial_axis_deg')}",
             "approach/mvt        manual  ours"]
    for appr in APPROACH_TO_LEG:
        for m in ALL_MVT:
            man = manual[appr][m]
            asg = assigned.get((appr, m), 0)
            if man < 0.5 and asg == 0:
                continue
            panel.append(f"{appr[:14]:<14} {m:<5} {man:>6.1f} {asg:>5}")
    y = 18
    for line in panel:
        cv2.putText(canvas, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(canvas, line, (8, y), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
        y += 16

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(args.out, canvas)
    print(f"wrote overlay -> {args.out}  ({w}x{h}, {len(sug['paths'])} paths, "
          f"{len(sug['updated_legs'])} legs, {len(trajs)} sample tracks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
