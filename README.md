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

## Multi-task / multi-object data collection

Recording controls also include two buttons for managing episodes without
stopping the session:

- **FINISH EPISODE NEXT** — ends the current episode's recording early, saves
  it, and moves to the next episode.
- **FAIL EPISODE NEXT** — ends the current episode's recording early,
  discards the data (unlike RE-RECORD, it is not retried), and moves on.

To collect a family of tasks like "pick up `<object>`" (e.g. "pick up the red
block", "pick up the blue block") as ONE Hugging Face dataset repo instead of
one repo per object, use the **OBJECT / VARIANT** field next to the task
dropdown:

1. In a task's config (`tasks.yaml`), write `task_description` with an
   `{object}` placeholder and list dropdown presets under `task_objects`:

   ```yaml
   - task_name: "trossen_ai_stationary_pick_and_place"
     robot_model: "trossen_ai_stationary"
     task_description: "Pick up the {object} and place it in the bin."
     task_objects:
       - "red block"
       - "blue block"
       - "green cup"
     hf_user: "YourUser"
     ...
   ```

2. In the UI, the OBJECT / VARIANT combobox is populated from `task_objects`
   but stays editable — pick a preset or type any custom value. The label
   below it previews the exact instruction string that will be recorded.
3. Between episodes (session keeps running, same dataset), change the
   object field to switch what gets recorded next — e.g. record a batch of
   episodes for "red block", then edit the field to "blue block" and keep
   going. All episodes land in the same repo (`hf_user/task_name`), each
   tagged with its own instruction, which is exactly how `LeRobotDataset`
   (`meta/tasks.jsonl`) represents multi-task data — no need to fragment
   variants across separate repos.

If `task_description` has no `{object}` placeholder, the field/preview are
simply unused and behavior is identical to the original fixed-instruction UI.

The OBJECT / VARIANT combobox and the "Recorded so far: ..." label below the
instruction preview are populated by reading the selected task's dataset
directly (`~/.cache/huggingface/lerobot/<hf_user>/<task_name>/meta/`, the
same local cache the recording session writes to) — no separate history
file is kept. Concretely:

- The dropdown always includes `task_objects` presets, plus every
  object/variant already recorded for that repo (so you can pick up a
  variant you used in a previous session instead of retyping it), and stays
  editable for typing a brand new one.
- Selecting a task defaults the field to whichever variant was recorded
  most recently, so an interrupted session can be resumed as-is.
- The history label shows a live episode count per variant (including
  presets with 0 so far), updated after every episode saved in the current
  session.

Since `~/.trossen/trossen_ai_data_collection/configs/tasks.yaml` is only
seeded from this repo's `configs/tasks.yaml` on first run, add the
`task_objects`/`{object}` fields to your existing persistent `tasks.yaml`
manually (via the app's `Edit > Task Configuration` menu, or by editing the
file directly) if you already ran the app before this feature existed.

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
