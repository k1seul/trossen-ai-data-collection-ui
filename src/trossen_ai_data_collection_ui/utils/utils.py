from dataclasses import dataclass
import json
import logging
import os
import shutil
from typing import Tuple, Type, Union

from PySide6.QtGui import QImage, QPainter
from PySide6.QtWidgets import QWidget
from lerobot.common.robot_devices.cameras.configs import (
    CameraConfig,
    IntelRealSenseCameraConfig,
    OpenCVCameraConfig,
)
from lerobot.common.robot_devices.motors.configs import TrossenArmDriverConfig
from lerobot.common.robot_devices.robots.configs import (
    TrossenAIMobileRobotConfig,
    TrossenAISoloRobotConfig,
    TrossenAIStationaryRobotConfig,
)
import yaml

from trossen_ai_data_collection_ui.utils.constants import (
    TROSSEN_AI_ROBOT_PATH_PERSISTENT,
    TROSSEN_AI_TASK_PATH_PERSISTENT,
)

# ANSI color codes for terminal output
RED = "\033[91m"
RESET = "\033[0m"

logger = logging.getLogger(__name__)


@dataclass
class CalibrationConfig:
    """
    Configuration class for calibration menu parameters.
    """

    @dataclass
    class CalibrationFollowerArmConfig:
        """
        Configuration class for arm parameters.
        """

        arm_name: str = ""
        """Name of the arm."""

        capture_positions_rad: list[float] = None
        """List of capture positions in radians."""

    left_arm: CalibrationFollowerArmConfig = None
    """Left arm configuration."""

    right_arm: CalibrationFollowerArmConfig = None
    """Right arm configuration."""

    @staticmethod
    def from_dict(data: dict) -> "CalibrationConfig":
        """
        Create a CalibrationConfig instance from a dictionary.

        :param data: Dictionary containing configuration data.
        :return: CalibrationConfig instance.
        """
        config = CalibrationConfig()
        follower_arms_config = data["follower_arms"]

        # Get left arm config
        left_arm_config = follower_arms_config.get("left")
        if left_arm_config is None:
            raise ValueError("Left arm configuration not found.")
        config.left_arm = CalibrationConfig.CalibrationFollowerArmConfig()
        config.left_arm.arm_name = "left"
        config.left_arm.capture_positions_rad = [
            float(pos) for pos in left_arm_config.get("capture_positions_rad", [])
        ]
        if len(config.left_arm.capture_positions_rad) != 7:
            raise ValueError("Capture positions for left arm must be a list of 7 floats.")

        # Get right arm config
        right_arm_config = follower_arms_config.get("right")
        if right_arm_config is None:
            raise ValueError("Right arm configuration not found.")
        config.right_arm = CalibrationConfig.CalibrationFollowerArmConfig()
        config.right_arm.arm_name = "right"
        config.right_arm.capture_positions_rad = [
            float(pos) for pos in right_arm_config.get("capture_positions_rad", [])
        ]
        if len(config.right_arm.capture_positions_rad) != 7:
            raise ValueError("Capture positions for right arm must be a list of 7 floats.")

        return config

    def to_dict(self) -> dict:
        """
        Convert the CalibrationConfig instance to a dictionary.

        :return: Dictionary representation of the configuration.
        """
        return {
            "follower_arms": {
                "left": {
                    "capture_positions_rad": self.left_arm.capture_positions_rad,
                },
                "right": {
                    "capture_positions_rad": self.right_arm.capture_positions_rad,
                },
            }
        }


def set_image(widget: QWidget, image: object) -> None:
    """
    Convert a BGR OpenCV image to RGB format and update the widget with the image.

    :param widget: The widget where the image will be displayed.
    :param image: The image data in OpenCV format (BGR).
    """
    widget.image = QImage(
        image.data, image.shape[1], image.shape[0], QImage.Format.Format_RGB888
    ).rgbSwapped()  # Convert BGR to RGB and swap channels.
    widget.update()  # Trigger a paint event to refresh the widget.


def paintEvent(widget: QWidget, _: object) -> None:
    """
    Handle the widget's paint event to draw an image if available.

    :param widget: The widget to be painted.
    :param event: The paint event object.
    """
    if hasattr(widget, "image") and widget.image is not None:  # Check if the widget has an image.
        painter = QPainter(widget)  # Create a painter for the widget.
        painter.drawImage(widget.rect(), widget.image)  # Draw the image in the widget's rectangle.


