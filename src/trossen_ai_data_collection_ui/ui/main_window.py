from collections import deque
from functools import wraps
import gc
import html
import json
import logging
import math
import os
from pathlib import Path
import re
import threading
import time
from typing import (
    Dict,
    List,
    Union,
)

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import (
    QAction,
    QImage,
    QKeySequence,
    QPixmap,
    QShortcut,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
import cv2
from trossen_ai_data_collection_ui.utils import framing as framing_utils
from lerobot.common.datasets.image_writer import safe_stop_image_writer
from lerobot.common.datasets.lerobot_dataset import LeRobotDataset
from lerobot.common.policies.factory import make_policy
from lerobot.common.policies.pretrained import PreTrainedPolicy
from lerobot.common.robot_devices.control_configs import (
    RecordControlConfig,
    TeleoperateControlConfig,
)
from lerobot.common.robot_devices.control_utils import (
    reset_environment,
    sanity_check_dataset_name,
    sanity_check_dataset_robot_compatibility,
    stop_recording,
)
from lerobot.common.robot_devices.robots.manipulator import ManipulatorRobot
from lerobot.common.robot_devices.robots.trossen_ai_mobile import TrossenAIMobile
from lerobot.common.robot_devices.robots.utils import Robot, make_robot_from_config
from lerobot.common.robot_devices.utils import busy_wait
from lerobot.common.utils.utils import has_method, log_say
import numpy as np
import pyrealsense2 as rs
from termcolor import colored
import trossen_arm
import yaml

from trossen_ai_data_collection_ui.resources.app import Ui_MainWindow
from trossen_ai_data_collection_ui.resources.calibration_menu import Ui_calibration_menu
from datetime import datetime

from trossen_ai_data_collection_ui.utils.constants import (
    DATA_COLLECTION_PLAN_CSV_PATH,
    DATA_COLLECTION_PLAN_MD_PATH,
    PACKAGE_ROOT,
    EPISODE_CONFIG_ROOT,
    FRAMING_CAMERA,
    FRAMING_REFERENCE,
    FRAMING_WORKSPACE,
    SESSION_LOG,
    STAGING_SHEET,
    TROSSEN_AI_CALIBRATION_CONFIG_PATH_PERSISTENT,
    TROSSEN_AI_ROBOT_PATH_PERSISTENT,
    TROSSEN_AI_TASK_PATH_PERSISTENT,
)
from trossen_ai_data_collection_ui.utils.utils import (
    CalibrationConfig,
    create_robot_config,
    get_last_episode_index,
    get_recorded_task_stats,
    init_data_collection_plan,
    load_config,
    paintEvent,
    record_episode_in_plan,
    remove_corrupted_files,
    render_data_collection_plan_md,
    set_image,
)
from trossen_ai_data_collection_ui.workers.recorder import RecordWorker
from trossen_ai_data_collection_ui.workers.yaml import YamlHighlighter

logger = logging.getLogger(__name__)

# Fallback speed-warning threshold (rad/s) for the fastest joint's apparent
# commanded velocity during teleoperation, used when a robot's config doesn't
# set its own `max_joint_velocity_rad_s`. This is a UI heads-up, not a
# hardware-enforced safety limit -- tune it per robot/arm model as needed.
DEFAULT_MAX_JOINT_VELOCITY_RAD_S = 3.5


def text_to_html(text: str) -> str:
    """
    Convert plain text with ANSI color codes to HTML.

    Handles ANSI escape sequences, HTML special characters, and newlines.

    :param text: The text to convert.
    :return: HTML-formatted text.
    """
    # Escape HTML special characters first
    text = html.escape(text)

    # ANSI color code mapping to HTML colors
    ansi_colors = {
        "30": "black",
        "31": "red",
        "32": "green",
        "33": "yellow",
        "34": "blue",
        "35": "magenta",
        "36": "cyan",
        "37": "white",
        "90": "gray",
        "91": "#ff6b6b",  # bright red
        "92": "#51cf66",  # bright green
        "93": "#ffd43b",  # bright yellow
        "94": "#4dabf7",  # bright blue
        "95": "#da77f2",  # bright magenta
        "96": "#22b8cf",  # bright cyan
        "97": "white",
    }

    # Replace ANSI color codes with HTML spans
    # Pattern: [XXm where XX is a color code
    def replace_ansi(match):
        code = match.group(1)
        if code == "0":  # Reset code
            return "</span>"
        elif code in ansi_colors:
            return f'<span style="color:{ansi_colors[code]};font-weight:bold;">'
        return ""  # Unknown code, remove it

    # Replace ANSI codes
    text = re.sub(r"\[([0-9;]+)m", replace_ansi, text)

    # Replace newlines with <br>
    text = text.replace("\n", "<br>")

    # Close any unclosed spans at the end
    open_spans = text.count("<span") - text.count("</span>")
    if open_spans > 0:
        text += "</span>" * open_spans

    return text


def safe_disconnect(func):
    """
    Decorator to safely disconnect a robot when an exception occurs.

    Ensures that if the decorated function raises an exception, the robot
    is properly disconnected before the exception is propagated.

    :param func: The function to decorate.
    :return: The decorated function.
    """

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        robot: None | Robot = None  # Initialize robot as None.

        # Extract the Robot instance from arguments if available.
        for arg in args:
            if hasattr(arg, "disconnect") and hasattr(
                arg, "is_connected"
            ):  # Assuming `Robot` is the correct class name.
                robot = arg
                break

        if robot is None:
            raise ValueError(
                "A Robot instance with a `disconnect` method is required as an argument."
            )

        try:
            return func(self, *args, **kwargs)  # Execute the decorated function.
        except Exception:
            if hasattr(robot, "disconnect") and robot.is_connected:
                logger.error("Error occurred, disconnecting the robot...")
                robot.disconnect()
            raise  # Re-raise the original exception.

    return wrapper


class CalibrationMenu(QDialog):
    """
    Calibration Menu for the Trossen AI Data Collection application.

    This class provides a dialog for calibrating the robot's arms and other components. As of now,
    this menu simply allows users to move their arms to a specified pose, allowing them to run a
    script externally to run external scripts for camera extrinsics calibration.

    Note that this assumes a bimanual setup and will not work on Solo.
    """

    config: CalibrationConfig | None = None
    """Calibration for the configuration routine."""

    safe_pose: list[float] = [0.0, math.pi / 3.0, math.pi / 6.0, math.pi / 5.0, 0.0, 0.0, 0.0]
    """Safe pose for the arms before going to their home pose."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.ui = Ui_calibration_menu()
        self.ui.setupUi(self)
        self.setWindowTitle("Calibration Menu")

        self.spinboxes_fl = [
            self.ui.doubleSpinBox_fl_0,
            self.ui.doubleSpinBox_fl_1,
            self.ui.doubleSpinBox_fl_2,
            self.ui.doubleSpinBox_fl_3,
            self.ui.doubleSpinBox_fl_4,
            self.ui.doubleSpinBox_fl_5,
            self.ui.doubleSpinBox_fl_6,
        ]

        self.spinboxes_fr = [
            self.ui.doubleSpinBox_fr_0,
            self.ui.doubleSpinBox_fr_1,
            self.ui.doubleSpinBox_fr_2,
            self.ui.doubleSpinBox_fr_3,
            self.ui.doubleSpinBox_fr_4,
            self.ui.doubleSpinBox_fr_5,
            self.ui.doubleSpinBox_fr_6,
        ]

        self.driver_fl = trossen_arm.TrossenArmDriver()
        self.driver_fr = trossen_arm.TrossenArmDriver()

        self.drivers = [self.driver_fl, self.driver_fr]

        robot = load_config(TROSSEN_AI_ROBOT_PATH_PERSISTENT).get("trossen_ai_stationary")

        try:
            self.driver_fl.configure(
                serv_ip=robot.get("follower_arms").get("left").get("ip"),
                model=trossen_arm.Model.wxai_v0,
                end_effector=trossen_arm.StandardEndEffector.wxai_v0_follower,
                clear_error=False,
            )
            self.driver_fr.configure(
                serv_ip=robot.get("follower_arms").get("right").get("ip"),
                model=trossen_arm.Model.wxai_v0,
                end_effector=trossen_arm.StandardEndEffector.wxai_v0_follower,
                clear_error=False,
            )
        except Exception as e:
            logger.error(f"Error configuring drivers: {e}")
            QMessageBox.critical(self, "Error", f"Failed to configure drivers: {e}")

        # Load existing configurations from the filesystem
        if not self.load_calibration_configs():
            # Notify the users
            warn_msg = (
                "Failed to load calibration configs from "
                f"'{TROSSEN_AI_CALIBRATION_CONFIG_PATH_PERSISTENT}'. Using default values."
            )
            logger.warning(warn_msg)
            QMessageBox.warning(
                self,
                "Warning",
                warn_msg,
            )

        # Connect the buttons to their respective functions
        self.ui.pushButton_teleop.clicked.connect(self.calib_teleop)
        self.ui.pushButton_capture.clicked.connect(self.calib_capture)
        self.ui.pushButton_save.clicked.connect(self.save_calibration_configs)
        self.ui.pushButton_gotohome.clicked.connect(self.calib_gotohome)
        self.ui.pushButton_gotopose.clicked.connect(self.calib_gotopose)

    def closeEvent(self, event):
        """
        Override the base class closeEvent with a graceful disconnect routine.

        This puts the arms to home, sets them to idle, and cleans.
        """
        self.calib_gotohome()
        for driver in self.drivers:
            driver.set_all_modes(trossen_arm.Mode.idle)
            driver.cleanup()
            time.sleep(0.1)

        # Call the base class closeEvent method.
        super().closeEvent(event)

    def load_calibration_configs(self) -> bool:
        try:
            logger.info(
                f"Loading calibration config from '{TROSSEN_AI_CALIBRATION_CONFIG_PATH_PERSISTENT}'"
            )
            with open(TROSSEN_AI_CALIBRATION_CONFIG_PATH_PERSISTENT) as file:
                config_dict = yaml.safe_load(file)
            self.config = CalibrationConfig.from_dict(config_dict)
        except FileNotFoundError as e:
            logger.error(
                f"Calibration config file not found at '{TROSSEN_AI_CALIBRATION_CONFIG_PATH_PERSISTENT}': {e}"
            )
            return False
        except yaml.YAMLError as e:
            logger.error(f"Error loading calibration config: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error loading calibration config: {e}")
            return False

        # Populate the spinboxes with the loaded values
        for i, pos in enumerate(self.config.left_arm.capture_positions_rad):
            self.spinboxes_fl[i].setValue(float(np.degrees(pos)))
        for i, pos in enumerate(self.config.right_arm.capture_positions_rad):
            self.spinboxes_fr[i].setValue(float(np.degrees(pos)))
        return True

    def save_calibration_configs(self) -> bool:
        """
        Save the calibration configurations to a YAML file.
        """
        # Update configs
        self.config.left_arm.capture_positions_rad = [
            float(np.radians(spinbox.value())) for spinbox in self.spinboxes_fl
        ]
        self.config.right_arm.capture_positions_rad = [
            float(np.radians(spinbox.value())) for spinbox in self.spinboxes_fr
        ]
        try:
            logger.info(
                f"Saving calibration config to '{TROSSEN_AI_CALIBRATION_CONFIG_PATH_PERSISTENT}'"
            )
            with open(TROSSEN_AI_CALIBRATION_CONFIG_PATH_PERSISTENT, "w") as file:
                config_dict = self.config.to_dict()
                yaml.safe_dump(config_dict, file)
        except Exception as e:
            logger.error(f"Error saving calibration config: {e}")
            return False

        # Make a dialog popup stating where the config were set to
        QMessageBox.information(
            self,
            "Success",
            f"Changes saved to '{TROSSEN_AI_CALIBRATION_CONFIG_PATH_PERSISTENT}'",
        )

        return True

    def calib_teleop(self) -> None:
        """
        Put the arms in gravity compensation mode.
        """
        for driver in self.drivers:
            driver.set_all_modes(trossen_arm.Mode.position)
            driver.set_all_positions(
                goal_positions=self.safe_pose,
                goal_time=2.0,
                blocking=False,
            )
        time.sleep(2.5)
        for driver in self.drivers:
            driver.set_all_modes(trossen_arm.Mode.external_effort)
            driver.set_all_external_efforts(
                goal_external_efforts=[0.0] * driver.get_num_joints(),
                goal_time=0.0,
                blocking=False,
            )

    def calib_capture(self) -> None:
        """
        Capture the current joint states and populate the spinboxes with them.
        """
        for i, pos in enumerate(self.driver_fl.get_positions()):
            self.spinboxes_fl[i].setValue(np.degrees(pos))

        for i, pos in enumerate(self.driver_fr.get_positions()):
            self.spinboxes_fr[i].setValue(np.degrees(pos))

    def calib_gotohome(self) -> None:
        """
        Move the arms to the home position.
        """
        # Move the arms to their home positions if they are not already there.
        positions = self.driver_fl.get_positions()
        positions.extend(self.driver_fr.get_positions())

        # Skip if arms are already close to their home positions.
        if all(abs(pos) < 0.02 for pos in positions):
            logger.info("Arms are already in home position.")
            return

        for driver in self.drivers:
            driver.set_all_modes(trossen_arm.Mode.position)
            driver.set_all_positions(
                goal_positions=self.safe_pose,
                goal_time=2.0,
                blocking=False,
            )
        time.sleep(2.0)
        for driver in self.drivers:
            driver.set_all_positions(
                goal_positions=[0.0] * driver.get_num_joints(),
                goal_time=2.0,
                blocking=False,
            )
        time.sleep(2.0)
        for driver in self.drivers:
            driver.set_all_modes(trossen_arm.Mode.idle)
            time.sleep(0.1)

    def calib_gotopose(self) -> None:
        """
        Move the arms to the specified pose based on the spinbox values.

        Note that this method leaves the arms in position mode.
        """
        self.driver_fl.set_all_modes(trossen_arm.Mode.position)
        self.driver_fr.set_all_modes(trossen_arm.Mode.position)

        for driver in self.drivers:
            driver.set_all_positions(
                goal_positions=self.safe_pose,
                goal_time=2.0,
                blocking=False,
            )
        time.sleep(2.0)
        self.driver_fl.set_all_positions(
            goal_positions=[np.radians(spinbox.value()) for spinbox in self.spinboxes_fl],
            goal_time=2.0,
            blocking=False,
        )
        self.driver_fr.set_all_positions(
            goal_positions=[np.radians(spinbox.value()) for spinbox in self.spinboxes_fr],
            goal_time=2.0,
            blocking=False,
        )
        time.sleep(2.0)


class MainWindow(QMainWindow):
    """
    Main window class for the Trossen AI Data Collection application.

    This class initializes the user interface, handles user interactions,
    and manages robot recording tasks.
    """

    log_signal = Signal(str, bool)  # Signal for logging messages.
    setup_gate_signal = Signal()   # worker asks the UI thread to raise the setup gate

    def __init__(self) -> None:
        """
        Initialize the main window, set up the UI, and configure event handlers.
        """
        super().__init__()  # Call the superclass constructor.
        logger.info("Initializing MainWindow")
        self.ui = Ui_MainWindow()  # Initialize the UI.
        self.ui.setupUi(self)  # Set up the UI layout and widgets.

        self.log_signal.connect(self.set_logs_slot)
        self.setup_gate_signal.connect(self.show_setup_gate)

        self.thread = None

        self.disable_active_ui_updates = False

        # Log management: use dequeue with maxlen for automatic pruning
        self.max_log_entries = 20  # Maximum number of log entries to retain in UI
        self.log_entries = deque(maxlen=self.max_log_entries)  # Auto-removes oldest when full

        # Connect the start recording button to the recording function.
        self.ui.pushButton_start_recording.clicked.connect(self.start_recording)

        # Set initial task selection.
        self.selected_task = self.ui.comboBox_task_selection.currentText()
        self.ui.comboBox_task_selection.currentIndexChanged.connect(
            self.on_dataset_selection
        )  # Handle task selection changes.

        self.ui.pushButton_start_recording.setEnabled(True)  # Enable the start button.
        self.set_logs("Application started! Ready to record...")  # Log startup message.

        self.episode_count = self.ui.spinBox_episode_count.value()  # Get the episode count.

        # Connect buttons to update the episode count.
        self.ui.pushButton_episode_count_plus.clicked.connect(lambda: self.update_episode_count(1))
        self.ui.pushButton_episode_count_minus.clicked.connect(
            lambda: self.update_episode_count(-1)
        )

        logger.info("Loading task configurations")
        self.tasks_config = load_config()  # Load task configurations.

        # Seed/update the data collection plan (CSV + generated markdown summary)
        # from tasks.yaml. Existing rows and any target_episodes already filled in
        # are left untouched; only new task/object combinations are added.
        init_data_collection_plan(DATA_COLLECTION_PLAN_CSV_PATH, self.tasks_config)
        render_data_collection_plan_md(DATA_COLLECTION_PLAN_CSV_PATH, DATA_COLLECTION_PLAN_MD_PATH)

        self.populate_task_combobox()  # Populate the task selection combobox.

        # Populate the object/variant combobox for the initially selected task, and
        # keep the live instruction preview in sync as the operator edits/selects it.
        # Counts of how many episodes have already been recorded per object/variant
        # for the currently selected task, keyed by the object/variant string.
        self._task_object_counts: dict[str, int] = {}
        self.ui.comboBox_episode_object.editTextChanged.connect(self.update_instruction_preview)
        self.refresh_episode_object_choices()

        # Dynamically assign methods to each camera widget.
        self.camera_widgets = [
            self.ui.openGLWidget_camera_0,
            self.ui.openGLWidget_camera_1,
            self.ui.openGLWidget_camera_2,
            self.ui.openGLWidget_camera_3,
        ]

        self.elements_disabled_while_recording: list[QWidget] = [
            self.ui.pushButton_start_recording,
            self.ui.pushButton_dryrun,
            self.ui.spinBox_episode_count,
            self.ui.pushButton_episode_count_plus,
            self.ui.pushButton_episode_count_minus,
            self.ui.comboBox_task_selection,
            self.ui.pushButton_resetarms,
            self.ui.pushButton_resetcameras,
        ]

        self.placeholder_path = (
            PACKAGE_ROOT / "resources/no_video.jpg"
        )  # Path to the placeholder image.
        self.placeholder_image = None  # Initialize placeholder image.

        self.initialize_image()  # Load and set up the placeholder image.

        # Set up fullscreen toggle shortcut (F11).
        self.fullscreen_shortcut = QShortcut(QKeySequence("F11"), self)
        self.fullscreen_shortcut.activated.connect(self.toggle_fullscreen)

        # Event flags for recording tasks.
        self.events = {
            "exit_early": False,
            "stop_recording": False,
            "rerecord_episode": False,
            "emergency": False,
            "start_episode": False,
            "finish_episode": False,
            "fail_episode": False,
        }

        # Reset tracking for non-blocking reset operations
        self._reset_thread = None  # threading.Thread instance

        # Connect buttons for re-recording, dry run and stopping recording.
        self.ui.pushButton_rerecord.clicked.connect(self.set_rerecord_episode)
        self.ui.pushButton_stop_recording.clicked.connect(self.set_stop_recording)
        self.ui.pushButton_dryrun.clicked.connect(self.start_dry_run)

        # Connect buttons for ending the current episode early (saved) and
        # marking the current episode as failed (discarded), both advancing
        # to the next episode.
        self.ui.pushButton_finish_episode.clicked.connect(self.set_finish_episode)
        self.ui.pushButton_fail_episode.clicked.connect(self.set_fail_episode)

        # Skip the rest of the environment-reset wait once re-setup is done,
        # only relevant (and enabled) while a reset is actually in progress.
        self.ui.pushButton_skip_reset.clicked.connect(self.set_skip_reset)

        # Keyboard shortcuts for the three things the operator does with a hand already busy
        # on the leader arm. Reaching for the mouse to end a take is what made every episode
        # run its full clock in the previous round, and a fifth of that data was the arm
        # sitting still afterwards.
        #
        #   Space / S  finish the episode now and KEEP it   (the object is placed)
        #   F          discard this take and move on        (spoiled: knocked off the mat)
        #   R          stop waiting out the reset           (scene is re-staged)
        # Per-episode staging, if scripts/staging_plan.py has written a sheet. Randomising the
        # container's position is the change that matters most this round -- the previous one
        # left it fixed, and the policy learned each task's container position as part of the
        # task rather than as something to look for. A sheet nobody reads changes nothing, so
        # the row is shown here, in the log, and advances when an episode is kept.
        self.staging_rows: list[dict] = []
        self.staging_idx = 0
        self._load_staging_sheet()

        # The main camera's framing. Loaded once: without it the crop simply is not drawn and
        # the check reports that it has nothing to compare against, rather than blocking a
        # session over a missing file.
        self.framing = framing_utils.Framing.load(FRAMING_REFERENCE, FRAMING_WORKSPACE)
        self.staging_active = False   # zone letters are drawn only while the gate is open
        # Resolved by name in update_camera_labels. Left unset until then: index 0 is not
        # reliably the main view, and drawing the crop over the wrist feed would mislead the
        # operator about where an object has to be staged.
        self.framing_camera_index = None
        self.last_main_frame = None
        if self.framing is None:
            logger.warning(
                f"no camera framing reference at {FRAMING_REFERENCE}; the crop will not be "
                f"drawn and the camera cannot be checked. Produce one with "
                f"real_robot/mark_workspace.sh in the dreamer-vla repo."
            )
        else:
            logger.info(f"camera framing: crop {self.framing.crop} from {FRAMING_REFERENCE}")

        self.episode_shortcuts = []
        for keys, slot in (
            (("Space", "S"), self.set_finish_episode),
            (("F",), self.set_fail_episode),
            (("R",), self.set_skip_reset),
            (("G",), self.set_start_episode),            # begin recording this episode
            (("Return", "Enter"), self.set_emergency),   # drop it and stop
            (("N",), self.show_staging),          # re-show the current staging row
            (("Ctrl+N",), self._load_staging_sheet),   # re-read the sheet from disk
            (("C",), self.check_camera_framing),   # has the camera been knocked?
        ):
            for k in keys:
                sc = QShortcut(QKeySequence(k), self)
                sc.activated.connect(slot)
                self.episode_shortcuts.append(sc)

        # Connect reset buttons.
        self.ui.pushButton_resetarms.clicked.connect(self.start_reset_arms)
        self.ui.pushButton_resetcameras.clicked.connect(self.hardware_reset_cameras)

        # Checking the framing is the first thing to do on opening the UI and the last thing
        # anyone remembers, so it gets a button next to the other hardware ones rather than
        # living only on a shortcut. Added here instead of in the generated resources/app.py,
        # which is regenerated from the .ui file and would lose it.
        self.pushButton_checkframing = QPushButton("Check Camera Framing", self)
        self.pushButton_checkframing.setFont(self.ui.pushButton_resetcameras.font())
        self.pushButton_checkframing.setSizePolicy(
            self.ui.pushButton_resetcameras.sizePolicy()
        )
        self.pushButton_checkframing.setToolTip(
            "Compare the camera against the frame the policy's crop was measured on, and show "
            "the crop over the current view (C)"
        )
        self.pushButton_checkframing.clicked.connect(lambda: self.check_camera_framing())
        layout = self.ui.pushButton_resetcameras.parentWidget().layout()
        target = self.ui.horizontalLayout_6 if hasattr(self.ui, "horizontalLayout_6") else layout
        if target is not None:
            target.addWidget(self.pushButton_checkframing)
        else:                                    # no layout to attach to; the shortcut still works
            logger.warning("could not place the Check Camera Framing button; use C instead")

        # Enable re-recording, dry run and stop buttons.
        self.ui.pushButton_rerecord.setEnabled(True)
        self.ui.pushButton_stop_recording.setEnabled(True)
        self.ui.pushButton_dryrun.setEnabled(True)

        # Connect menu actions for editing configurations.
        self.ui.actionRobot_Configuration.triggered.connect(self.edit_robot_config)
        self.ui.actionTask_Configuration.triggered.connect(self.edit_task_config)
        self.ui.actionNew_Task.triggered.connect(self.open_new_task_dialog)

        # Connect menu actions for calibration
        self.ui.actionCalibrate.triggered.connect(self.open_calibration_menu)

        # Add a quit action to the menu.
        quit_action = QAction("Quit", self)  # Create the quit action.
        quit_action.setShortcut("Ctrl+Q")  # Assign a keyboard shortcut.
        quit_action.triggered.connect(QApplication.quit)  # Connect to quit the application.
        self.ui.menuQuit.addAction(quit_action)  # Add the quit action to the menu.

    def toggle_fullscreen(self) -> None:
        """
        Toggle between fullscreen and normal window modes.

        This method checks if the window is currently in fullscreen mode and toggles
        it to normal mode if it is, or to fullscreen mode if it isn't.
        """
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def open_calibration_menu(self) -> None:
        self.calibration_popup = CalibrationMenu(self)

        # Open the calibration menu dialog.
        self.calibration_popup.exec()

    def initialize_image(self) -> None:
        """
        Load and set a placeholder image for all camera widgets and reset camera labels.

        This method attempts to load a placeholder image from the specified path
        and assigns it to the camera widgets. It also resets the camera labels to empty.
        If the image cannot be loaded, warnings or errors are printed to the console.
        """
        # Load and convert the placeholder image.
        if os.path.exists(self.placeholder_path):  # Check if the placeholder path exists.
            self.placeholder_image = cv2.imread(
                str(self.placeholder_path)
            )  # Read the image from the path.
            if self.placeholder_image is not None:
                self.placeholder_image = cv2.cvtColor(
                    self.placeholder_image, cv2.COLOR_BGR2RGB
                )  # Convert image from BGR to RGB.
            else:
                logger.error(f"Unable to load placeholder image {self.placeholder_path}")
                return
        else:
            logger.warning(f"Placeholder image not found at {self.placeholder_path}")
            return

        # Assign the placeholder image to all camera widgets.
        if self.placeholder_image is not None:  # Ensure the placeholder image was loaded.
            qimage = QImage(
                self.placeholder_image.data,
                self.placeholder_image.shape[1],
                self.placeholder_image.shape[0],
                QImage.Format.Format_RGB888,
            )  # Convert OpenCV image to QImage.

            for widget in self.camera_widgets:  # Iterate over all camera widgets.
                # Assign the converted QImage and related methods to the widget.
                widget.set_image = lambda img, w=widget: set_image(w, img)
                widget.paintEvent = lambda event, w=widget: paintEvent(w, event)
                widget.image = qimage  # Initialize the widget with the placeholder image.
                widget.update()  # Force widget to redraw

        # Reset camera labels to empty
        label_widgets = [
            self.ui.label_cameraFeed1,
            self.ui.label_cameraFeed2,
            self.ui.label_cameraFeed3,
            self.ui.label_cameraFeed4,
        ]
        for label in label_widgets:
            label.setText("")  # Reset label to empty string

    def edit_robot_config(self) -> None:
        """
        Open the robot configuration editor.

        This method opens a dialog allowing the user to edit the robot configuration YAML file.
        """
        self.open_edit_dialog("Edit Robot Configuration", TROSSEN_AI_ROBOT_PATH_PERSISTENT)

    def edit_task_config(self) -> None:
        """
        Open the task configuration editor.

        This method opens a dialog allowing the user to edit the task configuration YAML file.
        """
        self.open_edit_dialog("Edit Task Configuration", TROSSEN_AI_TASK_PATH_PERSISTENT)

    def open_edit_dialog(self, title: str, file_path: str) -> None:
        """
        Open a dialog for editing a configuration file.

        This method creates a dialog where the user can view and edit a specified configuration file.
        Changes are validated as YAML before saving.

        :param title: The title of the dialog window.
        :param file_path: The path to the configuration file to be edited.
        """
        logger.info(f"Opening config editor: {title} ({file_path})")
        self.initialize_image()  # Initialize placeholder images.

        # Create and configure the dialog window.
        dialog = QDialog(self)
        dialog.setWindowTitle(title)  # Set the title of the dialog.
        dialog.setWindowModality(Qt.ApplicationModal)  # Make the dialog modal.
        dialog.resize(800, 600)  # Set the dialog size.

        # Create layout and widgets.
        layout = QVBoxLayout(dialog)
        text_edit = QPlainTextEdit(dialog)  # Text editor for file content.
        save_button = QPushButton("Save", dialog)  # Button to save changes.
        cancel_button = QPushButton("Cancel", dialog)  # Button to cancel changes.

        layout.addWidget(text_edit)  # Add text editor to layout.
        layout.addWidget(save_button)  # Add save button to layout.
        layout.addWidget(cancel_button)  # Add cancel button to layout.

        # Apply YAML syntax highlighting to the text editor.
        _ = YamlHighlighter(text_edit.document())

        # Load the file content into the text editor.
        try:
            with open(file_path) as file:  # Open the file for reading.
                content = file.read()  # Read the file content.
                text_edit.setPlainText(content)  # Display content in the text editor.
        except FileNotFoundError:
            QMessageBox.critical(
                self, "Error", f"File not found: {file_path}"
            )  # Show error message for missing file.
            return
        except Exception as e:
            QMessageBox.critical(
                self, "Error", f"Failed to load file: {e}"
            )  # Show error message for other issues.
            return

        # Define the save action.
        def save_changes():
            try:
                yaml.safe_load(text_edit.toPlainText())  # Validate YAML format.

                # Save validated changes to the file.
                with open(file_path, "w") as file:
                    file.write(text_edit.toPlainText())
                logger.info(f"Config saved to {file_path}")
                QMessageBox.information(
                    self, "Success", f"Changes saved to {file_path}"
                )  # Show success message.
                self.tasks_config = load_config()  # Reload the task configuration.
                init_data_collection_plan(DATA_COLLECTION_PLAN_CSV_PATH, self.tasks_config)
                render_data_collection_plan_md(DATA_COLLECTION_PLAN_CSV_PATH, DATA_COLLECTION_PLAN_MD_PATH)

                # Join this episode to the staging row it was recorded under, so the conditions
                # behind it -- zones, lighting, distractors, start nudge -- stay recoverable.
                self.log_staged_episode(episode_idx, episode_instruction)
                self.populate_task_combobox()  # Refresh the task selection combobox.
                dialog.accept()  # Close the dialog.
            except yaml.YAMLError as e:
                QMessageBox.critical(
                    self, "Error", f"Invalid YAML format: {e}"
                )  # Show error for invalid YAML.
            except Exception as e:
                QMessageBox.critical(
                    self, "Error", f"Failed to save file: {e}"
                )  # Show error for save failure.

        # Define the cancel action.
        def cancel_changes():
            dialog.reject()  # Close the dialog without saving.

        # Connect buttons to their respective actions.
        save_button.clicked.connect(save_changes)
        cancel_button.clicked.connect(cancel_changes)

        dialog.exec()  # Execute the dialog.

    @staticmethod
    def _build_task_yaml_block(task: dict) -> str:
        """
        Format a single task as an appendable YAML block for tasks.yaml.

        Uses yaml.safe_dump for correct quoting/escaping, then re-indents to
        match the file's "  - task_name: ..." list style, so it can be
        appended as raw text without touching (or reformatting/losing
        comments in) the rest of the file.

        :param task: The task dict to format, in the desired key order.
        :return: A YAML text block, prefixed with a blank line for spacing.
        """
        dumped = yaml.safe_dump({"tasks": [task]}, default_flow_style=False, sort_keys=False)
        body_lines = dumped.splitlines()[1:]  # Drop the leading "tasks:" line.
        indented = "\n".join(f"  {line}" for line in body_lines)
        return f"\n{indented}\n"

    def open_new_task_dialog(self) -> None:
        """
        Open a form for creating a new task without hand-editing YAML.

        Appends a new entry to the persistent tasks.yaml (preserving the rest
        of the file, including comments), reloads the task configuration,
        refreshes the data collection plan, and selects the new task in
        TASK SELECTION -- ready to record with no further setup.
        """
        logger.info("Opening New Task dialog")

        robot_config_data = load_config(TROSSEN_AI_ROBOT_PATH_PERSISTENT) or {}
        robot_models = list(robot_config_data.keys())
        if not robot_models:
            QMessageBox.critical(
                self,
                "Error",
                "No robots found in the robot configuration. "
                "Set up Robot Configuration first.",
            )
            return

        # Default to whichever hf_user was used most recently, if any, so it
        # doesn't need to be retyped for every new task.
        default_hf_user = ""
        for task in (self.tasks_config or {}).get("tasks", []):
            if task.get("hf_user"):
                default_hf_user = task["hf_user"]

        dialog = QDialog(self)
        dialog.setWindowTitle("New Task")
        dialog.setWindowModality(Qt.ApplicationModal)
        dialog.resize(520, 560)

        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        layout.addLayout(form)

        task_name_edit = QLineEdit(dialog)
        task_name_edit.setPlaceholderText("e.g. pick_place_block_bowl")
        form.addRow("Task name:", task_name_edit)

        robot_model_combo = QComboBox(dialog)
        robot_model_combo.addItems(robot_models)
        if "trossen_ai_solo" in robot_models:
            robot_model_combo.setCurrentText("trossen_ai_solo")
        form.addRow("Robot model:", robot_model_combo)

        hf_user_edit = QLineEdit(dialog)
        hf_user_edit.setText(default_hf_user)
        form.addRow("Hugging Face user:", hf_user_edit)

        description_edit = QLineEdit(dialog)
        description_edit.setPlaceholderText("Pick up the {object} and place it in the bowl.")
        form.addRow("Instruction ({object} = variant slot):", description_edit)

        objects_edit = QPlainTextEdit(dialog)
        objects_edit.setPlaceholderText(
            "Optional: one object/variant per line, e.g.\nred block\nblue block"
        )
        objects_edit.setFixedHeight(90)
        form.addRow("Objects / variants:", objects_edit)

        episode_length_spin = QSpinBox(dialog)
        episode_length_spin.setRange(1, 600)
        episode_length_spin.setValue(15)
        form.addRow("Episode length (s):", episode_length_spin)

        warmup_spin = QSpinBox(dialog)
        warmup_spin.setRange(0, 600)
        warmup_spin.setValue(5)
        form.addRow("Warmup time (s):", warmup_spin)

        reset_spin = QSpinBox(dialog)
        reset_spin.setRange(0, 600)
        reset_spin.setValue(15)
        form.addRow("Reset time (s):", reset_spin)

        fps_spin = QSpinBox(dialog)
        fps_spin.setRange(1, 120)
        fps_spin.setValue(30)
        form.addRow("FPS:", fps_spin)

        display_fps_spin = QSpinBox(dialog)
        display_fps_spin.setRange(0, 120)
        display_fps_spin.setValue(30)
        form.addRow("Display FPS:", display_fps_spin)

        save_interval_spin = QSpinBox(dialog)
        save_interval_spin.setRange(-1, 1000)
        save_interval_spin.setValue(1)
        form.addRow("Save interval:", save_interval_spin)

        push_to_hub_check = QCheckBox("Push to Hugging Face Hub automatically", dialog)
        push_to_hub_check.setChecked(True)
        form.addRow(push_to_hub_check)

        play_sounds_check = QCheckBox("Play sounds", dialog)
        play_sounds_check.setChecked(True)
        form.addRow(play_sounds_check)

        button_row = QHBoxLayout()
        create_button = QPushButton("Create Task", dialog)
        cancel_button = QPushButton("Cancel", dialog)
        button_row.addWidget(create_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        def create_task():
            task_name = task_name_edit.text().strip().replace(" ", "_")
            if not task_name:
                QMessageBox.warning(dialog, "Missing task name", "Enter a task name.")
                return
            if not re.match(r"^[A-Za-z0-9_-]+$", task_name):
                QMessageBox.warning(
                    dialog,
                    "Invalid task name",
                    "Task name can only contain letters, numbers, underscores and hyphens.",
                )
                return
            existing_names = {
                t.get("task_name") for t in (self.tasks_config or {}).get("tasks", [])
            }
            if task_name in existing_names:
                QMessageBox.warning(
                    dialog, "Duplicate task", f"A task named '{task_name}' already exists."
                )
                return

            hf_user = hf_user_edit.text().strip()
            if not hf_user:
                QMessageBox.warning(
                    dialog, "Missing Hugging Face user", "Enter a Hugging Face username."
                )
                return

            description = description_edit.text().strip()
            if not description:
                QMessageBox.warning(dialog, "Missing instruction", "Enter an instruction.")
                return

            objects = [
                line.strip() for line in objects_edit.toPlainText().splitlines() if line.strip()
            ]

            task = {
                "task_name": task_name,
                "robot_model": robot_model_combo.currentText(),
                "task_description": description,
                "episode_length_s": episode_length_spin.value(),
                "warmup_time_s": warmup_spin.value(),
                "reset_time_s": reset_spin.value(),
                "hf_user": hf_user,
                "fps": fps_spin.value(),
                "display_fps": display_fps_spin.value(),
                "push_to_hub": push_to_hub_check.isChecked(),
                "play_sounds": play_sounds_check.isChecked(),
                "disable_active_ui_updates": False,
                "save_interval": save_interval_spin.value(),
            }
            if objects:
                task["task_objects"] = objects

            try:
                block = self._build_task_yaml_block(task)
                with open(TROSSEN_AI_TASK_PATH_PERSISTENT, "a") as f:
                    f.write(block)
                logger.info(f"New task '{task_name}' appended to {TROSSEN_AI_TASK_PATH_PERSISTENT}")
            except Exception as e:
                QMessageBox.critical(dialog, "Error", f"Failed to save new task: {e}")
                return

            self.tasks_config = load_config()
            init_data_collection_plan(DATA_COLLECTION_PLAN_CSV_PATH, self.tasks_config)
            render_data_collection_plan_md(DATA_COLLECTION_PLAN_CSV_PATH, DATA_COLLECTION_PLAN_MD_PATH)
            self.populate_task_combobox()
            self.ui.comboBox_task_selection.setCurrentText(task_name)

            self.set_logs(
                f"Created new task '{task_name}'. Select it and click START RECORDING SESSION."
            )
            QMessageBox.information(
                dialog,
                "Task created",
                f"'{task_name}' is ready -- repo: {hf_user}/{task_name}\n"
                "It's now selected in TASK SELECTION; click START RECORDING SESSION to begin.",
            )
            dialog.accept()

        create_button.clicked.connect(create_task)
        cancel_button.clicked.connect(dialog.reject)

        dialog.exec()

    def set_rerecord_episode(self) -> None:
        """
        Trigger re-recording of the current episode.

        Sets the appropriate event flags to indicate that the current episode
        should be re-recorded and the recording process should exit early.
        """
        logger.info("Re-record episode triggered by user")
        self.set_logs("Re-record episode triggered")
        self.events["rerecord_episode"] = True
        self.events["exit_early"] = True

    def set_stop_recording(self) -> None:
        """
        Stop the recording process.

        Sets the appropriate event flags to indicate that the recording process
        should stop and exit early.
        """
        logger.info("Stop recording triggered by user")
        self.set_logs("Stop recording triggered")
        self.events["stop_recording"] = True
        self.events["exit_early"] = True

    def set_finish_episode(self) -> None:
        """
        Finish the current episode early and advance to the next one.

        Ends data collection for the current episode immediately, keeps the
        data recorded so far, saves it, and moves on to the next episode
        (or ends the session if this was the last episode).
        """
        logger.info("Finish episode triggered by user")
        self.advance_staging()
        self.set_logs("Finish episode triggered: saving episode and moving to the next one")
        self.events["finish_episode"] = True
        self.events["exit_early"] = True

    def set_fail_episode(self) -> None:
        """
        Mark the current episode as failed and advance to the next one.

        Ends data collection for the current episode immediately, discards
        the data recorded so far (unlike re-record, it is not retried), and
        moves on to the next episode.
        """
        logger.info("Fail episode triggered by user")
        self.set_logs("Fail episode triggered: discarding episode and moving to the next one")
        self.events["fail_episode"] = True
        self.events["exit_early"] = True

    def set_skip_reset(self) -> None:
        """
        End the current environment-reset wait early.

        Only meaningful while a reset is in progress (the button is disabled
        otherwise): lets the operator start the next episode immediately once
        they've finished re-setting up the scene, instead of waiting out the
        full reset_time_s/long_reset_time_s countdown.
        """
        logger.info("Skip reset triggered by user")
        self.set_logs("Setup done: starting the next episode now")
        self.events["exit_early"] = True

    def on_worker_finished(self) -> None:
        """Handle cleanup when worker finishes (success or error)."""
        logger.info("Worker thread finished, re-enabling UI")
        self.set_recording_ui_elements_enabled(True)
        self.initialize_image()

    def _connect_robot_with_timeout(
        self, robot: Union[ManipulatorRobot, TrossenAIMobile], timeout: float = 30.0
    ) -> bool:
        """
        Connect to the robot with a timeout using a separate thread.

        This method attempts to connect to the robot within a specified timeout period.
        If the connection fails or times out, it logs an error and returns False.

        :param robot: The robot instance to connect.
        :param timeout: Maximum time in seconds to wait for connection. Defaults to 30.0.
        :return: True if connection successful, False otherwise.
        """
        logger.info(f"Connecting to robot (timeout={timeout}s)")
        exception_holder = None  # To capture exceptions from thread

        def connect_robot():
            nonlocal exception_holder
            try:
                robot.connect()
            except Exception as e:
                exception_holder = e

        # Run connection in separate thread with timeout
        connect_thread = threading.Thread(target=connect_robot, daemon=True)
        connect_thread.start()
        connect_thread.join(timeout=timeout)

        # Check if thread is still alive (timeout occurred)
        if connect_thread.is_alive():
            error_msg = (
                f"Robot failed to connect within {timeout} seconds. "
                "Please power cycle your control box."
            )
            logger.error(error_msg)
            self.log_signal.emit(f"Error connecting to robot:\n{error_msg}", False)
            return False

        # Check if an exception occurred in the thread
        if exception_holder is not None:
            logger.error(f"Robot connection failed: {exception_holder}")
            self.log_signal.emit(f"Error connecting to robot:\n{exception_holder}", False)
            return False

        logger.info("Robot connected successfully")
        return True

    def populate_task_combobox(self) -> None:
        """
        Populate the task selection combobox with tasks from the configuration file.

        Clears the existing items in the combobox and adds task names from the loaded
        YAML configuration. Logs a message if no tasks are found.
        """
        # Keep whatever the operator had chosen. This runs again every time the task config is
        # edited, and clear() moves the index to -1 while the first addItem moves it to 0, both
        # of which reach on_dataset_selection -- so editing any task silently reselected the
        # first one. Nothing says so, and the selection decides the HuggingFace repo the
        # episodes are written to, so the cost of not noticing is a session recorded into the
        # wrong dataset.
        previous = self.selected_task or self.ui.comboBox_task_selection.currentText()

        box = self.ui.comboBox_task_selection
        # Task names from the LAST populate, not the box's contents: the .ui file ships a
        # placeholder item, so at startup "previous" is a name that was never a task, and
        # warning about losing it would train the operator past the warning that matters.
        had = getattr(self, "_task_names", set())
        box.blockSignals(True)                   # repopulating is not the operator choosing
        try:
            box.clear()
            if (
                self.tasks_config and "tasks" in self.tasks_config
            ):  # Check if tasks exist in the configuration.
                task_names = []
                for task in self.tasks_config["tasks"]:  # Iterate over the tasks.
                    task_name = task.get("task_name")  # Get the task name.
                    if task_name:
                        box.addItem(task_name)  # Add task name to the combobox.
                        task_names.append(task_name)
                logger.info(f"Loaded {len(task_names)} tasks: {task_names}")
                self._task_names = set(task_names)
            else:
                self.set_logs(
                    "No tasks found in the configuration file."
                )  # Log a message if no tasks are found.
            if previous and box.findText(previous) >= 0:
                box.setCurrentText(previous)
        finally:
            box.blockSignals(False)

        # Signals were blocked, so bring selected_task back in step by hand -- and say so when
        # the task that was selected is gone, rather than quietly recording into another one.
        restored = box.currentText()
        if previous in had and previous != restored:
            self.set_logs(
                f"Task '{previous}' is no longer in the configuration; selected "
                f"'{restored}' instead. Episodes would be recorded to that dataset.",
                clear=False,
            )
            logger.warning(f"selected task '{previous}' vanished; now '{restored}'")
        if restored != self.selected_task:
            self.selected_task = restored
            self.refresh_episode_object_choices()

    def get_task_parameters(self, task_name: str) -> dict | None:
        """
        Retrieve the configuration of a specific task by its name.

        Searches through the loaded task configuration to find a matching task
        by its name. Logs a message if the task or configuration is not found.

        :param task_name: The name of the task to search for.
        :return: The task configuration as a dictionary if found, otherwise None.
        """
        if not self.tasks_config or "tasks" not in self.tasks_config:  # Check if tasks are loaded.
            self.set_logs(
                "Task configuration not found or tasks not defined."
            )  # Log error if config is missing.
            return None

        for task in self.tasks_config["tasks"]:  # Iterate over tasks in the configuration.
            if task["task_name"] == task_name:  # Check if the task name matches.
                return task  # Return the matching task configuration.

        self.set_logs(
            f"Task '{task_name}' not found in configuration."
        )  # Log message if task is not found.
        return None  # Return None if no match is found.

    def get_max_joint_velocity_rad_s(self, robot_model: str) -> float:
        """
        Look up the speed-warning threshold (rad/s) for a robot model.

        Reads the optional `max_joint_velocity_rad_s` field from the
        persistent robot config, falling back to a generic default if the
        robot or field isn't set.

        :param robot_model: The robot model name, e.g. "trossen_ai_stationary".
        :return: The threshold in rad/s used to flag teleoperation as too fast.
        """
        robot_config_data = load_config(TROSSEN_AI_ROBOT_PATH_PERSISTENT) or {}
        robot = robot_config_data.get(robot_model) or {}
        try:
            return float(robot.get("max_joint_velocity_rad_s", DEFAULT_MAX_JOINT_VELOCITY_RAD_S))
        except (TypeError, ValueError):
            return DEFAULT_MAX_JOINT_VELOCITY_RAD_S

    def update_speed_warning(self, max_velocity: float) -> None:
        """
        Show or hide the "moving too fast" warning banner.

        :param max_velocity: The fastest joint's apparent commanded velocity
            (max absolute per-joint delta over dt) for the current control
            loop iteration, in rad/s. Pass 0.0 to clear the warning.
        """
        threshold = getattr(self, "max_joint_velocity_rad_s", DEFAULT_MAX_JOINT_VELOCITY_RAD_S)
        is_too_fast = max_velocity > threshold

        if is_too_fast != getattr(self, "_speed_warning_active", False):
            self._speed_warning_active = is_too_fast
            self.ui.label_speed_warning.setStyleSheet(
                "background-color: #d62728; color: white; border-radius: 6px;"
                if is_too_fast
                else ""
            )

        if is_too_fast:
            self.ui.label_speed_warning.setText(
                f"⚠ MOVING TOO FAST — SLOW DOWN  "
                f"({max_velocity:.1f} rad/s > {threshold:.1f} rad/s)"
            )
        else:
            self.ui.label_speed_warning.setText("")

    @Slot(int)
    def update_progress(self, value: int) -> None:
        """
        Update the progress bar with the given value.

        This method is triggered by a signal to visually indicate progress during recording.

        :param value: The progress value to set (0-100).
        """
        self.ui.progressBar_recording_progress.setValue(value)  # Update the progress bar.

    @Slot(int, object)
    def update_image(self, index: int, image: object) -> None:
        """
        Update the image display for a specified camera widget.

        This method is triggered by a signal to update the displayed image
        for a specific camera widget. Performs color conversion from RGB to BGR
        for proper display.

        :param index: The index of the camera widget to update.
        :param image: The raw RGB image data to display.
        """
        if 0 <= index < len(self.camera_widgets):  # Ensure the index is within range.
            # Convert RGB to BGR for proper display (moved from control loop for better performance)
            bgr_image = cv2.cvtColor(image, cv2.COLOR_RGB2BGR)
            if index == self.framing_camera_index and self.framing is not None:
                # Keep the unmarked frame for the camera check, and show the operator the
                # window the policy will actually see. An object staged outside it is invisible
                # to the policy however clean the demonstration is, and an unmarked feed gives
                # no way to notice.
                self.last_main_frame = image
                bgr_image = framing_utils.draw_crop(bgr_image, self.framing.crop)
                # Only while a scene is being staged. During an episode the letters would be
                # clutter over the thing being watched, and the zones are settled by then.
                if getattr(self, "staging_active", False):
                    bgr_image = framing_utils.draw_zones(
                        bgr_image, self.framing.crop, self.framing.table_top)
                # Blob detection every frame would cost more than it is worth at 30 fps, and a
                # prop that leaves the crop stays out until somebody moves it, so a few times a
                # second is as good as every frame. The result is held between checks so the
                # warning does not strobe.
                self._framing_tick = getattr(self, "_framing_tick", 0) + 1
                if self._framing_tick % 8 == 0:
                    self.strays = framing_utils.outside_crop(
                    image, self.framing.crop, skip_top=self.framing.table_top)
                bgr_image = framing_utils.draw_outside(bgr_image, getattr(self, "strays", []))
            self.camera_widgets[index].set_image(bgr_image)  # Update the image in the widget.

    @Slot(list)
    def update_camera_labels(self, camera_keys: list) -> None:
        """
        Update the camera feed labels with the actual camera names.

        This method is triggered by a signal to update the camera feed labels
        with the names extracted from the observation keys.

        :param camera_keys: List of camera keys from the observation dictionary.
        """
        # Map camera feed labels
        label_widgets = [
            self.ui.label_cameraFeed1,  # Camera 0
            self.ui.label_cameraFeed2,  # Camera 1
            self.ui.label_cameraFeed3,  # Camera 2
            self.ui.label_cameraFeed4,  # Camera 3
        ]

        # Update labels with camera names extracted from keys
        for i, key in enumerate(camera_keys[:4]):
            if i < len(label_widgets):
                # Extract camera name from observation key
                # Key format: "observation.images.cam_high" -> "cam_high"
                camera_name = key.split(".")[-1] if "." in key else key
                label_widgets[i].setText(camera_name)
                if camera_name == FRAMING_CAMERA:
                    self.framing_camera_index = i
        if self.framing is not None and self.framing_camera_index is None:
            logger.warning(
                f"'{FRAMING_CAMERA}' is not among the cameras "
                f"{[k.split('.')[-1] for k in camera_keys[:4]]}; the crop belongs to that view "
                f"only, so it will not be drawn and the camera will not be checked."
            )

    def update_episode_count(self, change: int) -> None:
        """
        Update the episode count by a specified change value.

        Ensures the episode count does not go below zero and updates the corresponding UI element.

        :param change: The value to add to the current episode count.
        """
        self.episode_count += change  # Adjust the episode count.
        if self.episode_count < 0:  # Ensure the count does not go below zero.
            self.episode_count = 0
        self.ui.spinBox_episode_count.setValue(self.episode_count)  # Update the UI element.

    def start_recording(self) -> None:
        """
        Start the recording process for the selected task.

        This method initializes a QThread and a RecordWorker instance to manage
        the recording process. It retrieves the task configuration, sets up the worker,
        connects signals, and starts the recording process.

        :return: None
        """
        logger.info(f"Starting recording for task '{self.selected_task}'")

        # A camera knocked since the crop was measured produces episodes that look perfect and
        # teach the policy to look at the wrong part of the table, and nothing downstream
        # reports it. Ask before spending a session on that, rather than after.
        if not self.check_camera_framing(quiet=True):
            ok, msg = framing_utils.check(self.framing, self.last_main_frame)
            if (
                QMessageBox.warning(
                    self,
                    "Camera has moved",
                    f"{msg}\n\nThe crop is fixed in camera pixels and is baked into the "
                    f"checkpoint, so episodes recorded now will train a policy that looks "
                    f"somewhere else.\n\nRecord anyway?",
                    QMessageBox.Yes | QMessageBox.No,
                    QMessageBox.No,
                )
                != QMessageBox.Yes
            ):
                logger.info("recording cancelled: camera framing")
                self.set_logs("Recording cancelled -- put the camera back first.", clear=False)
                return

        # Perform hardware reset on all connected RealSense devices
        self.hardware_reset_cameras()

        # Disable the UI elements that are not required while recording.
        self.set_recording_ui_elements_enabled(False)

        task_config = self.get_task_parameters(self.selected_task)
        if not task_config:
            self.set_logs("Unable to find configuration for the selected task.")
            return
        self.disable_active_ui_updates = task_config.get("disable_active_ui_updates", False)

        config = RecordControlConfig(
            repo_id=f"{task_config.get('hf_user')}/{self.selected_task}",
            single_task=task_config.get("task_description", "No task definition was provided"),
            num_episodes=self.episode_count,
            fps=task_config.get("fps", 30),
            push_to_hub=task_config.get("push_to_hub", False),
            warmup_time_s=task_config.get("warmup_time_s", 3),
            episode_time_s=task_config.get("episode_length_s", 10),
            reset_time_s=task_config.get("reset_time_s", 5),
            num_image_writer_threads_per_camera=8,
            play_sounds=task_config.get("play_sounds", False),
            save_interval=task_config.get("save_interval", 1),
        )
        logger.info(
            f"Recording config: repo_id={config.repo_id}, num_episodes={config.num_episodes}, "
            f"fps={config.fps}, episode_time_s={config.episode_time_s}, "
            f"warmup_time_s={config.warmup_time_s}, reset_time_s={config.reset_time_s}, "
            f"robot_model={task_config.get('robot_model')}"
        )
        # Set display frequency lower than control loop fps for better performance
        self.display_fps = task_config.get("display_fps", 1)
        # Update the UI label to show the camera feed FPS value
        self.ui.label_cameraFeedValue.setText(str(self.display_fps))
        # Speed-warning threshold for this robot model (see control_loop/update_speed_warning).
        self.max_joint_velocity_rad_s = self.get_max_joint_velocity_rad_s(
            task_config.get("robot_model")
        )
        self.update_speed_warning(0.0)  # Clear any leftover warning from a previous session.
        # Initialize the robot with the configuration.
        try:
            self.robot = make_robot_from_config(create_robot_config(task_config.get("robot_model")))
        except Exception as e:
            logger.error(f"Failed to initialize robot: {e}")
            self.set_logs(f"Error initializing robot: {e}")
            self.set_recording_ui_elements_enabled(True)
            return
        logger.info(f"Robot initialized: {type(self.robot).__name__}")

        # Get the operators from the task configuration.
        operators = []
        for operator in task_config.get("operators", []):
            operators.append(
                {"name": operator.get("name", None), "email": operator.get("email", None)}
            )

        # Initialize the thread and worker with the task configuration.
        self._thread = QThread()
        self.worker = RecordWorker(
            robot=self.robot,
            config=config,
            operators=operators,
            main_window=self,
        )

        # Move the worker to the thread.
        self.worker.moveToThread(self._thread)

        # Connect worker signals to relevant slots.
        self.worker.progress.connect(self.update_progress)
        self.worker.image_update.connect(self.update_image)
        self.worker.camera_labels_update.connect(self.update_camera_labels)
        self.worker.log_signal.connect(self.set_logs_slot)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.finished.connect(self._thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.started.connect(self.worker.run)
        logger.info("Recording worker thread starting")
        self._thread.start()

        self.set_logs(f"Starting recording for task '{self.selected_task}'.")
        log_say("Initializing", False)
        self.set_logs(
            "Please be patient, while the robot is being prepared for recording.",
            False,
        )

    def start_dry_run(self) -> None:
        """
        Start the recording process for the selected task.

        This method initializes a QThread and a RecordWorker instance to manage
        the recording process. It retrieves the task configuration, sets up the worker,
        connects signals, and starts the recording process.

        :return: None
        """
        logger.info(f"Starting dry run for task '{self.selected_task}'")

        # Disable the UI elements that are not required during dry run.
        self.set_recording_ui_elements_enabled(False)

        task_config = self.get_task_parameters(self.selected_task)
        if not task_config:
            self.set_logs("Unable to find configuration for the selected task.")
            return
        self.disable_active_ui_updates = task_config.get("disable_active_ui_updates", False)

        config = TeleoperateControlConfig(
            fps=task_config.get("fps", 30),
            teleop_time_s=task_config.get("episode_length_s", 10),
        )
        logger.info(
            f"Dry run config: fps={config.fps}, teleop_time_s={config.teleop_time_s}, "
            f"robot_model={task_config.get('robot_model')}"
        )
        # Set display frequency lower than control loop fps for better performance
        self.display_fps = task_config.get("display_fps", 1)
        # Update the UI label to show the camera feed FPS value
        self.ui.label_cameraFeedValue.setText(str(self.display_fps))
        # Speed-warning threshold for this robot model (see control_loop/update_speed_warning).
        self.max_joint_velocity_rad_s = self.get_max_joint_velocity_rad_s(
            task_config.get("robot_model")
        )
        self.update_speed_warning(0.0)  # Clear any leftover warning from a previous session.
        # Initialize the robot with the configuration.
        try:
            self.robot = make_robot_from_config(create_robot_config(task_config.get("robot_model")))
        except Exception as e:
            logger.error(f"Failed to initialize robot for dry run: {e}")
            self.set_logs(f"Error initializing robot: {e}")
            self.set_recording_ui_elements_enabled(True)
            return
        logger.info(f"Robot initialized for dry run: {type(self.robot).__name__}")

        # Initialize the thread and worker with the task configuration.
        self._thread = QThread()
        self.worker = RecordWorker(
            robot=self.robot,
            config=config,
            operators=[],
            main_window=self,
        )

        # Move the worker to the thread.
        self.worker.moveToThread(self._thread)

        # Connect worker signals to relevant slots.
        self.worker.progress.connect(self.update_progress)
        self.worker.image_update.connect(self.update_image)
        self.worker.camera_labels_update.connect(self.update_camera_labels)
        self.worker.log_signal.connect(self.set_logs_slot)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.finished.connect(self._thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        self._thread.started.connect(self.worker.dry_run)
        logger.info("Dry run worker thread starting")
        self._thread.start()

        self.set_logs(f"Starting Dry Run for {self.selected_task=}.")

    def start_reset_arms(self) -> None:
        """
        Start the reset arm process for the robot mentioned in the selected task.

        This method initializes a QThread and a RecordWorker instance to manage
        the reset arm process. It retrieves the task configuration, sets up the worker,
        connects signals, and starts the reset arm process.

        :return: None
        """
        logger.info("Starting arm reset")

        # Disable UI elements during arm reset.
        self.set_recording_ui_elements_enabled(False)

        # Reset the cameras before resetting the arms to ensure that any camera resources are freed
        self.hardware_reset_cameras()

        task_config = self.get_task_parameters(self.selected_task)
        if not task_config:
            self.set_logs("Unable to find configuration for the selected task.")
            return
        self.disable_active_ui_updates = task_config.get("disable_active_ui_updates", False)

        config = None

        try:
            self.robot = make_robot_from_config(create_robot_config(task_config.get("robot_model")))
        except Exception as e:
            logger.error(f"Failed to initialize robot for arm reset: {e}")
            self.set_logs(f"Error initializing robot: {e}")
            self.set_recording_ui_elements_enabled(True)
            return

        # Initialize the thread and worker with the task configuration.
        self._thread = QThread()
        self.worker = RecordWorker(
            robot=self.robot,
            config=config,
            operators=[],
            main_window=self,
        )

        # Move the worker to the thread.
        self.worker.moveToThread(self._thread)

        # Connect worker signals to relevant slots.
        self.worker.log_signal.connect(self.set_logs_slot)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.finished.connect(self._thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)

        message = "Resetting arms."
        log_say(message, True)
        self.set_logs(message, False)

        self._thread.started.connect(self.worker.reset_arm)
        logger.info("Arm reset worker thread starting")
        self._thread.start()

    def reset_environment_async(self, reset_time_s: float | None = None) -> None:
        """
        Start the environment reset asynchronously without blocking.

        This method starts a Python thread for the reset operation that runs
        in the background. Use wait_for_reset_completion() to block until reset finishes.
        Enables the SETUP DONE button for the duration of the reset, so the
        operator can end the wait early once they're ready.

        :param reset_time_s: Duration of this reset, in seconds. Defaults to
            the task's configured reset_time_s if not given (used for the
            periodic longer reset -- see record()).
        :return: None
        """
        duration = reset_time_s if reset_time_s is not None else self.worker.config.reset_time_s

        def reset_task():
            try:
                self.ui.pushButton_skip_reset.setEnabled(True)
                reset_environment(
                    self.robot,
                    self.events,
                    duration,
                    self.worker.config.fps,
                )
            except Exception as e:
                logger.error(f"Error during async reset: {e}")
                self.log_signal.emit(f"Error during reset: {e}", True)
            finally:
                self.ui.pushButton_skip_reset.setEnabled(False)

        logger.debug(f"Starting async environment reset ({duration}s)")
        self._reset_thread = threading.Thread(target=reset_task, daemon=True)
        self._reset_thread.start()

    def wait_for_reset_completion(self) -> None:
        """
        Wait for the reset operation to complete.

        This method blocks until the reset started by reset_environment_async() finishes.
        Does nothing if no reset is in progress.

        :return: None
        """
        if self._reset_thread is not None:
            if self._reset_thread.is_alive():
                logger.debug("Waiting for async reset to complete")
                self._reset_thread.join()
                logger.debug("Async reset completed")
                self.log_signal.emit("Reset completed", True)
            self._reset_thread = None

    def on_dataset_selection(self, _) -> None:
        """
        Handle changes in the selected dataset from the combobox.

        This method updates the currently selected task based on the user's selection
        in the combobox and logs the change.

        :param _: The current index of the combobox (unused).
        :return: None
        """
        self.selected_task = self.ui.comboBox_task_selection.currentText()
        logger.info(f"Task selection changed to '{self.selected_task}'")
        self.set_logs(f"Selected new task: {self.selected_task}")
        self.refresh_episode_object_choices()

    @staticmethod
    def _extract_object_from_instruction(template: str, instruction: str) -> str | None:
        """
        Reverse-map a full recorded instruction back to its `{object}` value.

        Given a task_description template containing an `{object}` placeholder
        and a full instruction string that was actually recorded, return the
        substring that must have filled the placeholder, or None if the
        instruction doesn't match the template's fixed prefix/suffix (e.g. it
        was recorded under a since-changed template).

        :param template: The task's task_description, e.g. "Pick up the {object}.".
        :param instruction: A previously recorded full instruction string.
        :return: The extracted object/variant substring, or None if no match.
        """
        if "{object}" not in template:
            return None
        prefix, suffix = template.split("{object}", 1)
        if not instruction.startswith(prefix) or not instruction.endswith(suffix):
            return None
        end = len(instruction) - len(suffix) if suffix else len(instruction)
        if end < len(prefix):
            return None
        return instruction[len(prefix) : end]

    def refresh_episode_object_choices(self) -> None:
        """
        Repopulate the object/variant combobox for the currently selected task.

        Combines the optional `task_objects` preset list from the task's config
        with every object/variant already recorded for this task's repo (read
        from its local meta/tasks.jsonl and meta/episodes.jsonl), so previously
        used instructions can be picked up again instead of only being typed
        from scratch. Defaults the selection to whichever variant was most
        recently recorded, so an interrupted session can be resumed as-is; if
        nothing has been recorded yet, falls back to the first preset. The
        combobox stays editable, so a brand new object/variant can still be
        typed in freely and will show up here again next time.

        Also refreshes the per-variant episode-count summary label.
        """
        task_config = self.get_task_parameters(self.selected_task) or {}
        preset_objects = list(task_config.get("task_objects", []) or [])
        template = task_config.get("task_description", "")
        hf_user = task_config.get("hf_user")

        self._task_object_counts = {}
        last_object = None

        if hf_user:
            repo_id = f"{hf_user}/{self.selected_task}"
            stats = get_recorded_task_stats(repo_id)

            for recorded_instruction, count in stats["counts"].items():
                if "{object}" in template:
                    obj = self._extract_object_from_instruction(template, recorded_instruction)
                    if obj is None:  # Doesn't match the current template; skip it.
                        continue
                else:
                    obj = recorded_instruction
                self._task_object_counts[obj] = self._task_object_counts.get(obj, 0) + count

            if stats["last_task"] is not None:
                if "{object}" in template:
                    last_object = self._extract_object_from_instruction(template, stats["last_task"])
                else:
                    last_object = stats["last_task"]

        # Presets first (so they're always available as suggestions), then any
        # additional objects/variants discovered from recording history. Kept
        # around so the history summary can list presets with zero episodes
        # too (useful for spotting under-recorded variants at a glance).
        combined_objects = list(preset_objects)
        for obj in self._task_object_counts:
            if obj not in combined_objects:
                combined_objects.append(obj)
        self._known_objects = combined_objects

        self.ui.comboBox_episode_object.blockSignals(True)
        self.ui.comboBox_episode_object.clear()
        self.ui.comboBox_episode_object.addItems(combined_objects)
        if last_object is not None and last_object in combined_objects:
            default_object = last_object
        else:
            default_object = combined_objects[0] if combined_objects else ""
        self.ui.comboBox_episode_object.setCurrentText(default_object)
        self.ui.comboBox_episode_object.blockSignals(False)

        self.update_instruction_preview()
        self.update_task_history_summary()

    def update_task_history_summary(self) -> None:
        """
        Refresh the label showing how many episodes have been recorded so far
        for each object/variant of the currently selected task. Includes
        presets with zero episodes recorded, so under-recorded variants are
        easy to spot at a glance.
        """
        known_objects = getattr(self, "_known_objects", [])
        # Include any object recorded live this session that wasn't in the
        # known list yet (e.g. a brand new one typed in mid-session).
        all_objects = list(known_objects)
        for obj in self._task_object_counts:
            if obj not in all_objects:
                all_objects.append(obj)

        if not all_objects:
            self.ui.label_task_history.setText("Recorded so far: (none yet)")
            return

        parts = [f"{obj} ×{self._task_object_counts.get(obj, 0)}" for obj in all_objects]
        self.ui.label_task_history.setText("Recorded so far: " + "  ·  ".join(parts))

    def get_current_instruction(self) -> str:
        """
        Compute the natural-language instruction for the episode about to be recorded.

        If the selected task's `task_description` contains an `{object}` placeholder,
        it is filled in with the current text of the object/variant combobox (which
        may be freely edited between episodes). Otherwise the task description is
        used as-is, unchanged.

        :return: The instruction string to record with the current/next episode.
        """
        task_config = self.get_task_parameters(self.selected_task) or {}
        template = task_config.get("task_description", "No task definition was provided")
        obj = self.ui.comboBox_episode_object.currentText().strip()
        if "{object}" in template:
            return template.replace("{object}", obj)
        return template

    def update_instruction_preview(self) -> None:
        """
        Refresh the on-screen preview of the instruction that will be recorded next.
        """
        self.ui.label_instruction_preview.setText(f"Instruction: {self.get_current_instruction()}")

    def _load_staging_sheet(self) -> None:
        """Read the staging sheet, if there is one. Absent is fine -- this is optional."""
        import csv
        self.staging_rows, self.staging_idx = [], 0
        try:
            if STAGING_SHEET.exists():
                with open(STAGING_SHEET, newline="") as fh:
                    self.staging_rows = list(csv.DictReader(fh))
        except Exception:
            logger.exception("could not read the staging sheet at %s", STAGING_SHEET)
            return
        if self.staging_rows:
            self.set_logs(f"staging sheet: {len(self.staging_rows)} episodes from "
                          f"{STAGING_SHEET}", clear=False)
            self.show_staging()

    def _grab_main_camera_frame(self) -> "np.ndarray | None":
        """One RGB frame from the main camera, without a recording session running.

        The live feed only exists while a worker is streaming, so the check would otherwise be
        unavailable at exactly the moment it is most useful -- before anything has been
        recorded. Opens the camera by the serial in the robot config, takes a few frames and
        closes again, so it never holds the device the recorder is about to want.
        """
        robot_model = None
        task_config = self.get_task_parameters(self.selected_task) if self.selected_task else None
        if task_config:
            robot_model = task_config.get("robot_model")
        robots = load_config(TROSSEN_AI_ROBOT_PATH_PERSISTENT) or {}
        cfg = robots.get(robot_model) if robot_model else None
        if cfg is None:
            # No task chosen yet: any robot entry that has the camera will do, since the serial
            # is what identifies it.
            cfg = next((v for v in robots.values()
                        if isinstance(v, dict) and FRAMING_CAMERA in (v.get("cameras") or {})),
                       None)
        cam = ((cfg or {}).get("cameras") or {}).get(FRAMING_CAMERA)
        if not cam or not cam.get("serial_number"):
            logger.warning(f"no serial number for '{FRAMING_CAMERA}' in the robot config")
            return None

        serial = str(cam["serial_number"])
        width, height = int(cam.get("width", 640)), int(cam.get("height", 480))
        fps = int(cam.get("fps", 30))

        def grab_once():
            """Open, take a few frames so auto-exposure settles, and let go completely.

            Letting go is the part that matters. pipeline.stop() is not enough on its own: the
            pipeline and config objects keep the device claimed until they are collected, and
            a device still claimed is one the recorder cannot open -- which is why a framing
            check used to have to be followed by a camera reset.
            """
            pipeline = rs.pipeline()
            rs_cfg = rs.config()
            rs_cfg.enable_device(serial)
            rs_cfg.enable_stream(rs.stream.color, width, height, rs.format.rgb8, fps)
            try:
                pipeline.start(rs_cfg)
                frame = None
                for _ in range(8):
                    fs = pipeline.wait_for_frames(2000)
                    c = fs.get_color_frame()
                    if c:
                        frame = np.asanyarray(c.get_data())
                return None if frame is None else frame.copy()
            finally:
                try:
                    pipeline.stop()
                except Exception:
                    pass
                del rs_cfg, pipeline
                gc.collect()

        try:
            return grab_once()
        except Exception as e:
            # Usually the device is still held from a previous open. Reset that one camera and
            # try once more, rather than leaving the operator to press Reset Cameras and guess
            # that this was why.
            logger.warning(f"'{FRAMING_CAMERA}' (serial {serial}) did not open: {e}; "
                           f"resetting it and retrying once")
            self.set_logs(f"{FRAMING_CAMERA} busy -- resetting it...", clear=False)
            try:
                for device in rs.context().query_devices():
                    if device.get_info(rs.camera_info.serial_number) == serial:
                        device.hardware_reset()
                        break
                time.sleep(3.0)                     # the device re-enumerates on USB
                return grab_once()
            except Exception as e2:
                logger.error(f"could not open '{FRAMING_CAMERA}' (serial {serial}): {e2}")
                return None

    def check_camera_framing(self, quiet: bool = False) -> bool:
        """Compare the live main camera against the frame the policy's crop was measured on.

        Returns True when it is safe to record. A missing reference returns True as well: it
        means nobody has measured a crop yet, which is a reason to say so, not to block a
        session.
        """
        if self.framing is None:
            msg = (
                f"No camera framing reference at {FRAMING_REFERENCE}. Nothing to check "
                f"against -- produce one with real_robot/mark_workspace.sh."
            )
            logger.warning(msg)
            if not quiet:
                self.set_logs(msg, clear=False)
            return True

        frame = self.last_main_frame
        if frame is None and not quiet:
            # Nothing streaming yet, which is the usual state when the UI has just opened and
            # the most useful moment to check. Take a frame directly.
            self.set_logs(f"Opening {FRAMING_CAMERA} to check the framing...", clear=False)
            QApplication.processEvents()
            frame = self._grab_main_camera_frame()
        if frame is None:
            msg = (
                f"No frame from {FRAMING_CAMERA}. Start a dry run, or check that the camera is "
                f"connected and its serial number is right in the robot configuration."
            )
            logger.warning(msg)
            if not quiet:
                self.set_logs(msg, clear=False)
                QMessageBox.warning(self, "Camera framing", msg)
            return True

        ok, msg = framing_utils.check(self.framing, frame)
        logger.info(f"camera framing: {msg}")
        self.set_logs(msg, clear=False)
        if not quiet:
            # Show the frame that was judged, with the crop on it: the number says whether the
            # camera moved, the picture says whether the objects are inside the window, and
            # only the second one is checkable while staging a scene.
            self._show_framing_preview(frame, ok, msg)
        return ok

    def _show_framing_preview(self, rgb, ok: bool, msg: str) -> None:
        """The judged frame with the crop drawn, in a dialog."""
        vis = framing_utils.draw_crop(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), self.framing.crop)
        vis = np.ascontiguousarray(vis)          # QImage wraps the buffer, it does not copy
        h, w = vis.shape[:2]
        img = QImage(vis.data, w, h, 3 * w, QImage.Format_BGR888).copy()

        dialog = QDialog(self)
        dialog.setWindowTitle("Camera framing")
        layout = QVBoxLayout(dialog)
        head = QLabel(msg, dialog)
        head.setStyleSheet(f"color: {'#2e7d32' if ok else '#c62828'}; font-weight: bold;")
        layout.addWidget(head)
        pic = QLabel(dialog)
        pic.setPixmap(QPixmap.fromImage(img).scaled(760, 570, Qt.KeepAspectRatio,
                                                    Qt.SmoothTransformation))
        layout.addWidget(pic)
        layout.addWidget(QLabel(
            "Orange box: what the policy sees. Anything staged outside it is invisible to the "
            "policy, however clean the demonstration.", dialog))
        close = QPushButton("Close", dialog)
        close.clicked.connect(dialog.accept)
        layout.addWidget(close)
        dialog.exec()

    # Fields of a staging row, in the order the scene gets built, with how to read each one.
    SETUP_STEPS = [
        ("variant", "Target", "the object the instruction names"),
        ("object_zone", "Target zone", "L / C / R across the reachable band"),
        ("container_zone", "Container zone", "where the bowl goes"),
        ("other_container", "Other container", "the one the instruction does NOT name"),
        ("distractors", "Also on the mat", "blocks and tape rolls, at their zones"),
        ("lighting", "Lighting", "overheads, lamp or blinds"),
        ("start_nudge", "Start pose", "nudge the arm off the home pose by this"),
    ]

    @staticmethod
    def scene_from_row(row: dict) -> list[dict]:
        """A staging row as the list of things that go on the mat, each with its zone.

        The row stores the target and the distractors in different fields and different
        formats, which is fine for a spreadsheet and wrong for setting up a scene: the operator
        has to be told what to put down, all of it, in one list. Resolving it here also gives
        the per-episode config something object-shaped to record instead of a joined string.
        """
        def cell(zone_key: str, row_key: str) -> str:
            """"L" plus a "far"/"near" column becomes "L-far"; without one it stays "L"."""
            z = (row.get(zone_key) or "?").strip()
            r = (row.get(row_key) or "").strip()
            return f"{z}-{r}" if r and "-" not in z else z

        scene = []
        target = (row.get("variant") or "").strip()
        if target:
            # A variant is either a bare object name or a whole instruction, depending on the
            # task. What goes on the mat is the object either way, and printing the sentence
            # where a prop name belongs makes the list harder to read at the moment it is
            # being worked through.
            name = target
            if " in the " in name:
                name = name.rsplit(" in the ", 1)[0]
                name = name.replace("Pick up the ", "").rsplit(" and place it", 1)[0].strip()
            scene.append({"object": name or target,
                          "zone": cell("object_zone", "object_row"), "role": "target"})
        container = row.get("container_zone")
        if container:
            # Which container it is comes from the instruction, not from the row: on
            # block_to_named_container the sentence is what names it, and calling it "bowl"
            # there would tell the operator to set up the wrong task.
            named = "bowl"
            if " in the " in target:
                named = target.rsplit(" in the ", 1)[1].strip(". ") or "bowl"
            scene.append({"object": named,
                          "zone": cell("container_zone", "container_row"),
                          "role": "container"})
        other = (row.get("other_container") or "").strip()
        if other and other != "(none)":
            name, _, zone = other.partition("@")
            scene.append({"object": name.strip(), "zone": zone.strip() or "?",
                          "role": "other container"})
        distractors = (row.get("distractors") or "").strip()
        if distractors and distractors != "(none)":
            for item in distractors.split(";"):
                item = item.strip()
                if not item:
                    continue
                name, _, zone = item.partition("@")
                scene.append({"object": name.strip(), "zone": zone.strip() or "?",
                              "role": "distractor"})
        return scene

    def save_episode_config(self, episode_idx, instruction: str = "") -> "Path | None":
        """Write everything about this episode's scene, as one file, when it is kept.

        The session log is a flat CSV and cannot hold the object list, and reconstructing a
        scene from "green block@R; red block@L" months later means re-parsing a display string
        and hoping its format never changed. Recording the resolved objects, the crop and the
        camera verdict instead makes each episode answerable on its own.
        """
        try:
            row = (self.staging_rows[self.staging_idx]
                   if self.staging_rows and self.staging_idx < len(self.staging_rows) else {})
            cam_ok, cam_msg = (None, "not checked")
            if self.framing is not None and self.last_main_frame is not None:
                cam_ok, cam_msg = framing_utils.check(self.framing, self.last_main_frame)
            rec = {
                "recorded_at": datetime.now().isoformat(timespec="seconds"),
                "task": self.selected_task,
                "episode_index": episode_idx,
                "staging_row": self.staging_idx + 1 if row else None,
                "instruction": instruction,
                "scene": self.scene_from_row(row) if row else [],
                "lighting": row.get("lighting"),
                "start_nudge": row.get("start_nudge"),
                "route": row.get("route"),
                "crop_main": list(self.framing.crop) if (self.framing and self.framing.crop)
                             else None,
                "camera_check": {"ok": cam_ok, "message": cam_msg},
                "staging_raw": dict(row),
            }
            EPISODE_CONFIG_ROOT.mkdir(parents=True, exist_ok=True)
            path = EPISODE_CONFIG_ROOT / f"{self.selected_task}_{int(episode_idx):05d}.json"
            path.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
            logger.info(f"episode config: {path}")
            return path
        except Exception:
            logger.exception("could not write the episode config")
            return None

    def sync_instruction_to_staging(self, row: dict) -> str:
        """Point the episode's instruction at the prop the staging row names. Returns it.

        The instruction is built from the object combobox, which nobody was setting from the
        sheet -- so a row asking for the green tape roll recorded "Pick up the red block",
        whatever the previous episode happened to leave there. The scene and the sentence then
        disagree, in a task whose entire point is that the sentence says which of eight objects
        to pick, and the demonstration teaches the policy to ignore it.
        """
        want = (row.get("variant") or "").strip()
        self._staging_task_mismatch = None
        if not want:
            return self.get_current_instruction()
        box = self.ui.comboBox_episode_object
        idx = box.findText(want)
        if idx < 0 and box.isEditable():
            # Substituting a whole instruction into an {object} slot yields "Pick up the Pick
            # up the blue block and place it in the pot. and place it in the bowl." -- which is
            # what a sheet built for another task produces, and it would be recorded verbatim.
            # Say the sheet is wrong instead of improvising a sentence out of it.
            task_config = self.get_task_parameters(self.selected_task) or {}
            if want not in (task_config.get("task_objects") or []):
                self._staging_task_mismatch = want
                logger.warning(
                    f"staging row names '{want}', which is not among '{self.selected_task}'"
                    f"'s objects -- the sheet was generated for another task"
                )
                return self.get_current_instruction()
        box.blockSignals(True)
        try:
            if idx >= 0:
                box.setCurrentIndex(idx)
            elif box.isEditable():
                box.setEditText(want)
            else:
                self._staging_task_mismatch = want
                logger.warning(
                    f"staging row names '{want}', which is not among this task's objects; "
                    f"the sheet may have been generated for another task"
                )
        finally:
            box.blockSignals(False)
        self.update_instruction_preview()
        return self.get_current_instruction()

    def show_setup_gate(self) -> None:
        """Ask whether the scene matches the staging row, and say what has to change.

        The sheet already randomises the container, the distractors and the lighting every
        episode, which is the whole reason it exists -- and it is exactly that randomisation
        that makes a row easy to half-apply. Moving the target and forgetting the lamp
        correlates lighting with something it should be independent of, quietly, in a way that
        only shows up when a split is drawn months later.

        So the difference from the previous episode is what gets emphasised, not the row: the
        fields that changed are the whole of the work, and the ones that did not are noise.
        """
        row = None
        if self.staging_rows and self.staging_idx < len(self.staging_rows):
            row = self.staging_rows[self.staging_idx]
        # What the live check compares against. Empty means "nothing to verify", which is the
        # honest state without a sheet rather than a pass.
        self._gate_scene = self.scene_from_row(row) if row else []
        # Before anything is drawn: the sentence has to name the prop the sheet is about to ask
        # for, and the operator has to be able to read the one that will actually be recorded.
        instruction = self.sync_instruction_to_staging(row) if row else \
            self.get_current_instruction()

        dialog = QDialog(self)
        dialog.setWindowTitle("Set up the scene")
        dialog.setModal(True)
        outer = QHBoxLayout(dialog)

        left = QVBoxLayout()
        if row is None:
            left.addWidget(QLabel("No staging sheet loaded -- stage the scene as you intend "
                                  "and start when ready.", dialog))
        else:
            head = QLabel(f"Episode {self.staging_idx + 1} of {len(self.staging_rows)}", dialog)
            head.setStyleSheet("font-size: 15px; font-weight: bold;")
            left.addWidget(head)
            # The object lives here, not on the main window. This dialog is modal, so while
            # it is open the combobox behind it cannot be reached -- and this is the moment the
            # object is actually being decided, with the scene in front of you.
            pick = QHBoxLayout()
            pick.addWidget(QLabel("Object:", dialog))
            self.gate_object = QComboBox(dialog)
            self.gate_object.setEditable(self.ui.comboBox_episode_object.isEditable())
            src = self.ui.comboBox_episode_object
            self.gate_object.addItems([src.itemText(i) for i in range(src.count())])
            self.gate_object.setCurrentText(src.currentText())
            pick.addWidget(self.gate_object, 1)
            left.addLayout(pick)

            said = QLabel(f"Recorded as:  \u201c{instruction}\u201d", dialog)
            said.setStyleSheet("color: #1565c0;")
            said.setWordWrap(True)
            left.addWidget(said)

            def object_changed(text):
                """Change it here and the episode is recorded with it -- nothing else to do."""
                box = self.ui.comboBox_episode_object
                box.blockSignals(True)
                try:
                    idx = box.findText(text)
                    if idx >= 0:
                        box.setCurrentIndex(idx)
                    elif box.isEditable():
                        box.setEditText(text)
                finally:
                    box.blockSignals(False)
                self.update_instruction_preview()
                said.setText(f"Recorded as:  \u201c{self.get_current_instruction()}\u201d")
                if text != (row.get("variant") or "").strip():
                    said.setStyleSheet("color: #ef6c00; font-weight: bold;")
                    said.setToolTip("This is not the object the staging sheet asked for.")
                else:
                    said.setStyleSheet("color: #1565c0;")
                    said.setToolTip("")

            self.gate_object.currentTextChanged.connect(object_changed)
            if self.gate_object.isEditable():
                self.gate_object.editTextChanged.connect(object_changed)
            prev = getattr(self, "_last_staged_row", None)
            changed = [k for k, _, _ in self.SETUP_STEPS
                       if prev is not None and row.get(k) != prev.get(k)]
            if prev is None:
                left.addWidget(QLabel("First episode -- set up every line below.", dialog))
            elif changed:
                labels = {k: lbl for k, lbl, _ in self.SETUP_STEPS}
                banner = QLabel(f"CHANGE {len(changed)}: "
                                + ", ".join(labels[c] for c in changed), dialog)
                banner.setStyleSheet("color: #c62828; font-weight: bold;")
                banner.setWordWrap(True)
                left.addWidget(banner)
            else:
                same = QLabel("Nothing changes from the last episode.", dialog)
                same.setStyleSheet("color: #2e7d32;")
                left.addWidget(same)

            # What actually has to happen, object by object. The row keeps the target and the
            # distractors in separate fields, which is fine for a spreadsheet and useless when
            # the job is to put things on a mat: what is needed is one list of everything that
            # goes down, and one of what has to come off. Setting up from the fields instead is
            # how a distractor from the previous episode gets left on the table.
            scene = self.scene_from_row(row)
            prev_scene = self.scene_from_row(prev) if prev else []
            prev_by_object = {s["object"]: s["zone"] for s in prev_scene}
            place = QLabel("PLACE ON THE MAT", dialog)
            place.setStyleSheet("font-weight: bold;")
            left.addWidget(place)
            grid = QFormLayout()
            for s in scene:
                was = prev_by_object.get(s["object"])
                moved = was is None or was != s["zone"]
                w = QLabel(f"zone {s['zone']}" + ("" if was is None else f"   (was {was})"),
                           dialog)
                if moved and prev:
                    w.setStyleSheet("color: #c62828; font-weight: bold;")
                name = f"{s['object']}  [{s['role']}]"
                grid.addRow(QLabel(("MOVE  " if moved and prev else "keep  ") + name, dialog), w)
            left.addLayout(grid)

            here = {s["object"] for s in scene}
            gone = [o for o in prev_by_object if o not in here]
            if gone:
                rm = QLabel("TAKE OFF THE MAT: " + ", ".join(sorted(gone)), dialog)
                rm.setStyleSheet("color: #c62828; font-weight: bold;")
                rm.setWordWrap(True)
                left.addWidget(rm)

            rest = QFormLayout()
            for key, label, hint in self.SETUP_STEPS:
                if key in ("variant", "object_zone", "container_zone", "other_container",
                           "distractors"):
                    continue                     # already spelled out object by object above
                w = QLabel(row.get(key, "-") or "-", dialog)
                w.setWordWrap(True)
                w.setToolTip(hint)
                if key in changed:
                    w.setStyleSheet("color: #c62828; font-weight: bold;")
                    label = f"CHANGE  {label}"
                rest.addRow(QLabel(label, dialog), w)
            left.addLayout(rest)

        self.gate_status = QLabel("", dialog)
        self.gate_status.setWordWrap(True)
        left.addWidget(self.gate_status)
        left.addStretch(1)

        live = QLabel("The arm is following the leader while this is open. "
                      "Enter opens the gripper and stops.", dialog)
        live.setStyleSheet("color: #ef6c00;")
        live.setWordWrap(True)
        left.addWidget(live)

        mismatch = getattr(self, "_staging_task_mismatch", None)
        if mismatch:
            warn = QLabel(
                f"This staging sheet is for a different task. It asks for\n"
                f"    \u201c{mismatch}\u201d\n"
                f"which is not one of '{self.selected_task}'s objects, so the sentence "
                f"recorded would not describe the scene.\n\n"
                f"Regenerate the sheet for this task:\n"
                f"    python scripts/staging_plan.py --task {self.selected_task} "
                f"--csv <staging_sheet.csv>", dialog)
            warn.setStyleSheet("color: #c62828; font-weight: bold;")
            warn.setWordWrap(True)
            left.addWidget(warn)

        start = QPushButton("Setup done -- start recording  (G)", dialog)
        if mismatch:
            start.setEnabled(False)
            start.setText("Sheet is for another task -- cannot record")
        start.setStyleSheet("font-weight: bold; padding: 8px;")
        start.setDefault(True)
        skip = QPushButton("Skip this staging row", dialog)
        stop = QPushButton("Stop recording", dialog)
        for b in (start, skip, stop):
            left.addWidget(b)
        outer.addLayout(left, 0)

        self.gate_preview = QLabel(dialog)
        self.gate_preview.setMinimumSize(640, 480)
        outer.addWidget(self.gate_preview, 1)

        # The camera keeps running while the gate is up, which is the point: the scene is being
        # built right now, and a prop that ends up outside the crop has to be visible while
        # there is still a chance to move it.
        timer = QTimer(dialog)
        timer.timeout.connect(self._refresh_setup_gate)
        timer.start(200)

        def go():
            self.set_start_episode()
            dialog.accept()

        def do_skip():
            self.advance_staging()
            dialog.accept()
            # Not emitted directly: accept() only asks exec() to return, so a direct re-entry
            # would open the next gate inside the one still closing.
            QTimer.singleShot(0, self.show_setup_gate)

        def do_stop():
            self.set_stop_recording()
            dialog.accept()

        start.clicked.connect(go)
        skip.clicked.connect(do_skip)
        stop.clicked.connect(do_stop)
        # G still works, so the habit built during earlier sessions is not broken.
        QShortcut(QKeySequence("G"), dialog).activated.connect(go)
        self._gate_dialog = dialog
        # The main feed is far larger than this preview, so the letters go on both: props get
        # placed by looking at the big picture, not at a thumbnail beside a checklist.
        self.staging_active = True
        self._refresh_setup_gate()
        dialog.exec()
        timer.stop()
        self.staging_active = False
        self._gate_dialog = None
        if row is not None:
            self._last_staged_row = row

    def _refresh_setup_gate(self) -> None:
        """Live camera in the gate: the crop, and anything that has fallen outside it."""
        if self.framing is None:
            self.gate_status.setText("No framing reference -- the crop cannot be shown.")
            return
        # Deliberately not _grab_main_camera_frame(): the gate only comes up between episodes
        # of a running session, where the recorder holds the device. Opening it here would
        # fight the recorder for it.
        frame = self.last_main_frame
        if frame is None:
            self.gate_status.setText(f"Waiting for the first {FRAMING_CAMERA} frame...")
            return
        crop = self.framing.crop
        strays = framing_utils.outside_crop(frame, crop, skip_top=self.framing.table_top)
        vis = framing_utils.draw_crop(cv2.cvtColor(frame, cv2.COLOR_RGB2BGR), crop)
        vis = framing_utils.draw_zones(vis, crop, self.framing.table_top)
        # Label what the checker believes it is looking at. When it disagrees with the
        # operator, the argument is settled by reading the labels rather than by trusting
        # either -- a tape roll read as a block would otherwise look like a missing object.
        #
        # Same arguments as the check itself, which this had been drawn without: the wooden
        # furniture passes the yellow gate that masking tape needs, and the gold pot is a ring
        # of the same hue. Eighteen labels were being drawn where there were nine props and two
        # containers, which reads as a broken detector rather than a missing argument.
        top = self.framing.table_top
        containers = framing_utils.find_containers(frame, crop, skip_top=top)
        for p in (framing_utils.identify_props(frame, crop, skip_top=top,
                                               exclude=containers) + containers):
            colour = (0, 200, 0) if p["inside_crop"] else (0, 0, 255)
            cv2.putText(vis, f"{p['object']} {p['zone']}",
                        (int(p["x"]) - 46, int(p["y"]) - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 3)
            cv2.putText(vis, f"{p['object']} {p['zone']}",
                        (int(p["x"]) - 46, int(p["y"]) - 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, colour, 1)
        vis = np.ascontiguousarray(framing_utils.draw_outside(vis, strays))
        h, w = vis.shape[:2]
        img = QImage(vis.data, w, h, 3 * w, QImage.Format_BGR888).copy()
        self.gate_preview.setPixmap(QPixmap.fromImage(img).scaled(
            640, 480, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        expected = getattr(self, "_gate_scene", [])
        if not expected:
            msg = ("No staging row -- nothing to verify. Objects inside the crop: "
                   + (", ".join(sorted({p["object"] for p in
                                        framing_utils.identify_props(
                                            frame, crop, skip_top=top, exclude=containers)
                                        if p["inside_crop"]})) or "none"))
            self.gate_status.setText(msg)
            self.gate_status.setStyleSheet("")
            return
        ok, lines = framing_utils.verify_scene(expected, frame, crop,
                                               skip_top=self.framing.table_top)
        icon = {"ok": "OK   ", "wrong": "WRONG", "missing": "MISS ", "extra": "EXTRA",
                "skip": "eye  "}
        body = "\n".join(f"{icon[s]}  {line}" for s, line in lines)
        if ok:
            self.gate_status.setText("Scene matches the staging row.\n" + body)
            self.gate_status.setStyleSheet("color: #2e7d32; font-family: monospace;")
        else:
            self.gate_status.setText("Scene does NOT match the staging row:\n" + body)
            self.gate_status.setStyleSheet("color: #c62828; font-family: monospace; "
                                           "font-weight: bold;")

    def show_staging(self) -> None:
        """Put the current staging row in the log, where the operator is already looking."""
        if not self.staging_rows:
            return
        if self.staging_idx >= len(self.staging_rows):
            self.set_logs("staging sheet finished -- every cell has been recorded", clear=False)
            return
        r = self.staging_rows[self.staging_idx]
        self.set_logs(
            f"[{self.staging_idx + 1}/{len(self.staging_rows)}]  "
            f"TARGET {r.get('variant', '?')} in zone {r.get('object_zone', '?')}  |  "
            f"BOWL in {r.get('container_zone', '?')}  |  "
            f"also on the mat: {r.get('distractors', '-')}  |  "
            f"lighting {r.get('lighting', '-')}  |  start {r.get('start_nudge', '-')}",
            clear=False)

    def log_staged_episode(self, episode_idx, instruction: str = "") -> None:
        """Record which staging row this episode was actually recorded under.

        A discarded take repeats its row, so episode N is not row N; without this join the
        conditions behind an episode -- zones, lighting, distractors, start nudge -- cannot be
        recovered, and a position or lighting OOD split has to be re-shot rather than drawn.
        """
        try:
            import csv as _csv
            row = (self.staging_rows[self.staging_idx]
                   if self.staging_rows and self.staging_idx < len(self.staging_rows) else {})
            rec = {"recorded_at": datetime.now().isoformat(timespec="seconds"),
                   "episode_index": episode_idx,
                   "staging_row": self.staging_idx + 1 if row else "",
                   "instruction": instruction, **row}
            SESSION_LOG.parent.mkdir(parents=True, exist_ok=True)
            new = not SESSION_LOG.exists()
            with open(SESSION_LOG, "a", newline="") as fh:
                w = _csv.DictWriter(fh, fieldnames=list(rec))
                if new:
                    w.writeheader()
                w.writerow(rec)
        except Exception:
            logger.exception("could not append to the session log")
        # Same moment, richer record: the CSV keeps the join, the JSON keeps the scene.
        self.save_episode_config(episode_idx, instruction)

    def advance_staging(self) -> None:
        """Move to the next row. Only a KEPT episode advances: a discarded take is re-recorded
        with the same staging, so the cell it belongs to still gets filled."""
        if not self.staging_rows:
            return
        self.staging_idx += 1
        self.show_staging()

    def set_logs(self, logs: str, clear: bool = True) -> None:
        """
        Update the log display with a new log message.

        This method appends or replaces the content of the log display widget
        based on the `clear` parameter. Automatically converts ANSI color codes
        and special characters to HTML. Uses a dequeue to automatically prune old
        log entries when the maximum limit is reached.

        :param logs: The log message to display.
        :param clear: Whether to clear existing logs before adding the new message.
                      If False, the new log is appended with a line break.
        :return: None
        """

        # Reference to the QTextBrowser
        text_browser = self.ui.textBrowser_log

        # Convert text to HTML (handles ANSI codes, escaping, newlines)
        formatted_logs = text_to_html(logs)

        if clear:
            # Clear mode: reset everything
            # Clear the text browser
            text_browser.clear()
            # Clear the dequeue
            self.log_entries.clear()
            # Insert the new log
            text_browser.insertHtml(formatted_logs)
            # Add to dequeue
            self.log_entries.append(formatted_logs)
        else:
            # Append mode: add to dequeue (auto-prunes oldest if at maxlen)
            # Add new entry to dequeue
            self.log_entries.append(formatted_logs)

            # If dequeue is at capacity, it auto-removed the oldest entry
            # Rebuild the display from the dequeue to reflect this
            if len(self.log_entries) >= self.max_log_entries:
                # Clear the display
                text_browser.clear()
                # Join all entries with line breaks for efficient rendering and rebuild from dequeue
                text_browser.insertHtml("<br>".join(self.log_entries))
            else:
                # Not at capacity yet, just append normally for O(1) performance
                # Get current cursor
                cursor = text_browser.textCursor()
                # Move to end
                cursor.movePosition(QTextCursor.MoveOperation.End)
                # Set cursor position
                text_browser.setTextCursor(cursor)
                # Append with line break
                text_browser.insertHtml("<br>" + formatted_logs)

        # Ensure auto-scroll
        # Get current cursor
        cursor = text_browser.textCursor()
        # Move cursor to end
        cursor.movePosition(QTextCursor.MoveOperation.End)
        # Apply new cursor position
        text_browser.setTextCursor(cursor)
        # Ensure scrolling to the end
        text_browser.ensureCursorVisible()

    @Slot(str, bool)
    def set_logs_slot(self, logs: str, clear: bool):
        self.set_logs(logs, clear)

    @safe_stop_image_writer
    def control_loop(
        self,
        robot: Union[ManipulatorRobot, TrossenAIMobile],
        control_time_s: float = None,
        teleoperate: bool = False,
        dataset: LeRobotDataset | None = None,
        events=None,
        policy: PreTrainedPolicy = None,
        fps: int | None = None,
        single_task: str | None = None,
        display_fps: int = 1,
    ) -> None:
        """
        Execute a control loop for the robot with optional teleoperation and data recording.

        This method performs the control operations for the robot, updates the display with camera images,
        and records data into a dataset if provided. It supports teleoperation and policy-based control.

        :param robot: The robot instance to control.
        :param control_time_s: The total duration for the control loop in seconds. Defaults to infinite.
        :param teleoperate: Whether to enable teleoperation. Defaults to False.
        :param dataset: A dataset dictionary to record observations and actions. Defaults to None.
        :param events: A dictionary of events controlling the loop behavior. Defaults to None.
        :param policy: A policy object for automated control. Defaults to None.
        :param device: The device to execute the policy on. Defaults to None.
        :param use_amp: Whether to use automatic mixed precision. Defaults to None.
        :param fps: The desired frames per second for the control loop. Defaults to None.
        :param display_fps: The desired frames per second for updating camera displays. Lower values improve performance. Defaults to 1.
        :return: None
        """
        logger.debug(
            f"Control loop starting: control_time_s={control_time_s}, fps={fps}, "
            f"teleoperate={teleoperate}, display_fps={display_fps}, "
            f"recording={'yes' if dataset is not None else 'no'}"
        )
        if not robot.is_connected:  # Connect the robot if not already connected.
            if not self._connect_robot_with_timeout(robot):
                return None

        if events is None:  # Initialize events dictionary if not provided.
            events = {"exit_early": False}

        if control_time_s is None:  # Set control time to infinite if not specified.
            control_time_s = float("inf")

        if teleoperate and policy is not None:  # Validate teleoperation and policy usage.
            raise ValueError("When `teleoperate` is True, `policy` should be None.")

        if dataset is not None and fps is not None and dataset.fps != fps:
            raise ValueError(
                f"The dataset fps should be equal to requested fps ({dataset['fps']} != {fps})."
            )

        timestamp = 0
        start_episode_t = time.perf_counter()  # Record the start time of the episode.
        frame_counter = 0  # Track frame count for display throttling
        # Calculate how many frames to skip between display updates
        # If control loop fps is not set, default to updating every frame; otherwise, calculate based on display_fps
        # If display_fps <= 0, disable display; if >= control fps, display every frame
        if fps is not None:
            if display_fps <= 0:
                display_frame_interval = 0  # Disable display
            elif display_fps >= fps:
                display_frame_interval = 1  # Display every frame
            else:
                display_frame_interval = max(1, int(fps / display_fps))
        else:
            display_frame_interval = 1  # Default to every frame

        # Cache image keys to avoid recalculating on every iteration
        cached_image_keys = None

        # Flag to track whether we should update the display on this iteration (used for throttling)
        should_update_display = False

        # Previous commanded action and its timestamp, used to estimate per-joint
        # velocity between consecutive teleoperation steps for the speed warning.
        prev_action = None
        prev_action_t = None

        while timestamp < control_time_s:  # Run the loop until the specified control time.
            start_loop_t = time.perf_counter()  # Record the loop start time.

            # Emergency release. Handled HERE rather than from the key handler because during
            # teleoperation the follower is re-commanded to the leader's position every tick:
            # a gripper-open written from the UI thread would be overwritten within 33 ms, and
            # two threads writing to the driver at once is worse than not stopping at all.
            if events.get("emergency"):
                events["emergency"] = False
                self._emergency_release(robot)
                events["stop_recording"] = True
                events["exit_early"] = True
                break

            if teleoperate:  # Perform teleoperation if enabled.
                observation, action = robot.teleop_step(record_data=True)

                # Estimate the fastest joint's commanded velocity since the last step
                # and flag it visually if it's moving too fast (see update_speed_warning).
                action_t = time.perf_counter()
                if prev_action is not None:
                    dt_action = action_t - prev_action_t
                    if dt_action > 0:
                        max_velocity = float((action["action"] - prev_action).abs().max() / dt_action)
                        self.update_speed_warning(max_velocity)
                prev_action = action["action"]
                prev_action_t = action_t

            if dataset is not None:  # Record data into the dataset if provided.
                frame = {**observation, **action, "task": single_task}
                dataset.add_frame(frame)

            # Update camera displays at throttled rate for better performance
            if display_frame_interval > 0:  # Only if display is enabled
                # Only update display every N frames based on display_fps
                should_update_display = frame_counter % display_frame_interval == 0

                if should_update_display:
                    # Cache image keys on first iteration for reuse
                    if cached_image_keys is None:
                        cached_image_keys = [
                            key for key in observation if "image" in key
                        ]  # Filter image-related keys.
                        # Update camera feed labels with actual camera names
                        self.worker.camera_labels_update.emit(cached_image_keys[:4])

                    for i, key in enumerate(cached_image_keys[:4]):
                        image = observation[key].numpy()
                        self.worker.image_update.emit(i, image)

            frame_counter += 1

            if fps is not None:
                dt_s = time.perf_counter() - start_loop_t
                busy_wait(1 / fps - dt_s)

            dt_s = time.perf_counter() - start_loop_t
            info = self.log_control_info(robot, dt_s, fps=fps)

            timestamp = time.perf_counter() - start_episode_t

            if not self.disable_active_ui_updates:
                self.log_signal.emit(info, False)

            # Update progress bar at throttled rate (same as display updates)
            if should_update_display:
                progress_value = int(
                    (timestamp / control_time_s) * 100
                )
                self.worker.progress.emit(progress_value)

            if events["exit_early"]:
                events["exit_early"] = False
                break

        if teleoperate:
            self.update_speed_warning(0.0)  # Clear the warning once teleoperation stops.

    # How fast the follower is allowed to close a gap to the leader when teleoperation starts.
    # Slow on purpose: this runs unattended between episodes, and the whole point is that the
    # motion be watchable rather than quick.
    ALIGN_RATE_RAD_S = 0.5
    ALIGN_MIN_S = 0.8
    ALIGN_MAX_S = 6.0
    ALIGN_TOL = 0.03            # radians; below this the arms are already together

    def align_follower_to_leader(self, robot, fps: float = 30.0) -> float:
        """Walk the follower onto the leader's pose before teleoperation begins. MOVES THE ARM.

        teleop_step writes the leader's position straight to the follower, and this robot's
        config sets max_relative_target to null, so lerobot's per-step cap is not in play. If
        the leader is left somewhere far away -- which it is, every time the operator lets go
        of it -- the first step of teleoperation closes the whole gap at once.

        That was tolerable while teleoperation only began once recording did, with a hand on
        the leader. It is not tolerable now that the arm goes live when the setup gate opens,
        with the operator's hands on the props.

        So the gap is closed deliberately instead: smoothstepped over a duration proportional
        to its size, at a rate slow enough to watch and interrupt. Returns the gap it started
        from, in the arms' own units.
        """
        try:
            pairs = [(robot.leader_arms[n], robot.follower_arms[n])
                     for n in robot.leader_arms if n in robot.follower_arms]
        except Exception:
            logger.exception("could not pair the leader and follower arms")
            return 0.0
        if not pairs:
            return 0.0

        starts, goals = [], []
        for leader, follower in pairs:
            goals.append(np.asarray(leader.read("Present_Position"), dtype=np.float32))
            starts.append(np.asarray(follower.read("Present_Position"), dtype=np.float32))
        gap = max((float(np.abs(g - s).max()) for g, s in zip(goals, starts)), default=0.0)
        if gap <= self.ALIGN_TOL:
            return gap

        seconds = min(self.ALIGN_MAX_S, max(self.ALIGN_MIN_S, gap / self.ALIGN_RATE_RAD_S))
        steps = max(2, int(seconds * fps))
        self.log_signal.emit(
            colored(f"aligning the arm to the leader: {gap:.2f} to close over {seconds:.1f}s "
                    f"-- keep clear (Enter stops)", "yellow"), False)
        for k in range(1, steps + 1):
            if self.events.get("emergency") or self.events.get("stop_recording"):
                break
            u = k / steps
            u = u * u * (3 - 2 * u)                  # smoothstep: no velocity step at either end
            for (_, follower), s, g in zip(pairs, starts, goals):
                follower.write("Goal_Position", (s + (g - s) * u).astype(np.float32))
            busy_wait(1 / fps)
        return gap

    def wait_for_start(self, cfg, robot=None) -> bool:
        """Block the recording thread until G (go), or a stop. Returns True if we should stop.

        Runs on the worker thread; the flags are set from the UI thread, which is why this
        polls a flag rather than touching Qt.

        It also teleoperates while it waits, at the recording rate. Frames otherwise only come
        from the control loop, which is not running yet -- so the feed and the setup gate both
        froze on whatever was in front of the camera when the previous episode ended, and a
        gate that checks the scene against a stale frame is worse than one that checks nothing,
        because it reports the last episode's layout as if it were this one's.

        Teleoperating rather than only reading the cameras is what makes the start pose part of
        the staging: the sheet asks for a different nudge off the home pose every episode, and
        an arm that cannot be moved until recording has already begun cannot be placed before
        it. It runs at cfg.fps for the same reason the control loop does -- a follower stepped
        at 10 Hz lurches between leader positions instead of tracking them.

        The arm being live here is why Enter has to do more than break the loop: it opens the
        gripper first, exactly as the control loop does.
        """
        self.events["start_episode"] = False
        # Say that the follower is live before it moves. It starts tracking the leader the
        # moment this gate opens, which is earlier than it used to -- and if the leader was
        # left somewhere far from the follower, the first step closes that gap at once.
        self.log_signal.emit(
            colored("TELEOPERATION LIVE -- the arm follows the leader, after walking onto it "
                    "first. Position the arm and the props, then press G to record "
                    "(Enter = open the gripper and stop)", "cyan"), False)
        # Queued to the UI thread, which owns the widgets. The gate sets the same flag G does,
        # so this loop needs no other change and G keeps working with the dialog closed.
        self.setup_gate_signal.emit()

        fps = float(getattr(cfg, "fps", 30) or 30)
        # Close any gap to the leader deliberately, before the first teleop step closes it all
        # at once. Does nothing when the arms are already together, which is the usual case
        # between episodes.
        if robot is not None:
            self.align_follower_to_leader(robot, fps)
        keys, last_emit, warned = None, 0.0, False
        while not self.events["start_episode"]:
            step_t = time.perf_counter()
            if self.events.get("emergency"):
                # The arm is following the leader by now, so breaking out is not enough.
                if robot is not None:
                    self._emergency_release(robot)
                return True
            if self.events["stop_recording"]:
                return True
            if robot is not None:
                try:
                    observation, _ = robot.teleop_step(record_data=True)
                    if keys is None:
                        keys = [k for k in observation if "image" in k]
                        self.worker.camera_labels_update.emit(keys[:4])
                    # Teleoperate at fps, redraw at 10 Hz. The follower needs every step; the
                    # operator staging a scene does not need thirty pictures a second, and the
                    # gate re-runs its scene check on each one.
                    if step_t - last_emit >= 0.1:
                        last_emit = step_t
                        for i, k in enumerate(keys[:4]):
                            self.worker.image_update.emit(i, observation[k].numpy())
                except Exception:
                    if not warned:                        # once, not thirty times a second
                        warned = True
                        logger.exception("teleoperation failed while waiting to start")
            busy_wait(max(0.0, 1 / fps - (time.perf_counter() - step_t)))
        self.events["start_episode"] = False
        return False

    def set_start_episode(self) -> None:
        """G: the scene is staged and the arm is where it should start. Begin recording."""
        logger.info("Start episode triggered by user")
        self.events["start_episode"] = True
        # The window-level G shortcut stays live alongside the gate's own, and recording
        # starting behind a dialog still asking whether the scene is ready would be worse than
        # either. Close it from here, so it does not matter which one fired.
        dialog = getattr(self, "_gate_dialog", None)
        if dialog is not None:
            dialog.accept()

    def _emergency_release(self, robot) -> None:
        """Open the follower's gripper and hold it where it is. Called from the control loop."""
        try:
            for name, arm in getattr(robot, "follower_arms", {}).items():
                here = arm.read("Present_Position")
                target = list(here)
                target[-1] = 0.040          # jaws open; 0 is closed on this arm
                arm.write("Goal_Position", target)
                logger.warning("EMERGENCY: opened %s gripper and held position", name)
            self.log_signal.emit(
                colored("EMERGENCY STOP -- gripper opened, arm holding position, "
                        "recording stopped", "red"), False)
        except Exception:
            logger.exception("emergency release failed")

    def set_emergency(self) -> None:
        """Enter: drop whatever is held and stop. The control loop acts on this within a tick."""
        logger.warning("Emergency triggered by user")
        self.events["emergency"] = True
        self.events["exit_early"] = True

    def log_control_info(
        self,
        robot: Union[ManipulatorRobot, TrossenAIMobile],
        dt_s: float,
        episode_index: int | None = None,
        frame_index: int | None = None,
        fps: int | None = None,
    ) -> None:
        """
        Log timing and performance information for the control loop.

        This method logs information about the control loop's execution time, including
        per-iteration duration and frequencies. It also logs device-specific timing metrics
        for leader arms, follower arms, and cameras.

        :param robot: The robot instance to retrieve log data from.
        :param dt_s: Duration of the control loop iteration in seconds.
        :param episode_index: The current episode index being recorded. Defaults to None.
        :param frame_index: The current frame index being processed. Defaults to None.
        :param fps: The desired frames per second for the control loop. Defaults to None.
        :return: None
        """
        log_items: list[str] = []  # Collect log information as a list of strings.

        if episode_index is not None:  # Log episode index if provided.
            log_items.append(f"ep:{episode_index}")
        if frame_index is not None:  # Log frame index if provided.
            log_items.append(f"frame:{frame_index}")

        def log_dt(shortname: str, dt_val_s: float) -> None:
            """
            Add timing and frequency information to the log.

            :param shortname: A short description of the metric being logged.
            :param dt_val_s: The duration of the metric in seconds.
            """
            nonlocal log_items, fps
            info_str = f"{shortname}:{dt_val_s * 1000:5.2f}ms ({1 / dt_val_s:3.1f}hz)"  # Format duration and frequency.
            if fps is not None:  # Check for FPS consistency.
                actual_fps = 1 / dt_val_s
                if actual_fps < fps - 1:  # Highlight low FPS in yellow.
                    info_str = colored(info_str, "yellow")
            log_items.append(info_str)  # Add to the log.

        log_dt("dt", dt_s)  # Log total loop time.

        # Log device-specific timing metrics for robots other than "stretch".
        if not robot.robot_type.startswith("stretch"):
            # Log leader arm timings.
            for name in robot.leader_arms:
                key = f"read_leader_{name}_pos_dt_s"
                if key in robot.logs:
                    log_dt("dtRlead", robot.logs[key])

            # Log follower arm write and read timings.
            for name in robot.follower_arms:
                write_key = f"write_follower_{name}_goal_pos_dt_s"
                read_key = f"read_follower_{name}_pos_dt_s"
                if write_key in robot.logs:
                    log_dt("dtWfoll", robot.logs[write_key])
                if read_key in robot.logs:
                    log_dt("dtRfoll", robot.logs[read_key])

            # Log camera read timings.
            for name in robot.cameras:
                key = f"read_camera_{name}_dt_s"
                if key in robot.logs:
                    log_dt(f"dtR{name}", robot.logs[key])

        info_str = " ".join(log_items)  # Combine log items into a single string.
        logger.info(info_str)
        return info_str

    @safe_disconnect
    def record(
        self,
        robot: Union[ManipulatorRobot, TrossenAIMobile],
        cfg: RecordControlConfig,
        operators: List[Dict[str, str]],
    ) -> dict:
        """
        Record episodes of robot operation, optionally using a pretrained policy.

        This method initializes a dataset for recording robot observations and actions.
        It optionally applies a policy for automated operation, handles teleoperation,
        and manages episodes with reset and rerecord functionality.

        :param robot: The robot instance to operate and record.
        :param root: The root directory for storing datasets.
        :param repo_id: The Hugging Face repository ID for the dataset.
        :param pretrained_policy_name_or_path: Path to a pretrained policy (optional).
        :param policy_overrides: Overrides for policy configuration (optional).
        :param fps: Desired frames per second for the recording loop (optional).
        :param warmup_time_s: Duration of the warmup phase in seconds. Defaults to 2.
        :param episode_time_s: Duration of each episode in seconds. Defaults to 10.
        :param reset_time_s: Duration for resetting the environment between episodes. Defaults to 5.
        :param num_episodes: Number of episodes to record. Defaults to 50.
        :param video: Whether to record video during the episodes. Defaults to True.
        :param run_compute_stats: Whether to compute dataset statistics after recording. Defaults to True.
        :param push_to_hub: Whether to push the dataset to Hugging Face Hub. Defaults to True.
        :param tags: Tags for the dataset (optional).
        :param num_image_writer_processes: Number of processes for writing images. Defaults to 0.
        :param num_image_writer_threads_per_camera: Threads per camera for writing images. Defaults to 4.
        :param force_override: Whether to override existing datasets. Defaults to False.
        :param play_sounds: Whether to play sounds during key events. Defaults to True.
        :return: A dictionary containing the recorded dataset information.
        """
        logger.info(
            f"Record started: repo_id={cfg.repo_id}, num_episodes={cfg.num_episodes}, fps={cfg.fps}"
        )
        last_recorded_episode_index = get_last_episode_index(cfg.repo_id)
        if last_recorded_episode_index is not None:
            logger.info(f"Resuming dataset from episode index {last_recorded_episode_index}")
            dataset = LeRobotDataset(
                cfg.repo_id,
                root=cfg.root,
            )
            if len(robot.cameras) > 0:
                dataset.start_image_writer(
                    num_processes=cfg.num_image_writer_processes,
                    num_threads=cfg.num_image_writer_threads_per_camera * len(robot.cameras),
                )
            sanity_check_dataset_robot_compatibility(dataset, robot, cfg.fps, cfg.video)
        else:
            logger.info(f"Creating new dataset for repo_id={cfg.repo_id}")
            # Remove corrupted files
            remove_corrupted_files(cfg.repo_id)
            # Create empty dataset or load existing saved episodes
            sanity_check_dataset_name(cfg.repo_id, cfg.policy)
            dataset = LeRobotDataset.create(
                cfg.repo_id,
                cfg.fps,
                root=cfg.root,
                robot=robot,
                use_videos=cfg.video,
                image_writer_processes=cfg.num_image_writer_processes,
                image_writer_threads=cfg.num_image_writer_threads_per_camera * len(robot.cameras),
            )

        for operator in operators:
            name = operator.get("name")
            email = operator.get("email") if "email" in operator else None
            dataset.meta.update_operator(name, email)

        policy = (
            None
            if cfg.policy is None
            else make_policy(cfg.policy, cfg.device, ds_meta=dataset.meta)
        )

        if not robot.is_connected:
            if not self._connect_robot_with_timeout(robot):
                self.set_recording_ui_elements_enabled(True)
                return None

        # Warmup phase
        log_say("Warmup", cfg.play_sounds)
        logger.info(f"Warmup phase starting ({cfg.warmup_time_s}s)")
        self.log_signal.emit("Warmup phase: Teleoperate the robot and verify camera feeds.", True)
        self.ui.label_total_time.setText(f"{float(cfg.warmup_time_s)}s")
        self.control_loop(
            robot=robot,
            control_time_s=cfg.warmup_time_s,
            teleoperate=True,
            dataset=None,
            events=self.events,
            policy=None,
            fps=cfg.fps,
            display_fps=self.display_fps,
        )

        # Ensure progress bar shows 100% at completion
        self.worker.progress.emit(100)

        logger.info("Warmup phase completed, starting recording session")
        self.log_signal.emit("Starting reset phase.", True)
        if has_method(robot, "teleop_safety_stop"):
            robot.teleop_safety_stop()

        recorded_episodes = 0
        batched_episodes = 0
        # Used to decide, per completed episode, whether to key the live
        # per-object/variant count by the object combobox text or the full
        # instruction (see the "{object}" in template checks below), and to
        # log completed episodes into the data collection plan.
        task_config_for_plan = self.get_task_parameters(self.selected_task) or {}
        template = task_config_for_plan.get("task_description", "")
        robot_model_for_plan = task_config_for_plan.get("robot_model", "")
        # Every `long_reset_interval` completed episodes, use `long_reset_time_s`
        # instead of the normal reset_time_s, for a proper environment re-setup
        # break (re-arranging props, etc.). Set long_reset_interval to 0 in the
        # task config to disable this and always use the normal reset time.
        long_reset_interval = int(task_config_for_plan.get("long_reset_interval", 10) or 0)
        long_reset_time_s = float(task_config_for_plan.get("long_reset_time_s", 60))
        # Recording loop
        try:
            while True:
                # Wait for any previous reset to complete before starting new episode
                self.wait_for_reset_completion()

                if recorded_episodes >= cfg.num_episodes:  # Stop if enough episodes recorded.
                    break

                if has_method(robot, "enable_teleoperation"):
                    robot.enable_teleoperation()

                episode_idx = dataset.num_episodes + batched_episodes
                # Read the instruction live so it can be changed between episodes
                # (e.g. editing the object combobox from "red block" to "blue block")
                # without needing to stop and restart the recording session.
                episode_instruction = self.get_current_instruction()
                logger.info(
                    f"Recording episode {episode_idx} ({recorded_episodes + 1}/{cfg.num_episodes}): "
                    f"{episode_instruction}"
                )
                log_say(f"Episode {episode_idx}", cfg.play_sounds)
                self.log_signal.emit(
                    colored(
                        f"Recording episode {dataset.num_episodes + batched_episodes}: "
                        f"{episode_instruction}",
                        "yellow",
                    ),
                    False,
                )

                self.ui.label_total_time.setText(f"{float(cfg.episode_time_s)}s")

                # Wait until the operator says the scene and the start pose are ready. There is
                # no warm-up phase in this loop -- recording begins the instant the episode
                # does -- so without this the arm's starting configuration is whatever the last
                # episode left, and staging has to be finished before the clock is running.
                # Space is deliberately NOT the key: it means "finish" a few seconds later, and
                # a start key that is also a stop key is one slip from a discarded take.
                if self.wait_for_start(cfg, robot):
                    break

                # Read it AGAIN, now that the gate has closed. The gate points the object
                # combobox at the staging row's prop, and it opens inside wait_for_start -- so
                # the sentence read above is the one from before the row was applied, which is
                # the previous episode's. The first episode of a session recorded "Pick up the
                # red block" for a row asking for a blue block, and nothing downstream could
                # tell that from a demonstration of ignoring the instruction.
                episode_instruction = self.get_current_instruction()
                self.log_signal.emit(
                    colored(f"recording: {episode_instruction}", "yellow"), False)

                # Enable rerecord, finish and fail buttons during episode recording
                self.ui.pushButton_rerecord.setEnabled(True)
                self.ui.pushButton_finish_episode.setEnabled(True)
                self.ui.pushButton_fail_episode.setEnabled(True)

                self.control_loop(
                    robot=robot,
                    control_time_s=cfg.episode_time_s,
                    teleoperate=True,
                    dataset=dataset,
                    events=self.events,
                    policy=policy,
                    fps=cfg.fps,
                    single_task=episode_instruction,
                    display_fps=self.display_fps,
                )

                # Ensure progress bar shows 100% at completion
                self.worker.progress.emit(100)

                # Disable rerecord, finish and fail buttons until new episode is started
                self.ui.pushButton_rerecord.setEnabled(False)
                self.ui.pushButton_finish_episode.setEnabled(False)
                self.ui.pushButton_fail_episode.setEnabled(False)

                # Reset phase - start reset without blocking
                if not self.events["stop_recording"] and (
                    (recorded_episodes < cfg.num_episodes - 1) or self.events["rerecord_episode"]
                ):
                    # A rerecord doesn't complete an episode, so it never triggers
                    # the periodic long reset (immediately redoing the same one
                    # doesn't need a fresh scene re-setup).
                    will_complete_episode = not self.events["rerecord_episode"]
                    next_recorded_count = (
                        recorded_episodes + 1 if will_complete_episode else recorded_episodes
                    )
                    is_long_reset = (
                        will_complete_episode
                        and long_reset_interval > 0
                        and next_recorded_count % long_reset_interval == 0
                        and next_recorded_count < cfg.num_episodes
                    )
                    reset_duration = long_reset_time_s if is_long_reset else cfg.reset_time_s

                    if is_long_reset:
                        self.log_signal.emit(
                            colored(
                                f"Long environment reset ({reset_duration:.0f}s) -- "
                                f"re-set-up the scene, then click SETUP DONE to continue.",
                                "cyan",
                            ),
                            True,
                        )

                    self.reset_environment_async(reset_duration)  # Non-blocking - returns immediately
                    log_say("Reset", cfg.play_sounds, blocking=True)
                    self.log_signal.emit("Reset the environment", True)

                # Handle rerecord event
                if self.events["rerecord_episode"]:
                    logger.info(f"Re-recording episode {episode_idx}")
                    log_say("Re-record", cfg.play_sounds)
                    self.log_signal.emit("Re-record episode", True)
                    self.events["rerecord_episode"] = False
                    self.events["exit_early"] = False
                    dataset.clear_episode_buffer()
                    continue

                # Handle fail episode event: discard the current episode's data
                # (unlike rerecord, it is NOT retried) and advance to the next episode.
                if self.events["fail_episode"]:
                    logger.info(f"Episode {episode_idx} marked as failed; discarding data")
                    log_say("Episode failed", cfg.play_sounds)
                    self.log_signal.emit(
                        colored(f"Episode {episode_idx} marked as failed. Discarding data.", "red"),
                        True,
                    )
                    self.events["fail_episode"] = False
                    self.events["exit_early"] = False
                    dataset.clear_episode_buffer()

                    recorded_episodes += 1
                    logger.info(
                        f"Episode {episode_idx} failed "
                        f"({recorded_episodes}/{cfg.num_episodes} attempted, "
                        f"{batched_episodes} in current batch)"
                    )

                    if self.events["stop_recording"]:  # Exit loop if stop event is triggered.
                        logger.info("Stop recording triggered by user")
                        break
                    continue

                if self.events["finish_episode"]:
                    logger.info(f"Episode {episode_idx} finished early by user")
                    self.log_signal.emit(
                        f"Episode {episode_idx} finished early. Saving and moving to the next episode.",
                        True,
                    )
                    self.events["finish_episode"] = False

                dataset.add_episode_to_batch()

                # Update the live per-object/variant episode count shown in the UI.
                if "{object}" in template:
                    obj_key = self.ui.comboBox_episode_object.currentText().strip()
                else:
                    obj_key = episode_instruction
                self._task_object_counts[obj_key] = self._task_object_counts.get(obj_key, 0) + 1
                self.update_task_history_summary()

                # Log this episode into the data collection plan (CSV + regenerated
                # markdown summary), so progress is tracked automatically as you record.
                record_episode_in_plan(
                    DATA_COLLECTION_PLAN_CSV_PATH,
                    task_name=self.selected_task,
                    robot_model=robot_model_for_plan,
                    repo_id=cfg.repo_id,
                    object_variant=obj_key,
                    instruction=episode_instruction,
                )
                render_data_collection_plan_md(DATA_COLLECTION_PLAN_CSV_PATH, DATA_COLLECTION_PLAN_MD_PATH)

                # Join this episode to the staging row it was recorded under, so the conditions
                # behind it -- zones, lighting, distractors, start nudge -- stay recoverable.
                self.log_staged_episode(episode_idx, episode_instruction)

                recorded_episodes += 1
                batched_episodes += 1
                logger.info(
                    f"Episode {episode_idx} completed "
                    f"({recorded_episodes}/{cfg.num_episodes} recorded, "
                    f"{batched_episodes} in current batch)"
                )

                if (
                    cfg.save_interval > 0
                    and recorded_episodes % cfg.save_interval == 0
                    and recorded_episodes > 0
                ):
                    logger.info(f"Saving dataset batch ({batched_episodes} episodes)")
                    log_say("Encoding and saving dataset batch...", cfg.play_sounds)
                    self.log_signal.emit("Saving dataset batch. This might take a while ...", False)
                    dataset.save_episode_batch()
                    logger.info("Dataset batch saved successfully")
                    batched_episodes = 0

                if self.events["stop_recording"]:  # Exit loop if stop event is triggered.
                    logger.info("Stop recording triggered by user")
                    break

            logger.info(f"Recording finished: {recorded_episodes} episodes recorded")
            log_say("Stop", cfg.play_sounds, blocking=True)
            self.log_signal.emit("Stop recording", True)
            stop_recording(robot, None, self.display_fps > 0)

            if cfg.save_interval <= 0 or (recorded_episodes % cfg.save_interval != 0):
                logger.info(f"Saving final dataset batch ({batched_episodes} episodes)")
                log_say("Encoding and saving dataset batch...", cfg.play_sounds)
                self.log_signal.emit("Saving dataset batch. This might take a while ...", True)
                dataset.save_episode_batch()
                logger.info("Final dataset batch saved successfully")
                batched_episodes = 0

            error_occurred = False

        except Exception as e:
            logger.exception("An error occurred during recording:")
            self.log_signal.emit(f"An error occurred during recording:\n{e}", True)
            error_occurred = True

        finally:
            self.initialize_image()

            if dataset.episode_batch:
                logger.info("Saving remaining episode batch before cleanup")
                try:
                    dataset.save_episode_batch()
                    logger.info("Remaining episode batch saved")
                except Exception as e:
                    logger.error(f"Failed to save remaining episode batch: {e}")
                    self.log_signal.emit(f"An error occurred while saving the dataset:\n{e}", True)
                    error_occurred = True

            # Enable the UI elements after recording.
            self.set_recording_ui_elements_enabled(True)

            if cfg.push_to_hub:  # Push the dataset to the Hugging Face Hub if requested.
                # A session stopped before the first episode is finished leaves nothing on
                # disk but a meta/ stub, and upload_folder on that raises "not a directory"
                # from inside the worker -- which surfaces as the window closing the moment
                # Start Recording is pressed, with the reason only in the log file.
                root = Path(getattr(dataset, "root", "") or "")
                episodes = int(getattr(dataset, "num_episodes", 0) or 0)
                if episodes < 1:
                    logger.info(f"nothing recorded; not pushing {cfg.repo_id}")
                    self.log_signal.emit(
                        "No episodes were recorded, so nothing was pushed to the Hub.", False)
                elif not root.is_dir():
                    logger.error(f"dataset root {root} is missing; not pushing {cfg.repo_id}")
                    self.log_signal.emit(
                        f"The dataset folder {root} is gone, so nothing was pushed. Delete "
                        f"the Hub repo too if it was half-created, then record again.", False)
                    error_occurred = True
                else:
                    logger.info(f"Pushing dataset to hub: {cfg.repo_id}")
                    try:
                        dataset.push_to_hub(tags=cfg.tags, private=cfg.private)
                        logger.info("Dataset pushed to hub successfully")
                    except Exception as e:
                        # Episodes on disk are the expensive part and they are safe; a failed
                        # upload is worth reporting in the window rather than ending the run.
                        logger.exception("push to hub failed")
                        self.log_signal.emit(
                            f"Recorded {episodes} episode(s) locally, but the upload failed:"
                            f"\n{e}\nThe data is at {root}.", False)
                        error_occurred = True

        if not error_occurred:
            log_say("Done", cfg.play_sounds)
            self.log_signal.emit("Done", True)
        return dataset

    @safe_disconnect
    def dry_run(
        self,
        robot: Union[ManipulatorRobot, TrossenAIMobile],
        cfg: TeleoperateControlConfig,
    ) -> None:
        """
        Execute a dry run of the robot's operation.

        This method performs a dry run of the robot's operation, allowing for
        teleoperation and testing without recording data. It handles camera display
        and teleoperation events.

        :param robot: The robot instance to operate.
        :param cfg: The configuration object for the dry run.
        :return: None
        """
        logger.info(f"Dry run started: fps={cfg.fps}, teleop_time_s={cfg.teleop_time_s}")
        if not robot.is_connected:  # Connect the robot if not already connected.
            if not self._connect_robot_with_timeout(robot):
                self.set_recording_ui_elements_enabled(True)
                return None
        self.ui.label_total_time.setText(f"{float(cfg.teleop_time_s)}s")
        self.control_loop(
            robot=robot,
            control_time_s=cfg.teleop_time_s,
            teleoperate=True,
            dataset=None,
            events=self.events,
            policy=None,
            fps=cfg.fps,
            display_fps=self.display_fps,
        )

        # Ensure progress bar shows 100% at completion
        self.worker.progress.emit(100)

        if has_method(robot, "teleop_safety_stop"):
            robot.teleop_safety_stop()
        robot.disconnect()
        logger.info("Dry run completed")

        self.initialize_image()  # Reinitialize the camera images.

        # Enable the UI elements after recording.
        self.set_recording_ui_elements_enabled(True)

        log_say("Done", True)
        self.log_signal.emit("Done", True)

    @safe_disconnect
    def reset_arm(
        self,
        robot: Union[ManipulatorRobot, TrossenAIMobile],
    ) -> None:
        """
        Reset the robot's arms to a safe state.

        Ensures the robot is connected, performs the reset operation, then
        disconnects and restores UI state. Emits status updates to the log.

        :param robot: The robot instance to reset.
        :return: None
        """
        logger.info("Reset arm started")
        if not robot.is_connected:  # Connect the robot if not already connected.
            if not self._connect_robot_with_timeout(robot):
                self.set_recording_ui_elements_enabled(True)
                return

        robot.disconnect()
        logger.info("Arms reset completed")

        # Enable the UI elements
        self.set_recording_ui_elements_enabled(True)

        log_say("Arms reset", True)
        self.log_signal.emit("Arms reset", True)

    def hardware_reset_cameras(self) -> None:
        """
        Perform a hardware reset of all connected cameras.

        This method triggers a hardware reset for each camera associated with the robot.
        It logs the reset action and handles any exceptions that may occur during the process.
        """
        logger.info("Hardware resetting cameras")
        self.set_logs("Resetting cameras...")
        # Query all devices connected to the robot.
        for device in rs.context().query_devices():
            try:
                serial_number = device.get_info(rs.camera_info.serial_number)
                camera_name = device.get_info(rs.camera_info.name)
                device.hardware_reset()  # Attempt to reset the camera hardware.
                logger.info(f"Camera '{camera_name}' (serial={serial_number}) reset successfully")
                self.set_logs(
                    f"Camera '{camera_name}' (Serial: {serial_number}) reset successfully.",
                    False,
                )  # Log success.
            except Exception as e:
                cam_id = camera_name if "camera_name" in locals() else "Unknown"
                logger.error(f"Failed to reset camera {cam_id}: {e}")
                self.set_logs(
                    f"Failed to reset camera {cam_id}: {e}",
                    False,
                )  # Log failure.

    def set_recording_ui_elements_enabled(self, enable: bool) -> None:
        """
        Set the enabled state of UI elements during recording.

        This method enables or disables all UI elements that should be
        inactive during recording/dry run operations.

        :param enable: True to enable UI elements, False to disable them.
        """
        for element in self.elements_disabled_while_recording:
            element.setEnabled(enable)
