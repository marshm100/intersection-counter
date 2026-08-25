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

        def _break(self, track, prob):
            old = int(track.id)
            track.id = track.next_id()           # identity broke at the gap
            self.gate_breaks.append((old, int(track.id), int(prob["frame"])))

        FLIP_CHECK_EVERY = 5          # frames between per-track flip scans

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
            d_min = 2.0 * CHAIN_BEARING_D_MIN   # the fallback-kin chord
            for track in strack_pool:
                if track.state != TrackState.Tracked:
                    continue
                last = getattr(track, "_flip_checked", 0)
                if self.frame_count - last < self.FLIP_CHECK_EVERY:
                    continue
                track._flip_checked = self.frame_count
                hist = list(track.history_observations)
                if len(hist) < 6:
                    continue
                pts = [(float(k), *_center(h)) for k, h in enumerate(hist)]
                ch = displacement_chords(pts, d_min)
                if len(ch) < 2:
                    continue
                if _bdiff(ch[-1][2], ch[-2][2]) > PINCH_ANGLE:
                    old = int(track.id)
                    track.id = track.next_id()
                    flip_f = self.frame_count - (len(hist) - 1
                                                 - int(ch[-1][4]))
                    self.gate_breaks.append((old, int(track.id),
                                             int(max(0, flip_f))))
                    # keep only the post-flip tail of the history so the
                    # same flip cannot re-trigger on the new identity
                    while len(track.history_observations) > 2:
                        track.history_observations.popleft()

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
                        continue
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
                            "frame": self.frame_count,
                            "b_pre": self._approach_bearing(
                                list(track.history_observations)),
                        }
                    track.re_activate(det, self.frame_count, new_id=False)
                    refind_stracks.append(track)
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
