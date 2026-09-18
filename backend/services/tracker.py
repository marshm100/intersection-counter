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
from supervision.tracker.byte_tracker import matching as _m
from supervision.tracker.byte_tracker.basetrack import TrackState as _TrackState
from supervision.tracker.byte_tracker.core import STrack as _STrack
from supervision.tracker.byte_tracker.core import joint_tracks as _joint_tracks
from supervision.tracker.byte_tracker.core import (
    remove_duplicate_tracks as _remove_duplicate_tracks,
)
from supervision.tracker.byte_tracker.core import sub_tracks as _sub_tracks

from backend.config import (
    TRACKER_ACTIVATION_THRESHOLD,
    TRACKER_LOST_BUFFER,
    TRACKER_MATCH_THRESHOLD,
    VEHICLE_CLASSES,
)

ALL_CLASSES = VEHICLE_CLASSES

# _RecoveringByteTrack.update_with_tensors is a line-for-line fork of this
# supervision version's ByteTrack.update_with_tensors (core.py L257-407) with
# one stage inserted. A version bump must re-diff the fork (test pins it).
_FORK_SV_VERSION = "0.17.1"


_SV_FUSE_SCORE_ORIG = None


def apply_fuse_score_setting(enabled: bool) -> None:
    """Switch supervision ByteTrack's first-association score fusion
    (config.TRACKER_FUSE_SCORE, 2026-09-12). The library multiplies IoU
    similarity by detection confidence before the Hungarian match, which
    makes the effective overlap bar 0.2 / conf; a confident box receding
    at 10 fps is refused at overlap 0.25-0.4 (cam4's nearest-lane NB
    tracks). Disabled = plain IoU in every stage, the original ByteTrack's
    MOT20 behaviour and boxmot BoT-SORT's default. Module-level patch:
    only the supervision backend consults this function."""
    global _SV_FUSE_SCORE_ORIG
    from supervision.tracker.byte_tracker import matching as _m
    if _SV_FUSE_SCORE_ORIG is None:
        _SV_FUSE_SCORE_ORIG = _m.fuse_score
    if enabled:
        _m.fuse_score = _SV_FUSE_SCORE_ORIG
    else:
        _m.fuse_score = lambda cost_matrix, detections: cost_matrix


def _dedup_boxes(detections: list[dict], iou_thr: float) -> list[dict]:
    """Drop the lower-confidence box of every pair overlapping above iou_thr,
    ANY class (YOLO26 is NMS-free: it emits same-class and cross-class double
    boxes alike). scripts/research_dup_boxes.py, 2026-09-12: pairs above 0.8
    IoU separate into two vehicles within +-1 s in 0-1% of cases on cam4,
    cam5 and FM51; between 0.6 and 0.8 in 2-14%. Stable order."""
    n = len(detections)
    if n < 2 or iou_thr <= 0:
        return detections
    b = np.asarray([d["bbox"] for d in detections], dtype=np.float32)
    c = np.asarray([d["confidence"] for d in detections], dtype=np.float32)
    order = np.argsort(-c, kind="stable")
    area = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    drop = np.zeros(n, dtype=bool)
    for a_i, i in enumerate(order):
        if drop[i]:
            continue
        for j in order[a_i + 1:]:
            if drop[j]:
                continue
            ix = max(0.0, min(b[i, 2], b[j, 2]) - max(b[i, 0], b[j, 0]))
            iy = max(0.0, min(b[i, 3], b[j, 3]) - max(b[i, 1], b[j, 1]))
            inter = ix * iy
            if inter > 0 and inter / (area[i] + area[j] - inter) > iou_thr:
                drop[j] = True
    return [d for d, x in zip(detections, drop) if not x]


def _recovery_cost(track_tlbr: np.ndarray, det_tlbr: np.ndarray,
                   size_ratio: float) -> np.ndarray:
    """(T,4) x (D,4) -> (T,D) centre distance in BOX UNITS: |c_t - c_d| /
    max(w_t, w_d). inf where min(w)/max(w) < size_ratio or a width is not
    positive (a 200-px near box and a 15-px far box are never the same
    vehicle one frame apart)."""
    if len(track_tlbr) == 0 or len(det_tlbr) == 0:
        return np.zeros((len(track_tlbr), len(det_tlbr)), dtype=np.float32)
    tc = (track_tlbr[:, :2] + track_tlbr[:, 2:]) / 2.0
    dc = (det_tlbr[:, :2] + det_tlbr[:, 2:]) / 2.0
    tw = (track_tlbr[:, 2] - track_tlbr[:, 0])[:, None]
    dw = (det_tlbr[:, 2] - det_tlbr[:, 0])[None, :]
    dist = np.hypot(tc[:, None, 0] - dc[None, :, 0], tc[:, None, 1] - dc[None, :, 1])
    wmax = np.maximum(tw, dw)
    wmin = np.minimum(tw, dw)
    with np.errstate(divide="ignore", invalid="ignore"):
        cost = dist / wmax
        ratio = wmin / wmax
    bad = (wmin <= 0) | ~np.isfinite(cost) | (ratio < size_ratio)
    cost = np.where(bad, np.inf, cost)
    return cost.astype(np.float32)


def _greedy_pairs(cost: np.ndarray, reach: float) -> list[tuple[int, int]]:
    """Nearest pair first, one-to-one, stop at the first cost >= reach.
    Stable ascending sort, so ties resolve in row order (rows are ordered
    tracked-then-lost by the caller: the live track wins a tie). Greedy on
    purpose: a sum-minimising assignment cross-pairs leftovers onto a
    FOLLOWER (the 2026-05-29 recovery failure); the nearest-within-reach
    rule is the one the census linker validated."""
    if cost.size == 0:
        return []
    order = np.argsort(cost, axis=None, kind="stable")
    used_t: set[int] = set()
    used_d: set[int] = set()
    pairs: list[tuple[int, int]] = []
    ncol = cost.shape[1]
    for flat in order:
        c = cost.flat[flat]
        if not np.isfinite(c) or c >= reach:
            break
        ti, di = divmod(int(flat), ncol)
        if ti in used_t or di in used_d:
            continue
        used_t.add(ti); used_d.add(di)
        pairs.append((ti, di))
    return pairs


