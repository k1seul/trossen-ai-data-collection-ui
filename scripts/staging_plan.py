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

# Depth, up and down the mat. Kept OUT of the route on purpose: making it part of the route
# would turn six routes into thirty and multiply the session by five, for an axis that does not
# need its own cell to vary. Drawn independently and balanced against the route instead, it
# adds reach distance to the data at no cost in episodes -- and reach distance is exactly what
# three columns of a single depth leave fixed.
ROWS = ["far", "near"]

CELLS = [f"{z}-{r}" for z in ZONES for r in ROWS]

# The props physically on the bench. Distractors are drawn from HERE and not from the task's
# sentence variants, because splitting a sentence yields a bare colour: a task whose variants
# name a container turned "Pick up the red block and place it in the pot." into "red", and the
# sheet then asked for "red@R", which is not a thing anyone can put on a mat. It was read as
# "any red object" and an apple went down -- a prop the jaws cannot close around and the scene
# check has never heard of.
PROPS = [f"{c} {k}" for k in ("block", "tape roll")
         for c in ("red", "blue", "green", "yellow")]


def target_object(v: str) -> str:
    """The physical prop a variant names, whether it is a bare name or a whole instruction."""
    if " in the " not in v:
        return v.strip()
    head = v.rsplit(" in the ", 1)[0]
    return head.replace("Pick up the ", "").rsplit(" and place it", 1)[0].strip()

# Every route gets recorded. Which ones become "unseen" is a decision made later, on the
# recorded data -- the route an episode took is recoverable from where the gripper closes and
# next opens, so nothing has to be withheld at collection time. Withholding here would only
# throw away episodes and tangle the axes: an eval set recorded in its own session under its own
# lighting cannot separate an unseen route from an unseen room.
#
# What collection must deliver instead is COVERAGE and DECORRELATION: every route, every
# lighting condition, every object, in combinations that do not line up with one another.
# What this room can actually do. The overheads stay on: measured, the table sits at V 150
# with them and V 157 with the sub lamp added, but with them OFF the props stop being visible
# at all -- and an unseen-lighting axis built from conditions nobody can reproduce is an axis
# that gets approximated at the bench and then analysed as though it were real.
#
# Two levels rather than three. Fewer than hoped, but both are a switch someone can flick.
LIGHTING = ["A: overheads only", "B: overheads + sub lamp"]

NUDGES = ["none", "shoulder +5deg", "shoulder -5deg", "elbow +5deg", "wrist +10deg"]


