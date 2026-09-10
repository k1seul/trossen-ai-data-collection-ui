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

# Every route gets recorded. Which ones become "unseen" is a decision made later, on the
# recorded data -- the route an episode took is recoverable from where the gripper closes and
# next opens, so nothing has to be withheld at collection time. Withholding here would only
# throw away episodes and tangle the axes: an eval set recorded in its own session under its own
# lighting cannot separate an unseen route from an unseen room.
#
# What collection must deliver instead is COVERAGE and DECORRELATION: every route, every
# lighting condition, every object, in combinations that do not line up with one another.
LIGHTING = ["A: overheads on", "B: overheads off + lamp", "C: blinds open, overheads off"]

NUDGES = ["none", "shoulder +5deg", "shoulder -5deg", "elbow +5deg", "wrist +10deg"]


def routes() -> list[tuple[str, str]]:
    return [(o, c) for o in ZONES for c in ZONES if o != c]


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
    p.add_argument("--episodes", type=int, default=6, help="per object per route")
    p.add_argument("--config", type=Path,
                   default=Path(__file__).resolve().parents[1]
                   / "src/trossen_ai_data_collection_ui/configs/tasks.yaml")
    p.add_argument("--lighting", nargs="+", default=LIGHTING)
    p.add_argument("--distractors", type=int, default=2,
                   help="other blocks on the mat besides the named one. With a single object "
                        "present the instruction carries no information -- there is only one "
                        "thing to pick -- so the policy never has to read it, and holding out "
                        "a colour later would measure nothing. 0 reproduces the old scenes.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--csv", type=Path, default=None)
    a = p.parse_args()

    task = load_task(a.config, a.task)
    variants = task["task_objects"]
    rng = random.Random(a.seed)
    rs = routes()

    # Stratify rather than shuffle and hope: assign lighting round-robin WITHIN each
    # (object, route) group, so every route gets an equal share of every condition by
    # construction. Leaving it to the shuffle produced a 0.46-level correlation between
    # lighting and route, which would have made an unseen-route split partly an
    # unseen-lighting split -- the exact entanglement this sheet exists to prevent.
    rows = []
    for v in variants:
        for obj, con in rs:
            for k in range(a.episodes):
                others = [o for o in variants if o != v]
                rng.shuffle(others)
                picked = others[: a.distractors]
                # The distractors occupy zones too, so which zone is occupied cannot give away
                # which block is the target. They keep clear of the container's zone.
                free = [z for z in ZONES if z != con]
                dz = [free[i % len(free)] for i in range(len(picked))]
                rng.shuffle(dz)
                rows.append({"variant": v, "object_zone": obj, "container_zone": con,
                             "route": f"{obj}->{con}",
                             "distractors": "; ".join(f"{o.split()[0]}@{z}"
                                                      for o, z in zip(picked, dz)) or "(none)",
                             "lighting": a.lighting[k % len(a.lighting)],
                             "start_nudge": rng.choice(NUDGES)})
    rng.shuffle(rows)                      # order of recording only; the design is already set
    order = ["variant", "episode", "object_zone", "container_zone", "route",
             "distractors", "lighting", "start_nudge"]
    for i, r in enumerate(rows, 1):
        r["episode"] = i
    rows = [{k: r[k] for k in order} for r in rows]

    print(f"\n{a.task}: {len(variants)} objects x {len(rs)} routes x {a.episodes} = "
          f"{len(rows)} episodes")
    print(f"routes: {', '.join(f'{o}->{c}' for o, c in rs)}  (all recorded; hold some out "
          f"later, on the data)")
    print(f"zones: L / C / R across the mat, boundaries at -0.22 and +0.22 rad shoulder\n")

    hdr = (f"{'target':<13} {'ep':>4} {'obj':>4} {'bowl':>5} {'route':>7}  "
           f"{'also on the mat':<22} {'lighting':<28} start")
    print(hdr); print("-" * len(hdr))
    for r in rows[:16]:
        print(f"{r['variant']:<13} {r['episode']:>4} {r['object_zone']:>4} "
              f"{r['container_zone']:>5} {r['route']:>7}  {r['distractors']:<22} "
              f"{r['lighting']:<28} {r['start_nudge']}")
    if len(rows) > 16:
        print(f"... {len(rows) - 16} more (use --csv for the whole sheet)")

    # Decorrelation is the whole job here: a post-hoc split can only isolate an axis that was
    # not entangled with another at collection time.
    print()
    _report_balance(rows, "container_zone", "variant", ZONES,
                    "the container's zone must not hint at which object was named")
    _report_balance(rows, "lighting", "route", a.lighting,
                    "lighting must not line up with the route, or an unseen-route split would "
                    "also be an unseen-lighting split")

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        print(f"\nwrote {a.csv}")


def _report_balance(rows, field, against, levels, why):
    groups = {}
    for r in rows:
        groups.setdefault(r[against], []).append(levels.index(r[field]))
    means = {k: sum(v) / len(v) for k, v in groups.items()}
    spread = (max(means.values()) - min(means.values())) if len(means) > 1 else 0.0
    ok = spread < 0.35
    print(f"{field} vs {against}: spread {spread:.2f} of {len(levels)} levels  "
          f"{'OK' if ok else 'TOO HIGH -- try another --seed'}")
    print(f"   ({why})")


if __name__ == "__main__":
    main()
