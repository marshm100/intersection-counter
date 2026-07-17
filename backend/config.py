import os
from pathlib import Path

# Base directories
APP_DIR = Path(__file__).parent.parent
DATA_DIR = APP_DIR / "data"
MODELS_DIR = APP_DIR / "models"
FRONTEND_DIR = APP_DIR / "frontend"

# Database
PROJECTS_DIR = DATA_DIR / "projects"

# Video processing
DEFAULT_FRAME_SKIP = 3
DEFAULT_INTERVAL_MINUTES = 15
MAX_PRESCAN_SECONDS = 600
PRESCAN_CONFIDENCE_THRESHOLD = 0.90
CHECKPOINT_INTERVAL_SECONDS = 120
MAX_CONCURRENT_PIPELINES = 2

# Detection — accurate mode is tuned for accuracy over speed. yolo26l is
# the large variant; imgsz=1280 keeps distant intersection vehicles
# detectable at 1080p capture. Confidence is intentionally low — obvious
# vehicles (e.g., a foreground pickup in glare) sometimes come back at
# 0.10-0.14 from yolo26l, especially when partially backlit.
# CAVEAT (FM51 recovery experiment, 2026-07-02): imgsz only helps when the
# detail is IN the source pixels. On 640x480 footage, running 1280 inference
# just upscales — distant vehicles below the source pixel floor are NOT
# recovered (measured +6% uniform, not a distant-vehicle recovery). A
# low-resolution source is a hard wall; the mitigation is spot-count coverage
# of the affected window (spot_check §5 stratification), not a detector knob.
#
# Fast mode uses the small variant at 640 + every-3rd-frame detection
# (tracker Kalman-interpolates between detections) — ~10-15× faster on
# CPU. Mode is per-project; default is "accurate" so existing projects
# don't change behavior on upgrade.
YOLO_MODEL = "yolo26l.pt"
YOLO_CONFIDENCE_THRESHOLD = 0.08
YOLO_IOU_THRESHOLD = 0.45
YOLO_IMGSZ = 1280

# Class-agnostic NMS applied to cached detections BEFORE the tracker (Stage-2
# anti-duplication, 2026-06-02). The detector double-boxes one vehicle (e.g. a
# 'car' AND a 'truck' box) in ~83% of frames at IoU>0.6 — model-independent
# (yolo26s@960 and yolo26l@1280 both do it). bytetrack tracks each box as its
# own ID, producing parallel duplicate THROUGH tracks (the cam5 NB-thru +162).
# YOLO's own per-class NMS (YOLO_IOU_THRESHOLD) does NOT suppress cross-class
# duplicates, so we collapse them class-agnostically at the tracking input. The
# detection CACHE stays raw (written before _ingest_detections); only tracking
# sees the deduped stream.
# DEFAULT OFF (None): measured per-camera and it is NOT corridor-safe — at IoU 0.7
# it over-merges DENSE but distinct throughs (cam4 NB-thru 728→~644) for only a
# ~0.4pp gain where it helps (cam5). The real Stage-2 through win came from
# REFRESHING stale shipped throughs (apply_hybrid --throughs-db), not NMS. Set to
# a float (e.g. 0.7) to enable for a specific camera's retrack; env override
# PRE_TRACK_NMS_IOU=<float> turns it on per-run.
import os as _os
_nms_env = _os.environ.get("PRE_TRACK_NMS_IOU")
PRE_TRACK_NMS_IOU = float(_nms_env) if (_nms_env and _nms_env != "off") else None

