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
from collections import deque as _deque

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
    only ~4 survive). cmc_method=None DISABLES global motion compensation —
    correct for a STATIC camera fed the bbox-only detection cache with a blank
    image. NB: pass Python None, not the STRING 'none' (which raises in boxmot 18
    — get_cmc_method only treats None as "disabled"). The prior 'ecc' fell through
    to running ECC against the blank frame EVERY frame → failed-to-converge →
    identity warp: a no-op that only burned cycles and spewed warnings.
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
            reid_model=None, with_reid=self._with_reid, cmc_method=None,
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
        from backend import config as _cfg
        if getattr(_cfg, "EMERGENCE_GUARD", False):
            BotSort = _emergence_botsort_class()   # production-recipe guard
        self._BotSort = BotSort
        self.bot = BotSort(**self._kwargs)
        self._img = np.zeros((frame_size[0], frame_size[1], 3), dtype=np.uint8)
        self._active_track_ids: set[int] = set()

    def update(self, detections: list[dict], frame_number: int) -> list[dict]:
        # The bot's internal frame_count is LOCAL (1..N from tracker
        # birth); dump rows are stamped with the ABSOLUTE video frame.
        # Hand the bot the absolute frame so anything it records for
        # the dump post-pass (gate_breaks) is minted in ROW units — a
        # local frame in gate_breaks made every re-stamp select the old
        # track's whole life (frame >= small_local is always true),
        # turning each intended split into a whole-track rename.
        self.bot._abs_now = int(frame_number)
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