def short(v: str) -> str:
    """A sentence variant is a whole instruction; label it by what actually varies.

    "Pick up the red block and place it in the pot." -> "red -> pot"
    """
    if " in the " not in v:
        return v
    tail = v.rsplit(" in the ", 1)[1]
    # The whole prop, not its colour: "green" is not something anyone can put on a mat, and a
    # sheet that said so got an apple instead of a green block.
    return f"{target_object(v)} -> {tail.strip('. ')}"


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
    p.add_argument("--props", nargs="+", default=PROPS,
                   help="the props physically on the bench, which distractors are drawn from. "
                        "Defaults to the task's own `props:` list, then to four blocks and "
                        "four tape rolls. Pass it only to override, since a sheet asking for a "
                        "prop nobody has gets improvised.")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--csv", type=Path, default=None)
    a = p.parse_args()

    task = load_task(a.config, a.task)
    variants = task["task_objects"]
    # The bench comes from the task itself when it says so, and the flag is the override. A
    # task and the props it needs belong together in one block; keeping them apart is how a
    # sheet comes to ask for something nobody has.
    props = list(a.props) if a.props is not PROPS else list(task.get("props") or PROPS)
    missing = sorted({target_object(v) for v in variants} - set(props))
    if missing:
        raise SystemExit(f"{a.task} names props that are not on the bench: {missing}\n"
                         f"  bench: {props}\n"
                         f"  Either put them out or pass --props with what is actually there.")
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
                # Exclude the target by the PHYSICAL PROP, not the sentence: with the
                # container named in the instruction, "red block -> bowl" and "red block ->
                # pot" are different variants and the same block, so comparing sentences would
                # put the target on the mat twice and make the instruction ambiguous.
                me = target_object(v)
                others = [p for p in props if p != me]
                rng.shuffle(others)
                picked = others[: a.distractors]

                # Alternate depth within each (object, route) group rather than sampling it,
                # for the same reason lighting is stratified: a shuffle left lighting 0.46
                # correlated with route, and depth drawn at random would land the same way.
                obj_row = ROWS[k % len(ROWS)]
                con_row = ROWS[(k + 1) % len(ROWS)]

                # Cells, not columns. A distractor in the target's column but at the other
                # depth is a different place, and naming only the column leaves the depth to
                # whoever is staging -- which is precisely the axis this sheet just gained.
                # They keep clear of the target's cell and the container's, so which cell is
                # occupied cannot give away which prop was named.
                free = [c for c in CELLS
                        if c not in (f"{obj}-{obj_row}", f"{con}-{con_row}")]
                rng.shuffle(free)
                dz = [free[i % len(free)] for i in range(len(picked))]
                # A task whose sentence names the container has the OTHER container on the mat
                # too, and it needs a zone -- otherwise the named one is the only place to put
                # anything and the word carries nothing, the way the colour did when a single
                # block was out.
                other_con = "(none)"
                if " in the " in v:
                    named = v.rsplit(" in the ", 1)[1].strip(". ")
                    alt = "pot" if named == "bowl" else "bowl"
                    taken = {f"{obj}-{obj_row}", f"{con}-{con_row}", *dz}
                    free_c = [c for c in CELLS if c not in taken] or \
                             [c for c in CELLS if c != f"{con}-{con_row}"]
                    other_con = f"{alt}@{rng.choice(free_c)}"
                rows.append({"variant": v, "object_zone": obj, "object_row": obj_row,
                             "container_zone": con, "container_row": con_row,
                             "route": f"{obj}->{con}", "other_container": other_con,
                             "distractors": "; ".join(
                                 f"{o}@{z}" for o, z in zip(picked, dz)) or "(none)",
                             "lighting": a.lighting[k % len(a.lighting)],
                             "start_nudge": rng.choice(NUDGES)})
    rng.shuffle(rows)                      # order of recording only; the design is already set
    order = ["variant", "episode", "object_zone", "object_row", "container_zone",
             "container_row", "route", "other_container", "distractors", "lighting",
             "start_nudge"]
    for i, r in enumerate(rows, 1):
        r["episode"] = i
    rows = [{k: r[k] for k in order} for r in rows]

    print(f"\n{a.task}: {len(variants)} objects x {len(rs)} routes x {a.episodes} = "
          f"{len(rows)} episodes")
    print(f"routes: {', '.join(f'{o}->{c}' for o, c in rs)}  (all recorded; hold some out "
          f"later, on the data)")
    print(f"zones: L / C / R across the mat, boundaries at -0.22 and +0.22 rad shoulder\n")

    hdr = (f"{'target':<22} {'ep':>4} {'obj':>4} {'depth':>5} {'dest':>5} {'depth':>5} {'route':>7}  "
           f"{'other cont.':<11} {'also on the mat':<24} {'lighting':<28} start")
    print(hdr); print("-" * len(hdr))
    for r in rows[:16]:
        print(f"{short(r['variant']):<22} {r['episode']:>4} {r['object_zone']:>4} "
              f"{r['object_row']:>5} {r['container_zone']:>5} {r['container_row']:>5} "
              f"{r['route']:>7}  {r['other_container']:<11} "
              f"{r['distractors']:<24} {r['lighting']:<28} {r['start_nudge']}")
    if len(rows) > 16:
        print(f"... {len(rows) - 16} more (use --csv for the whole sheet)")

    # Decorrelation is the whole job here: a post-hoc split can only isolate an axis that was
    # not entangled with another at collection time.
    print()
    _report_balance(rows, "container_zone", "variant", ZONES,
                    "the container's zone must not hint at which object was named")
    _report_balance(rows, "object_row", "route", ROWS,
                    "depth must not line up with the route, or an unseen-route split would "
                    "also be an unseen-distance split")
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
        key = short(r[against]) if against == "variant" else r[against]
        groups.setdefault(key, []).append(levels.index(r[field]))
    means = {k: sum(v) / len(v) for k, v in groups.items()}
    spread = (max(means.values()) - min(means.values())) if len(means) > 1 else 0.0
    ok = spread < 0.35
    print(f"{field} vs {against}: spread {spread:.2f} of {len(levels)} levels  "
          f"{'OK' if ok else 'TOO HIGH -- try another --seed'}")
    print(f"   ({why})")


if __name__ == "__main__":
    main()