PROCESSING_MODES = {
    "accurate": {
        "yolo_model": "yolo26l.pt",
        "yolo_imgsz": 1280,
        "yolo_confidence": 0.08,
        # Detect on every frame — tracker sees full source frame rate.
        "detection_skip": 1,
        # Strict ByteTrack defaults: Kalman has fresh velocity every step.
        "tracker_match_threshold": 0.8,
        "tracker_activation_threshold": 0.25,
        "label": "Accurate",
        "description": "Best accuracy. Large model at 1280 px, every frame. On CPU this is ~60× slower than real-time and is only practical for short clips; for full-day footage use Balanced or Fast.",
    },
    "balanced": {
        # PROMOTED 2026-07-17 (plan_detector_finetune, FM51 full-chain gate:
        # total -9.1% -> +1.1%, interval MAE 8.8% -> 2.5% PASS, PM miss
        # closed, on the held-out site): the corridor-fine-tuned two-class
        # head at its VALIDATED imgsz. Fallback = the previous stock pair
        # (yolo26s.pt @ 960, class_scheme coco). Known residual, tracked in
        # the plan doc: far-field side-leg origin grab at T-stems (the
        # origin-grab cycle owns it).
        "yolo_model": "yolo26s_ft1.pt",
        "yolo_imgsz": 640,
        "yolo_class_scheme": "finetune_v1",
        "yolo_confidence": 0.10,
        "detection_skip": 1,
        # Detection every frame, so strict ByteTrack defaults are appropriate.
        "tracker_match_threshold": 0.8,
        "tracker_activation_threshold": 0.25,
        "label": "Balanced",
        "description": "Recommended for full-day clips. Fine-tuned site-trained model at 640 px detecting every frame (FM51-validated: interval error 8.8%→2.5%); fast vehicles track reliably (no skip-frame Kalman mismatch). Full-day footage usually fits in an overnight run.",
    },
    "fast": {
        "yolo_model": "yolo26s.pt",
        "yolo_imgsz": 640,
        # Slightly higher conf floor — small model is noisier at low conf.
        "yolo_confidence": 0.15,
        # Detect every 3rd frame; tracker Kalman-interpolates between.
        "detection_skip": 3,
        # Loosened tracker thresholds for the skip-3 regime. ByteTrack's
        # Kalman assumes consecutive update() calls are 1 frame apart, so
        # at detection_skip=3 it under-predicts motion by 3× and a moving
        # vehicle's new bbox can have ~0 IoU with the predicted bbox.
        # match_thresh=0.95 → match when IoU≥0.05 (vs the 0.8/IoU≥0.2 default).
        # activation_threshold=0.15 lets single-detection fast vehicles
        # start a track rather than dying in the BYTE association queue.
        "tracker_match_threshold": 0.95,
        "tracker_activation_threshold": 0.15,
        "label": "Fast",
        "description": "~10-15× faster. Small model at 640 px with detection every 3rd frame; tracker interpolates. May miss small/distant vehicles. Good for previewing.",
    },
}
DEFAULT_PROCESSING_MODE = "accurate"

# Two-pass counting flow (MASTER_PLAN 2c / plan_A4_stage3_2026-07-10):
# pass-1 raw-track dumps at ingest, pass-2 (bank + replay-classify + turn
# merge + QA) behind "Confirm & process". DEFAULT ON since 2026-07-13: the
# stage-3.4 operator dry-run passed its gate (UI-only run reproduced the
# shipped corridor counts exactly — plan_stage34_operator_surface doc).
# Env override to disable (reverts to the legacy live pipeline, untouched):
# TWO_PASS_ENABLED=0.
import os as _os2
TWO_PASS_ENABLED = _os2.environ.get("TWO_PASS_ENABLED", "1") in ("1", "true", "on")


def get_processing_mode_config(mode: str | None) -> dict:
    """Return the config dict for `mode`, falling back to default on unknown."""
    if mode and mode in PROCESSING_MODES:
        return PROCESSING_MODES[mode]
    return PROCESSING_MODES[DEFAULT_PROCESSING_MODE]

# Classification mapping (pedestrians out of scope for v2 per PRD)
# 8 = the fine-tuned head's NATIVE articulated class (plan_articulated_native
# 2026-07-17). COCO 8 is "boat", which no code path ever requests, so the id
# is free in every cache/dump this app has written; it must stay OUT of the
# stock-model class filter (detector.RELEVANT_CLASSES excludes it).
NATIVE_ARTICULATED_CLASS_ID = 8
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck",
                   NATIVE_ARTICULATED_CLASS_ID: "articulated_truck"}

# Trajectory classification thresholds (degrees)
TRAJECTORY_THROUGH_MAX_ANGLE = 25
TRAJECTORY_TURN_MIN_ANGLE = 35
TRAJECTORY_TURN_MAX_ANGLE = 135
TRAJECTORY_UTURN_MIN_ANGLE = 135
TRAJECTORY_MIN_POINTS = 5
TRAJECTORY_MIN_DISTANCE_PX = 50
TRAJECTORY_CURVATURE_THRESHOLD = 40  # cumulative curvature tiebreaker for ambiguous zone
# A real U-turn vehicle traverses the intersection and ends a meaningful distance
# from where it entered. A trajectory that classifies as a U-turn (>=135° net
# heading change) but ends very close to its start, having looped through a large
# cumulative arc, is a TRACKING ARTIFACT (ID-switch / coasting doubling back), not
# a vehicle — at the Sunnyvale cam1 these phantom U-turns were 20/30min vs ~0
# real. Gate on net (start->end) displacement, NOT path arc length.
TRAJECTORY_UTURN_MIN_NET_DISPLACEMENT_PX = 90

