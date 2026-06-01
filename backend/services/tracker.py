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


class OcSortBackend:
    """OC-SORT backend (boxmot). Motion-based (observation-centric momentum +
    virtual-trajectory gap recovery), so it sustains tracks through turns and
    short detection gaps far better than IoU-only ByteTrack — the gap diagnosed
    at the Sunnyvale camera (turning vehicles fragmented into straight stubs).

    boxmot is imported lazily so this module still imports without the dep.
    OC-SORT is appearance-free, so update() needs only a dummy frame of the
    right size for bounds; we never decode real frames for it.
    """

    def __init__(
        self,
        track_activation_threshold: float = TRACKER_ACTIVATION_THRESHOLD,
        lost_track_buffer: int = TRACKER_LOST_BUFFER,
        minimum_matching_threshold: float = TRACKER_MATCH_THRESHOLD,
        frame_rate: int = 30,
        frame_size: tuple[int, int] = (480, 640),
        # min_hits=3 (vs OC-SORT's looser 2) suppresses spurious short tracks
        # (the fragments that inflate counts); inertia=0.4 (vs 0.2) trusts the
        # motion model more, reducing ID-switches on dense linear queues. Tuned
        # on the Sunnyvale cam1 30-min window (per-minute gross 35.7%->30.3%,
        # NB-left turn recovery preserved) — both are sane general OC-SORT
        # values, not scene-specific. See docs/dedup_plan_2026-05-29.md.
        min_hits: int = 3,
        delta_t: int = 3,
        inertia: float = 0.4,
        # use_byte=True runs OC-SORT's second association round on LOW-confidence
        # detections (below det_thresh). On a dense linear queue those marginal
        # boxes cause ID-switches that split one through vehicle into two tracks
        # (the Sunnyvale SB-through overcount); use_byte=False / a higher
        # det_thresh trades a little recall for fewer such switches. det_thresh
        # defaults to the activation threshold when None.
        use_byte: bool = True,
        det_thresh: float | None = None,
    ):
        from boxmot.trackers.ocsort.ocsort import OcSort  # lazy
        eff_det_thresh = track_activation_threshold if det_thresh is None else det_thresh
        self._init_kwargs = dict(
            min_conf=track_activation_threshold, delta_t=delta_t, inertia=inertia,
            use_byte=use_byte,
        )
        self._base_kwargs = dict(
            det_thresh=eff_det_thresh, max_age=lost_track_buffer,
            min_hits=min_hits, iou_threshold=1.0 - minimum_matching_threshold,
        )
        self._OcSort = OcSort
        self.ocsort = OcSort(**self._init_kwargs, **self._base_kwargs)
        self._img = np.zeros((frame_size[0], frame_size[1], 3), dtype=np.uint8)
        self._active_track_ids: set[int] = set()

    def update(self, detections: list[dict], frame_number: int) -> list[dict]:
        if not detections:
            dets = np.empty((0, 6), dtype=np.float32)
        else:
            dets = np.array(
                [[*d["bbox"], d["confidence"], d["class_id"]] for d in detections],
                dtype=np.float32,
            )
        tracked = np.asarray(self.ocsort.update(dets, self._img))
        results = []
        for row in tracked:
            x1, y1, x2, y2 = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            track_id = int(row[4]); conf = float(row[5]); cid = int(row[6])
            w, h = x2 - x1, y2 - y1
            results.append({
                "track_id": track_id,
                "bbox": [x1, y1, x2, y2],
                "center": [(x1 + x2) / 2, (y1 + y2) / 2],
                "class_id": cid,
                "class_name": ALL_CLASSES.get(cid, f"class_{cid}"),
                "confidence": conf,
                "is_vehicle": cid in VEHICLE_CLASSES,
                "bbox_width": w, "bbox_height": h, "bbox_area": w * h,
            })
        self._active_track_ids = {r["track_id"] for r in results}
        return results

    def get_active_track_ids(self) -> list[int]:
        return sorted(self._active_track_ids)

    def reset(self):
        self.ocsort = self._OcSort(**self._init_kwargs, **self._base_kwargs)
        self._active_track_ids = set()

    def get_state(self) -> bytes:
        return pickle.dumps(self.ocsort)

    def load_state(self, state: bytes):
        self.ocsort = pickle.loads(state)  # noqa: S301


