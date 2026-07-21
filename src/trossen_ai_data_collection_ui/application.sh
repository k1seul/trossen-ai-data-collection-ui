#!/bin/bash

# Path to your conda installation
CONDA_PATH="$HOME/miniconda3"

# Detect Ubuntu version
UBUNTU_VERSION=""
if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    if [[ "$ID" == "ubuntu" ]]; then
        UBUNTU_VERSION="${VERSION_ID%%.*}"
    fi
fi

# Activate the conda environment
source "$CONDA_PATH/bin/activate" trossen_ai_data_collection_ui_env

# Configure LD_PRELOAD for Ubuntu 24+ where the system libstdc++ must take
# precedence over the one bundled with conda to avoid symbol-version conflicts.
# Ubuntu 22 ships a compatible version so no override is needed there.
# On other distros or architectures we skip this entirely.
LIBSTDCPP_PATH="/usr/lib/x86_64-linux-gnu/libstdc++.so.6"

if [[ "$UBUNTU_VERSION" -ge 24 ]] 2>/dev/null; then
    if [[ -f "$LIBSTDCPP_PATH" ]]; then
        echo "[INFO] Ubuntu ${UBUNTU_VERSION} - LD_PRELOAD enabled using: $LIBSTDCPP_PATH"
        export LD_PRELOAD="$LIBSTDCPP_PATH"
    else
        echo "[WARN] Ubuntu ${UBUNTU_VERSION} - LD_PRELOAD not set: $LIBSTDCPP_PATH not found; running without LD_PRELOAD" >&2
    fi
else
    echo "[INFO] Ubuntu ${UBUNTU_VERSION:-unknown} - LD_PRELOAD not required"
fi

# Run the executable
trossen_ai_data_collection_ui
