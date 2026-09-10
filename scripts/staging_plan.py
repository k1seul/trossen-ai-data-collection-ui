"""Print where to put things, episode by episode, so the randomization actually happens.

The last round's protocol asked for randomized object placement and got it: the object spans
about a radian of shoulder travel across 120 episodes. It said nothing about the container, so
the container never moved -- and because it sat on a different side for different fruits, the
policy learned "banana" to mean "carry right" instead of "find the bowl". An instruction to
"vary it" is not enough when the thing being varied is a physical object someone has to move
between takes; a sheet that names a cell is.

The mat is treated as a grid. Zone letters are columns left to right, numbers are rows near to
far, so "C2" is a place a person can find without measuring.

    python scripts/staging_plan.py --task pick_place_fruit_bowl --episodes 30
    python scripts/staging_plan.py --task pick_place_fruit_bowl --episodes 30 --csv plan.csv

Rules it enforces, each from something that went wrong:
  * the container moves every episode, over as many cells as the object
  * the container's position does not correlate with which object is named
  * object and container never land in the same cell, or adjacent ones
  * lighting rotates through the conditions you list instead of staying fixed
  * the start pose gets a small nudge, which the last dataset never had
"""
from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

import yaml

COLS = "ABCDE"          # left to right across the mat
ROWS = [1, 2, 3]        # near to far


def cells() -> list[str]:
    return [f"{c}{r}" for c in COLS for r in ROWS]


def adjacent(a: str, b: str) -> bool:
    return abs(COLS.index(a[0]) - COLS.index(b[0])) <= 1 and abs(int(a[1]) - int(b[1])) <= 1


def load_task(cfg: Path, name: str) -> dict:
    d = yaml.safe_load(cfg.read_text())
    for t in d["tasks"]:
        if t["task_name"] == name:
            return t
    raise SystemExit(f"{name!r} not in {cfg}. Available: "
                     + ", ".join(t["task_name"] for t in d["tasks"]))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--task", required=True)
    p.add_argument("--episodes", type=int, default=30, help="per object variant")
    p.add_argument("--config", type=Path,
                   default=Path(__file__).resolve().parents[1]
                   / "src/trossen_ai_data_collection_ui/configs/tasks.yaml")
    p.add_argument("--lighting", nargs="+",
                   default=["overheads on", "overheads off + lamp", "blinds open"],
                   help="conditions to rotate through; one lighting condition is what made the "
                        "policy fail in a dimmer room")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--csv", type=Path, default=None)
    a = p.parse_args()

    task = load_task(a.config, a.task)
    variants = task["task_objects"]
    rng = random.Random(a.seed)
    grid = cells()

    rows = []
    for v in variants:
        for i in range(a.episodes):
            while True:
                obj, con = rng.choice(grid), rng.choice(grid)
                if obj != con and not adjacent(obj, con):
                    break
            rows.append({
                "variant": v if len(v) < 30 else v[:27] + "...",
                "episode": i + 1,
                "object_cell": obj,
                "container_cell": con,
                "lighting": a.lighting[(len(rows)) % len(a.lighting)],
                "start_nudge": rng.choice(["none", "shoulder +5deg", "shoulder -5deg",
                                           "elbow +5deg", "wrist +10deg"]),
            })

    # Did the container end up correlated with the variant after all? Say so rather than
    # assuming: that correlation is the exact defect this sheet exists to prevent.
    by_variant = {}
    for r in rows:
        by_variant.setdefault(r["variant"], []).append(COLS.index(r["container_cell"][0]))
    means = {k: sum(v) / len(v) for k, v in by_variant.items()}
    spread = max(means.values()) - min(means.values())

    print(f"\n{a.task}: {len(variants)} variants x {a.episodes} episodes = {len(rows)} takes")
    print(f"mat grid: columns {COLS[0]}-{COLS[-1]} left to right, rows {ROWS[0]}-{ROWS[-1]} "
          f"near to far\n")
    hdr = f"{'variant':<30} {'ep':>3} {'object':>7} {'container':>10} {'lighting':<22} {'start'}"
    print(hdr); print("-" * len(hdr))
    for r in rows[: min(len(rows), 24)]:
        print(f"{r['variant']:<30} {r['episode']:>3} {r['object_cell']:>7} "
              f"{r['container_cell']:>10} {r['lighting']:<22} {r['start_nudge']}")
    if len(rows) > 24:
        print(f"... {len(rows) - 24} more (use --csv to write the whole sheet)")

    print(f"\ncontainer column mean per variant: "
          + ", ".join(f"{k.split()[-1]}={v:.1f}" for k, v in means.items()))
    print(f"spread across variants: {spread:.2f} columns "
          + ("(good: the container is not a hint about the object)" if spread < 1.0
             else "(TOO HIGH -- re-run with another --seed; the container is leaking the task)"))

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        print(f"\nwrote {a.csv}")


if __name__ == "__main__":
    main()
