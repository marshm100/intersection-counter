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
#
# Fast mode uses the small variant at 640 + every-3rd-frame detection
# (tracker Kalman-interpolates between detections) — ~10-15× faster on
# CPU. Mode is per-project; default is "accurate" so existing projects
# don't change behavior on upgrade.
YOLO_MODEL = "yolo26l.pt"
YOLO_CONFIDENCE_THRESHOLD = 0.08
YOLO_IOU_THRESHOLD = 0.45
YOLO_IMGSZ = 1280

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
        # Small model at a moderate input size — better recall for small/distant
        # vehicles than Fast's 640, but no detection_skip so ByteTrack's Kalman
        # filter has fresh velocity every step (no skip-frame mismatch that
        # drops fast vehicles).
        "yolo_model": "yolo26s.pt",
        "yolo_imgsz": 960,
        "yolo_confidence": 0.10,
        "detection_skip": 1,
        # Detection every frame, so strict ByteTrack defaults are appropriate.
        "tracker_match_threshold": 0.8,
        "tracker_activation_threshold": 0.25,
        "label": "Balanced",
        "description": "Recommended for full-day clips. Small model at 960 px detecting every frame; fast vehicles track reliably (no skip-frame Kalman mismatch). ~3-5× slower than Fast on CPU; full-day footage usually fits in an overnight run.",
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


def get_processing_mode_config(mode: str | None) -> dict:
    """Return the config dict for `mode`, falling back to default on unknown."""
    if mode and mode in PROCESSING_MODES:
        return PROCESSING_MODES[mode]
    return PROCESSING_MODES[DEFAULT_PROCESSING_MODE]

# Classification mapping (pedestrians out of scope for v2 per PRD)
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

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
JOINT_SCORER_COST_METRIC = "dtw_mean"
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

# Pipeline-level grace period before considering a tracker-missing vehicle
# "lost" and finalizing it. YOLO detection can flicker (detect, miss, detect)
# on consecutive frames; without a grace window every flicker fragments a
# single vehicle into many one-point "tracks" that get dropped as
# insufficient_data. Bytetrack's own lost_buffer is TRACKER_LOST_BUFFER
# frames; this should be ≤ that so we don't outlive the tracker.
TRACK_FINALIZE_GAP_FRAMES = 60   # 2s @ 30fps

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)