def _coverage(a_tlbr: np.ndarray, b_tlbr: np.ndarray) -> np.ndarray:
    """(A,4) x (B,4) -> (A,B): the share of each a-box's area that lies inside
    each b-box (asymmetric; a weak double box riding a held car covers ~1)."""
    a = np.asarray(a_tlbr, dtype=np.float32).reshape(-1, 4)
    b = np.asarray(b_tlbr, dtype=np.float32).reshape(-1, 4)
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)), dtype=np.float32)
    ix = np.clip(np.minimum(a[:, None, 2], b[None, :, 2]) - np.maximum(a[:, None, 0], b[None, :, 0]), 0, None)
    iy = np.clip(np.minimum(a[:, None, 3], b[None, :, 3]) - np.maximum(a[:, None, 1], b[None, :, 1]), 0, None)
    area = np.maximum((a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1]), 1e-6)
    return (ix * iy / area[:, None]).astype(np.float32)


def _obs(lf: int, af: int, tlbr, score: float, cls, cover: float) -> tuple:
    """One tentative observation as a tuple of Python scalars (pickle-stable):
    (local frame, absolute frame, x1, y1, x2, y2, score, class, cover)."""
    try:
        c = int(cls)
    except (TypeError, ValueError):
        c = -1
    return (int(lf), int(af), float(tlbr[0]), float(tlbr[1]), float(tlbr[2]), float(tlbr[3]),
            float(score), c, float(cover))


def _majority(classes: list) -> int:
    """Most common class; ties go to the latest."""
    if not classes:
        return -1
    counts: dict = {}
    for c in classes:
        counts[c] = counts.get(c, 0) + 1
    best = max(counts.values())
    for c in reversed(classes):
        if counts[c] == best:
            return int(c)
    return int(classes[-1])


def _adopt(track, det, frame_id: int, kalman_filter, width_jump: float,
           was_tracked: bool) -> bool:
    """Continue `track` on `det`: a normal Kalman update (or re_activate for a
    lost track) unless the box width jumped by more than `width_jump` against
    the PREDICTED width, in which case the motion state restarts from `det`
    (_adopt_reinit). Records the observed box on the track (last_obs_tlbr).
    Returns True when the state was re-initiated."""
    pred = track.tlbr
    pw = float(pred[2] - pred[0]); dw = float(det.tlbr[2] - det.tlbr[0])
    jump = (width_jump > 0 and pw > 0 and dw > 0
            and (dw / pw > width_jump or pw / dw > width_jump))
    if jump:
        _adopt_reinit(track, det, frame_id, kalman_filter)
    elif was_tracked:
        track.update(det, frame_id)
    else:
        track.re_activate(det, frame_id, new_id=False)
    _note_obs(track, det.tlbr, frame_id)
    return jump


def _match_rec(bt, stage: str, track, det, was_lost: bool) -> tuple:
    """One match_log record, taken BEFORE the track adopts the box: (absolute
    frame, track id, stage, was_lost, frames since the track was last seen,
    the track's predicted tlbr, the det tlbr, det score). Stages: "s1" (high
    boxes, IoU x conf), "s2" (low boxes, IoU 0.5), "s25" (position recovery),
    "unconf" (a newborn confirmed by IoU x conf), "confirm_pos" (confirmed by
    position), "birth"."""
    return (bt._abs(), int(track.track_id), stage, bool(was_lost),
            int(bt.frame_id - track.end_frame),
            tuple(float(v) for v in track.tlbr), tuple(float(v) for v in det.tlbr),
            float(det.score))


def _note_obs(track, tlbr, frame_id: int) -> None:
    """Record an OBSERVED box on the track: last_obs_tlbr + the last few
    observed centres (the exit-direction test reads them)."""
    tlbr = np.asarray(tlbr, dtype=np.float32)
    track.last_obs_tlbr = tlbr
    hist = getattr(track, "obs_centers", None) or []
    hist.append((int(frame_id), float((tlbr[0] + tlbr[2]) / 2), float((tlbr[1] + tlbr[3]) / 2)))
    track.obs_centers = hist[-4:]


def _reverse_jump_mask(tracks: list, det_tlbr: np.ndarray, max_deg: float,
                       min_jump: float) -> np.ndarray:
    """(T,D) bool: the box lies >= min_jump box widths from the track's last
    OBSERVED box in a direction more than max_deg off the track's observed
    motion (over its last few observed centres). A track with no observed
    motion (standing, or one observation) refuses nothing."""
    T, D = len(tracks), len(det_tlbr)
    mask = np.zeros((T, D), dtype=bool)
    if T == 0 or D == 0:
        return mask
    dc = (det_tlbr[:, :2] + det_tlbr[:, 2:]) / 2.0
    dw = det_tlbr[:, 2] - det_tlbr[:, 0]
    cos_max = float(np.cos(np.radians(max_deg)))
    for ti, t in enumerate(tracks):
        hist = getattr(t, "obs_centers", None) or []
        last = getattr(t, "last_obs_tlbr", None)
        if len(hist) < 2 or last is None:
            continue
        w = float(last[2] - last[0])
        if w <= 0:
            continue
        vx, vy = hist[-1][1] - hist[0][1], hist[-1][2] - hist[0][2]
        nv = float(np.hypot(vx, vy))
        if nv < 0.1 * w:          # no observed motion: no direction to judge
            continue
        jx, jy = dc[:, 0] - hist[-1][1], dc[:, 1] - hist[-1][2]
        nj = np.hypot(jx, jy)
        jump = nj / np.maximum(np.maximum(w, dw), 1e-6)
        with np.errstate(divide="ignore", invalid="ignore"):
            cosang = (vx * jx + vy * jy) / (nv * nj)
        mask[ti] = (jump >= min_jump) & (nj > 0) & (cosang < cos_max)
    return mask


def _exited_frame(track, frame_w: float, frame_h: float, margin: float) -> bool:
    """True when the track's last OBSERVED box touches a frame edge AND its
    observed motion was toward that edge: the vehicle drove out of the
    picture. (A box touching the edge while moving AWAY from it is entering.)"""
    b = getattr(track, "last_obs_tlbr", None)
    hist = getattr(track, "obs_centers", None) or []
    if b is None or len(hist) < 2 or frame_w <= 0 or frame_h <= 0:
        return False
    (f0, x0, y0), (f1, x1, y1) = hist[0], hist[-1]
    vx, vy = x1 - x0, y1 - y0
    return ((b[2] >= frame_w - margin and vx > 0) or (b[0] <= margin and vx < 0)
            or (b[3] >= frame_h - margin and vy > 0) or (b[1] <= margin and vy < 0))


