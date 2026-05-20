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

# Backward-extrapolation origin fallback. When tripwire crossing fails
# (vehicle first detected past the synthesized line), this second-tier
# fallback projects the trajectory's first detection point backward along
# the early motion vector to the frame boundary, then assigns the leg
# whose origin point is nearest to that synthetic entry point.
#
# Rationale (Bug A from the 2026-05-20 handoff): L19's origin sits at
# (85, 370) — the lower-left of a 640x480 frame. YOLO doesn't detect
# vehicles entering NB Belt Line until they're already past the tripwire,
# so they fall through to heading fallback, which mis-picks L20 / L18 /
# L21 based on which reference heading is closest in angle. Offline replay
# on a truncated-trajectory simulation (drop first 10 frames) showed
# heading fallback recovering 1/9 L20 events; backward extrapolation
# recovers 9/9. Wins also on L19 (4/7 -> 6/7) and L18 (16/32 -> 18/32).
#
# Runs BEFORE heading fallback because it constrains position AND early
# direction — strictly more specific than the direction-only heading
# check.
BACKWARD_EXTRAP_MATCH_RADIUS_PX = 180.0   # max distance from synthetic entry to leg origin
BACKWARD_EXTRAP_MIN_DISP_PX = 15.0        # early-window displacement floor (rejects jitter)
BACKWARD_EXTRAP_WINDOW_FRAMES = 8         # look at up to this many early frames for motion

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
