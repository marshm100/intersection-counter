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

# Detection — tuned for accuracy over speed. yolo26l is the large variant;
# imgsz=1280 keeps distant intersection vehicles detectable at 1080p capture.
# Expect ~6-10× slower than yolo26s @ 640.
YOLO_MODEL = "yolo26l.pt"
YOLO_CONFIDENCE_THRESHOLD = 0.15
YOLO_IOU_THRESHOLD = 0.45
YOLO_IMGSZ = 1280

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

# Tracker tuning — looser thresholds + longer lost buffer so brief occlusions
# (a vehicle passing behind a pole / another car) don't kill the track and
# cause re-detection as a new vehicle (which then gets double-counted).
TRACKER_LOST_BUFFER = 150            # frames before dropping track (5s at 30fps)
TRACKER_MATCH_THRESHOLD = 0.3        # IoU matching — loose enough to re-associate after brief occlusion
TRACKER_ACTIVATION_THRESHOLD = 0.2   # easier to start a new track on weak first-frame match

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
