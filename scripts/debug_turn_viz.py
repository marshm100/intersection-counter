"""One-shot debug visualization for Sunnyvale (project 97a7849a, camera 1).

Reads all vehicle_events for camera 1, overlays trajectories on a sample
video frame, colored by classifier movement. Marks each leg origin and
its synthesized tripwire so we can eyeball where classification goes
wrong. Output: screenshots/turn_debug_sunnyvale.png
"""
import json
import math
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

PROJECT_DB = Path("data/projects/97a7849a/project.db")
OUT_DIR = Path("screenshots")
OUT_DIR.mkdir(parents=True, exist_ok=True)

MOVEMENT_COLORS = {
    "through": (200, 200, 200),  # gray-white
    "left":    (255, 120,  60),  # orange-ish (BGR)
    "right":   ( 60, 200, 255),  # cyan
    "u_turn":  ( 60,  60, 255),  # red
}
LEG_COLOR = (0, 255, 0)
TRIPWIRE_COLOR = (0, 200, 0)


def tripwire_from_point(p, ref_heading, half=40.0):
    perp = math.radians(ref_heading + 90.0)
    dx = math.sin(perp); dy = -math.cos(perp)
    x, y = float(p[0]), float(p[1])
    return (int(x - dx*half), int(y - dy*half)), (int(x + dx*half), int(y + dy*half))


def heading_arrow(origin, ref_heading, length=50):
    rad = math.radians(ref_heading)
    dx = math.sin(rad); dy = -math.cos(rad)
    return (int(origin[0]), int(origin[1])), (int(origin[0] + dx*length), int(origin[1] + dy*length))


