"""Frame annotation for live processing preview.

Renders bounding boxes, track IDs, origin zone lines, and trajectory polylines
onto a video frame and returns the result as JPEG bytes.
"""

import numpy as np
import cv2

LEG_COLORS_BGR = [
    (68,  68, 239),   # red   → BGR
    (246, 130, 59),   # blue  → BGR
    (94,  197, 34),   # green → BGR
    (11,  158, 245),  # amber → BGR
]

MOVEMENT_COLORS_BGR = {
    "through": (94, 197, 34),    # green
    "left":    (246, 130, 59),   # blue
    "right":   (11, 158, 245),   # orange/amber
    "uturn":   (68, 68, 239),    # red
}
TRACKING_COLOR_BGR = (180, 180, 180)     # gray — active, origin assigned
UNASSIGNED_COLOR_BGR = (100, 100, 100)   # dark gray — no origin yet

PREVIEW_MAX_WIDTH = 640


def render_frame_preview(
    frame: np.ndarray,
    tracked: list[dict],
    origin_zones: list[list[list[float]]],
    legs: list[dict],
    active_trajectories: dict[int, dict] | None = None,
    finalized_trajectories: list[dict] | None = None,
) -> bytes:
    """Draw bounding boxes, origin nodes, and trajectory polylines onto frame.

    Returns JPEG-encoded bytes.
    """
    img = frame.copy()
    h, w = img.shape[:2]

    # Scale down if wider than PREVIEW_MAX_WIDTH
    scale = 1.0
    if w > PREVIEW_MAX_WIDTH:
        scale = PREVIEW_MAX_WIDTH / w
        new_w = PREVIEW_MAX_WIDTH
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)

    # Draw origin nodes as filled colored circles
    for i, zone in enumerate(origin_zones):
        try:
            if not zone or not zone[0] or len(zone[0]) < 2:
                continue
            color = LEG_COLORS_BGR[i % len(LEG_COLORS_BGR)]
            px = int(zone[0][0] * scale)
            py = int(zone[0][1] * scale)
            cv2.circle(img, (px, py), 14, color, -1)
            label = legs[i].get("cardinal_direction", "") if i < len(legs) else ""
            if label:
                cv2.putText(img, label[:2], (px - 8, py + 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2, cv2.LINE_AA)
        except (IndexError, TypeError, ValueError):
            continue

    # Draw finalized trajectories (movement color, thicker)
    if finalized_trajectories:
        for ftraj in finalized_trajectories:
            traj = ftraj.get("trajectory", [])
            if len(traj) < 2:
                continue
            movement = ftraj.get("movement", "")
            color = MOVEMENT_COLORS_BGR.get(movement, TRACKING_COLOR_BGR)
            pts = np.array(
                [[int(p[0] * scale), int(p[1] * scale)] for p in traj],
                dtype=np.int32,
            )
            cv2.polylines(img, [pts], isClosed=False, color=color, thickness=3, lineType=cv2.LINE_AA)

    # Draw active trajectories (gray/dark gray, thinner)
    if active_trajectories:
        for _tid, info in active_trajectories.items():
            traj = info.get("trajectory", [])
            if len(traj) < 2:
                continue
            color = TRACKING_COLOR_BGR if info.get("origin_leg_id") else UNASSIGNED_COLOR_BGR
            pts = np.array(
                [[int(p[0] * scale), int(p[1] * scale)] for p in traj],
                dtype=np.int32,
            )
            cv2.polylines(img, [pts], isClosed=False, color=color, thickness=2, lineType=cv2.LINE_AA)

    # Draw tracked detections
    for t in tracked:
        track_id = t.get("track_id", 0)
        class_name = t.get("class_name", "")
        is_vehicle = t.get("is_vehicle", True)
        rect_color = (0, 200, 0) if is_vehicle else (200, 100, 0)

        # Support both "bbox" tuple/list and individual x1/y1/x2/y2 keys
        bbox = t.get("bbox")
        if bbox is not None:
            x1, y1, x2, y2 = bbox
        else:
            x1 = t.get("x1", 0)
            y1 = t.get("y1", 0)
            x2 = t.get("x2", 0)
            y2 = t.get("y2", 0)

        x1s = int(x1 * scale)
        y1s = int(y1 * scale)
        x2s = int(x2 * scale)
        y2s = int(y2 * scale)

        cv2.rectangle(img, (x1s, y1s), (x2s, y2s), rect_color, thickness=2)

        label = f"#{track_id} {class_name}"
        cv2.putText(
            img, label,
            (x1s, max(y1s - 4, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            rect_color,
            1,
            cv2.LINE_AA,
        )

    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 75])
    if not ok:
        raise ValueError("cv2.imencode failed to encode frame as JPEG")
    return buf.tobytes()
