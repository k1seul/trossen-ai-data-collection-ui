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