def get_video_frame(video_path: str, frame_idx: int = 100):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def main():
    conn = sqlite3.connect(str(PROJECT_DB))
    conn.row_factory = sqlite3.Row

    legs = list(conn.execute(
        "SELECT leg_id, label, cardinal_direction, reference_heading, origin_zone "
        "FROM legs WHERE camera_id=1 ORDER BY leg_id"
    ).fetchall())

    cam_video = conn.execute(
        "SELECT path FROM videos WHERE camera_id=1 LIMIT 1"
    ).fetchone()
    frame = get_video_frame(cam_video["path"]) if cam_video else None
    if frame is None:
        print(f"  Could not read video frame; using black canvas", file=sys.stderr)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

    events = list(conn.execute(
        "SELECT event_id, origin_leg_id, destination_leg_id, movement, "
        "       destination_confidence, classifier_num_points, "
        "       classifier_path_distance, trajectory_data "
        "FROM vehicle_events WHERE camera_id=1 AND rejected=0 "
        "ORDER BY event_id"
    ).fetchall())
    print(f"loaded {len(events)} events")

    # 4-panel layout: one per movement class
    panels = {m: frame.copy() for m in MOVEMENT_COLORS}
    combined = frame.copy()

    leg_lookup = {r["leg_id"]: dict(r) for r in legs}

    def draw_legs_and_tripwires(img):
        for leg in legs:
            oz = json.loads(leg["origin_zone"])
            p = (int(oz[0][0]), int(oz[0][1]))
            t0, t1 = tripwire_from_point(p, leg["reference_heading"])
            cv2.line(img, t0, t1, TRIPWIRE_COLOR, 2)
            cv2.circle(img, p, 6, LEG_COLOR, -1)
            arrow_from, arrow_to = heading_arrow(p, leg["reference_heading"])
            cv2.arrowedLine(img, arrow_from, arrow_to, LEG_COLOR, 2, tipLength=0.3)
            cv2.putText(img, f"L{leg['leg_id']} ({leg['cardinal_direction']}) "
                             f"{leg['reference_heading']:.0f}",
                        (p[0]+8, p[1]-8), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                        (0,255,0), 1, cv2.LINE_AA)

    for img in [combined] + list(panels.values()):
        draw_legs_and_tripwires(img)

    # Draw trajectories
    counts = {m: 0 for m in MOVEMENT_COLORS}
    for ev in events:
        traj = json.loads(ev["trajectory_data"])
        if len(traj) < 2:
            continue
        movement = ev["movement"]
        color = MOVEMENT_COLORS.get(movement, (255,255,255))
        pts = np.array([[int(p[0]), int(p[1])] for p in traj], dtype=np.int32)

        target_imgs = [combined, panels[movement]]
        for img in target_imgs:
            cv2.polylines(img, [pts], False, color, 1, cv2.LINE_AA)
            # start dot
            cv2.circle(img, tuple(pts[0]), 3, (255,255,0), -1)
            # end dot
            cv2.circle(img, tuple(pts[-1]), 3, color, -1)
        counts[movement] += 1

    def add_title(img, text):
        cv2.rectangle(img, (0,0), (640, 26), (0,0,0), -1)
        cv2.putText(img, text, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255,255,255), 1, cv2.LINE_AA)

    add_title(combined, f"ALL n={sum(counts.values())} | tripwires=green | start=yellow end=movement-color")
    for m, img in panels.items():
        add_title(img, f"{m.upper()} n={counts[m]}  color BGR={MOVEMENT_COLORS[m]}")

    # 2x3 grid: combined | through ; left | right ; u_turn | (legend)
    blank = np.zeros_like(combined)
    add_title(blank, "Legend")
    cv2.putText(blank, "tripwires (green lines)", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, TRIPWIRE_COLOR, 1)
    cv2.putText(blank, "leg origin + heading arrow", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, LEG_COLOR, 1)
    cv2.putText(blank, "trajectory start: yellow dot", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,0), 1)
    cv2.putText(blank, "trajectory end: movement color", (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255,255,255), 1)
    for i, m in enumerate(["through","left","right","u_turn"]):
        y = 200 + i*30
        cv2.line(blank, (10, y), (50, y), MOVEMENT_COLORS[m], 2)
        cv2.putText(blank, f"{m}  n={counts[m]}", (60, y+5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, MOVEMENT_COLORS[m], 1)

    row1 = np.hstack([combined, panels["through"]])
    row2 = np.hstack([panels["left"], panels["right"]])
    row3 = np.hstack([panels["u_turn"], blank])
    grid = np.vstack([row1, row2, row3])

    out_path = OUT_DIR / "turn_debug_sunnyvale.png"
    cv2.imwrite(str(out_path), grid)
    print(f"Wrote {out_path} ({grid.shape[1]}x{grid.shape[0]})")

    # Also dump per-event details for the 18->20 "left" set we flagged
    print("\n--- 18 -> 20 'left' trajectories (the 22 suspicious ones) ---")
    print(f"{'event':>6} {'pts':>4} {'dist_px':>8} {'dest_conf':>9}")
    for ev in events:
        if ev["origin_leg_id"] == 18 and ev["destination_leg_id"] == 20:
            print(f"{ev['event_id']:>6} {ev['classifier_num_points']:>4} "
                  f"{ev['classifier_path_distance']:>8.0f} "
                  f"{ev['destination_confidence']:>9.2f}")

    print("\n--- short 'through' trajectories (<=8 points, suspect 'rescued') ---")
    print(f"{'event':>6} {'orig':>4} {'dest':>4} {'pts':>4} {'dist_px':>8} {'dest_conf':>9}")
    n_short_through = 0
    for ev in events:
        if ev["movement"] == "through" and ev["classifier_num_points"] <= 8:
            print(f"{ev['event_id']:>6} {ev['origin_leg_id']:>4} "
                  f"{ev['destination_leg_id']:>4} "
                  f"{ev['classifier_num_points']:>4} "
                  f"{ev['classifier_path_distance']:>8.0f} "
                  f"{ev['destination_confidence']:>9.2f}")
            n_short_through += 1
    print(f"({n_short_through} short 'through' events of {counts['through']} total)")


if __name__ == "__main__":
    main()