def _adopt_reinit(track, det, frame_id: int, kalman_filter) -> None:
    """Continue `track` on `det` with a FRESH motion state instead of a Kalman
    update. supervision's filter tracks aspect ratio and height with their
    velocities; one violent shape change (a frame-edge strip becoming a full
    box, a far box replacing a near one) launches those velocities and the
    predicted box balloons to twice the real width within frames — 60% of
    the remaining breaks on cam4 1600 (2026-09-12). Mirrors STrack.update
    except kf.initiate replaces kf.update."""
    track.frame_id = frame_id
    track.tracklet_len += 1
    track.mean, track.covariance = kalman_filter.initiate(
        _STrack.tlwh_to_xyah(det.tlwh))
    # Keep the vehicle's MOTION, drop only the poisoned SHAPE state: the
    # centre velocity restarts from the observed displacement since the last
    # observed box, not from zero. A zero-velocity restart parked the
    # prediction of a vehicle entering over the frame edge (its box grows
    # 44 -> 154 px while it moves ~50 px/frame) at the edge, where the vehicle
    # it had been hiding appeared and took its id (cam5 1600 hand-off reel
    # clip 6, operator ruling 2026-09-12).
    hist = getattr(track, "obs_centers", None) or []
    if hist:
        f0, x0, y0 = hist[-1]
        gap = frame_id - f0
        if gap >= 1:
            cx = float(det.tlwh[0] + det.tlwh[2] / 2.0)
            cy = float(det.tlwh[1] + det.tlwh[3] / 2.0)
            track.mean[4] = (cx - x0) / gap
            track.mean[5] = (cy - y0) / gap
    track.state = _TrackState.Tracked
    track.is_activated = True
    track.score = det.score