# Tracker tuning — ByteTrack defaults are 0.25 / 0.8 / 30 fps with
# track_buffer=30 frames. We bump track_buffer to 5s (150) so brief
# occlusions don't kill tracks, but the match/activation thresholds
# stay at defaults — match_thresh is a DISTANCE gate (1-IoU), so
# lower values are STRICTER, not looser. Setting it to 0.3 (as we
# previously did, misreading the semantics) required IoU>=0.7 every
# frame and silently dropped tracks the instant a vehicle moved any
# meaningful distance.
TRACKER_LOST_BUFFER = 150            # frames before dropping track (5s @ 30fps; ByteTrack default 30)
TRACKER_MATCH_THRESHOLD = 0.8        # ByteTrack default — IoU>=0.2 matches (loose)
TRACKER_ACTIVATION_THRESHOLD = 0.25  # ByteTrack default — confirms tracks for conf >= 0.25

# Origin assignment
ORIGIN_ASSIGN_MIN_FRAMES = 2   # trajectory points needed before assigning origin

# Half-length of the synthesized tripwire built from a single calibrated
# origin point (perpendicular to reference_heading, extending each way).
# 40 px was too short for legs whose origin sits near a frame edge —
# vehicles entering from those approaches are often first detected by
# YOLO at positions past the short tripwire's extent, missing it
# entirely and falling to the heading-fallback path. 120 px gives more
# lateral coverage; the line-crossing math still only matches actual
# trajectory segments, so we don't pick up spurious crossings outside
# the image.
TRIPWIRE_HALF_LENGTH_PX = 120

# Origin Tier-2 (heading fallback) leg-label blocklist. Heading-only
# attribution has a wide angular basin (<=90 deg from leg ref_heading) so
# a low-volume leg whose ref_heading sits between two main legs can
# silently absorb cross-leg traffic. At Sunnyvale this is the private
# driveway (L24) attracting 596 phantom heading-fallback events. Any leg
# whose label contains one of these keywords is excluded from heading
# fallback; polyline + tripwire tiers still attribute to it normally.
HEADING_FALLBACK_EXCLUDE_LABEL_KEYWORDS = ("Driveway",)

# Origin Tier-0 (polyline) heading-consistency gate. A polyline match is
# accepted only if the polyline's averaged first-3-segments bearing is
# within this many degrees of the track prefix's averaged first-3-segments
# bearing. Eliminates cross-leg coincidental spatial matches where a
# trajectory happens to score low against a polyline whose road points
# in a different direction.
ORIGIN_POLYLINE_HEADING_GATE_DEG = 25.0

