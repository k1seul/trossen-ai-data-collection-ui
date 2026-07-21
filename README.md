# Trossen AI Data Collection UI (local fork)

A `uv`-managed, self-contained fork of the [Trossen AI Data Collection UI](https://docs.trossenrobotics.com/trossen_arm/main/tutorials/trossen_data_collection_ui.html)
for editing and running from this project directory, without relying on a
global conda environment.

Source code lives in [`src/trossen_ai_data_collection_ui/`](src/trossen_ai_data_collection_ui/)
and was vendored from the upstream `trossen-ai-data-collection-ui` PyPI package
(v1.2.2) so it can be modified directly. It depends on the
[`Interbotix/lerobot`](https://github.com/Interbotix/lerobot) fork (`trossen-ai` branch).

## Prerequisites

- Linux (tested on aarch64, e.g. NVIDIA DGX Spark / GB10)
- [`uv`](https://docs.astral.sh/uv/) installed
- `ffmpeg` on `PATH` (used by lerobot to encode episode videos):

  ```bash
  sudo apt-get update && sudo apt-get install -y ffmpeg
  ```

- Robot arm access: the [Trossen ARM driver](https://docs.trossenrobotics.com/trossen_arm/)
  requires your user to have permission to access the arms over the network/serial
  interface as usual (see upstream hardware setup docs).

## Setup

```bash
uv sync
```

This creates a `.venv` in this directory with Python 3.10 and installs all
dependencies (PySide6, OpenCV, lerobot + trossen extras, trossen_arm SDK, etc.)
directly from PyPI/git — no conda required.

## Running

```bash
uv run trossen_ai_data_collection_ui
```

On first run, default configs are copied to `~/.trossen/trossen_ai_data_collection/configs/`.
Edit robot/task configuration either through the app's `Edit` menu or directly in
that directory (see upstream docs for the YAML schema).

## Making changes

Since the UI source is vendored under `src/trossen_ai_data_collection_ui/`, edit it
directly and re-run with `uv run trossen_ai_data_collection_ui` — the package is
installed in editable mode so changes take effect immediately.

Key files:

- `src/trossen_ai_data_collection_ui/ui/main_window.py` — main window/controller logic
- `src/trossen_ai_data_collection_ui/workers/recorder.py` — recording/episode worker thread
- `src/trossen_ai_data_collection_ui/resources/app.ui` / `app.py` — Qt Designer UI + generated code
- `src/trossen_ai_data_collection_ui/configs/` — default robot/task YAML configs

## Updating the `lerobot` dependency

`lerobot` is pulled from `Interbotix/lerobot@trossen-ai` via `[tool.uv.sources]`
in `pyproject.toml`. To pick up upstream changes:

```bash
uv lock --upgrade-package lerobot
uv sync
```

## Notes

- This is a fork of Trossen Robotics' BSD-3-Clause licensed application; see [LICENSE](LICENSE).
- Original upstream tutorial: https://docs.trossenrobotics.com/trossen_arm/main/tutorials/trossen_data_collection_ui.html
