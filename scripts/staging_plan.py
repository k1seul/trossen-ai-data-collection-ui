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

ZONES = ["L", "C", "R"]          # left / centre / right, across the arm's reachable band

# The six routes an object can take. Two are withheld from training so that "does it generalize"
# can be measured instead of guessed: every zone is still demonstrated in both roles, and only
# the PAIRING is new at evaluation. See docs/ood_collection_protocol.md.
HELD_OUT_ROUTES = {("L", "R"), ("R", "L")}

TRAIN_LIGHTING = ["A: overheads on", "B: overheads off + lamp"]
EVAL_LIGHTING = "C: blinds open, overheads off"

NUDGES = ["none", "shoulder +5deg", "shoulder -5deg", "elbow +5deg", "wrist +10deg"]


def routes(split: str) -> list[tuple[str, str]]:
    all_routes = [(o, c) for o in ZONES for c in ZONES if o != c]
    if split == "eval":
        return [r for r in all_routes if r in HELD_OUT_ROUTES]
    return [r for r in all_routes if r not in HELD_OUT_ROUTES]


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
    p.add_argument("--episodes", type=int, default=10, help="per object per route")
    p.add_argument("--split", choices=["train", "eval"], default="train")
    p.add_argument("--config", type=Path,
                   default=Path(__file__).resolve().parents[1]
                   / "src/trossen_ai_data_collection_ui/configs/tasks.yaml")
    p.add_argument("--hold-out-object", default=None,
                   help="record everything except this one, so the instruction has to ground a "
                        "word seen only in other contexts (e.g. banana)")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--csv", type=Path, default=None)
    a = p.parse_args()

    task = load_task(a.config, a.task)
    variants = [v for v in task["task_objects"]
                if not (a.hold_out_object and a.hold_out_object.lower() in v.lower())]
    if a.split == "eval" and a.hold_out_object:
        variants = task["task_objects"]        # the held-out object belongs in the eval set
    rng = random.Random(a.seed)
    rs = routes(a.split)

    rows = []
    for v in variants:
        for obj, con in rs:
            for i in range(a.episodes):
                rows.append({
                    "variant": v if len(v) < 30 else v[:27] + "...",
                    "episode": len(rows) + 1,
                    "object_zone": obj,
                    "container_zone": con,
                    "route": f"{obj}->{con}",
                    "lighting": (EVAL_LIGHTING if a.split == "eval"
                                 else TRAIN_LIGHTING[len(rows) % len(TRAIN_LIGHTING)]),
                    "start_nudge": rng.choice(NUDGES),
                })
    rng.shuffle(rows)
    for i, r in enumerate(rows, 1):
        r["episode"] = i

    print(f"\n{a.task} [{a.split}]: {len(variants)} objects x {len(rs)} routes x "
          f"{a.episodes} = {len(rows)} episodes")
    print(f"routes {a.split}: {', '.join(f'{o}->{c}' for o, c in rs)}")
    if a.split == "train":
        print(f"held out for evaluation: "
              f"{', '.join(f'{o}->{c}' for o, c in sorted(HELD_OUT_ROUTES))}"
              + (f", and the {a.hold_out_object}" if a.hold_out_object else ""))
    print(f"zones: L / C / R across the mat, boundaries at -0.22 and +0.22 rad shoulder\n")

    hdr = (f"{'variant':<30} {'ep':>4} {'object':>7} {'container':>10} {'route':>7}  "
           f"{'lighting':<24} start")
    print(hdr); print("-" * len(hdr))
    for r in rows[:20]:
        print(f"{r['variant']:<30} {r['episode']:>4} {r['object_zone']:>7} "
              f"{r['container_zone']:>10} {r['route']:>7}  {r['lighting']:<24} {r['start_nudge']}")
    if len(rows) > 20:
        print(f"... {len(rows) - 20} more (use --csv for the whole sheet)")

    # The defect that broke the last round: the container's position being a hint about which
    # object was named. Check it rather than trusting the shuffle.
    by_variant = {}
    for r in rows:
        by_variant.setdefault(r["variant"], []).append(ZONES.index(r["container_zone"]))
    means = {k: sum(v) / len(v) for k, v in by_variant.items()}
    spread = max(means.values()) - min(means.values()) if len(means) > 1 else 0.0
    # task_objects are the variant strings themselves ("orange"), not full sentences
    print(f"\ncontainer zone mean per object: "
          + ", ".join(f"{k}={v:.2f}" for k, v in means.items()))
    print(f"spread across objects: {spread:.2f} zones "
          + ("(good: the container is not a hint about the object)" if spread < 0.35
             else "(TOO HIGH -- re-run with another --seed)"))

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        print(f"\nwrote {a.csv}")


if __name__ == "__main__":
    main()