def load_config(file_path: str = TROSSEN_AI_TASK_PATH_PERSISTENT) -> dict | None:
    """
    Load a YAML configuration file for tasks and return the parsed data as a dictionary.

    :param file_path: Path to the YAML configuration file. Defaults to TROSSEN_AI_TASK_PATH.
    :return: Parsed configuration data as a dictionary, or None if an error occurs.
    """
    logger.debug(f"Loading config from '{file_path}'")
    try:
        with open(file_path) as file:  # Open the file for reading.
            config_data = yaml.safe_load(file)  # Parse the YAML content.
        logger.debug(f"Config loaded successfully from '{file_path}'")
        return config_data  # Return the parsed data.
    except FileNotFoundError:
        logger.error(f"The file '{file_path}' was not found.")
        return None
    except yaml.YAMLError as e:
        logger.error(f"Error parsing YAML file: {e}")
        return None


def get_last_episode_index(file_path):
    file_path = os.path.join(
        os.path.expanduser("~"),
        ".cache",
        "huggingface",
        "lerobot",
        file_path,
        "meta",
        "episodes.jsonl",
    )
    if not os.path.exists(file_path):
        return None  # Return None if file is missing

    last_entry = None

    # Read the file line by line (JSONL format)
    with open(file_path, encoding="utf-8") as f:
        for line in f:
            last_entry = json.loads(line)  # Keep updating last_entry with the latest line

    if last_entry:
        return last_entry.get("episode_index", None)
    else:
        return None


