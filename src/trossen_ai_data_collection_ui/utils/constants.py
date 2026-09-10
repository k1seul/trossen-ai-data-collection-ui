from pathlib import Path

# Define the root directory of the package
PACKAGE_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIGS_ROOT = PACKAGE_ROOT / "configs"

# Path to the default robot configuration YAML file
TROSSEN_AI_ROBOT_PATH_DEFAULT = DEFAULT_CONFIGS_ROOT / "robot" / "trossen_ai_robots.yaml"

# Path to the default task configuration YAML file
TROSSEN_AI_TASK_PATH_DEFAULT = DEFAULT_CONFIGS_ROOT / "tasks.yaml"

# Path to the calibration configuration YAML file.
TROSSEN_AI_CALIBRATION_CONFIG_PATH_DEFAULT = DEFAULT_CONFIGS_ROOT / "calibration_config.yaml"

# Configuration root directory in the user's home directory where persistent configs will be
# stored.
PERSISTENT_CONFIGS_ROOT = Path.home() / ".trossen" / "trossen_ai_data_collection" / "configs"

# Directory for log files
LOG_DIR = Path.home() / ".trossen" / "trossen_ai_data_collection" / "logs"

# Path to the persistent robot configuration YAML file
TROSSEN_AI_ROBOT_PATH_PERSISTENT = PERSISTENT_CONFIGS_ROOT / "robot" / "trossen_ai_robots.yaml"

# Path to the persistent task configuration YAML file
TROSSEN_AI_TASK_PATH_PERSISTENT = PERSISTENT_CONFIGS_ROOT / "tasks.yaml"

# Path to the persistent calibration configuration YAML file
TROSSEN_AI_CALIBRATION_CONFIG_PATH_PERSISTENT = PERSISTENT_CONFIGS_ROOT / "calibration_config.yaml"

# Directory for the data collection plan/progress tracking files
DATA_COLLECTION_PLAN_ROOT = Path.home() / ".trossen" / "trossen_ai_data_collection" / "plan"

# Per-episode staging produced by scripts/staging_plan.py: which zone the target and the
# container go in, which blocks are also on the mat, the lighting and the start-pose nudge.
# Randomising these is what the previous round did not do for the container, which taught the
# policy that each task had a fixed place to carry things to.
STAGING_SHEET = DATA_COLLECTION_PLAN_ROOT / "staging_sheet.csv"

# One row per KEPT episode: which staging row it was recorded under, and when. Without it the
# sheet and the dataset cannot be joined -- a discarded take repeats a row, so the Nth episode
# is not the Nth row -- and the conditions an episode was recorded under are unrecoverable.
# That join is what lets a position or lighting OOD split be drawn later instead of re-shot.
SESSION_LOG = DATA_COLLECTION_PLAN_ROOT / "session_log.csv"

# The main camera's framing, produced by real_robot/mark_workspace.py in the dreamer-vla repo.
# The policy does not see the whole 640x480 frame: a square window of it is cropped out before
# the resize to 224, because the camera cannot be brought closer to the table and a 25 mm block
# would otherwise cover a fraction of one patch. That window is fixed in camera pixels and baked
# into the checkpoint, so a camera knocked between sessions, or an object staged outside the
# window, silently produces episodes the policy cannot learn from.
FRAMING_ROOT = Path.home() / ".trossen" / "trossen_ai_data_collection" / "framing"

# The frame the crop was measured against. Compared to the live feed before recording starts.
FRAMING_REFERENCE = FRAMING_ROOT / "reference.png"

# The marks and the resulting crop, as mark_workspace.py wrote them.
FRAMING_WORKSPACE = FRAMING_ROOT / "workspace.json"

# Which camera the crop belongs to. The forecast loss reads this view's patch tokens and
# no other, so it is the only feed the crop means anything on -- drawing it over the wrist
# view would be worse than not drawing it.
FRAMING_CAMERA = "cam_high"

# One JSON per KEPT episode: the staging row it was recorded under, the scene resolved into
# a list of objects and zones, the crop the policy will see, and what the camera check said at
# the moment the episode started. The session log is a CSV and has to stay one flat row per
# episode; this is where anything shaped -- lists, the framing verdict -- can live, and it is
# what makes a scene reproducible object by object rather than from a semicolon-joined string.
EPISODE_CONFIG_ROOT = DATA_COLLECTION_PLAN_ROOT / "episodes"

# Path to the data collection plan CSV (target vs. recorded episodes per task/object).
# Auto-seeded from tasks.yaml and auto-updated as episodes are recorded; target_episodes
# is left for the user to fill in and is never overwritten automatically.
DATA_COLLECTION_PLAN_CSV_PATH = DATA_COLLECTION_PLAN_ROOT / "data_collection_plan.csv"

# Path to the human-readable markdown summary, regenerated from the CSV.
DATA_COLLECTION_PLAN_MD_PATH = DATA_COLLECTION_PLAN_ROOT / "data_collection_plan.md"

# The pose every episode starts from, which the staging sheet's start_nudge is measured
# against. Same numbers as CalibrationMenu.safe_pose here and as HOME_POSE in the dreamer-vla
# repo, where it was checked against the recordings: frame 0 of every episode sits within
# 0.0002 rad of it.
import math as _math

EPISODE_START_POSE = [0.0, _math.pi / 3.0, _math.pi / 6.0, _math.pi / 5.0, 0.0, 0.0, 0.0]

# Which joint each nudge in the sheet refers to. Read off the arm's kinematic order rather than
# from a published table, so check it against the arm before trusting a small angle: joint 0
# swings the whole arm, 1 raises it, 2 bends the elbow, 4 pitches the wrist.
NUDGE_JOINTS = {"base": 0, "shoulder": 1, "elbow": 2, "forearm": 3, "wrist": 4, "roll": 5}

# How close counts as "at the nudge". The sheet asks for 5 or 10 degrees, and the point is a
# start pose that varies rather than one hit precisely, so this is generous on purpose.
NUDGE_TOL_DEG = 1.5

# One signature of the mat per lighting condition, learned from the live camera. The conditions
# this room can produce are close enough together that whether they are distinguishable at all
# is a measurement, not an assumption -- see framing.classify_lighting.
LIGHTING_PROFILE = FRAMING_ROOT / "lighting.json"