# --- Attribution v2: joint partial-Fréchet scorer (2026-05-27) -------------
# When enabled and the camera has calibrated paths, a single joint scorer
# (score_path_joint) runs at finalization and reads origin + destination +
# movement off the best-matching path's SUB-CURVE, replacing the separate
# Tier-0 origin (entry-tangent) + Tier-0 destination polyline scorers and the
# Stage A gates above. The old scorers remain as the automatic fallback when
# the joint scorer returns no confident match, and the early _assign_origin
# tiers still gate "is this a real intersection vehicle". See
# docs/implementation_plan_accuracy_2026-05-27.md. Tunables below are starting
# values; tune on the replay harness against B0_baseline once trajectories are
# regenerated (the original 9,785 were deleted; only ~144 remain).
USE_JOINT_PARTIAL_FRECHET_SCORER = True
# Cost metric for the sub-curve match. "dtw_mean" = robust mean coupled distance
# (default); "frechet" = classic sup-norm discrete Fréchet. We use dtw_mean
# because pure Fréchet is a sup norm that a single jittery tracking point spikes:
# on the real Sunnyvale trajectories best-match Fréchet ran ~82 px median, while
# the (true-mean) dtw_mean runs ~29 px median — close to the scale the proven
# Stage A mean-perpendicular destination scorer (20 px one-way radius) used.
# Default flipped to "mdh" (Phase 2.3, 2026-06-11): fragmentation-robust
# min-directed-Hausdorff + tail-angle + exit-proximity. Corridor A/B under
# identical banks/recipes: cam1 19.4->18.4, cam2 AM 15.8->13.4 and HELD-OUT PM
# 21.6->18.9, cam4 22.5->14.7 (gross 26.0->18.8), cam5 flat; only cam3
# regressed (+1.1 net, gross flat) and is pinned to dtw_mean via its
# per-camera calib_cost_metric override. Env override for per-run sweeps.
JOINT_SCORER_COST_METRIC = _os.environ.get("JOINT_SCORER_COST_METRIC", "mdh")
# Calibrated on the surviving 144-event sample (median ~29 px, ~60% match at 35);
# RE-TUNE against B0_baseline once the full trajectory set is regenerated.
JOINT_SCORER_MAX_COST_PX = 35.0        # reject matches whose mean coupled distance exceeds this
# Deliberately LOW: a mid-turn entry (the failure mode this scorer rescues)
# covers only the path suffix (~0.40-0.55 of arc length), so a high floor would
# reject exactly those tracks. Keep this just high enough to kill tiny-fragment
# matches; lean on the soft coverage term (weight below) + max_cost for quality.
JOINT_SCORER_MIN_COVERAGE_FRAC = 0.28  # hard floor on matched sub-curve arc-length fraction
JOINT_SCORER_TAIL_WINDOW = 7           # tail points used for the exit-direction prior
JOINT_SCORER_TAIL_WEIGHT = 0.35        # blend weight of tail prior vs shape cost
JOINT_SCORER_COVERAGE_WEIGHT = 0.15    # blend weight of coverage term
# Strict gate for TURN-labelled paths only (left/right/u_turn): a turn path may
# claim a track only if the track's tail aligns with the turn's exit tangent
# (tail_prior >= floor) AND it covers enough of the turn arc. Stops straight
# through trajectories from shape-matching a turn polyline's sub-curve and being
# mislabelled as turns. See docs/turn_attribution_plan_2026-05-29.md.
JOINT_SCORER_TURN_TAIL_PRIOR_FLOOR = 0.85
JOINT_SCORER_TURN_MIN_COVERAGE = 0.40

# Origin-rewrite gate (snap-magnet defence, 2026-06-02). The joint scorer READS
# origin off the winning path, which lets a straight "turn" polyline capture a
# THROUGH track and rewrite its origin to a leg the track never entered from
# (the cam4 EB-left magnet: manual 6, attributed 214). This gate rejects a TURN
# match that would rewrite origin to a leg that is NOT the nearest origin-zone to
# the track's first point — BUT ONLY when the trajectory is itself geometrically
# straight (a through). Real turns curve, so a genuine mid-turn-FOV-entry turn
# (the joint scorer's raison d'être at cam1) stays BELOW the straightness floor
# and is spared. Self-limiting and data-driven — no per-camera flag needed.
# Validated on the snap-magnet replay (scripts/replay_snapmagnet.py): cam4
# 22.7%->7.0% net, cam1/cam2/cam3 unharmed. See memory
# project_accuracy_snap_magnet_mechanism.
ORIGIN_REWRITE_GATE_ENABLED = True
ORIGIN_REWRITE_GATE_STRAIGHTNESS = 0.97  # only gate tracks at/above this straightness