def get_recorded_task_stats(repo_id: str) -> dict:
    """
    Summarize the instructions already recorded for a dataset repo, by reading
    its local meta/episodes.jsonl (the same file get_last_episode_index reads).

    :param repo_id: The dataset repo id, e.g. "YourUser/trossen_ai_pick_and_place".
    :return: dict with:
        - "counts": {instruction_string: episode_count}
        - "last_task": the instruction used in the most recently recorded
          episode, or None if the dataset doesn't exist locally yet.
    """
    file_path = os.path.join(
        os.path.expanduser("~"),
        ".cache",
        "huggingface",
        "lerobot",
        repo_id,
        "meta",
        "episodes.jsonl",
    )
    counts: dict = {}
    last_task = None

    if not os.path.exists(file_path):
        return {"counts": counts, "last_task": last_task}

    with open(file_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            tasks = entry.get("tasks", [])
            for task in tasks:
                counts[task] = counts.get(task, 0) + 1
            if tasks:
                last_task = tasks[-1]

    return {"counts": counts, "last_task": last_task}


def remove_corrupted_files(file_path):
    file_path = os.path.join(os.path.expanduser("~"), ".cache", "huggingface", "lerobot", file_path)
    if os.path.exists(file_path):
        shutil.rmtree(file_path)


def get_camera_interface(camera_type: str) -> Tuple[CameraConfig, str]:
    if camera_type == "opencv":
        return OpenCVCameraConfig, "camera_index"
    elif camera_type == "intel_realsense":
        return IntelRealSenseCameraConfig, "serial_number"
    else:
        raise ValueError(f"Invalid camera interface: {camera_type}")


def make_camera_config(
    serial_number: str,
    fps: int,
    width: int,
    height: int,
    camera_interface_class: Type[Union[IntelRealSenseCameraConfig, OpenCVCameraConfig]],
    key_name: str,
) -> Union[IntelRealSenseCameraConfig, OpenCVCameraConfig]:
    return camera_interface_class(
        **{key_name: serial_number},
        fps=fps,
        width=width,
        height=height,
    )


def create_robot_config(
    robot_name: str,
) -> Union[TrossenAIStationaryRobotConfig, TrossenAISoloRobotConfig, TrossenAIMobileRobotConfig]:
    logger.info(f"Creating robot config for '{robot_name}'")
    # Load robot configuration
    robot_config_data = load_config(TROSSEN_AI_ROBOT_PATH_PERSISTENT)
    if not robot_config_data:
        raise ValueError(
            f"{RED}Robot config error: Failed to load config file.\n"
            f"Fix: Check that {TROSSEN_AI_ROBOT_PATH_PERSISTENT} exists and is valid YAML{RESET}"
        )

    # Check if robot exists
    robot = robot_config_data.get(robot_name)
    if not robot:
        available = list(robot_config_data.keys())
        raise ValueError(
            f"{RED}Robot config error: Robot '{robot_name}' not found.\n"
            f"Available: {', '.join(available)}\n"
            f"Fix: Use one of the available robot names or add '{robot_name}' to config{RESET}"
        )

    # Validate camera_interface exists
    camera_interface_type = robot.get("camera_interface")
    if not camera_interface_type:
        raise ValueError(
            f"{RED}Robot config error for '{robot_name}': Missing 'camera_interface'.\n"
            f"Fix: Add 'camera_interface: opencv' or 'camera_interface: intel_realsense'{RESET}"
        )

    try:
        camera_interface_class, key_name = get_camera_interface(camera_interface_type)
    except ValueError as e:
        raise ValueError(
            f"{RED}Robot config error for '{robot_name}': Invalid camera_interface '{camera_interface_type}'.\n"
            f"Fix: Use 'opencv' or 'intel_realsense'{RESET}"
        ) from e

    try:
        cameras = {
            name: make_camera_config(
                index["serial_number"],
                index["fps"],
                index["width"],
                index["height"],
                camera_interface_class,
                key_name,
            )
            for name, index in robot.get("cameras").items()
        }
    except KeyError as e:
        cams = robot.get("cameras", {})
        missing_fields = []

        if isinstance(cams, dict):
            for cam_name, cfg in cams.items():
                if isinstance(cfg, dict):
                    missing = sorted({"serial_number", "fps", "width", "height"} - set(cfg.keys()))
                    if missing:
                        missing_fields.append(f"{cam_name}: {', '.join(missing)}")

        details = "\n  ".join(missing_fields) if missing_fields else f"Missing {e}"
        raise ValueError(
            f"{RED}Camera config error for robot '{robot_name}':\n  {details}\n"
            f"Fix: Add missing fields (serial_number, fps, width, height){RESET}"
        ) from e

    except AttributeError as e:
        cams = robot.get("cameras") if robot else None
        if cams is None:
            raise ValueError(
                f"{RED}Camera config error for robot '{robot_name}': 'cameras' section missing.\n"
                f"Fix: Add 'cameras' dictionary to robot config{RESET}"
            ) from e
        raise ValueError(
            f"{RED}Camera config error for robot '{robot_name}': 'cameras' has invalid type {type(cams).__name__}.\n"
            f"Fix: 'cameras' must be a dictionary{RESET}"
        ) from e

    except TypeError as e:
        raise ValueError(
            f"{RED}Camera config error for robot '{robot_name}': Invalid value types.\n"
            f"Fix: Ensure serial_number=str, fps/width/height=int. Error: {e}{RESET}"
        ) from e

    except Exception as e:
        raise ValueError(
            f"{RED}Camera config error for robot '{robot_name}': {e}\n"
            f"Fix: Check config at {TROSSEN_AI_ROBOT_PATH_PERSISTENT}{RESET}"
        ) from e

    logger.info(
        f"Robot '{robot_name}': camera_interface={camera_interface_type}, "
        f"cameras={list(cameras.keys())}"
    )

    min_time_to_move_multiplier = robot.get("min_time_to_move_multiplier", 3.0)

    # Validate arm configurations based on robot type
    def validate_arm_config(arm_type: str, arm_name: str) -> None:
        """Validate that an arm configuration has all required keys."""
        arm_section = robot.get(arm_type)
        if not arm_section:
            raise ValueError(
                f"{RED}Arm config error for robot '{robot_name}': Missing '{arm_type}' section.\n"
                f"Fix: Add '{arm_type}' dictionary to robot config{RESET}"
            )

        arm_config = arm_section.get(arm_name)
        if not arm_config:
            raise ValueError(
                f"{RED}Arm config error for robot '{robot_name}': Missing '{arm_type}.{arm_name}'.\n"
                f"Fix: Add '{arm_name}' arm to '{arm_type}' section{RESET}"
            )

        if not isinstance(arm_config, dict):
            raise ValueError(
                f"{RED}Arm config error for robot '{robot_name}': '{arm_type}.{arm_name}' has invalid type {type(arm_config).__name__}.\n"
                f"Fix: '{arm_type}.{arm_name}' must be a dictionary with 'ip' and 'model'{RESET}"
            )

        missing = []
        if "ip" not in arm_config:
            missing.append("ip")
        if "model" not in arm_config:
            missing.append("model")

        if missing:
            raise ValueError(
                f"{RED}Arm config error for robot '{robot_name}': '{arm_type}.{arm_name}' missing {', '.join(missing)}.\n"
                f"Fix: Add missing fields to '{arm_type}.{arm_name}'{RESET}"
            )

    # Validate arms based on robot type
    if robot_name == "trossen_ai_stationary":
        validate_arm_config("leader_arms", "left")
        validate_arm_config("leader_arms", "right")
        validate_arm_config("follower_arms", "left")
        validate_arm_config("follower_arms", "right")
    elif robot_name == "trossen_ai_solo":
        validate_arm_config("leader_arms", "main")
        validate_arm_config("follower_arms", "main")
    elif robot_name == "trossen_ai_mobile":
        validate_arm_config("leader_arms", "left")
        validate_arm_config("leader_arms", "right")
        validate_arm_config("follower_arms", "left")
        validate_arm_config("follower_arms", "right")
    else:
        raise ValueError(
            f"{RED}Robot config error: Unknown robot type '{robot_name}'.\n"
            f"Fix: Use 'trossen_ai_stationary', 'trossen_ai_solo', or 'trossen_ai_mobile'{RESET}"
        )

    if robot_name == "trossen_ai_stationary":
        robot_config = TrossenAIStationaryRobotConfig(
            max_relative_target=None,
            mock=False,
        )
        robot_config.leader_arms = {
            "left": TrossenArmDriverConfig(
                ip=robot.get("leader_arms").get("left").get("ip"),
                model=robot.get("leader_arms").get("left").get("model"),
                min_time_to_move_multiplier=min_time_to_move_multiplier,
            ),
            "right": TrossenArmDriverConfig(
                ip=robot.get("leader_arms").get("right").get("ip"),
                model=robot.get("leader_arms").get("right").get("model"),
                min_time_to_move_multiplier=min_time_to_move_multiplier,
            ),
        }
        robot_config.follower_arms = {
            "left": TrossenArmDriverConfig(
                ip=robot.get("follower_arms").get("left").get("ip"),
                model=robot.get("follower_arms").get("left").get("model"),
                min_time_to_move_multiplier=min_time_to_move_multiplier,
            ),
            "right": TrossenArmDriverConfig(
                ip=robot.get("follower_arms").get("right").get("ip"),
                model=robot.get("follower_arms").get("right").get("model"),
                min_time_to_move_multiplier=min_time_to_move_multiplier,
            ),
        }
        robot_config.cameras = cameras
    elif robot_name == "trossen_ai_solo":
        robot_config = TrossenAISoloRobotConfig(
            max_relative_target=None,
            mock=False,
        )
        robot_config.leader_arms = {
            "main": TrossenArmDriverConfig(
                ip=robot.get("leader_arms").get("main").get("ip"),
                model=robot.get("leader_arms").get("main").get("model"),
                min_time_to_move_multiplier=min_time_to_move_multiplier,
            ),
        }
        robot_config.follower_arms = {
            "main": TrossenArmDriverConfig(
                ip=robot.get("follower_arms").get("main").get("ip"),
                model=robot.get("follower_arms").get("main").get("model"),
                min_time_to_move_multiplier=min_time_to_move_multiplier,
            ),
        }
        robot_config.cameras = cameras

    elif robot_name == "trossen_ai_mobile":
        robot_config = TrossenAIMobileRobotConfig(
            max_relative_target=None,
            mock=False,
        )
        robot_config.leader_arms = {
            "left": TrossenArmDriverConfig(
                ip=robot.get("leader_arms").get("left").get("ip"),
                model=robot.get("leader_arms").get("left").get("model"),
                min_time_to_move_multiplier=min_time_to_move_multiplier,
            ),
            "right": TrossenArmDriverConfig(
                ip=robot.get("leader_arms").get("right").get("ip"),
                model=robot.get("leader_arms").get("right").get("model"),
                min_time_to_move_multiplier=min_time_to_move_multiplier,
            ),
        }
        robot_config.follower_arms = {
            "left": TrossenArmDriverConfig(
                ip=robot.get("follower_arms").get("left").get("ip"),
                model=robot.get("follower_arms").get("left").get("model"),
            ),
            "right": TrossenArmDriverConfig(
                ip=robot.get("follower_arms").get("right").get("ip"),
                model=robot.get("follower_arms").get("right").get("model"),
            ),
        }
        robot_config.cameras = cameras
    else:
        raise ValueError(f"Invalid robot name: {robot_name}")

    logger.info(
        f"Robot config created: type={type(robot_config).__name__}, "
        f"leader_arms={list(robot_config.leader_arms.keys())}, "
        f"follower_arms={list(robot_config.follower_arms.keys())}, "
        f"cameras={list(robot_config.cameras.keys())}"
    )
    return robot_config
