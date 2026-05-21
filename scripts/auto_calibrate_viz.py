"""Render an auto-calibration suggestion onto a video frame.

Overlays the entry zones, exit zones, and discovered paths produced by
scripts/auto_calibrate.py onto a chosen frame of the source video so we
can visually validate the clustering output before committing to the
Phase 1 pipeline work.

Usage:
  py scripts/auto_calibrate_viz.py --suggestion PATH [--video PATH] [--frame-seconds S] [--out PATH]
  # Defaults: video read from the suggestion JSON; frame at t=5s;
  #           output to screenshots/auto_cal_<basename>.png
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# BGR colors (OpenCV convention).
MOVEMENT_COLORS = {
    "through":  (110, 230, 110),   # green
    "left":     (255, 170,  60),   # cyan-ish
    "right":    ( 60, 170, 255),   # orange-ish
    "u_turn":   ( 80,  80, 230),   # red
    "insufficient_data": (160, 160, 160),
}
ENTRY_ZONE_COLOR = (255, 255, 255)
EXIT_ZONE_COLOR  = (180, 180, 180)
CONFIDENCE_RING_COLORS = {
    "high":   (  0, 200,   0),   # green
    "medium": (  0, 200, 220),   # yellow
    "low":    (  0,   0, 220),   # red
}


def load_video_frame(video_path: str, seconds: float) -> np.ndarray | None:
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(seconds * fps)))
        ok, frame = cap.read()
        return frame if ok else None
    finally:
        cap.release()


def draw_path(img: np.ndarray, polyline, color, thickness=2) -> None:
    pts = np.array([[int(round(x)), int(round(y))] for x, y in polyline], dtype=np.int32)
    if len(pts) >= 2:
        cv2.polylines(img, [pts], False, color, thickness, cv2.LINE_AA)
        # Mark each control point with a small filled dot.
        for p in pts:
            cv2.circle(img, tuple(p), 2, color, -1, cv2.LINE_AA)
        # Arrowhead at the end.
        tip = pts[-1]
        prev = pts[-2]
        d = tip - prev
        norm = np.linalg.norm(d)
        if norm > 0:
            d = d / norm
            perp = np.array([-d[1], d[0]])
            base = tip - d * 10
            left_pt = (base + perp * 4).astype(int)
            right_pt = (base - perp * 4).astype(int)
            tri = np.array([tip, left_pt, right_pt], dtype=np.int32)
            cv2.fillPoly(img, [tri], color, cv2.LINE_AA)


def draw_zone(img: np.ndarray, center, radius=20, color=(255, 255, 255),
              label=None, confidence_color=None) -> None:
    cx, cy = int(round(center[0])), int(round(center[1]))
    cv2.circle(img, (cx, cy), radius, color, 2, cv2.LINE_AA)
    cv2.circle(img, (cx, cy), 3, color, -1, cv2.LINE_AA)
    if confidence_color is not None:
        cv2.circle(img, (cx, cy), radius + 4, confidence_color, 2, cv2.LINE_AA)
    if label is not None:
        cv2.putText(img, label, (cx + radius + 6, cy + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)


def render(suggestion: dict, video_path: str, frame_seconds: float,
           out_path: Path) -> None:
    frame = load_video_frame(video_path, frame_seconds)
    if frame is None:
        fw, fh = suggestion.get("frame_size", [640, 480])
        frame = np.zeros((fh, fw, 3), dtype=np.uint8)

    img = frame.copy()

    # Paths (drawn first, under the zone markers).
    paths = suggestion.get("paths", [])
    for p in paths:
        color = MOVEMENT_COLORS.get(p.get("movement_label", "insufficient_data"))
        draw_path(img, p["polyline"], color, thickness=2)

    # Exit zones (drawn under entry zones, smaller).
    for z in suggestion.get("exit_zones", []):
        draw_zone(img, z["centroid"], radius=12, color=EXIT_ZONE_COLOR,
                  label=f"x{z['zone_id']}")

    # Entry zones (top layer, with confidence ring + reference-heading arrow).
    for z in suggestion.get("leg_zones", []):
        conf_color = CONFIDENCE_RING_COLORS.get(z.get("confidence", "low"))
        center = z["origin_point"]
        radius = 18
        draw_zone(img, center, radius=radius, color=ENTRY_ZONE_COLOR,
                  label=f"z{z['zone_id']}  n={z['supporting_count']}",
                  confidence_color=conf_color)
        # Reference-heading arrow (approach direction).
        h = z.get("reference_heading")
        if h is not None:
            import math
            cx, cy = int(round(center[0])), int(round(center[1]))
            rad = (h - 90) * math.pi / 180   # convert to canvas angle
            tip = (cx + int(math.cos(rad) * 32), cy + int(math.sin(rad) * 32))
            cv2.arrowedLine(img, (cx, cy), tip, ENTRY_ZONE_COLOR, 2,
                            cv2.LINE_AA, tipLength=0.3)

    # Legend in the lower-left.
    _draw_legend(img, paths)

    # Caption with stats.
    stats = suggestion.get("stats", {})
    caption = (f"auto-cal  legs={len(suggestion.get('leg_zones', []))}  "
               f"paths={len(paths)}  trajectories={stats.get('trajectories_kept', '?')}/"
               f"{stats.get('trajectories_raw', '?')}  "
               f"sample={suggestion.get('sample_window', [])}s")
    cv2.rectangle(img, (0, 0), (img.shape[1], 22), (0, 0, 0), -1)
    cv2.putText(img, caption, (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                (255, 255, 255), 1, cv2.LINE_AA)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out_path), img)
    print(f"wrote {out_path}")


def _draw_legend(img: np.ndarray, paths: list[dict]) -> None:
    """Tiny legend showing movement-color mapping + per-(origin,dest) path counts."""
    if not paths:
        return
    # Aggregate counts per (origin, dest, label).
    rows = []
    for p in sorted(paths, key=lambda q: (q["origin_zone_id"], q["destination_zone_id"])):
        rows.append((f"z{p['origin_zone_id']}->z{p['destination_zone_id']}",
                     p["movement_label"], p["supporting_count"]))
    h_per_row = 14
    box_h = h_per_row * len(rows) + 10
    box_w = 200
    y0 = img.shape[0] - box_h - 10
    x0 = 10
    cv2.rectangle(img, (x0, y0), (x0 + box_w, y0 + box_h), (0, 0, 0), -1)
    cv2.rectangle(img, (x0, y0), (x0 + box_w, y0 + box_h), (90, 90, 90), 1)
    for i, (pair, label, n) in enumerate(rows):
        y = y0 + 8 + i * h_per_row
        color = MOVEMENT_COLORS.get(label, (160, 160, 160))
        cv2.rectangle(img, (x0 + 6, y), (x0 + 18, y + 8), color, -1)
        cv2.putText(img, f"{pair} {label} n={n}", (x0 + 24, y + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (220, 220, 220), 1, cv2.LINE_AA)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suggestion", required=True, help="auto-cal JSON output")
    parser.add_argument("--video", default=None,
                        help="source video (default: read from suggestion)")
    parser.add_argument("--frame-seconds", type=float, default=5.0,
                        help="which frame to render onto, in seconds")
    parser.add_argument("--out", default=None,
                        help="output PNG (default: screenshots/auto_cal_<basename>.png)")
    args = parser.parse_args()

    sug = json.loads(Path(args.suggestion).read_text())
    video = args.video or sug.get("video_path")
    if not video:
        print("no --video given and suggestion JSON has no video_path", file=sys.stderr)
        return 1
    out = Path(args.out) if args.out else (
        Path("screenshots") / f"auto_cal_{Path(args.suggestion).stem}.png"
    )
    render(sug, video, args.frame_seconds, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
