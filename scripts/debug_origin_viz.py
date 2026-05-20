"""Origin-leg attribution diagnosis for Sunnyvale (project 97a7849a, camera 1).

For each origin leg, plot the trajectory's START point on the calibration
frame. If origin assignment is correct, starts should cluster near that
leg's tripwire. If heading-fallback is mis-attributing, starts will scatter.

Also dumps:
  - per-leg event counts
  - per-leg avg start-to-tripwire distance (lower = trajectory really
    came from that leg)
  - candidate tripwire-crossing rate vs heading-fallback rate

Output: screenshots/origin_attribution_sunnyvale.png
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

# Distinct per-leg colors (BGR)
LEG_COLORS = {
    18: (60, 120, 255),    # orange-ish
    19: (255, 180, 60),    # cyan-ish
    20: (60, 255, 120),    # green
    21: (180, 60, 255),    # magenta
}


def tripwire_from_point(p, ref_heading, half=40.0):
    perp = math.radians(ref_heading + 90.0)
    dx, dy = math.sin(perp), -math.cos(perp)
    x, y = float(p[0]), float(p[1])
    return (int(x - dx*half), int(y - dy*half)), (int(x + dx*half), int(y + dy*half))


def get_video_frame(video_path: str, frame_idx: int = 100):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    return frame if ret else None


def dist_point_to_segment(px, py, ax, ay, bx, by):
    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay
    ab_sq = abx*abx + aby*aby
    if ab_sq == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (apx*abx + apy*aby) / ab_sq))
    cx, cy = ax + t*abx, ay + t*aby
    return math.hypot(px - cx, py - cy)


def main():
    conn = sqlite3.connect(str(PROJECT_DB))
    conn.row_factory = sqlite3.Row

    legs = list(conn.execute(
        "SELECT leg_id, label, cardinal_direction, reference_heading, origin_zone "
        "FROM legs WHERE camera_id=1 ORDER BY leg_id"
    ).fetchall())
    leg_by_id = {l["leg_id"]: dict(l) for l in legs}

    cam_video = conn.execute("SELECT path FROM videos WHERE camera_id=1 LIMIT 1").fetchone()
    frame = get_video_frame(cam_video["path"]) if cam_video else None
    if frame is None:
        print("Could not read video frame; using black canvas", file=sys.stderr)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)

    events = list(conn.execute(
        "SELECT event_id, origin_leg_id, destination_leg_id, movement, "
        "       trajectory_data, classifier_path_distance "
        "FROM vehicle_events WHERE camera_id=1 AND rejected=0 ORDER BY event_id"
    ).fetchall())
    print(f"loaded {len(events)} events")

    # Compute synthesized tripwires for each leg
    tripwires: dict[int, tuple] = {}
    for leg in legs:
        oz = json.loads(leg["origin_zone"])
        p = (float(oz[0][0]), float(oz[0][1]))
        t0, t1 = tripwire_from_point(p, leg["reference_heading"])
        tripwires[leg["leg_id"]] = (t0, t1, p)

    # Panel grid: 1 combined + 1 per leg
    n_legs = len(legs)
    panels = {leg["leg_id"]: frame.copy() for leg in legs}
    combined = frame.copy()

    def draw_overlay(img, only_leg_id=None):
        for leg in legs:
            t0, t1, p = tripwires[leg["leg_id"]]
            faded = only_leg_id is not None and leg["leg_id"] != only_leg_id
            color = LEG_COLORS.get(leg["leg_id"], (255, 255, 255))
            if faded:
                color = tuple(int(c*0.3) for c in color)
            cv2.line(img, t0, t1, color, 2 if not faded else 1)
            cv2.circle(img, (int(p[0]), int(p[1])), 6, color, -1)
            cv2.putText(img, f"L{leg['leg_id']} {leg['cardinal_direction']}",
                        (int(p[0])+8, int(p[1])-8),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1, cv2.LINE_AA)

    for img in [combined] + list(panels.values()):
        draw_overlay(img)
    for lid, img in panels.items():
        draw_overlay(img, only_leg_id=lid)  # redraw with fading

    # Plot trajectory STARTS as dots, scaled by trajectory length
    per_leg_starts: dict[int, list] = {l["leg_id"]: [] for l in legs}
    per_leg_dist_to_own_tripwire: dict[int, list] = {l["leg_id"]: [] for l in legs}
    per_leg_dist_to_nearest_tripwire_id: dict[int, list] = {l["leg_id"]: [] for l in legs}

    for ev in events:
        traj = json.loads(ev["trajectory_data"])
        if len(traj) < 2:
            continue
        oid = ev["origin_leg_id"]
        if oid not in LEG_COLORS:
            continue
        start = traj[0]
        per_leg_starts[oid].append(start)

        # Distance from start to this leg's tripwire
        t0, t1, _ = tripwires[oid]
        dist = dist_point_to_segment(start[0], start[1], t0[0], t0[1], t1[0], t1[1])
        per_leg_dist_to_own_tripwire[oid].append(dist)

        # Which leg's tripwire is start CLOSEST to?
        best_lid, best_d = None, float("inf")
        for lid, (a, b, _) in tripwires.items():
            d = dist_point_to_segment(start[0], start[1], a[0], a[1], b[0], b[1])
            if d < best_d:
                best_d = d
                best_lid = lid
        per_leg_dist_to_nearest_tripwire_id[oid].append(best_lid)

        color = LEG_COLORS[oid]
        # Combined: draw start as a small dot
        cv2.circle(combined, (int(start[0]), int(start[1])), 3, color, -1)
        # Per-leg panel: draw start dot + faint trajectory line
        panel = panels[oid]
        pts = np.array([[int(p[0]), int(p[1])] for p in traj], dtype=np.int32)
        cv2.polylines(panel, [pts], False, color, 1, cv2.LINE_AA)
        cv2.circle(panel, (int(start[0]), int(start[1])), 4, color, -1)

    def add_title(img, text):
        cv2.rectangle(img, (0, 0), (img.shape[1], 26), (0, 0, 0), -1)
        cv2.putText(img, text, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1, cv2.LINE_AA)

    add_title(combined, f"ALL n={len(events)} (start-points colored by origin leg)")
    for leg in legs:
        lid = leg["leg_id"]
        starts = per_leg_starts[lid]
        own_dists = per_leg_dist_to_own_tripwire[lid]
        avg_own = sum(own_dists) / len(own_dists) if own_dists else 0
        # How often does the start point actually sit closest to ANOTHER leg's tripwire?
        nearest = per_leg_dist_to_nearest_tripwire_id[lid]
        wrong_nearest = sum(1 for n in nearest if n != lid)
        add_title(panels[lid],
                  f"Origin=L{lid} ({leg['cardinal_direction']}) n={len(starts)} "
                  f"avg_to_own_tripwire={avg_own:.0f}px wrong_nearest={wrong_nearest}/{len(starts)}")

    # 3-row grid: combined + L18; L19 + L20; L21 + legend
    blank = np.zeros_like(combined)
    add_title(blank, "Per-leg findings")
    for i, leg in enumerate(legs):
        lid = leg["leg_id"]
        starts = per_leg_starts[lid]
        own_dists = per_leg_dist_to_own_tripwire[lid]
        avg_own = sum(own_dists) / len(own_dists) if own_dists else 0
        max_own = max(own_dists) if own_dists else 0
        nearest = per_leg_dist_to_nearest_tripwire_id[lid]
        wrong_nearest = sum(1 for n in nearest if n != lid)
        color = LEG_COLORS[lid]
        y = 60 + i*60
        cv2.putText(blank, f"L{lid} ({leg['cardinal_direction']})  n={len(starts)}",
                    (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
        cv2.putText(blank, f"  start->own tripwire: avg {avg_own:.0f}px, max {max_own:.0f}px",
                    (10, y+18), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)
        cv2.putText(blank, f"  start was nearest a DIFFERENT leg's tripwire: {wrong_nearest}/{len(starts)}",
                    (10, y+36), cv2.FONT_HERSHEY_SIMPLEX, 0.4, color, 1)

    row1 = np.hstack([combined, panels[18]])
    row2 = np.hstack([panels[19], panels[20]])
    row3 = np.hstack([panels[21], blank])
    grid = np.vstack([row1, row2, row3])

    out_path = OUT_DIR / "origin_attribution_sunnyvale.png"
    cv2.imwrite(str(out_path), grid)
    print(f"Wrote {out_path} ({grid.shape[1]}x{grid.shape[0]})")

    # Console summary
    print("\n--- Per-leg start-point analysis ---")
    print(f"{'leg':>4} {'n':>4} {'avg_dist':>9} {'wrong_nearest':>14}")
    for leg in legs:
        lid = leg["leg_id"]
        starts = per_leg_starts[lid]
        if not starts:
            print(f"{lid:>4} {0:>4}")
            continue
        own_dists = per_leg_dist_to_own_tripwire[lid]
        nearest = per_leg_dist_to_nearest_tripwire_id[lid]
        wrong = sum(1 for n in nearest if n != lid)
        avg = sum(own_dists) / len(own_dists)
        print(f"{lid:>4} {len(starts):>4} {avg:>9.0f} {wrong:>4}/{len(starts):<10}")

    print("\n--- 'wrong nearest' confusion matrix ---")
    print("rows: assigned origin, cols: nearest tripwire leg")
    print(f"{'':>5} {18:>6} {19:>6} {20:>6} {21:>6}")
    for leg in legs:
        lid = leg["leg_id"]
        nearest = per_leg_dist_to_nearest_tripwire_id[lid]
        counts = {18: 0, 19: 0, 20: 0, 21: 0}
        for n in nearest:
            counts[n] = counts.get(n, 0) + 1
        print(f"L{lid:>3} {counts[18]:>6} {counts[19]:>6} {counts[20]:>6} {counts[21]:>6}")


if __name__ == "__main__":
    main()
