"""Frame annotation for live processing preview.

Renders bounding boxes, track IDs, and origin zone lines onto a video frame
and returns the result as JPEG bytes.
"""

import numpy as np
import cv2

LEG_COLORS_BGR = [
    (68,  68, 239),   # red   → BGR
    (246, 130, 59),   # blue  → BGR
    (94,  197, 34),   # green → BGR
    (11,  158, 245),  # amber → BGR
]

PREVIEW_MAX_WIDTH = 640


def render_frame_preview(
    frame: np.ndarray,
    tracked: list[dict],
    origin_zones: list[list[list[float]]],
    legs: list[dict],
) -> bytes:
    """Draw bounding boxes and origin zones onto frame, return JPEG bytes.

    Args:
        frame: Raw BGR frame from cv2.
        tracked: List of track dicts with keys: track_id, class_name, is_vehicle,
                 bbox (x1, y1, x2, y2 or similar), center.
        origin_zones: List of zones, each [[x1,y1],[x2,y2]].
        legs: List of leg dicts (used only for count; index maps to LEG_COLORS_BGR).

    Returns:
        JPEG-encoded bytes.

    Raises:
        ValueError: If cv2.imencode fails.
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

    # Draw origin zones as thick colored lines
    for i, zone in enumerate(origin_zones):
        if len(zone) < 2:
            continue
        color = LEG_COLORS_BGR[i % len(LEG_COLORS_BGR)]
        p1 = (int(zone[0][0] * scale), int(zone[0][1] * scale))
        p2 = (int(zone[1][0] * scale), int(zone[1][1] * scale))
        cv2.line(img, p1, p2, color, thickness=3)

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
