import os
from pathlib import Path
import shutil
from site import getsitepackages
import subprocess
import sys

BLUE = "\033[94m"
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def run_command(command, cwd=None):
    """Execute a command and print it before running."""
    print(f"{GREEN} Executing: {' '.join(command)} {RESET}")
    subprocess.check_call(command, cwd=cwd)


def check_conda_env(env_name="trossen_ai_data_collection_env"):
    """Check if the specified conda environment is active and re-run the script in the environment if not."""
    active_env = os.environ.get("CONDA_DEFAULT_ENV")
    if active_env != env_name:
        print(
            f"{BLUE} Current conda environment is '{active_env}'. Switching to '{env_name}'... {RESET}"
        )
        conda_executable = os.environ.get("CONDA_EXE")
        if not conda_executable:
            raise OSError("Conda is not installed or not properly configured.")

        activate_script = Path(conda_executable).parent.parent / "etc" / "profile.d" / "conda.sh"
        if not activate_script.exists():
            raise OSError(f"Conda activation script not found at {activate_script}.")

        # Re-run the script in the correct conda environment
        command = f"source {activate_script} && conda activate {env_name} && post_install"
        print(f"{BLUE} Re-running the script in the '{env_name}' environment... {RESET}")
        run_command(["bash", "-c", command])
        sys.exit(0)  # Exit the current script since it's re-launched in the correct environment

    print(f"{GREEN} Running in the correct conda environment: '{active_env}' {RESET}")


def install_additional_packages():
    """Clone a specific commit of a GitHub repository and install its dependencies, and fix common issues."""

    # Step 1: Update package list and install build dependencies
    print(f"{BLUE} Updating package list... {RESET}")
    run_command(["sudo", "apt-get", "update"])
    run_command(
        [
            "sudo",
            "apt-get",
            "install",
            "-y",
            "build-essential",
            "cmake",
            "libavcodec-dev",
            "libavdevice-dev",
            "libavfilter-dev",
            "libavformat-dev",
            "libavutil-dev",
            "libswresample-dev",
            "libswscale-dev",
            "pkg-config",
            "python3-dev",
        ]
    )

    repo_url = "https://github.com/Interbotix/lerobot.git"
    clone_dir = (
        Path.home() / ".lerobot_trossen_ai_data_collection_ui"
    )  # Clone to the user's home directory
    branch = "trossen-ai"

    # Step 2: Clone the repository if it doesn't exist
    if not clone_dir.exists():
        print(f"{GREEN} Cloning repository from {repo_url} to {clone_dir}... {RESET}")
        run_command(["git", "clone", "-b", branch, repo_url, str(clone_dir)])
    else:
        print(
            f"{YELLOW} Repository already exists at {clone_dir}. Fetching the latest changes... {RESET}"
        )
        # Fetch the latest changes
        run_command(["git", "fetch"], cwd=str(clone_dir))
        # Checkout the specified branch
        run_command(["git", "checkout", branch], cwd=str(clone_dir))
        # Pull the latest changes
        run_command(["git", "pull"], cwd=str(clone_dir))

    # Step 3: Install the cloned repository with optional dependencies
    print(f"{BLUE} Installing lerobot with optional dependencies from {clone_dir}... {RESET}")
    run_command(
        [sys.executable, "-m", "pip", "install", "--no-binary=av", ".[trossen-ai]"],
        cwd=str(clone_dir),
    )

    # Step 4: Install ffmpeg using Conda
    try:
        print("Installing ffmpeg using Conda to fix video encoding errors...")
        run_command(["conda", "install", "-c", "conda-forge", "ffmpeg>=7.0", "-y"])

    except subprocess.CalledProcessError as e:
        print(f"Error installing ffmpeg via Conda: {e}. Continuing...")

    # Step 5: Install PySide6 using Conda
    try:
        print("Installing PySide6 using Conda...")
        run_command(["conda", "install", "-y", "-c", "conda-forge", "pyside6==6.8.0"])
    except subprocess.CalledProcessError as e:
        print(f"Error installing PySide6 via Conda: {e}. Continuing...")


def create_desktop_icon():
    """Create a desktop icon dynamically resolving the script path."""
    # Determine the site-packages directory
    site_packages_dir = next((Path(p) for p in getsitepackages() if Path(p).exists()), None)
    if not site_packages_dir:
        print("Site-packages directory not found.")
        return

    # Locate the application.sh script
    application_script_path = site_packages_dir / "trossen_ai_data_collection_ui/application.sh"
    if not application_script_path.exists():
        print(f"{RED} application.sh script not found at {application_script_path} {RESET}")
        return

    # Define the desktop file content
    desktop_file_content = f"""
        [Desktop Entry]
        Version=1.0
        Type=Application
        Name=Trossen AI Data Collection UI
        Exec=/bin/bash -c "{application_script_path}"
        Icon={Path.home()}/.local/share/icons/trossen_ai.svg
        Terminal=false
        Categories=Utility;
        """

    # Write the desktop file
    desktop_file_path = (
        Path.home() / ".local/share/applications/trossen_ai_data_collection_ui.desktop"
    )
    desktop_file_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"{BLUE} Creating desktop entry at {desktop_file_path} {RESET}")
    with open(desktop_file_path, "w") as desktop_file:
        desktop_file.write(desktop_file_content)

    # Copy the desktop file to the Desktop directory
    desktop_copy_path = Path.home() / "Desktop/trossen_ai_data_collection_ui.desktop"
    try:
        shutil.copy(desktop_file_path, desktop_copy_path)
        print(f"Desktop entry copied to {desktop_copy_path}")

        # Allow execution
        subprocess.run(["chmod", "a+x", str(desktop_copy_path)], check=True)
        print(f"Set executable permissions for {desktop_copy_path}")

    except Exception as e:
        print(f"{RED} Failed to configure desktop entry: {e} {RESET}")

    # Copy the application icon (make sure it's packaged with your app)
    app_icon_path = Path(__file__).resolve().parent / "resources/trossen_ai.svg"
    icon_file_path = Path.home() / ".local/share/icons/trossen_ai.svg"
    if app_icon_path.exists():
        print(f"Copying icon from {app_icon_path} to {icon_file_path}")
        icon_file_path.parent.mkdir(parents=True, exist_ok=True)
        icon_file_path.write_bytes(app_icon_path.read_bytes())
    else:
        print(f"{RED} Icon not found at {app_icon_path}, skipping icon copy. {RESET}")

    print(f"{GREEN} Desktop icon created at {desktop_file_path} {RESET}")


def main():
    check_conda_env("trossen_ai_data_collection_ui_env")
    install_additional_packages()
    create_desktop_icon()
    print(f"{GREEN} Post-installation tasks completed. {RESET}")


if __name__ == "__main__":
    main()