# Entry-tiebreak for shared-exit collinear path pairs (2026-07-02). Under the
# mdh cost metric two paths that MERGE to the same exit and run collinear near
# it are indistinguishable to min-directed-Hausdorff: the min-relaxation that
# makes mdh fragment-robust discards the one signal that separates them, the
# ENTRY. cam2 is the exemplar — SB-thru (27->29) and EB-right (28->29) share the
# leg-29 exit (1 px), run 11 px apart, but their entries are 171 px apart; mdh
# sees ~11 px = "same shape", so a real SB-thru track matches the EB-right path
# and its origin is rewritten SB->EB (EB +25% over / SB -11% under, a ~700-veh
# swap; a second pair does the same at the leg-26 exit). This targeted tiebreak:
# when the top match has a collinear rival that SHARES its exit AND whose entry
# is well separated, re-pick by which candidate's ENTRY is closest to the
# track's first point. It is a RELATIVE tiebreak between two already-collinear
# candidates, never an absolute entry->origin estimate (that fails here — the
# FOV clips approaches, which regressed cam2 14.4->23.5 when tried globally),
# fires only under mdh (dtw cameras like cam3 can never trigger it, so they are
# byte-identical), and overrides the mdh winner only on a decisive entry margin.
# See docs/handoff_2026-07-02_session_end.md + memory
# project_per_approach_attribution_2026_06_30.
#
# DISPROVEN 2026-07-02 (kept OFF; scaffolding retained for a non-entry retry).
# Full-chain replay REGRESSED cam2: EB 33.2->41.0, SB 12.3->15.8, 747 firings.
# Birth diagnostic (scripts/diagnose_cam2_entry.py) shows why: SB tracks are 84%
# born near the SB entry, so births DO discriminate — but the tiebreak by
# construction only fires when the entry DECISIVELY favors the rival, which
# selects exactly the misleading ~16% of genuinely-SB tracks born mid-approach
# (past the far-edge SB bank entry, drifting toward the central EB entry pixel).
# It is a biased sampler of its own worst cases: it can't move the real overcount
# (EB-attributed tracks are 87% EB-near) and corrupts the SB tracks it touches.
# The cluster detection (shared-exit + collinear) is sound and reusable; only the
# entry DISCRIMINATOR is dead here. A speed/curvature discriminator is the retry.
ENTRY_TIEBREAK_ENABLED = False
ENTRY_TIEBREAK_EXIT_PX = 15.0           # top & rival exit points within this = "shared exit"
ENTRY_TIEBREAK_COLLINEAR_PX = 15.0      # min-directed dist between the two paths below this = collinear
ENTRY_TIEBREAK_MIN_ENTRY_SEP_PX = 60.0  # only fire when the two ENTRIES are at least this far apart
ENTRY_TIEBREAK_DECISIVE_PX = 30.0       # override the mdh winner only if the rival's entry is this much closer

# Speed-tiebreak (2026-07-02) — the retry after the ENTRY tiebreak was disproven.
# Same shared-exit collinear cluster (reuses ENTRY_TIEBREAK_EXIT_PX/COLLINEAR_PX),
# but splits the pair by the track's PIXEL SPEED (median inter-point step) vs each
# candidate path's `expected_speed` signature. Speed is a per-approach signature
# mdh does NOT use and FOV-clipping does NOT corrupt (diagnostic: cam2 SB approaches
# ~5 px/step, EB ~1-2, Cohen's d~2-2.8; and it leans the RIGHT way on the exact
# tracks entry got wrong). Overrides the mdh pick only when the track's speed is
# DECISIVELY closer to a collinear rival whose signature differs enough to
# discriminate. Blind-deployable: `expected_speed` is computed from a path's
# SUPPORTING TRACKS at bank-build time (NOT Miovision) — so this is INERT until the
# bank carries it (live banks don't yet; the replay harness augments for the A/B).
# See scripts/diagnose_cam2_speed*.py + memory project_per_approach_attribution_2026_06_30.
#
# PER-CAMERA, NOT global (1/3/4/5 regression sweep 2026-07-02). Validated
# NET-POSITIVE on cam2 (EB 33.2->28.8, SB 12.3->10.8, 392 fires) and cam5 (NB
# 9.0->5.3, 2027 fires); provably INERT on cam1 (0 fires, no qualifying cluster)
# and cam3 (dtw-gated, 0 fires). BUT it REGRESSED cam4 (NB 4.9->5.8 PASS->FAIL,
# 1487 fires) — cam4's collinear speed signatures don't separate cleanly. So the
# default is OFF; enable per camera via the `calib_speed_tiebreak` knob only where
# a sweep confirms it helps (cam2, cam5). Still inert until build_bank supplies
# expected_speed on the paths.
SPEED_TIEBREAK_ENABLED = False          # OFF by default; per-camera calib_speed_tiebreak opt-in (cam2/cam5 validated)
SPEED_TIEBREAK_DECISIVE = 1.0           # px/step: override only if track speed is this much closer to the rival's signature
SPEED_TIEBREAK_MIN_SEP = 1.5            # px/step: only fire when the two paths' speed signatures differ by this

