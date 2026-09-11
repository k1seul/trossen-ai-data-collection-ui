"""Put the recorded dataset on the Hub, from a process nobody is about to close.

The UI pushes at the end of a session and every session so far lost it: the upload starts, the
window looks idle because an upload looks exactly like an idle window, and it gets closed a
second later. The Hub held seven episodes against a hundred and nine on disk.

    python scripts/push_dataset.py            # what it would do
    python scripts/push_dataset.py --apply

Deletes what is no longer local as well as adding what is new, so a Hub copy cannot keep files
from a numbering that episodes were removed from.
"""
import argparse
import json
import pathlib

from huggingface_hub import HfApi

DEFAULT = pathlib.Path.home() / ".cache/huggingface/lerobot/k1seul/pick_specific_item_from_clutter"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--dataset", type=pathlib.Path, default=DEFAULT)
    p.add_argument("--repo-id", default="k1seul/pick_specific_item_from_clutter")
    p.add_argument("--apply", action="store_true")
    a = p.parse_args()

    info = json.loads((a.dataset / "meta/info.json").read_text())
    api = HfApi()
    print(f"  local: {info['total_episodes']} episodes, {info['total_frames']} frames, "
          f"{info['total_tasks']} instructions")
    try:
        remote = json.loads(pathlib.Path(api.hf_hub_download(
            a.repo_id, "meta/info.json", repo_type="dataset",
            force_download=True)).read_text())
        print(f"  hub  : {remote['total_episodes']} episodes, {remote['total_frames']} frames")
    except Exception:
        print("  hub  : nothing there yet")
    if not a.apply:
        print("\n  nothing sent. Pass --apply.")
        return 0
    api.upload_folder(
        repo_id=a.repo_id, repo_type="dataset", folder_path=str(a.dataset),
        delete_patterns=["data/**", "videos/**", "meta/**"],
        commit_message=f"{info['total_episodes']} episodes, {info['total_frames']} frames",
    )
    print("  uploaded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