class BotSortBackend:
    """BoT-SORT backend (boxmot), motion-only (with_reid=False). Its association
    (IoU + Kalman, ByteTrack-style high/low two-stage) is less momentum-reliant
    than OC-SORT's observation-centric model, which mispredicts on SHARP turns
    (the Sunnyvale EB cross-street turns: the boxes exist across the curve — the
    greedy NN-linker recovers ~22 — but OC-SORT's momentum breaks the track and
    only ~4 survive). cmc_method='none' because this is a STATIC camera, so no
    image is needed → runs on the bbox-only detection cache like OC-SORT.
    """

    def __init__(
        self,
        track_activation_threshold: float = TRACKER_ACTIVATION_THRESHOLD,
        lost_track_buffer: int = TRACKER_LOST_BUFFER,
        minimum_matching_threshold: float = TRACKER_MATCH_THRESHOLD,
        frame_rate: int = 30,
        frame_size: tuple[int, int] = (480, 640),
        new_track_thresh: float = 0.3,
        track_low_thresh: float = 0.1,
        # ReID (Stage 1, docs/reid_project_plan_2026-06-01.md). When with_reid is
        # True we feed PRE-COMPUTED appearance embeddings (from the sidecar built by
        # scripts/build_reid_cache.py) via boxmot's embs= path — so reid_model stays
        # None (no get_features call, no per-frame video decode) and the bbox-cache
        # iteration loop is preserved. reid_embeddings is a provider exposing
        # embs_for(frame_number, detections) -> (N,512) float32 aligned to detections.
        with_reid: bool = False,
        reid_embeddings=None,
        proximity_thresh: float | None = None,
        appearance_thresh: float | None = None,
    ):
        from boxmot.trackers.botsort.botsort import BotSort  # lazy
        self._with_reid = bool(with_reid)
        self._reid = reid_embeddings if self._with_reid else None
        self._kwargs = dict(
            reid_model=None, with_reid=self._with_reid, cmc_method="ecc",
            track_high_thresh=track_activation_threshold,
            track_low_thresh=track_low_thresh,
            new_track_thresh=new_track_thresh,
            track_buffer=lost_track_buffer,
            match_thresh=minimum_matching_threshold,
            frame_rate=frame_rate,
        )
        if proximity_thresh is not None:
            self._kwargs["proximity_thresh"] = proximity_thresh
        if appearance_thresh is not None:
            self._kwargs["appearance_thresh"] = appearance_thresh
        self._BotSort = BotSort
        self.bot = BotSort(**self._kwargs)
        self._img = np.zeros((frame_size[0], frame_size[1], 3), dtype=np.uint8)
        self._active_track_ids: set[int] = set()

    def update(self, detections: list[dict], frame_number: int) -> list[dict]:
        if not detections:
            dets = np.empty((0, 6), dtype=np.float32)
        else:
            dets = np.array(
                [[*d["bbox"], d["confidence"], d["class_id"]] for d in detections],
                dtype=np.float32,
            )
        if self._with_reid and self._reid is not None:
            embs = self._reid.embs_for(frame_number, detections)  # (N,512), aligned
            tracked = np.asarray(self.bot.update(dets, self._img, embs=embs))
        else:
            tracked = np.asarray(self.bot.update(dets, self._img))
        results = []
        for row in tracked:
            if len(row) < 7:
                continue
            x1, y1, x2, y2 = float(row[0]), float(row[1]), float(row[2]), float(row[3])
            track_id = int(row[4]); conf = float(row[5]); cid = int(row[6])
            w, h = x2 - x1, y2 - y1
            results.append({
                "track_id": track_id,
                "bbox": [x1, y1, x2, y2],
                "center": [(x1 + x2) / 2, (y1 + y2) / 2],
                "class_id": cid,
                "class_name": ALL_CLASSES.get(cid, f"class_{cid}"),
                "confidence": conf,
                "is_vehicle": cid in VEHICLE_CLASSES,
                "bbox_width": w, "bbox_height": h, "bbox_area": w * h,
            })
        self._active_track_ids = {r["track_id"] for r in results}
        return results

    def get_active_track_ids(self) -> list[int]:
        return sorted(self._active_track_ids)

    def reset(self):
        self.bot = self._BotSort(**self._kwargs)
        self._active_track_ids = set()

    def get_state(self) -> bytes:
        return pickle.dumps(self.bot)

    def load_state(self, state: bytes):
        self.bot = pickle.loads(state)  # noqa: S301


# NB: a position-NN track-recovery wrapper over OC-SORT was tried 2026-05-29 and
# REMOVED as net-harmful: on the dense arterial OC-SORT does drop-and-respawn and
# the nearby respawn is a FOLLOWER -> wrong merge (NB-thru 150->77, NB-left
# 97->34), while it did NOT recover the sharp EB turns at all (OC doesn't respawn
# a catchable nearby id there — turn-sustaining is BoT-SORT's *association*
# property, not post-hoc recoverable). Position-based sequential recovery is a
# dead end at this scene; the robust turn fix needs BoT-style association or ReID.

# Backend registry. ByteTrack is the default; OC-SORT/BoT-SORT (boxmot) are
# opt-in. boxmot is imported lazily inside each backend so this module imports
# fine without the dependency installed.
_BACKENDS = {
    "bytetrack": ByteTrackBackend,
    "ocsort": OcSortBackend,
    "botsort": BotSortBackend,
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
        # Extra backend-specific constructor kwargs (e.g. OC-SORT use_byte,
        # det_thresh, inertia, min_hits). Splatted into the backend ctor.
        backend_kwargs: dict | None = None,
    ):
        self.backend_name = backend
        self._backend = create_tracker_backend(
            backend,
            track_activation_threshold=track_activation_threshold,
            lost_track_buffer=lost_track_buffer,
            minimum_matching_threshold=minimum_matching_threshold,
            frame_rate=frame_rate,
            **(backend_kwargs or {}),
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
