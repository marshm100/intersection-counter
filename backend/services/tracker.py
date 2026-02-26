"""ByteTrack tracker wrapper using the supervision library."""

import pickle

import numpy as np
import supervision as sv

from backend.config import PEDESTRIAN_CLASSES, VEHICLE_CLASSES

ALL_CLASSES = {**VEHICLE_CLASSES, **PEDESTRIAN_CLASSES}


class VehicleTracker:
    """Wraps supervision's ByteTrack for persistent object ID assignment."""

    def __init__(
        self,
        track_activation_threshold: float = 0.25,
        lost_track_buffer: int = 90,
        minimum_matching_threshold: float = 0.8,
        frame_rate: int = 30,
    ):
        """Initialize ByteTrack tracker via supervision library."""
        self._init_kwargs = {
            "track_thresh": track_activation_threshold,
            "track_buffer": lost_track_buffer,
            "match_thresh": minimum_matching_threshold,
            "frame_rate": frame_rate,
        }
        self.byte_track = sv.ByteTrack(**self._init_kwargs)
        self._active_track_ids: set[int] = set()

    def update(self, detections: list[dict], frame_number: int) -> list[dict]:
        """Feed new detections, return tracked objects with persistent IDs."""
        if not detections:
            self.byte_track.update_with_detections(sv.Detections.empty())
            self._active_track_ids = set()
            return []

        xyxy = np.array([d["bbox"] for d in detections], dtype=np.float32)
        confidence = np.array([d["confidence"] for d in detections], dtype=np.float32)
        class_id = np.array([d["class_id"] for d in detections], dtype=int)

        sv_detections = sv.Detections(
            xyxy=xyxy,
            confidence=confidence,
            class_id=class_id,
        )

        tracked = self.byte_track.update_with_detections(sv_detections)

        results = []
        if len(tracked) > 0 and tracked.tracker_id is not None:
            for i in range(len(tracked)):
                track_id = int(tracked.tracker_id[i])
                x1, y1, x2, y2 = tracked.xyxy[i]
                cid = int(tracked.class_id[i]) if tracked.class_id is not None else -1
                conf = float(tracked.confidence[i]) if tracked.confidence is not None else 0.0

                cx = (x1 + x2) / 2
                cy = (y1 + y2) / 2
                w = x2 - x1
                h = y2 - y1

                results.append({
                    "track_id": track_id,
                    "bbox": [float(x1), float(y1), float(x2), float(y2)],
                    "center": [float(cx), float(cy)],
                    "class_id": cid,
                    "class_name": ALL_CLASSES.get(cid, f"class_{cid}"),
                    "confidence": conf,
                    "is_vehicle": cid in VEHICLE_CLASSES,
                    "is_pedestrian": cid in PEDESTRIAN_CLASSES,
                    "bbox_width": float(w),
                    "bbox_height": float(h),
                    "bbox_area": float(w * h),
                })

        self._active_track_ids = {r["track_id"] for r in results}
        return results

    def get_active_track_ids(self) -> list[int]:
        """Return list of currently active track IDs."""
        return sorted(self._active_track_ids)

    def reset(self):
        """Reset the tracker state."""
        self.byte_track = sv.ByteTrack(**self._init_kwargs)
        self._active_track_ids = set()

    def get_state(self) -> bytes:
        """Serialize tracker state for checkpointing."""
        return pickle.dumps(self.byte_track)

    def load_state(self, state: bytes):
        """Restore tracker state from serialized data."""
        self.byte_track = pickle.loads(state)  # noqa: S301
