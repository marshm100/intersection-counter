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

# Detection
YOLO_MODEL = "yolov8n.pt"
YOLO_CONFIDENCE_THRESHOLD = 0.25
YOLO_IOU_THRESHOLD = 0.45

# Classification mapping
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck"}
PEDESTRIAN_CLASSES = {0: "person", 1: "bicycle"}

# Trajectory classification thresholds (degrees)
TRAJECTORY_THROUGH_MAX_ANGLE = 30
TRAJECTORY_TURN_MIN_ANGLE = 35
TRAJECTORY_TURN_MAX_ANGLE = 135
TRAJECTORY_UTURN_MIN_ANGLE = 135
TRAJECTORY_MIN_POINTS = 3
TRAJECTORY_MIN_DISTANCE_PX = 30

# Tracker tuning
TRACKER_LOST_BUFFER = 150            # frames before dropping track (5s at 30fps)
TRACKER_MATCH_THRESHOLD = 0.5        # IoU matching (was 0.7 — lowered to reduce fragmentation at frame_skip=3)
TRACKER_ACTIVATION_THRESHOLD = 0.25  # unchanged

# Track stitching — merge fragmented tracks across ByteTrack ID switches
STITCH_MAX_GAP_FRAMES = 45       # max effective-frames gap to attempt stitching (~4.5s at frame_skip=3)
STITCH_MAX_DISTANCE_PX = 150     # max px between lost endpoint and new startpoint
STITCH_HEADING_TOLERANCE = 60    # max heading difference (degrees)

# Origin assignment
ORIGIN_ASSIGN_MIN_FRAMES = 5   # trajectory points needed before assigning origin

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)