def _emergence_botsort_class():
    """Anti-theft campaign (2026-09-06): the emergence guard mounted on
    the PRODUCTION recipes (plain botsort / botsort+reid) — the shipped
    dumps never ran botsort_locked, so the guard must ride the library
    class the cameras actually use. Copies of _loss_profile /
    _emergence_row live in GatedBotSort too (the campaign's copy-body
    precedent); behavior is identical, only the bus-law/flip machinery
    is absent here. bytetrack cameras (4, 5) have no mount point —
    chartered follow-up."""
    import math

    import numpy as np
    from boxmot.trackers.botsort.basetrack import TrackState
    from boxmot.trackers.botsort.botsort import BotSort, STrack
    from boxmot.utils.matching import (embedding_distance, fuse_score,
                                       iou_distance, linear_assignment)

    from backend.config import EMERGENCE_SIZE_FLOOR
    from backend.services.track_chains import (
        CHAIN_BEARING_D_MIN, CHAIN_DIR_TOL_DEG, STITCH_MOVE_DIST,
        STITCH_MOVE_GAP_S, STITCH_STAT_DIST, STITCH_STAT_SPEED_PXS)
    from backend.services.track_cut import _bdiff, _bearing

    def _center(xyxy):
        return ((float(xyxy[0]) + float(xyxy[2])) / 2.0,
                (float(xyxy[1]) + float(xyxy[3])) / 2.0)

    class EmergenceBotSort(BotSort):
        GATE_GRACE_S = 0.5
        RECOVERY_COST_LO = 0.55
        RECOVERY_COST_HI = 0.90

        def __init__(self, *args, **kwargs):
            self._gate_fr = int(kwargs.get("frame_rate") or 30)
            self._emergence_on = True
            self.emergence_vetoes = 0
            super().__init__(*args, **kwargs)

        def _expire_movers(self):
            window = STITCH_MOVE_GAP_S[1] * self._gate_fr
            kept = []
            for t in self.lost_stracks:
                if self.frame_count - t.end_frame > window:
                    prof = self._loss_profile(t)
                    if prof is not None and prof[2]:
                        t.mark_removed()
                        continue
                kept.append(t)
            self.lost_stracks = kept

        def _gate_row(self, track, detections):
            gap = self.frame_count - track.end_frame
            if gap <= self.GATE_GRACE_S * self._gate_fr:
                return None
            prof = self._loss_profile(track)
            if prof is None:
                return None
            lx, ly, moving, b_pre, vx, vy = prof
            if moving and gap > STITCH_MOVE_GAP_S[1] * self._gate_fr:
                return ([True] * len(detections),
                        [1.0] * len(detections))
            veto = [False] * len(detections)
            cost = [1.0] * len(detections)
            span = self.RECOVERY_COST_HI - self.RECOVERY_COST_LO
            for j, det in enumerate(detections):
                cx, cy = _center(det.xyxy)
                if not moving:
                    d = math.hypot(cx - lx, cy - ly)
                    if d > STITCH_STAT_DIST:
                        veto[j] = True
                    else:
                        cost[j] = (self.RECOVERY_COST_LO
                                   + span * (d / STITCH_STAT_DIST))
                    continue
                brg = _bearing((0.0, lx, ly), (0.0, cx, cy))
                d = math.hypot(cx - lx, cy - ly)
                if (d > STITCH_STAT_DIST
                        and _bdiff(brg, b_pre) > CHAIN_DIR_TOL_DEG):
                    veto[j] = True
                    continue
                ex, ey = lx + vx * gap, ly + vy * gap
                dev = math.hypot(cx - ex, cy - ey)
                if dev > STITCH_MOVE_DIST:
                    veto[j] = True
                else:
                    cost[j] = (self.RECOVERY_COST_LO
                               + span * (dev / STITCH_MOVE_DIST))
            return veto, cost

        def _loss_profile(self, track):
            hist = list(track.history_observations)
            if not hist:
                return None
            lx, ly = _center(hist[-1])
            k = min(len(hist) - 1, 6)
            moving, b_pre, vx, vy = False, None, 0.0, 0.0
            if k >= 1:
                px, py = _center(hist[-1 - k])
                net = math.hypot(lx - px, ly - py)
                if (net >= CHAIN_BEARING_D_MIN
                        and (net / k) * self._gate_fr
                        >= STITCH_STAT_SPEED_PXS):
                    moving = True
                    b_pre = _bearing((0.0, px, py), (0.0, lx, ly))
                    vx, vy = (lx - px) / k, (ly - py) / k
            return lx, ly, moving, b_pre, vx, vy

        def _last_obs_frame(self, track):
            """Frame of the last TRUE observation (history append) —
            end_frame lies after re_activate, which advances it without
            appending; projecting from end_frame then vetoes the
            track's own next detection (measured: a re-found track
            re-lost itself every frame until death). Tail-object
            identity, the _ledger_obs trick."""
            hist = track.history_observations
            tail = hist[-1] if hist else None
            if tail is not None and tail is not getattr(
                    track, "_eg_tail", None):
                track._eg_tail = tail
                track._eg_tail_f = int(track.end_frame)
            return getattr(track, "_eg_tail_f", int(track.end_frame))

        def _emergence_row(self, track, detections):
            prof = self._loss_profile(track)
            if prof is None:
                return None
            lx, ly, moving, b_pre, vx, vy = prof
            if not moving:
                return None
            gap = max(1, self.frame_count - self._last_obs_frame(track))
            ex, ey = lx + vx * gap, ly + vy * gap
            hb = track.history_observations[-1]
            own = max(float(hb[2]) - float(hb[0]),
                      float(hb[3]) - float(hb[1]))
            bound = max(STITCH_STAT_DIST,
                        0.6 * math.hypot(vx, vy) * gap,
                        EMERGENCE_SIZE_FLOOR * own)
            # Iteration-2 redesign (G-LT-1 miss 1: 764k vetoes on one
            # 2h window = ~500x the theft rate; honest box-extent
            # wobble faked wrong-direction bearings over tiny
            # displacements and fragmentation shattered the rescue
            # equilibrium). Two disciplines:
            #  - DIRECTION is judged only beyond the box-size floor —
            #    sub-box displacement cannot carry a bearing.
            #  - DEVIATION is COMPETITIVE — it only vetoes a box when
            #    the track has a physics-consistent ALTERNATIVE to
            #    claim; a track is never starved by deviation alone.
            dir_floor = max(CHAIN_BEARING_D_MIN,
                            EMERGENCE_SIZE_FLOOR * own)
            veto = [False] * len(detections)
            devs = [0.0] * len(detections)
            for j, det in enumerate(detections):
                cx, cy = _center(det.xyxy)
                devs[j] = math.hypot(cx - ex, cy - ey)
                d = math.hypot(cx - lx, cy - ly)
                if (d > dir_floor
                        and _bdiff(_bearing((0.0, lx, ly),
                                            (0.0, cx, cy)),
                                   b_pre) > CHAIN_DIR_TOL_DEG):
                    veto[j] = True
            has_consistent = any(
                (not veto[j]) and devs[j] <= bound
                for j in range(len(detections)))
            if has_consistent:
                for j in range(len(detections)):
                    if not veto[j] and devs[j] > bound:
                        veto[j] = True
            if any(veto):
                self.emergence_vetoes += 1
            return veto, [1.0] * len(detections)

        def _first_association(self, dets, dets_first, active_tracks,
                               unconfirmed, img, detections,
                               activated_stracks, refind_stracks,
                               strack_pool):
            # Body mirrors boxmot 19.0.0 (pinned) with the emergence
            # mask inserted before linear_assignment.
            self._expire_movers()
            STrack.multi_predict(strack_pool)
            self._apply_camera_motion_compensation(
                dets, img, strack_pool, unconfirmed)
            ious_dists = iou_distance(strack_pool, detections,
                                      is_obb=self.is_obb)
            ious_dists_mask = ious_dists > self.proximity_thresh
            if self.fuse_first_associate:
                ious_dists = fuse_score(ious_dists, detections)
            if self.with_reid:
                emb_dists = embedding_distance(strack_pool, detections)
                emb_dists[emb_dists > self.appearance_thresh] = 1.0
                emb_dists[ious_dists_mask] = 1.0
                dists = np.minimum(ious_dists, emb_dists)
            else:
                dists = ious_dists
            if len(detections) and dists.size:
                grace = self.GATE_GRACE_S * self._gate_fr
                for i, track in enumerate(strack_pool):
                    if track.state == TrackState.Tracked:
                        row = self._emergence_row(track, detections)
                    elif (self.frame_count - track.end_frame) <= grace:
                        # a graced lost mover obeys the same physics —
                        # its coast must not re-steal what the veto
                        # just refused (the one-frame-later theft)
                        row = self._emergence_row(track, detections)
                    else:
                        row = self._gate_row(track, detections)
                    if row is None:
                        continue
                    veto, cost = row
                    for j in range(len(detections)):
                        if veto[j]:
                            dists[i, j] = 1.0
                        elif cost[j] < dists[i, j]:
                            dists[i, j] = cost[j]
            matches, u_track, u_detection = linear_assignment(
                dists, thresh=self.match_thresh)
            for itracked, idet in matches:
                track = strack_pool[itracked]
                det = detections[idet]
                if track.state == TrackState.Tracked:
                    track.update(detections[idet], self.frame_count)
                    activated_stracks.append(track)
                else:
                    track.re_activate(det, self.frame_count,
                                      new_id=False)
                    refind_stracks.append(track)
            return matches, u_track, u_detection

        def _second_association(self, dets_second, activated_stracks,
                                lost_stracks, refind_stracks,
                                u_track_first, strack_pool):
            # Body mirrors boxmot 19.0.0 (pinned) + the guard on the
            # low-confidence band (the ungated second theft surface).
            if len(dets_second) > 0:
                detections_second = [
                    STrack(det, max_obs=self.max_obs, is_obb=self.is_obb)
                    for det in dets_second]
            else:
                detections_second = []
            r_tracked_stracks = [
                strack_pool[i] for i in u_track_first
                if strack_pool[i].state == TrackState.Tracked]
            dists = iou_distance(r_tracked_stracks, detections_second,
                                 is_obb=self.is_obb)
            if len(detections_second) and dists.size:
                for i, track in enumerate(r_tracked_stracks):
                    row = self._emergence_row(track, detections_second)
                    if row is None:
                        continue
                    for j, v in enumerate(row[0]):
                        if v:
                            dists[i, j] = 1.0
            matches, u_track, u_detection = linear_assignment(
                dists, thresh=0.5)
            for itracked, idet in matches:
                track = r_tracked_stracks[itracked]
                det = detections_second[idet]
                if track.state == TrackState.Tracked:
                    track.update(det, self.frame_count)
                    activated_stracks.append(track)
                else:
                    track.re_activate(det, self.frame_count,
                                      new_id=False)
                    refind_stracks.append(track)
            for it in u_track:
                track = r_tracked_stracks[it]
                if not track.state == TrackState.Lost:
                    track.mark_lost()
                    lost_stracks.append(track)
            return matches, u_track, u_detection

    return EmergenceBotSort