class _RecoveringByteTrack(sv.ByteTrack):
    """supervision ByteTrack with STAGE 2.5 — position recovery
    (config.TRACKER_POSITION_RECOVERY, 2026-09-12).

    After the library's stage 1 (high dets, IoU x conf) and stage 2 (low
    dets, IoU 0.5), the tracks still unmatched (Tracked leftovers AND the
    Lost tracks stage 1 passed over) meet the detections still unmatched
    (high AND low, any conf >= 0.10) on centre distance in box units against
    the track's Kalman-PREDICTED box. A recovered Tracked track is updated,
    a recovered Lost track re-activated with its own id; the detection leaves
    both leftover pools, so it never reaches the unconfirmed pass or a
    birth. Births are unchanged (det_thresh). Confirmation by position now
    offers a just-born track the leftover boxes, low ones included.

    WEAK-BOX BIRTHS (config.TRACKER_WEAK_BIRTH, 2026-09-12): a distant or
    partly hidden car's boxes stay under det_thresh for 0.5-1.5 s (cam5 1600:
    12% of vehicles start >= 0.5 s late). The leftover weak boxes are kept as
    TENTATIVE histories, linked frame to frame by the tracker's own position
    rule. Inheritance: the track born from the car's first confident box takes
    the history as its prefix. Promotion (TRACKER_WEAK_BIRTH_PROMOTE): a
    tentative that held together 0.5 s and moved >= 0.5 box widths, and does
    not ride a held vehicle (coverage guard), becomes a track. Either way the
    prefix is emitted as back-fill rows at their absolute frames (opt-in
    collection, popped by run_pass1; the live pipeline never collects).

    Module-level class with plain attributes: pickles through the backend's
    get_state/load_state. recovery_reach <= 0 disables the stage (the fork
    is then byte-identical to the library; a test proves it)."""

    def __init__(self, *args, recovery_reach: float = 0.9,
                 recovery_size_ratio: float = 0.3, recovery_min_iou: float = 0.2,
                 recovery_held_iou: float = 0.6, recovery_reverse_deg: float = 0.0,
                 recovery_reverse_jump: float = 0.15,
                 confirm_by_position: bool = True, confirm_width_ratio: float = 0.5,
                 reinit_width_jump: float = 1.5, lost_patience_s: float = 0.5,
                 edge_exit: bool = True, frame_size: tuple | None = None,
                 edge_margin: float = 3.0, stack_iou: float = 0.6,
                 weak_birth: bool = False, weak_birth_persist_s: float = 0.5,
                 weak_birth_gap_s: float = 0.2, weak_birth_min_move: float = 0.5,
                 weak_birth_max_cover: float = 0.6, weak_birth_history_s: float = 10.0,
                 weak_birth_promote: bool = True, collect_backfill: bool = False,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.stack_iou = float(stack_iou)
        self.n_births_deferred = 0
        self.edge_exit = bool(edge_exit)
        self.edge_margin = float(edge_margin)
        # (w, h) of the video. Edge exit applies ONLY when the caller knows it
        # (pass 1 and the live pipeline read it from the videos row): extents
        # learnt from boxes are defined by the very vehicles they would judge.
        self.frame_w = float(frame_size[0]) if frame_size else 0.0
        self.frame_h = float(frame_size[1]) if frame_size else 0.0
        self.n_edge_exits = 0
        fr = float(kwargs.get("frame_rate", 30) or 30)
        # a LOST track is offered a box by position only while its prediction
        # is still trustworthy: the census linker held every vehicle with 5
        # frames of patience at 10 fps; the library keeps lost ids 5 s, and
        # recovering those by position hands a stale id to the next vehicle
        # through the spot (2026-09-12: FM51 0700 stale hand-offs 246 -> 573).
        self.lost_patience_frames = max(1, int(round(float(lost_patience_s) * fr)))
        # weak-box births (see the class docstring). Plain attributes only:
        # tentatives are dicts of scalar tuples, so checkpoints pickle stably.
        self.weak_birth = bool(weak_birth)
        self.wb_persist_frames = max(2, int(round(float(weak_birth_persist_s) * fr)))
        self.wb_gap_frames = max(1, int(round(float(weak_birth_gap_s) * fr)))
        self.wb_history_frames = max(self.wb_persist_frames + 1,
                                     int(round(float(weak_birth_history_s) * fr)))
        self.wb_min_move = float(weak_birth_min_move)
        self.wb_max_cover = float(weak_birth_max_cover)
        self.wb_promote = bool(weak_birth_promote)
        self.tentatives: list = []
        self.backfill = [] if collect_backfill else None
        self.n_weak_births = 0
        self.n_weak_inherited = 0
        self.weak_birth_log = None
        self._abs_now = None
        self.recovery_reach = float(recovery_reach)
        self.recovery_size_ratio = float(recovery_size_ratio)
        self.recovery_min_iou = float(recovery_min_iou)
        self.recovery_held_iou = float(recovery_held_iou)
        self.recovery_reverse_deg = float(recovery_reverse_deg)
        self.recovery_reverse_jump = float(recovery_reverse_jump)
        self.n_recovery_refused_held = 0
        self.n_recovery_refused_reverse = 0
        self.confirm_by_position = bool(confirm_by_position)
        self.confirm_width_ratio = float(confirm_width_ratio)
        self.reinit_width_jump = float(reinit_width_jump)
        self.n_confirmed_by_position = 0
        self.n_reinit = 0
        self.n_recovered = 0        # Tracked leftovers continued
        self.n_recovered_lost = 0   # Lost tracks re-found by position
        # Diagnostics only (research scripts set a list): one tuple per
        # recovery — (frame, track_id, was_lost, frames_since_seen, cost,
        # predicted tlbr, det tlbr, det score). None = no logging.
        self.recovery_log = None
        # Diagnostics only: births (frame, id, tlbr, score) and newborns
        # removed unconfirmed (frame, id, their box, the nearest leftover box
        # tlbr or None, its score). None = no logging.
        self.birth_log = None
        self.unconfirmed_death_log = None
        # Diagnostics only (research_thefts.py sets a list): one tuple per
        # association that puts a box on a track — see _match_rec. None = off.
        self.match_log = None

    def update_with_tensors(self, tensors: np.ndarray) -> list:
        mlog = getattr(self, "match_log", None)
        # ---- fork of supervision 0.17.1 core.py L267-327 (verbatim) ----------
        self.frame_id += 1
        wb = (getattr(self, "weak_birth", False) and self.recovery_reach > 0
              and getattr(self, "tentatives", None) is not None)
        activated_starcks = []
        refind_stracks = []
        lost_stracks = []
        removed_stracks = []

        class_ids = tensors[:, 5]
        scores = tensors[:, 4]
        bboxes = tensors[:, :4]

        remain_inds = scores > self.track_thresh
        inds_low = scores > 0.1
        inds_high = scores < self.track_thresh

        inds_second = np.logical_and(inds_low, inds_high)
        dets_second = bboxes[inds_second]
        dets = bboxes[remain_inds]
        scores_keep = scores[remain_inds]
        scores_second = scores[inds_second]

        class_ids_keep = class_ids[remain_inds]
        class_ids_second = class_ids[inds_second]

        if len(dets) > 0:
            detections = [
                _STrack(_STrack.tlbr_to_tlwh(tlbr), s, c)
                for (tlbr, s, c) in zip(dets, scores_keep, class_ids_keep)
            ]
        else:
            detections = []

        unconfirmed = []
        tracked_stracks = []
        for track in self.tracked_tracks:
            if not track.is_activated:
                unconfirmed.append(track)
            else:
                tracked_stracks.append(track)

        # Stage 1: high dets, IoU x conf (module attribute: the fuse switch applies)
        strack_pool = _joint_tracks(tracked_stracks, self.lost_tracks)
        _STrack.multi_predict(strack_pool)
        dists = _m.iou_distance(strack_pool, detections)
        dists = _m.fuse_score(dists, detections)
        matches, u_track, u_detection = _m.linear_assignment(
            dists, thresh=self.match_thresh
        )
        for itracked, idet in matches:
            track = strack_pool[itracked]
            det = detections[idet]
            was_tracked = track.state == _TrackState.Tracked
            if mlog is not None:
                mlog.append(_match_rec(self, "s1", track, det, not was_tracked))
            if _adopt(track, det, self.frame_id, self.kalman_filter,
                      self.reinit_width_jump, was_tracked):
                self.n_reinit += 1
            (activated_starcks if was_tracked else refind_stracks).append(track)

        # ---- L329-356: stage 2, low dets, plain IoU 0.5 -------------------------
        if len(dets_second) > 0:
            detections_second = [
                _STrack(_STrack.tlbr_to_tlwh(tlbr), s, c)
                for (tlbr, s, c) in zip(dets_second, scores_second, class_ids_second)
            ]
        else:
            detections_second = []
        r_tracked_stracks = [
            strack_pool[i]
            for i in u_track
            if strack_pool[i].state == _TrackState.Tracked
        ]
        # Lost tracks stage 1 passed over: the library forgets them here
        # (they are not in stage 2); the recovery stage offers them a box.
        r_lost_stracks = [
            strack_pool[i]
            for i in u_track
            if strack_pool[i].state == _TrackState.Lost
        ]
        dists = _m.iou_distance(r_tracked_stracks, detections_second)
        matches, u_track_second, u_detection_second = _m.linear_assignment(
            dists, thresh=0.5
        )
        for itracked, idet in matches:
            track = r_tracked_stracks[itracked]
            det = detections_second[idet]
            was_tracked = track.state == _TrackState.Tracked
            if mlog is not None:
                mlog.append(_match_rec(self, "s2", track, det, not was_tracked))
            if _adopt(track, det, self.frame_id, self.kalman_filter,
                      self.reinit_width_jump, was_tracked):
                self.n_reinit += 1
            (activated_starcks if was_tracked else refind_stracks).append(track)

        # ---- STAGE 2.5: position recovery (the insertion) -----------------------
        recovered_ids: set[int] = set()
        u_detection = list(u_detection)
        u_detection_second = list(u_detection_second)
        if self.recovery_reach > 0:
            fresh_lost = [t for t in r_lost_stracks
                          if self.frame_id - t.end_frame <= self.lost_patience_frames]
            cand_tracks = [r_tracked_stracks[i] for i in u_track_second] + fresh_lost
            cand_index = [(0, i) for i in u_detection] + [(1, i) for i in u_detection_second]
            cand_dets = [detections[i] if p == 0 else detections_second[i]
                         for p, i in cand_index]
            if cand_tracks and cand_dets:
                t_tlbr = np.asarray([t.tlbr for t in cand_tracks], dtype=np.float32)
                d_tlbr = np.asarray([d.tlbr for d in cand_dets], dtype=np.float32)
                # where the vehicle was last actually SEEN: a drifted or ballooned
                # prediction must not hide a box that overlaps the last real one
                o_tlbr = np.asarray([getattr(t, "last_obs_tlbr", t.tlbr) for t in cand_tracks],
                                    dtype=np.float32)
                cost = np.minimum(_recovery_cost(t_tlbr, d_tlbr, self.recovery_size_ratio),
                                  _recovery_cost(o_tlbr, d_tlbr, self.recovery_size_ratio))
                if self.recovery_min_iou > 0:
                    # the box must still overlap the prediction OR the last observed
                    # box: a jump to a non-overlapping box is where the steals live (d18)
                    iou_ = np.maximum(1.0 - _m.iou_distance(t_tlbr, d_tlbr),
                                      1.0 - _m.iou_distance(o_tlbr, d_tlbr))
                    cost = np.where(iou_ >= self.recovery_min_iou, cost, np.inf).astype(np.float32)
                # ---- recovery guards (Phase B, 2026-09-15; 0 = off) ----
                held_iou = float(getattr(self, "recovery_held_iou", 0.0))
                if held_iou > 0 and (activated_starcks or refind_stracks):
                    # a box on top of one some other track already took this
                    # frame is that vehicle's second box: taking it is a theft
                    h_tlbr = np.asarray([h.tlbr for h in activated_starcks + refind_stracks],
                                        dtype=np.float32)
                    stacked = (1.0 - _m.iou_distance(d_tlbr, h_tlbr)).max(axis=1) >= held_iou
                    if stacked.any():
                        self.n_recovery_refused_held += int(np.isfinite(cost[:, stacked]).sum())
                        cost[:, stacked] = np.inf
                rev_deg = float(getattr(self, "recovery_reverse_deg", 0.0))
                if rev_deg > 0:
                    refused = _reverse_jump_mask(cand_tracks, d_tlbr, rev_deg,
                                                 float(getattr(self, "recovery_reverse_jump", 0.15)))
                    if refused.any():
                        self.n_recovery_refused_reverse += int(np.isfinite(cost[refused]).sum())
                        cost[refused] = np.inf
                used_d: set[int] = set()
                for ti, di in _greedy_pairs(cost, self.recovery_reach):
                    track, det = cand_tracks[ti], cand_dets[di]
                    if self.recovery_log is not None:
                        self.recovery_log.append((
                            self.frame_id, int(track.track_id),
                            track.state == _TrackState.Lost,
                            int(self.frame_id - track.end_frame),
                            float(cost[ti, di]), tuple(float(v) for v in track.tlbr),
                            tuple(float(v) for v in det.tlbr), float(det.score)))
                    was_tracked = track.state == _TrackState.Tracked
                    if mlog is not None:
                        mlog.append(_match_rec(self, "s25", track, det, not was_tracked))
                    if _adopt(track, det, self.frame_id, self.kalman_filter,
                              self.reinit_width_jump, was_tracked):
                        self.n_reinit += 1
                    if was_tracked:
                        activated_starcks.append(track)
                        self.n_recovered += 1
                    else:
                        refind_stracks.append(track)
                        self.n_recovered_lost += 1
                    recovered_ids.add(track.track_id)
                    used_d.add(di)
                if used_d:
                    u_detection = [i for n, (p, i) in enumerate(cand_index)
                                   if p == 0 and n not in used_d]
                    u_detection_second = [i for n, (p, i) in enumerate(cand_index)
                                          if p == 1 and n not in used_d]

        # ---- L358-362: leftovers of stage 2 go lost (recovered ones skipped) ----
        for it in u_track_second:
            track = r_tracked_stracks[it]
            if track.track_id in recovered_ids:
                continue
            if not track.state == _TrackState.Lost:
                if self.edge_exit and _exited_frame(track, self.frame_w, self.frame_h, self.edge_margin):
                    # the vehicle left the picture: its id must not wait at the
                    # edge for the next vehicle through the same spot
                    track.mark_removed()
                    removed_stracks.append(track)
                    self.n_edge_exits += 1
                    continue
                track.mark_lost()
                lost_stracks.append(track)

        # ---- L364-407 (verbatim) -------------------------------------------------
        detections = [detections[i] for i in u_detection]
        dists = _m.iou_distance(unconfirmed, detections)
        dists = _m.fuse_score(dists, detections)
        matches, u_unconfirmed, u_detection = _m.linear_assignment(
            dists, thresh=0.7
        )
        for itracked, idet in matches:
            if mlog is not None:
                mlog.append(_match_rec(self, "unconf", unconfirmed[itracked], detections[idet], False))
            unconfirmed[itracked].update(detections[idet], self.frame_id)
            _note_obs(unconfirmed[itracked], detections[idet].tlbr, self.frame_id)
            activated_starcks.append(unconfirmed[itracked])
        # ---- CONFIRMATION BY POSITION (the second insertion) --------------------
        # A just-born track the IoU x conf pass (0.3) did not confirm is offered
        # the remaining boxes — high AND low — that still overlap it and keep
        # its width (a frame-edge strip becomes a full box of the same width).
        u_unconfirmed = list(u_unconfirmed)
        u_detection = list(u_detection)
        if self.confirm_by_position and u_unconfirmed:
            cand_tracks = [unconfirmed[i] for i in u_unconfirmed]
            cand_index = [(0, i) for i in u_detection] + [(1, i) for i in u_detection_second]
            cand_dets = [detections[i] if p == 0 else detections_second[i] for p, i in cand_index]
            if cand_dets:
                t_tlbr = np.asarray([t.tlbr for t in cand_tracks], dtype=np.float32)
                d_tlbr = np.asarray([d.tlbr for d in cand_dets], dtype=np.float32)
                cost = _recovery_cost(t_tlbr, d_tlbr, self.confirm_width_ratio)
                iou_ = 1.0 - _m.iou_distance(t_tlbr, d_tlbr)
                cost = np.where(iou_ > 0.0, cost, np.inf).astype(np.float32)
                # a box stacked on a track that already holds a vehicle this
                # frame (IoU > stack_iou) is that vehicle's double box, not a
                # second vehicle: confirming it would make a twin track
                held = activated_starcks + refind_stracks
                if held and self.stack_iou > 0:
                    h_tlbr = np.asarray([h.tlbr for h in held], dtype=np.float32)
                    stacked = (1.0 - _m.iou_distance(d_tlbr, h_tlbr)).max(axis=1) > self.stack_iou
                    cost[:, stacked] = np.inf
                taken_t: set[int] = set()
                used_d: set[int] = set()
                for ti, di in _greedy_pairs(cost, self.recovery_reach):
                    track, det = cand_tracks[ti], cand_dets[di]
                    if mlog is not None:
                        mlog.append(_match_rec(self, "confirm_pos", track, det, False))
                    # the birth box was the unrepresentative one (an edge strip);
                    # the motion state starts over from this full box
                    _adopt_reinit(track, det, self.frame_id, self.kalman_filter)
                    _note_obs(track, det.tlbr, self.frame_id)
                    activated_starcks.append(track)
                    self.n_confirmed_by_position += 1
                    taken_t.add(ti); used_d.add(di)
                if taken_t:
                    u_unconfirmed = [u for n, u in enumerate(u_unconfirmed) if n not in taken_t]
                    u_detection = [i for n, (p, i) in enumerate(cand_index) if p == 0 and n not in used_d]
                    u_detection_second = [i for n, (p, i) in enumerate(cand_index) if p == 1 and n not in used_d]
        if self.unconfirmed_death_log is not None and u_unconfirmed:
            left = [detections[i] for i in u_detection] + [detections_second[i] for i in u_detection_second]
            for it in u_unconfirmed:
                tb = np.asarray(unconfirmed[it].tlbr, dtype=np.float32)
                near, near_s = None, None
                if left:
                    lt = np.asarray([d.tlbr for d in left], dtype=np.float32)
                    cd = np.hypot((lt[:, 0] + lt[:, 2]) / 2 - (tb[0] + tb[2]) / 2,
                                  (lt[:, 1] + lt[:, 3]) / 2 - (tb[1] + tb[3]) / 2)
                    k = int(np.argmin(cd))
                    near, near_s = tuple(float(v) for v in lt[k]), float(left[k].score)
                self.unconfirmed_death_log.append(
                    (self.frame_id, int(unconfirmed[it].track_id), tuple(float(v) for v in tb), near, near_s))
        for it in u_unconfirmed:
            track = unconfirmed[it]
            track.mark_removed()
            removed_stracks.append(track)
            if wb and getattr(track, "weak_prefix", None):
                # the newborn died unconfirmed: its weak history goes back to the pool
                self.tentatives.append({"obs": list(track.weak_prefix[-self.wb_history_frames:])})
                track.weak_prefix = None

        if wb:
            self.tentatives = [t for t in self.tentatives
                               if self.frame_id - t["obs"][-1][0] <= self.wb_gap_frames]
        born = []

        # births: a box stacked (IoU > stack_iou) on a box already held by a
        # track this frame is that vehicle's double box 86-98% of the time
        # (research_dup_boxes.py); a real occluded vehicle is born once it
        # separates. Deferring the birth prevents the twin track.
        held_tlbr = (np.asarray([h.tlbr for h in activated_starcks + refind_stracks], dtype=np.float32)
                     if self.stack_iou > 0 and (activated_starcks or refind_stracks) else None)
        for inew in u_detection:
            track = detections[inew]
            if track.score < self.det_thresh:
                continue
            if held_tlbr is not None:
                ov = 1.0 - _m.iou_distance(np.asarray([track.tlbr], dtype=np.float32), held_tlbr)
                if ov.max() > self.stack_iou:
                    self.n_births_deferred += 1
                    if self.birth_log is not None:
                        self.birth_log.append((self.frame_id, -1, tuple(float(v) for v in track.tlbr), float(track.score)))
                    continue
            track.activate(self.kalman_filter, self.frame_id)
            _note_obs(track, track.tlbr, self.frame_id)
            if mlog is not None:
                mlog.append(_match_rec(self, "birth", track, track, False))
            if self.birth_log is not None:
                self.birth_log.append((self.frame_id, int(track.track_id),
                                       tuple(float(v) for v in track.tlbr), float(track.score)))
            activated_starcks.append(track)
            born.append(track)
        if wb:
            weak = ([detections_second[i] for i in u_detection_second]
                    + [detections[i] for i in u_detection if detections[i].score < self.det_thresh])
            self._weak_stage(born, weak, activated_starcks + refind_stracks, activated_starcks)
        for track in self.lost_tracks:
            if self.frame_id - track.end_frame > self.max_time_lost:
                track.mark_removed()
                removed_stracks.append(track)

        self.tracked_tracks = [
            t for t in self.tracked_tracks if t.state == _TrackState.Tracked
        ]
        self.tracked_tracks = _joint_tracks(self.tracked_tracks, activated_starcks)
        self.tracked_tracks = _joint_tracks(self.tracked_tracks, refind_stracks)
        self.lost_tracks = _sub_tracks(self.lost_tracks, self.tracked_tracks)
        self.lost_tracks.extend(lost_stracks)
        self.lost_tracks = _sub_tracks(self.lost_tracks, self.removed_tracks)
        self.removed_tracks.extend(removed_stracks)
        self.tracked_tracks, self.lost_tracks = _remove_duplicate_tracks(
            self.tracked_tracks, self.lost_tracks
        )
        output_stracks = [track for track in self.tracked_tracks if track.is_activated]
        if wb:
            self._emit_backfill(output_stracks)
        return output_stracks

    # ---- weak-box births -----------------------------------------------------
    def _abs(self) -> int:
        a = getattr(self, "_abs_now", None)
        return int(a) if a is not None else int(self.frame_id)

    def _tent_boxes(self):
        """Last observed box and a velocity-shifted box per tentative."""
        L, P = [], []
        for t in self.tentatives:
            o = t["obs"]
            last = o[-1]
            box = np.array(last[2:6], dtype=np.float32)
            vx = vy = 0.0
            a = o[max(0, len(o) - 4)]
            if last[0] > a[0]:
                vx = ((last[2] + last[4]) - (a[2] + a[4])) / 2.0 / (last[0] - a[0])
                vy = ((last[3] + last[5]) - (a[3] + a[5])) / 2.0 / (last[0] - a[0])
            g = self.frame_id - last[0]
            L.append(box)
            P.append(box + np.array([vx * g, vy * g, vx * g, vy * g], dtype=np.float32))
        return (np.asarray(L, dtype=np.float32).reshape(-1, 4),
                np.asarray(P, dtype=np.float32).reshape(-1, 4))

    def _tent_pairs(self, boxes_tlbr: np.ndarray) -> list[tuple[int, int]]:
        """(tentative index, box index) pairs by the tracker's position rule:
        box units against the last or velocity-shifted box, overlap gate,
        width ratio, nearest first, oldest tentative first on ties."""
        if not self.tentatives or len(boxes_tlbr) == 0:
            return []
        L, P = self._tent_boxes()
        cost = np.minimum(_recovery_cost(L, boxes_tlbr, self.confirm_width_ratio),
                          _recovery_cost(P, boxes_tlbr, self.confirm_width_ratio))
        if self.recovery_min_iou > 0:
            ov = np.maximum(1.0 - _m.iou_distance(L, boxes_tlbr), 1.0 - _m.iou_distance(P, boxes_tlbr))
            cost = np.where(ov >= self.recovery_min_iou, cost, np.inf).astype(np.float32)
        return _greedy_pairs(cost, self.recovery_reach)

    def _tent_ready(self, t: dict) -> bool:
        if not self.wb_promote:
            return False
        o = t["obs"]
        if len(o) < 3 or o[-1][0] - o[0][0] < self.wb_persist_frames:
            return False
        k = min(3, len(o) // 2)
        c = np.array([((q[2] + q[4]) / 2.0, (q[3] + q[5]) / 2.0) for q in o], dtype=np.float64)
        w = float(np.median([q[4] - q[2] for q in o]))
        move = float(np.hypot(*(c[-k:].mean(axis=0) - c[:k].mean(axis=0)))) / max(w, 1e-6)
        if move < self.wb_min_move:
            return False
        recent = [q[8] for q in o if o[-1][0] - q[0] < self.wb_persist_frames] or [o[-1][8]]
        if float(np.median(recent)) >= self.wb_max_cover or o[-1][8] >= self.wb_max_cover:
            return False
        return True

    def _promote(self, t: dict, det, out_list: list) -> None:
        o = t["obs"]
        det.class_ids = _majority([q[7] for q in o])
        det.activate(self.kalman_filter, self.frame_id)     # new id, Kalman from this box
        det.is_activated = True                             # output THIS frame
        a, b = o[max(0, len(o) - 4)], o[-1]
        if b[0] > a[0]:
            det.mean[4] = ((b[2] + b[4]) - (a[2] + a[4])) / 2.0 / (b[0] - a[0])
            det.mean[5] = ((b[3] + b[5]) - (a[3] + a[5])) / 2.0 / (b[0] - a[0])
        det.obs_centers = [(q[0], (q[2] + q[4]) / 2.0, (q[3] + q[5]) / 2.0) for q in o[-4:-1]]
        _note_obs(det, det.tlbr, self.frame_id)
        det.weak_prefix = list(o[:-1])                      # strictly before this frame
        out_list.append(det)
        self.n_weak_births += 1
        if self.weak_birth_log is not None:
            self.weak_birth_log.append(("promote", self.frame_id, int(det.track_id), len(o)))

    def _weak_stage(self, born: list, weak: list, held: list, out_list: list) -> None:
        lf, af = self.frame_id, self._abs()
        # (a) inheritance: a newborn that continues a tentative takes its history
        if born and self.tentatives:
            bt = np.asarray([b.tlbr for b in born], dtype=np.float32)
            used = set()
            for ti, bi in self._tent_pairs(bt):
                b = born[bi]
                used.add(ti)
                obs = self.tentatives[ti]["obs"]
                # the same coverage guard as promotion: a history that rode
                # inside a held vehicle is that vehicle's double box, and
                # back-filling it would run a twin beside the vehicle's track
                if float(np.median([q[8] for q in obs])) >= self.wb_max_cover:
                    continue
                b.weak_prefix = obs + [_obs(lf, af, b.tlbr, b.score, b.class_ids, 0.0)]
                self.n_weak_inherited += 1
                if self.weak_birth_log is not None:
                    self.weak_birth_log.append(("inherit", lf, int(b.track_id), len(self.tentatives[ti]["obs"])))
            if used:
                self.tentatives = [t for i, t in enumerate(self.tentatives) if i not in used]
        # (b) candidates: weak leftovers not stacked on a held vehicle
        kept, covers = [], []
        if weak:
            wt = np.asarray([d.tlbr for d in weak], dtype=np.float32)
            if held:
                ht = np.asarray([h.tlbr for h in held], dtype=np.float32)
                stacked = ((1.0 - _m.iou_distance(wt, ht)).max(axis=1) > self.stack_iou
                           if self.stack_iou > 0 else np.zeros(len(weak), dtype=bool))
                cov_max = _coverage(wt, ht).max(axis=1)
            else:
                stacked = np.zeros(len(weak), dtype=bool)
                cov_max = np.zeros(len(weak), dtype=np.float32)
            for i, d in enumerate(weak):
                if not stacked[i]:
                    kept.append(d)
                    covers.append(float(cov_max[i]))
        # (c) association (and new tentatives from unmatched candidates)
        seen = set()
        if kept:
            kt = np.asarray([d.tlbr for d in kept], dtype=np.float32)
            used_k = set()
            for ti, ki in self._tent_pairs(kt):
                t = self.tentatives[ti]
                d = kept[ki]
                t["obs"].append(_obs(lf, af, d.tlbr, d.score, d.class_ids, covers[ki]))
                if len(t["obs"]) > self.wb_history_frames:
                    del t["obs"][:len(t["obs"]) - self.wb_history_frames]
                t["det"] = d
                seen.add(ti)
                used_k.add(ki)
            for ki, d in enumerate(kept):
                if ki not in used_k:
                    self.tentatives.append({"obs": [_obs(lf, af, d.tlbr, d.score, d.class_ids, covers[ki])],
                                            "det": d})
                    seen.add(len(self.tentatives) - 1)
        # (d) promotion, oldest first, never onto a box promoted this frame
        promoted: list = []
        drop = set()
        for ti in sorted(seen):
            t = self.tentatives[ti]
            d = t.get("det")
            if d is None or not self._tent_ready(t):
                continue
            box = np.asarray([d.tlbr], dtype=np.float32)
            if promoted:
                pt = np.asarray(promoted, dtype=np.float32)
                if ((1.0 - _m.iou_distance(box, pt)).max() > self.stack_iou
                        or _coverage(box, pt).max() >= self.wb_max_cover):
                    continue
            self._promote(t, d, out_list)
            promoted.append(np.asarray(d.tlbr, dtype=np.float32))
            drop.add(ti)
        for t in self.tentatives:
            t.pop("det", None)
        if drop:
            self.tentatives = [t for i, t in enumerate(self.tentatives) if i not in drop]

    def _emit_backfill(self, output: list) -> None:
        """A track's weak prefix becomes back-fill rows on its first output
        frame (after duplicate removal, so no row is orphaned)."""
        promo = self._abs()
        rows = getattr(self, "backfill", None)
        for t in output:
            pre = getattr(t, "weak_prefix", None)
            if not pre:
                continue
            t.weak_prefix = None
            if rows is None:
                continue
            try:
                cls = int(t.class_ids)
            except (TypeError, ValueError):
                cls = -1
            tid = int(t.track_id)
            for q in pre:
                if q[1] < promo:
                    rows.append((tid, q[1], (q[2] + q[4]) / 2.0, (q[3] + q[5]) / 2.0,
                                 q[4] - q[2], q[5] - q[3], q[6], cls, promo))


class ByteTrackBackend:
    """supervision ByteTrack backend (the original, default implementation)."""

    def __init__(
        self,
        track_activation_threshold: float = TRACKER_ACTIVATION_THRESHOLD,
        lost_track_buffer: int = TRACKER_LOST_BUFFER,
        minimum_matching_threshold: float = TRACKER_MATCH_THRESHOLD,
        frame_rate: int = 30,
        frame_size: tuple | None = None,
        collect_backfill: bool = False,
    ):
        from backend import config as _cfg
        self.fuse_score = bool(getattr(_cfg, "TRACKER_FUSE_SCORE", True))
        apply_fuse_score_setting(self.fuse_score)
        # Read late (per instance) so tests can monkeypatch the config module.
        self.position_recovery = bool(getattr(_cfg, "TRACKER_POSITION_RECOVERY", False))
        self._recovery_kwargs = {
            "recovery_reach": float(getattr(_cfg, "TRACKER_RECOVERY_REACH", 0.9)),
            "recovery_size_ratio": float(getattr(_cfg, "TRACKER_RECOVERY_SIZE_RATIO", 0.3)),
            "recovery_min_iou": float(getattr(_cfg, "TRACKER_RECOVERY_MIN_IOU", 0.2)),
            "recovery_held_iou": float(getattr(_cfg, "TRACKER_RECOVERY_HELD_IOU", 0.6)),
            "recovery_reverse_deg": float(getattr(_cfg, "TRACKER_RECOVERY_REVERSE_DEG", 0.0)),
            "recovery_reverse_jump": float(getattr(_cfg, "TRACKER_RECOVERY_REVERSE_JUMP", 0.15)),
            "confirm_by_position": bool(getattr(_cfg, "TRACKER_CONFIRM_BY_POSITION", True)),
            "confirm_width_ratio": float(getattr(_cfg, "TRACKER_CONFIRM_WIDTH_RATIO", 0.5)),
            "reinit_width_jump": float(getattr(_cfg, "TRACKER_REINIT_WIDTH_JUMP", 1.5)),
            "lost_patience_s": float(getattr(_cfg, "TRACKER_RECOVERY_LOST_PATIENCE_S", 0.5)),
            "edge_exit": bool(getattr(_cfg, "TRACKER_EDGE_EXIT", True)),
            "frame_size": (tuple(frame_size) if frame_size else None),
            "stack_iou": float(getattr(_cfg, "TRACKER_STACK_IOU", 0.6)),
            "weak_birth": bool(getattr(_cfg, "TRACKER_WEAK_BIRTH", False)),
            "weak_birth_persist_s": float(getattr(_cfg, "TRACKER_WEAK_BIRTH_PERSIST_S", 0.5)),
            "weak_birth_gap_s": float(getattr(_cfg, "TRACKER_WEAK_BIRTH_GAP_S", 0.2)),
            "weak_birth_min_move": float(getattr(_cfg, "TRACKER_WEAK_BIRTH_MIN_MOVE", 0.5)),
            "weak_birth_max_cover": float(getattr(_cfg, "TRACKER_WEAK_BIRTH_MAX_COVER", 0.6)),
            "weak_birth_history_s": float(getattr(_cfg, "TRACKER_WEAK_BIRTH_HISTORY_S", 10.0)),
            "weak_birth_promote": bool(getattr(_cfg, "TRACKER_WEAK_BIRTH_PROMOTE", False)),
            "collect_backfill": bool(collect_backfill),
        }
        self._init_kwargs = {
            "track_thresh": track_activation_threshold,
            "track_buffer": lost_track_buffer,
            "match_thresh": minimum_matching_threshold,
            "frame_rate": frame_rate,
        }
        self.byte_track = self._make_bytetrack()
        self._active_track_ids: set[int] = set()
        # the tracker's input step: stacked double boxes (> 0.8 IoU) are one
        # vehicle; below that the tracker decides (see the confirmation guard)
        self.dup_box_iou = (float(getattr(_cfg, "TRACKER_DUP_BOX_IOU", 0.8))
                            if self.position_recovery else 0.0)

    def _make_bytetrack(self):
        if self.position_recovery:
            return _RecoveringByteTrack(**self._init_kwargs, **self._recovery_kwargs)
        return sv.ByteTrack(**self._init_kwargs)

    def update(self, detections: list[dict], frame_number: int) -> list[dict]:
        # the absolute frame, for back-fill rows (the fork counts frames locally)
        self.byte_track._abs_now = int(frame_number)
        if not detections:
            self.byte_track.update_with_detections(sv.Detections.empty())
            self._active_track_ids = set()
            return []

        if getattr(self, "dup_box_iou", 0.0) > 0:
            detections = _dedup_boxes(detections, self.dup_box_iou)
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

    def pop_backfill(self) -> list[dict]:
        """Back-fill rows collected since the last call (weak-box births):
        each a past-frame observation of a track now in the output, at its
        ABSOLUTE frame, with the frame the track was first output. Empty
        unless the backend was built with collect_backfill=True."""
        bt = self.byte_track
        rows = getattr(bt, "backfill", None)
        if not rows:
            return []
        bt.backfill = []
        return [{"track_id": int(r[0]), "frame": int(r[1]), "center": [float(r[2]), float(r[3])],
                 "bbox_width": float(r[4]), "bbox_height": float(r[5]), "confidence": float(r[6]),
                 "class_id": int(r[7]), "promoted_at": int(r[8])} for r in rows]

    def reset(self):
        self.byte_track = self._make_bytetrack()
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
# 2026-09-12: _RecoveringByteTrack is NOT that wrapper — it runs INSIDE the
# association, before births, on leftovers only, gated in box units, so a
# recovered box can never seed a follower's new track; the follower-merge risk
# above is exactly what its fleet arm (d18) measures. Default OFF until then.

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