# --- Origin-evidence gate (item-8 mechanism 1, 2026-07-14) ------------------
# Phase-0 autopsy: all three attribution walls share one axis — origin gets
# CLAIMED without entry evidence (the joint scorer reads origin off the winning
# bank path; 208 NB-left->SB-right + 454 EB->SB-thru flips on cam2, 71 mid-block
# driveway grabs on cam4). When ON, a track that crossed a leg's entry gate
# inward has that origin BOUND: the joint scorer's candidates are filtered to
# paths from that leg, and the early entry-tangent origin is overridden to the
# evidenced leg. Tracks with NO entry evidence keep current behavior (counted
# via n_origin_unevidenced; the posterior half gates separately per the plan).
# OFF by default until the cam2 fit-window ablation + five-cam blind sweep
# (docs/plan_origin_evidence_gate_2026-07-14.md). Env override for dev sweeps.
ORIGIN_EVIDENCE_GATE_ENABLED = _os.environ.get(
    "ORIGIN_EVIDENCE_GATE_ENABLED", "") in ("1", "true", "on")

# --- Partial-evidence posterior (item-8 mechanism 1, posterior half) ---------
# docs/plan_posterior_half_2026-07-15.md. When the evidence cannot decide a
# single cell, build an explicit posterior over the feasible cells from corpus
# supports x shape residual, count at the posterior max, and record the
# posterior + margin so the flag queue surfaces the near-ties. Three branches:
# unevidenced-origin posterior, evidenced-truncated destination tie-break, and
# the evidenced insufficient-data rescue (the no-drop principle). Requires
# ORIGIN_EVIDENCE_GATE_ENABLED (evidence comes from the same gate pass).
# OFF by default until the stage-4 fit + stage-5 held-out + stage-6 sweep.
ORIGIN_POSTERIOR_ENABLED = _os.environ.get(
    "ORIGIN_POSTERIOR_ENABLED", "") in ("1", "true", "on")
# The two fit-then-frozen constants (stage 4 fits them on cam2 study_0700
# ONLY; env overrides exist for that sweep and nothing else):
# margin floor — an origin posterior whose top-2 margin falls below this is
# flagged origin_ambiguous (Feeder-1 subtype). Unitless probability margin.
ORIGIN_POSTERIOR_MARGIN_FLOOR = float(_os.environ.get(
    "ORIGIN_POSTERIOR_MARGIN_FLOOR", "0.25"))
# tie band — candidates whose joint-scorer cost sits within this RATIO of the
# winner's cost are "tied" (their separating geometry lies past the track's
# death point); tied cells re-pick by corpus-support proportions. Unitless.
DEST_TIE_BAND = float(_os.environ.get("DEST_TIE_BAND", "0.15"))

# --- Claim-time origin veto (origin-grab phase 1, 2026-07-17) ----------------
# docs/plan_origin_veto_2026-07-17.md — mechanism ② with phase 0's measured
# signature (phase0_origin_grab_2026-07-17.md, 394 claims, two sites): a
# candidate origin leg may NOT be claimed when the track was born ON another
# leg-pair's through-road (< D_MAIN px from its bank polyline) AND beyond the
# candidate's mouth throat (> D_MOUTH px from its anchor). Applies to all
# three _assign_origin claim tiers; the fallback is the remaining candidates
# (phase 0: the grabs' births already sit nearest the true main-road origin).
# Constants are FROZEN geometry px from the phase-0 doc — D_MAIN=25 is the
# measured knee (20→30 moves genuine-capture 21%→38%), D_MOUTH=60 sits in a
# flat window (40→70 changes nothing at either site). No time constants.
# OFF by default until the FM51 ablation + frozen-constant corridor sweep
# pass (the plan's phase 2). Env override for replay harnesses only.
ORIGIN_CLAIM_VETO_ENABLED = _os.environ.get(
    "ORIGIN_CLAIM_VETO", "") in ("1", "true", "on")
ORIGIN_VETO_D_MAIN_PX = 25.0
ORIGIN_VETO_D_MOUTH_PX = 60.0

# --- Report letterhead (§3-E deliverables, 2026-07-16) -----------------------
# The operating firm's block on the PDF report (the example deliverable
# carries the operator's OWN brand). Empty name = the block is omitted —
# never render placeholder branding. Set once per install (env or here).
REPORT_LETTERHEAD = {
    "name": _os.environ.get("REPORT_FIRM_NAME", ""),
    "address_lines": [ln for ln in _os.environ.get(
        "REPORT_FIRM_ADDRESS", "").split("|") if ln],
    "contact": _os.environ.get("REPORT_FIRM_CONTACT", ""),
    "tagline": _os.environ.get("REPORT_FIRM_TAGLINE", ""),
}

