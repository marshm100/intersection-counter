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
        "label": "Accurate",
        "description": "Best accuracy. Uses the large model at 1280 px and detects every frame. ~10-15× slower than Fast mode on CPU; recommended for final counts.",
    },
    "fast": {
        "yolo_model": "yolo26s.pt",
        "yolo_imgsz": 640,
        # Slightly higher conf floor — small model is noisier at low conf.
        "yolo_confidence": 0.15,
        # Detect every 3rd frame; tracker Kalman-interpolates between.
        "detection_skip": 3,
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
TRAJECTORY_MIN_POINTS = 2
TRAJECTORY_MIN_DISTANCE_PX = 8        # catch slow turners — was 15, missed lots of left/right turns
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
