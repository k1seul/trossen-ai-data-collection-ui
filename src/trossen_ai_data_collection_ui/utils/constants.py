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

# Path to the data collection plan CSV (target vs. recorded episodes per task/object).
# Auto-seeded from tasks.yaml and auto-updated as episodes are recorded; target_episodes
# is left for the user to fill in and is never overwritten automatically.
DATA_COLLECTION_PLAN_CSV_PATH = DATA_COLLECTION_PLAN_ROOT / "data_collection_plan.csv"

# Path to the human-readable markdown summary, regenerated from the CSV.
DATA_COLLECTION_PLAN_MD_PATH = DATA_COLLECTION_PLAN_ROOT / "data_collection_plan.md"
