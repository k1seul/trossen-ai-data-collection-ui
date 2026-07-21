from datetime import datetime
import importlib.metadata
import logging
import os
import platform
import shutil
import sys

from trossen_ai_data_collection_ui.utils.constants import (
    LOG_DIR,
    TROSSEN_AI_ROBOT_PATH_PERSISTENT,
    TROSSEN_AI_TASK_PATH_PERSISTENT,
)


def setup_logging() -> None:
    """
    Configure root logger with stdout and file handlers.

    - stdout handler: INFO level, concise format
    - file handler: DEBUG level, detailed format with module and line number
    - Log files are written to '~/.trossen/trossen_ai_data_collection/logs/'
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = LOG_DIR / f"session_{timestamp}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)

    # Stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.setFormatter(
        logging.Formatter("[%(levelname)s] %(asctime)s %(message)s", datefmt="%H:%M:%S")
    )

    # File handler
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "[%(levelname)s] %(asctime)s %(module)s:%(lineno)d %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    root_logger.addHandler(stdout_handler)
    root_logger.addHandler(file_handler)


def _get_package_version(package_name: str) -> str:
    """Get version string for an installed package, or 'not installed' if unavailable."""
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return "not installed"


def _get_ffmpeg_version() -> str:
    """Get the ffmpeg CLI version string."""
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        return "not found on PATH"
    try:
        import subprocess

        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # First line looks like: "ffmpeg version 7.0.2 Copyright ..."
        first_line = result.stdout.split("\n")[0]
        return first_line
    except Exception as e:
        return f"error querying: {e}"


def log_system_info() -> None:
    """Log system and environment information for diagnostics."""
    logger = logging.getLogger(__name__)

    logger.info("--- System Information ---")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"OS: {platform.system()} {platform.release()}")
    logger.info(f"Architecture: {platform.machine()}")
    logger.info(f"Python: {sys.version}")

    # Conda environment
    conda_env = os.environ.get("CONDA_DEFAULT_ENV", "not detected")
    conda_prefix = os.environ.get("CONDA_PREFIX", "not detected")
    logger.info(f"Conda environment: {conda_env} ({conda_prefix})")

    # Package versions for libraries known to cause issues
    packages = {
        "trossen-ai-data-collection-ui": "trossen-ai-data-collection-ui",
        "opencv-python": "opencv-python",
        "opencv-contrib-python": "opencv-contrib-python",
        "av (PyAV/ffmpeg)": "av",
        "PySide6": "PySide6",
        "numpy": "numpy",
        "pyrealsense2": "pyrealsense2",
        "trossen-arm": "trossen-arm",
        "lerobot": "lerobot",
        "pyyaml": "pyyaml",
    }

    logger.info("--- Package Versions ---")
    for display_name, pkg_name in packages.items():
        logger.info(f"  {display_name}: {_get_package_version(pkg_name)}")

    # ffmpeg CLI
    logger.info(f"  ffmpeg (CLI): {_get_ffmpeg_version()}")
    logger.info("---")


def _log_file_contents(path, label: str) -> None:
    """Log the raw contents of a config file."""
    logger = logging.getLogger(__name__)

    if not path.exists():
        logger.info(f"{label} not found at {path}")
        return

    try:
        contents = path.read_text()
    except Exception as e:
        logger.warning(f"Failed to read {label}: {e}")
        return

    logger.info(f"--- {label} ({path}) ---")
    for line in contents.splitlines():
        logger.info(line)
    logger.info("---")


def log_robot_config() -> None:
    """Log the raw contents of the robot and task config files."""
    _log_file_contents(TROSSEN_AI_ROBOT_PATH_PERSISTENT, "Robot Config")
    _log_file_contents(TROSSEN_AI_TASK_PATH_PERSISTENT, "Task Config")