def _gated_botsort_class():
    """Build the bus-law-gated BotSort subclass (lazy: boxmot + the gate
    constants import only when the locked recipe is actually used)."""
    import math

    from boxmot.trackers.botsort.basetrack import TrackState
    from boxmot.trackers.botsort.botsort import BotSort, STrack
    from boxmot.utils.matching import (
        embedding_distance, fuse_score, iou_distance, linear_assignment)

    from backend.services.track_chains import (
        CHAIN_BEARING_D_MIN, CHAIN_DIR_TOL_DEG, STITCH_MOVE_DIST,
        STITCH_MOVE_GAP_S, STITCH_STAT_DIST, STITCH_STAT_SPEED_PXS)
    from backend.config import EMERGENCE_SIZE_FLOOR
    from backend.services.track_cut import (PINCH_ANGLE, _bdiff,
                                            _bearing,
                                            displacement_chords)

    def _center(xyxy):
        return ((float(xyxy[0]) + float(xyxy[2])) / 2.0,
                (float(xyxy[1]) + float(xyxy[3])) / 2.0)

    class GatedBotSort(BotSort):
        """BoT-SORT + the operator's identity law at re-association
        (Stage 4, 2026-08-24). Occlusion does NOT end identity —
        INCOMPATIBLE MOTION does: a lost track may only re-activate onto a
        detection its physics could have reached. Stock BoT-SORT
        re-activates a lost track onto whatever detection wins pure-IoU
        assignment against its Kalman-coasted box — a queued car's coast
        catches opposite-direction traffic (the splice/theft mechanism,
        docs/plan_track_repair_2026-08-24.md). The gate masks the cost
        matrix BEFORE assignment, so a vetoed detection flows naturally to
        new-track init; Tracked-state rows are never masked, and lost
        tracks never reach the second association (stock BoT filters it to
        Tracked). Constants are the validated chain-rule constants, not new
        numbers. NB: veto cost is 1.0, the library's own mask convention —
        effective for any match_thresh < 1.0 (production 0.8/0.9).

        Second mechanism, PROBATION: at the single re-acquisition frame a
        thief's detection can be positionally indistinguishable from the
        owner reappearing (it is passing over the coasted/parked box) —
        the discriminator is what the box does NEXT. Any long-gap
        re-activation is placed on probation; once the resumed motion has
        accumulated enough displacement to show its direction, it is
        judged against the track's pre-loss APPROACH bearing. A flip
        beyond PINCH_ANGLE (120°, the splice-validated theft signature —
        wide enough to spare real turns) breaks the identity THERE: the
        track continues under a fresh id, bounding thief contamination to
        the judgment window (~a second) instead of a 60 s ride. A parked
        car discharging forward, a turner curving, a car resuming its
        journey all pass; only impossible motion breaks identity — the
        operator's bus law, stated temporally."""

        GATE_GRACE_S = 0.5      # short flicker: plain IoU is fine

        def __init__(self, *args, **kwargs):
            self._gate_fr = int(kwargs.get("frame_rate") or 30)
            # (old_id, new_id, resume_frame) per probation break — the dump
            # writer re-stamps rows [resume_frame..break) from old to new,
            # so the old track ends AT ITS LOSS and the thief owns its
            # whole post-gap track (zero contamination; without this every
            # break minted a flip-shaped tail on the old track).
            self.gate_breaks: list[tuple[int, int, int]] = []
            # Anti-theft campaign (2026-09-06): emergence guard on
            # TRACKED rows, read per-instance so test monkeypatching of
            # backend.config lands regardless of class-build timing.
            from backend import config as _cfg
            self._emergence_on = bool(getattr(_cfg, "EMERGENCE_GUARD",
                                              False))
            self.emergence_vetoes = 0
            super().__init__(*args, **kwargs)

        def _loss_profile(self, track):
            """(lx, ly, moving, b_pre, vx, vy) at the track's loss, from
            its OBSERVED history (never the drifting Kalman coast)."""
            hist = list(track.history_observations)
            if not hist:
                return None
            lx, ly = _center(hist[-1])
            k = min(len(hist) - 1, 6)
            moving, b_pre, vx, vy = False, None, 0.0, 0.0
            if k >= 1:
                px, py = _center(hist[-1 - k])
                net = math.hypot(lx - px, ly - py)
                if (net >= CHAIN_BEARING_D_MIN
                        and (net / k) * self._gate_fr >= STITCH_STAT_SPEED_PXS):
                    moving = True
                    b_pre = _bearing((0.0, px, py), (0.0, lx, ly))
                    vx, vy = (lx - px) / k, (ly - py) / k
            return lx, ly, moving, b_pre, vx, vy

        def _expire_movers(self):
            """A1 companion: a MOVER past the claim window can never be
            legally re-claimed, so its coasted ghost must not linger —
            measured failure: remove_duplicate_stracks deletes the
            legitimate NEW track wherever the ghost still overlaps it
            (the ghost suppressed the very identity the veto protected).
            Stopped tracks keep the full buffer (the bus law)."""
            window = STITCH_MOVE_GAP_S[1] * self._gate_fr
            kept = []
            for t in self.lost_stracks:
                if self.frame_count - t.end_frame > window:
                    prof = self._loss_profile(t)
                    if prof is not None and prof[2]:
                        t.mark_removed()
                        continue
                kept.append(t)
            self.lost_stracks = kept

        @staticmethod
        def _approach_bearing(hist):
            """Pre-loss travel bearing: walk back from the last observation
            until net displacement reaches CHAIN_BEARING_D_MIN — finds the
            APPROACH direction even when the track dwelled at a stop before
            it was lost. None when the whole history is a dwell."""
            if len(hist) < 2:
                return None
            lx, ly = _center(hist[-1])
            for i in range(len(hist) - 2, -1, -1):
                px, py = _center(hist[i])
                if math.hypot(lx - px, ly - py) >= CHAIN_BEARING_D_MIN:
                    return _bearing((0.0, px, py), (0.0, lx, ly))
            return None

        def _to_abs(self, local_f):
            """Local frame_count units -> ABSOLUTE video-frame units
            (the units dump rows carry). gate_breaks must be minted in
            row units or the re-stamp's frame >= resume_f test matches
            the old track's entire life — measured: all 15,978 breaks
            on s4_study_1600 degenerated into whole-track renames,
            gluing every severed thief straight back on."""
            abs_now = getattr(self, "_abs_now", None)
            if abs_now is None:            # unit streams feed abs frames
                return int(local_f)
            return int(local_f) + (int(abs_now) - int(self.frame_count))

        def _break(self, track, prob):
            old = int(track.id)
            track.id = track.next_id()           # identity broke at the gap
            self.gate_breaks.append((old, int(track.id), int(prob["frame"])))

        FLIP_CHECK_EVERY = 5          # frames between per-track flip scans

        def _ledger_obs(self, track):
            """Parallel deque of TRUE observation frames, index-aligned
            with track.history_observations. boxmot appends one box per
            STrack.update() ONLY (re_activate advances end_frame without
            appending), so growth is detected by tail-object identity —
            each append pushes a fresh array. Needed because the linear
            index->frame assumption breaks across re-association gaps
            (measured: a 359-frame gap placed a break ~14 s off the
            labeled theft) and gaps are exactly where thefts live."""
            hist = track.history_observations
            tail = hist[-1] if hist else None
            lf = getattr(track, "_obs_frames", None)
            if lf is None:
                n = len(hist)
                end = int(track.end_frame)
                lf = track._obs_frames = _deque(
                    range(end - n + 1, end + 1), maxlen=hist.maxlen)
            elif tail is not None and tail is not getattr(
                    track, "_obs_tail", None):
                lf.append(int(track.end_frame))
            track._obs_tail = tail
            return lf

        def _obs_frame(self, track, idx, hist_len):
            lf = getattr(track, "_obs_frames", None)
            if lf is not None and len(lf) == hist_len:
                return int(lf[int(idx)])
            return int(self.frame_count - (hist_len - 1 - int(idx)))

        def _judge_flips(self, track, final):
            """Judge EVERY not-yet-judged consecutive chord pair on this
            track's observed history; sever at the first flip. Two
            hard-won rules live here:
            - all pairs, not just the latest: chords complete about as
              fast as the 5-frame scan cadence on a dense mover, so a
              latest-pair-only judge skips the flip pair outright
              (measured: 3 of 4 probed carried thefts had the flip in
              their chords, unjudged).
            - dedup on the pair's TRUE end frame, never a window index:
              once the deque saturates at max_obs, indices slide left
              each frame and an index watermark freezes judging for the
              rest of the track's life.
            Still judged on COMPLETED chords only (ch[-1] forming; a
            still-forming chord fired on transients — measured 16,359
            breaks). final=True (end of run) also judges the last,
            still-open chord — at death it IS final (thieves ride to
            the horizon)."""
            hist = list(track.history_observations)
            if len(hist) < 6:
                return
            self._ledger_obs(track)
            pts = [(float(k), *_center(h)) for k, h in enumerate(hist)]
            ch = displacement_chords(pts, 2.0 * CHAIN_BEARING_D_MIN)
            last = len(ch) - (1 if final else 2)
            if last < 1:
                return
            upto = getattr(track, "_flip_upto", -1)
            for i in range(1, last + 1):
                a, b = ch[i - 1], ch[i]
                b_end = self._obs_frame(track, b[1], len(hist))
                if b_end <= upto:
                    continue
                upto = track._flip_upto = b_end
                if _bdiff(a[2], b[2]) > PINCH_ANGLE:
                    old = int(track.id)
                    track.id = track.next_id()
                    flip_f = self._to_abs(
                        self._obs_frame(track, b[4], len(hist)))
                    self.gate_breaks.append((old, int(track.id),
                                             int(max(0, flip_f))))
                    # keep only the post-flip tail (frames ledger in
                    # step) so the same flip cannot re-trigger on the
                    # new identity; chord indices are stale after the
                    # trim — stop judging this track this round
                    lf = track._obs_frames
                    while len(track.history_observations) > 2:
                        track.history_observations.popleft()
                        if len(lf) > 2:
                            lf.popleft()
                    return

        def _monitor_flips(self, strack_pool):
            """Identity-stack Pillar B (operator label class 2026-08-24:
            the SAME-LEG mid-motion handoff — lock hops from vehicle A
            turning right to vehicle B going straight, continuously, no
            loss event, so the re-association gate never fires). The
            cutter's splice-validated signature applied LIVE: two
            consecutive displacement chords disagreeing by more than
            PINCH_ANGLE (120°) at chord-qualifying displacement = the
            identity ends AT THE FLIP. New id forward; the flip is
            recorded via gate_breaks so the dump re-stamp hands the
            thief its own track. A smooth turn never fires it — turns
            curve chord-by-chord; thefts flip."""
            for track in strack_pool:
                if track.state != TrackState.Tracked:
                    continue
                self._ledger_obs(track)   # every frame, cadence-free
                last = getattr(track, "_flip_checked", 0)
                if self.frame_count - last < self.FLIP_CHECK_EVERY:
                    continue
                track._flip_checked = self.frame_count
                self._judge_flips(track, final=False)

        def flush_flips(self):
            """End-of-run sweep with final=True: the last chord never
            completes for a theft riding to the track's end (measured:
            13/29 labeled flips carried, most at track ends). The dump
            re-stamp runs after this, so late breaks still hand the
            thief its own track."""
            pools = (list(self.active_tracks) + list(self.lost_stracks)
                     + list(self.removed_stracks))
            for track in pools:
                self._judge_flips(track, final=True)

        def _judge_probations(self, strack_pool):
            for track in strack_pool:
                prob = getattr(track, "_gate_probation", None)
                if prob is None:
                    continue
                rx, ry = prob["resume"]
                b_pre = prob["b_pre"]
                if track.state == TrackState.Tracked:
                    cx, cy = _center(track.xyxy)
                    if math.hypot(cx - rx, cy - ry) < 2.0 * CHAIN_BEARING_D_MIN:
                        continue                  # direction not shown yet
                    if b_pre is not None:
                        b_post = _bearing((0.0, rx, ry), (0.0, cx, cy))
                        if _bdiff(b_post, b_pre) > PINCH_ANGLE:
                            self._break(track, prob)
                    track._gate_probation = None
                    continue
                # Re-lost while on probation. A transient flicker gets
                # grace; past that, the claim died unproven — measured on
                # the first arm dump: 930 of 1,215 theft-shaped tracks
                # were exactly this (thief re-lost before judgment).
                # Identity claims must PROVE compatibility: judge with
                # whatever motion exists, else REVOKE at the gap.
                if (self.frame_count - track.end_frame
                        <= self.GATE_GRACE_S * self._gate_fr):
                    continue
                hist = list(track.history_observations)
                cx, cy = _center(hist[-1]) if hist else (rx, ry)
                net = math.hypot(cx - rx, cy - ry)
                if net >= CHAIN_BEARING_D_MIN and b_pre is not None:
                    b_post = _bearing((0.0, rx, ry), (0.0, cx, cy))
                    if _bdiff(b_post, b_pre) > PINCH_ANGLE:
                        self._break(track, prob)
                else:
                    self._break(track, prob)      # unproven claim: revoked
                track._gate_probation = None

        # Physics-recovery costs sit ABOVE any live IoU match (an active
        # track claims its own detection at cost ~0.1) and BELOW
        # match_thresh, so a lost vehicle only wins detections nobody
        # alive is claiming — and among competing lost tracks, the one
        # whose physics fits best wins.
        RECOVERY_COST_LO = 0.55
        RECOVERY_COST_HI = 0.90

        def _gate_row(self, track, detections):
            """Per-detection (veto, physics_cost) for one LOST track, or
            None when the gate does not apply (short gap / no history).

            Verified failure this replaces: over a long gap the Kalman
            coast DRIFTS (a dwelling track retains residual velocity —
            measured 35 px over 100 frames), so coast-IoU alone cannot
            re-find honest reappearances; that is why a bigger buffer
            alone measured inert. Stopped tracks may be claimed near the
            LOSS position (STITCH_STAT_DIST); moving tracks near the
            EXTRAPOLATED position within the rev-4 latch tolerance
            (max(stat dist, 0.6 * speed * gap)) — the cutter's
            extrapolation-continuity law, applied prospectively."""
            gap = self.frame_count - track.end_frame
            if gap <= self.GATE_GRACE_S * self._gate_fr:
                return None
            prof = self._loss_profile(track)
            if prof is None:
                return None
            lx, ly, moving, b_pre, vx, vy = prof
            # A1 claim-cone cap (operator ruling, diag_lock_demo_review
            # 2026-08-24): a MOVER may only be re-claimed within the frozen
            # move-stitch window — beyond it the prediction is a lottery
            # (387/1,162 long re-finds had claim cones wider than two
            # lanes). Stopped vehicles keep the full buffer (the bus law's
            # protected case).
            if moving and gap > STITCH_MOVE_GAP_S[1] * self._gate_fr:
                return ([True] * len(detections), [1.0] * len(detections))
            veto = [False] * len(detections)
            cost = [1.0] * len(detections)
            span = self.RECOVERY_COST_HI - self.RECOVERY_COST_LO
            for j, det in enumerate(detections):
                cx, cy = _center(det.xyxy)
                if not moving:
                    d = math.hypot(cx - lx, cy - ly)
                    if d > STITCH_STAT_DIST:
                        veto[j] = True            # parked cars don't teleport
                    else:
                        cost[j] = (self.RECOVERY_COST_LO
                                   + span * (d / STITCH_STAT_DIST))
                    continue
                brg = _bearing((0.0, lx, ly), (0.0, cx, cy))
                d = math.hypot(cx - lx, cy - ly)
                if d > STITCH_STAT_DIST and _bdiff(brg, b_pre) > CHAIN_DIR_TOL_DEG:
                    veto[j] = True                # wrong direction = thief
                    continue
                ex, ey = lx + vx * gap, ly + vy * gap
                dev = math.hypot(cx - ex, cy - ey)
                if dev > STITCH_MOVE_DIST:        # frozen 70 px, never
                    veto[j] = True                # gap-scaled (A1 cap)
                else:
                    cost[j] = (self.RECOVERY_COST_LO
                               + span * (dev / STITCH_MOVE_DIST))
            return veto, cost

        def _last_obs_frame(self, track):
            """Frame of the last TRUE observation (history append) —
            end_frame lies after re_activate, which advances it without
            appending; projecting from end_frame then vetoes the
            track's own next detection (measured: a re-found track
            re-lost itself every frame until death). Tail-object
            identity, the _ledger_obs trick."""
            hist = track.history_observations
            tail = hist[-1] if hist else None
            if tail is not None and tail is not getattr(
                    track, "_eg_tail", None):
                track._eg_tail = tail
                track._eg_tail_f = int(track.end_frame)
            return getattr(track, "_eg_tail_f", int(track.end_frame))

        def _emergence_row(self, track, detections):
            """Per-detection veto for one MOVING track (Tracked, or
            lost within grace) — the operator emergence law
            (2026-09-06): when a hidden vehicle emerges beside a
            tracked one, the newcomer gets a NEW track; a moving track
            may only claim a detection its own motion reaches.
            IoU-only assignment hands moving tracks to emergent
            neighbors (the measured 71% theft class); this masks those
            hand-offs so the detection falls through to new-track
            birth. None when the guard does not apply (not moving /
            no history). An all-veto row goes unmatched -> LOST, which
            is recoverable — being stolen is not (the starvation
            unveto was measured to re-enable the theft)."""
            prof = self._loss_profile(track)
            if prof is None:
                return None
            lx, ly, moving, b_pre, vx, vy = prof
            if not moving:
                return None            # a dwell has no direction to defend
            gap = max(1, self.frame_count - self._last_obs_frame(track))
            ex, ey = lx + vx * gap, ly + vy * gap
            speed = math.hypot(vx, vy)
            # rev-4 latch tolerance, applied prospectively (per-frame
            # scaled -> frame-rate independent); size floor absorbs
            # box-extent jitter on large near-field boxes
            hb = track.history_observations[-1]
            own = max(float(hb[2]) - float(hb[0]),
                      float(hb[3]) - float(hb[1]))
            bound = max(STITCH_STAT_DIST, 0.6 * speed * gap,
                        EMERGENCE_SIZE_FLOOR * own)
            # Iteration-2 redesign (G-LT-1 miss 1: 764k vetoes on one
            # 2h window = ~500x the theft rate; honest box-extent
            # wobble faked wrong-direction bearings over tiny
            # displacements and fragmentation shattered the rescue
            # equilibrium). Two disciplines:
            #  - DIRECTION is judged only beyond the box-size floor —
            #    sub-box displacement cannot carry a bearing.
            #  - DEVIATION is COMPETITIVE — it only vetoes a box when
            #    the track has a physics-consistent ALTERNATIVE to
            #    claim; a track is never starved by deviation alone.
            dir_floor = max(CHAIN_BEARING_D_MIN,
                            EMERGENCE_SIZE_FLOOR * own)
            veto = [False] * len(detections)
            devs = [0.0] * len(detections)
            for j, det in enumerate(detections):
                cx, cy = _center(det.xyxy)
                devs[j] = math.hypot(cx - ex, cy - ey)
                d = math.hypot(cx - lx, cy - ly)
                if (d > dir_floor
                        and _bdiff(_bearing((0.0, lx, ly),
                                            (0.0, cx, cy)),
                                   b_pre) > CHAIN_DIR_TOL_DEG):
                    veto[j] = True
            has_consistent = any(
                (not veto[j]) and devs[j] <= bound
                for j in range(len(detections)))
            if has_consistent:
                for j in range(len(detections)):
                    if not veto[j] and devs[j] > bound:
                        veto[j] = True
            if any(veto):
                self.emergence_vetoes += 1
            return veto, [1.0] * len(detections)

        def _first_association(self, dets, dets_first, active_tracks,
                               unconfirmed, img, detections,
                               activated_stracks, refind_stracks,
                               strack_pool):
            # Body mirrors boxmot 19.0.0 (pinned) with the theft mask
            # inserted before linear_assignment and probation judgment on
            # previously re-activated tracks.
            self._judge_probations(strack_pool)
            self._expire_movers()
            self._monitor_flips(strack_pool)
            STrack.multi_predict(strack_pool)
            self._apply_camera_motion_compensation(
                dets, img, strack_pool, unconfirmed)
            ious_dists = iou_distance(strack_pool, detections,
                                      is_obb=self.is_obb)
            ious_dists_mask = ious_dists > self.proximity_thresh
            if self.fuse_first_associate:
                ious_dists = fuse_score(ious_dists, detections)
            if self.with_reid:
                emb_dists = embedding_distance(strack_pool, detections)
                emb_dists[emb_dists > self.appearance_thresh] = 1.0
                emb_dists[ious_dists_mask] = 1.0
                dists = np.minimum(ious_dists, emb_dists)
            else:
                dists = ious_dists
            if len(detections) and dists.size:
                for i, track in enumerate(strack_pool):
                    if track.state == TrackState.Tracked:
                        if not self._emergence_on:
                            continue
                        row = self._emergence_row(track, detections)
                    elif (self._emergence_on
                          and (self.frame_count - track.end_frame)
                          <= self.GATE_GRACE_S * self._gate_fr):
                        # graced lost mover: same physics; the coast
                        # must not re-steal a vetoed emergent
                        row = self._emergence_row(track, detections)
                    else:
                        row = self._gate_row(track, detections)
                    if row is None:
                        continue
                    veto, cost = row
                    for j in range(len(detections)):
                        if veto[j]:
                            dists[i, j] = 1.0
                        elif cost[j] < dists[i, j]:
                            dists[i, j] = cost[j]
            matches, u_track, u_detection = linear_assignment(
                dists, thresh=self.match_thresh)
            for itracked, idet in matches:
                track = strack_pool[itracked]
                det = detections[idet]
                if track.state == TrackState.Tracked:
                    track.update(detections[idet], self.frame_count)
                    activated_stracks.append(track)
                else:
                    gap = self.frame_count - track.end_frame
                    if gap > self.GATE_GRACE_S * self._gate_fr:
                        cx, cy = _center(det.xyxy)
                        track._gate_probation = {
                            "resume": (cx, cy),
                            "frame": self._to_abs(self.frame_count),
                            "b_pre": self._approach_bearing(
                                list(track.history_observations)),
                        }
                    track.re_activate(det, self.frame_count, new_id=False)
                    refind_stracks.append(track)
            return matches, u_track, u_detection

        def _second_association(self, dets_second, activated_stracks,
                                lost_stracks, refind_stracks,
                                u_track_first, strack_pool):
            # Body mirrors boxmot 19.0.0 (pinned) with the emergence
            # guard applied to the low-confidence band too — the ungated
            # second theft surface (hardcoded thresh 0.5, Tracked only).
            if len(dets_second) > 0:
                detections_second = [
                    STrack(det, max_obs=self.max_obs, is_obb=self.is_obb)
                    for det in dets_second]
            else:
                detections_second = []
            r_tracked_stracks = [
                strack_pool[i] for i in u_track_first
                if strack_pool[i].state == TrackState.Tracked]
            dists = iou_distance(r_tracked_stracks, detections_second,
                                 is_obb=self.is_obb)
            if (self._emergence_on and len(detections_second)
                    and dists.size):
                for i, track in enumerate(r_tracked_stracks):
                    row = self._emergence_row(track, detections_second)
                    if row is None:
                        continue
                    for j, v in enumerate(row[0]):
                        if v:
                            dists[i, j] = 1.0
            matches, u_track, u_detection = linear_assignment(
                dists, thresh=0.5)
            for itracked, idet in matches:
                track = r_tracked_stracks[itracked]
                det = detections_second[idet]
                if track.state == TrackState.Tracked:
                    track.update(det, self.frame_count)
                    activated_stracks.append(track)
                else:
                    track.re_activate(det, self.frame_count, new_id=False)
                    refind_stracks.append(track)
            for it in u_track:
                track = r_tracked_stracks[it]
                if not track.state == TrackState.Lost:
                    track.mark_lost()
                    lost_stracks.append(track)
            return matches, u_track, u_detection

    return GatedBotSort


class GatedBotSortBackend(BotSortBackend):
    """The 'botsort_locked' recipe: BotSortBackend with the bus-law
    re-association gate and an observation history that outlives a
    generous lost buffer (stock max_obs=50 truncates the pre-loss motion
    the gate reads)."""

    def __init__(self, lost_track_buffer: int = TRACKER_LOST_BUFFER,
                 **kwargs):
        super().__init__(lost_track_buffer=lost_track_buffer, **kwargs)
        fr = int(self._kwargs.get("frame_rate") or 30)
        buffer_frames = int(fr / 30.0 * lost_track_buffer)
        self._kwargs["max_obs"] = max(60, buffer_frames + 10)
        self._BotSort = _gated_botsort_class()
        self.bot = self._BotSort(**self._kwargs)

    def finalize(self):
        """End-of-run flip flush (called by run_pass1 before the
        gate-break re-stamp)."""
        try:
            self.bot.flush_flips()
        except Exception:
            pass


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
    "botsort_locked": GatedBotSortBackend,
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
