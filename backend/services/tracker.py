"""Multi-object tracker with a pluggable backend.

`VehicleTracker` is the public facade the pipeline constructs; it delegates to a
backend (default ByteTrack via supervision). The backend seam exists so an
alternative tracker (e.g. OC-SORT via boxmot, gated on the Step 0 detection
audit — see docs/implementation_plan_accuracy_2026-05-27.md P2.D) can be added
without touching the pipeline call site or the checkpoint contract. The public
API — update(list[dict], frame) -> list[dict], reset, get_state/load_state
(pickle), get_active_track_ids — is identical across backends.
"""

import pickle

import numpy as np
import supervision as sv

from backend.config import (
    TRACKER_ACTIVATION_THRESHOLD,
    TRACKER_LOST_BUFFER,
    TRACKER_MATCH_THRESHOLD,
    VEHICLE_CLASSES,
)

ALL_CLASSES = VEHICLE_CLASSES


class ByteTrackBackend:
    """supervision ByteTrack backend (the original, default implementation)."""

    def __init__(
        self,
        track_activation_threshold: float = TRACKER_ACTIVATION_THRESHOLD,
        lost_track_buffer: int = TRACKER_LOST_BUFFER,
        minimum_matching_threshold: float = TRACKER_MATCH_THRESHOLD,
        frame_rate: int = 30,
    ):
        self._init_kwargs = {
            "track_thresh": track_activation_threshold,
            "track_buffer": lost_track_buffer,
            "match_thresh": minimum_matching_threshold,
            "frame_rate": frame_rate,
        }
        self.byte_track = sv.ByteTrack(**self._init_kwargs)
        self._active_track_ids: set[int] = set()

    def update(self, detections: list[dict], frame_number: int) -> list[dict]:
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
                    "bbox_width": float(w),
                    "bbox_height": float(h),
                    "bbox_area": float(w * h),
                })

        self._active_track_ids = {r["track_id"] for r in results}
        return results

    def get_active_track_ids(self) -> list[int]:
        return sorted(self._active_track_ids)

    def reset(self):
        self.byte_track = sv.ByteTrack(**self._init_kwargs)
        self._active_track_ids = set()

    def get_state(self) -> bytes:
        return pickle.dumps(self.byte_track)

    def load_state(self, state: bytes):
        self.byte_track = pickle.loads(state)  # noqa: S301


# Backend registry. OC-SORT (boxmot) registers here once the Step 0 audit
# green-lights it; until then only ByteTrack is available and importing boxmot
# is intentionally avoided (no speculative dependency).
_BACKENDS = {
    "bytetrack": ByteTrackBackend,
}


def create_tracker_backend(backend: str, **kwargs):
    """Instantiate a tracker backend by name. Raises on unknown backend."""
    if backend not in _BACKENDS:
        raise ValueError(
            f"Unknown tracker backend {backend!r}. Available: {sorted(_BACKENDS)}"
        )
    return _BACKENDS[backend](**kwargs)


class VehicleTracker:
    """Public tracker facade. Delegates to a pluggable backend.

    Signature is unchanged from the original ByteTrack-only wrapper (so the
    pipeline call site and tests need no changes); `backend` defaults to
    "bytetrack". Adding a backend is a registry entry, not an API change.
    """

    def __init__(
        self,
        track_activation_threshold: float = TRACKER_ACTIVATION_THRESHOLD,
        lost_track_buffer: int = TRACKER_LOST_BUFFER,
        minimum_matching_threshold: float = TRACKER_MATCH_THRESHOLD,
        frame_rate: int = 30,
        backend: str = "bytetrack",
    ):
        self.backend_name = backend
        self._backend = create_tracker_backend(
            backend,
            track_activation_threshold=track_activation_threshold,
            lost_track_buffer=lost_track_buffer,
            minimum_matching_threshold=minimum_matching_threshold,
            frame_rate=frame_rate,
        )

    def update(self, detections: list[dict], frame_number: int) -> list[dict]:
        """Feed new detections, return tracked objects with persistent IDs."""
        return self._backend.update(detections, frame_number)

    def get_active_track_ids(self) -> list[int]:
        """Return list of currently active track IDs."""
        return self._backend.get_active_track_ids()

    def reset(self):
        """Reset the tracker state."""
        self._backend.reset()

    def get_state(self) -> bytes:
        """Serialize tracker state for checkpointing."""
        return self._backend.get_state()

    def load_state(self, state: bytes):
        """Restore tracker state from serialized data."""
        self._backend.load_state(state)
