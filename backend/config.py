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

# Detection
YOLO_MODEL = "yolo26s.pt"
YOLO_CONFIDENCE_THRESHOLD = 0.15
YOLO_IOU_THRESHOLD = 0.45
YOLO_IMGSZ = 640

# Classification mapping (pedestrians out of scope for v2 per PRD)
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}

# Trajectory classification thresholds (degrees)
TRAJECTORY_THROUGH_MAX_ANGLE = 25
TRAJECTORY_TURN_MIN_ANGLE = 35
TRAJECTORY_TURN_MAX_ANGLE = 135
TRAJECTORY_UTURN_MIN_ANGLE = 135
TRAJECTORY_MIN_POINTS = 2
TRAJECTORY_MIN_DISTANCE_PX = 15
TRAJECTORY_CURVATURE_THRESHOLD = 40  # cumulative curvature tiebreaker for ambiguous zone

# Tracker tuning
TRACKER_LOST_BUFFER = 90             # frames before dropping track (3s at 30fps — fewer stale candidates)
TRACKER_MATCH_THRESHOLD = 0.4        # IoU matching — stricter to prevent ID swaps between nearby vehicles
TRACKER_ACTIVATION_THRESHOLD = 0.25  # unchanged

# Origin assignment
ORIGIN_ASSIGN_MIN_FRAMES = 2   # trajectory points needed before assigning origin

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)