# Pipeline-level grace period before considering a tracker-missing vehicle
# "lost" and finalizing it. YOLO detection can flicker (detect, miss, detect)
# on consecutive frames; without a grace window every flicker fragments a
# single vehicle into many one-point "tracks" that get dropped as
# insufficient_data. Bytetrack's own lost_buffer is TRACKER_LOST_BUFFER
# frames; this should be ≤ that so we don't outlive the tracker.
TRACK_FINALIZE_GAP_FRAMES = 60   # 2s @ 30fps

# --- Articulated (semi-truck) classification (§3-D, 2026-07-06) -------------
# The COCO "truck" class is one bucket; distinguishing an articulated semi
# (FHWA 8-13) from a single-unit box truck (FHWA 5) needs a size signal. bbox
# ASPECT RATIO fails at approach-angle cameras (a truck viewed end-on is
# near-square: FM51 truck aspect p50 1.34 ~ car 1.38), so the old aspect>2.0 gate
# never fired -> 0 articulated vs Miovision's 102. The view-invariant signal is a
# truck's LENGTH relative to the LOCAL CAR baseline (median car length at the same
# image-distance band): a semi runs ~2x a box truck runs ~2x a car, at any
# distance. A truck whose length exceeds ARTICULATED_LEN_RATIO x the local car
# median is re-bucketed to articulated. K is BELOW the raw 3x length ratio because
# a long vehicle foreshortens MORE than a short one at an approach angle, so its
# bbox-length ratio compresses; validated offline on FM51 -> ~95 articulated ~=
# 102 at K=2.0 (a geometric threshold, SANITY-checked vs the aggregate, NOT fit to
# it -- the §0 overfit guard). The split is approximate: bbox size can't perfectly
# separate a short semi from a long box truck. See memory
# project_articulated_classification_2026_07_06.
ARTICULATED_LEN_RATIO = 2.0      # truck length > this x local-car-median -> articulated
ARTICULATED_BAND_PX = 40         # image-row band (px) for the local car-size baseline
ARTICULATED_MIN_CARS_PER_BAND = 20  # a band needs this many cars for a trustworthy median

# Native articulated votes (plan_articulated_native_2026-07-17): a track is
# articulated when >= this many of its detections carry the fine-tuned head's
# native class (NATIVE_ARTICULATED_CLASS_ID). 2 mirrors the size pass's
# _MIN_MATCHED_FRAMES=2 — by construction, not fit: one flickered frame never
# flips a class, two independent frames is the established evidence floor.
# Class-at-birth alone would systematically under-call semis (far-field births
# detect as plain vehicle before the trailer resolves), hence votes.
NATIVE_ARTICULATED_MIN_FRAMES = 2

# --- Bank-gated through filter (FM51 audit #4, 2026-07-06) ------------------
# A "through" movement is only legitimate between OPPOSING legs; a through from a
# T-intersection stem (side road) is geometrically impossible. Short fragments of
# main-road through vehicles can fall to the fallback scorer, get their origin
# mis-read onto an adjacent side-road leg, and be labelled a "through" that
# DUPLICATES an already-counted main-road vehicle (FM51 side road: ours 105 vs
# Miovision 60, +75%; 33 bogus S->E throughs start at the main-road zone, avg 32-pt
# fragments). The bank is the authority on which through-movements are real (built
# from the site's own tracks) -> reject a "through" whose (origin,dest) is NOT a
# bank through-pair with real support (>= MIN_SUPPORT, so phantom 0-support paths
# don't count). Blind-deployable (no through where the site has no through-movement),
# generalizes to any T; 4-ways reject nothing (all throughs connect opposing legs).
# PER-CAMERA VALIDATED TOOL, NOT a blind default: the corridor regression (2026-07-06)
# showed cam3 has 691 LONG throughs on a bank-LEFT pair (real left-turners mislabeled,
# not duplicate fragments) — rejecting those would delete real vehicles. So run
# reject_invalid_throughs only where validated vs ground truth (FM51 cam2: 33 short
# duplicate fragments, side road 105->72). See MASTER_PLAN §2 #4 + memory
# project_per_approach_attribution_2026_06_30.
THROUGH_GATE_MIN_SUPPORT = 1     # bank turn-paths below this support are phantom (ignored)

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)
