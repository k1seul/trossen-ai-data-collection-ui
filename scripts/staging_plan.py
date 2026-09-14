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
import hashlib
import json
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


# ---------------------------------------------------------------- where, exactly

FRAMING = Path.home() / ".trossen" / "trossen_ai_data_collection" / "framing" / "workspace.json"
MM_PER_PX = 25.0 / 27.0

# The bowl may not come closer than this to the object. Physical: with the container beside it
# the jaws cannot get round the object. The last dataset never came closer than 104 mm and its
# 5th percentile was 128.
MIN_TARGET_BOWL_MM = 130.0

# Margin from the edge of the hand-marked reachable quad, so a prop is not half off it.
REACH_MARGIN_PX = 18


def reachable(path: Path = FRAMING):
    """The quad the arm was actually pushed to, and the crop, from the framing file.

    The last dataset put every target inside 31% of the crop while 43% is reachable -- a 61 mm
    band under the arm was never used once. Naming a cell leaves the spot inside it to whoever
    is staging, and they chose the middle every time. So the sheet names the spot.
    """
    meta = json.loads(Path(path).read_text())
    marks = {m["name"]: (float(m["x"]), float(m["y"])) for m in meta.get("marks", [])
             if "x" in m}
    need = ("top-left", "top-right", "bottom-right", "bottom-left")
    if not all(n in marks for n in need):
        return None, None
    quad = [marks[n] for n in need]

    # The marks are where the arm was pushed to by hand, and they came out conservative: 13 of
    # the 95 recorded targets sat outside them, as far as 21 mm past the near edge, and the arm
    # picked every one of them up. Taking the hull of the marks AND the positions that demonstrably
    # worked uses both kinds of evidence instead of throwing one away.
    done = Path.home() / ".trossen" / "trossen_ai_data_collection" / "plan" / "target_map.json"
    if done.exists():
        try:
            pts = [(t["x"], t["y"]) for t in json.loads(done.read_text()).get("targets", [])]
        except (ValueError, KeyError):
            pts = []
        if pts:
            quad = _hull(quad + pts)
    return quad, meta.get("crop_main")


def _hull(points):
    """Convex hull, monotone chain -- so this file keeps needing nothing but the stdlib."""
    pts = sorted(set((round(x, 2), round(y, 2)) for x, y in points))
    if len(pts) < 3:
        return pts
    def half(ps):
        out = []
        for q in ps:
            while len(out) >= 2 and \
                    (out[-1][0] - out[-2][0]) * (q[1] - out[-2][1]) - \
                    (out[-1][1] - out[-2][1]) * (q[0] - out[-2][0]) <= 0:
                out.pop()
            out.append(q)
        return out[:-1]
    return half(pts) + half(pts[::-1])


def _inside(poly, x, y, margin=0.0) -> bool:
    """Point in quad, with a margin, by the sign of the cross products along each edge."""
    n = len(poly)
    signs = []
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        ex, ey = bx - ax, by - ay
        L = (ex * ex + ey * ey) ** 0.5 or 1.0
        # distance from the edge, positive on the inside for a clockwise quad
        signs.append(((x - ax) * ey - (y - ay) * ex) / L)
    return all(v >= margin for v in signs) or all(-v >= margin for v in signs)


def spots(poly, rng, n: int, *, cols: int = 6, rows: int = 4, margin=REACH_MARGIN_PX):
    """n places inside the quad, spread by construction rather than by luck.

    Sampling uniformly at random clumps; rotating through a grid of sub-cells and jittering
    inside each one covers the whole area for any n, which is the point -- the axis this is
    being widened for is position.
    """
    xs = [q[0] for q in poly]; ys = [q[1] for q in poly]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cells = [(c, r) for r in range(rows) for c in range(cols)]
    rng.shuffle(cells)
    out = []
    i = 0
    while len(out) < n and i < n * 200:
        c, r = cells[len(out) % len(cells)]
        x = x0 + (x1 - x0) * (c + rng.random()) / cols
        y = y0 + (y1 - y0) * (r + rng.random()) / rows
        i += 1
        if _inside(poly, x, y, margin):
            out.append((round(x, 1), round(y, 1)))
    return out


def spot_in_cell(poly, crop, zone: str, row: str, rng, margin=REACH_MARGIN_PX,
                 tries: int = 400):
    """A place inside one cell that the arm can reach, chosen anywhere in it but the middle.

    The cell is the design's; this only decides where within it. Rejection sampling because the
    cell is a rectangle and the reachable region is a hull, and their intersection has no useful
    closed form -- with a few hundred tries it either finds one or the cell genuinely has none.
    """
    if not crop:
        return None
    x, y, side = crop
    col = {"L": 0, "C": 1, "R": 2}.get(zone)
    if col is None:
        return None
    x0 = x + side * col / 3.0
    x1 = x + side * (col + 1) / 3.0
    top_y = 102.0
    mid = (max(y, top_y) + y + side) / 2.0
    y0, y1 = (max(y, top_y), mid) if row == "far" else (mid, y + side)
    for _ in range(tries):
        px = rng.uniform(x0 + margin, x1 - margin)
        py = rng.uniform(y0 + margin, y1 - margin)
        if _inside(poly, px, py, margin):
            return (round(px, 1), round(py, 1))
    return None


def far_enough(a, b, mm: float) -> bool:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 * MM_PER_PX >= mm


def cell_of(xy, crop, top: float = 102.0) -> str:
    """The cell a spot falls in, so the existing zone columns stay true to the coordinates."""
    if not crop:
        return "?"
    x, y, side = crop
    col = "LCR"[min(2, max(0, int((xy[0] - x) / side * 3)))]
    mid = (max(y, top) + y + side) / 2
    return f"{col}-{'far' if xy[1] < mid else 'near'}"


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

# Fixed, on purpose. Five degrees of shoulder is the one part of staging a person cannot set
# by hand, so a start-pose axis does not become five conditions -- it becomes unmeasured
# variance in the follower pose that every episode records, spread across an already thin
# budget. LIBERO, which this is being compared against, starts from one pose too.
#
# The variance worth having is in the scene: object cell, container cell, distractors,
# lighting. Those are all things a hand can place and a camera can check. This one was neither.
NUDGES = ["none"]


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
    p.add_argument("--spots", action="store_true",
                   help="name the exact spot for every prop, in pixels of the camera frame, "
                        "sampled over the quad the arm was actually pushed to. Naming a cell "
                        "leaves the place inside it to whoever is staging, and last time they "
                        "chose the middle every time: every target landed inside 31%% of the "
                        "crop while 43%% is reachable, and a 61 mm band under the arm was "
                        "never used once.")
    p.add_argument("--eval-frac", type=float, default=0.15,
                   help="fraction of rows marked split=eval. Recorded in the same session, "
                        "under the same conditions, and held out of training -- which is the "
                        "only way an episode-level generalization number means anything. The "
                        "last round had none and its held-out set was 90%% training data.")
    p.add_argument("--per-object", type=int, default=None,
                   help="aim for this many episodes of EACH object once what is already "
                        "recorded is counted, instead of a flat number each. Five new props "
                        "beside six that already have thirty episodes would otherwise get "
                        "twelve apiece, and 'the policy cannot handle the new objects' would "
                        "be a statement about how much data they got.")
    p.add_argument("--recorded", type=Path,
                   default=Path.home() / ".trossen" / "trossen_ai_data_collection" / "plan"
                   / "episodes",
                   help="[--per-object] where the already-recorded episode configs live")
    p.add_argument("--second-object", action="store_true",
                   help="[pick_two_in_order] name a second object and its spot")
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

    # How many of each object are already in the can, so the sheet can level them up.
    already: dict = {}
    if a.per_object:
        for q in sorted(Path(a.recorded).glob("*.json")):
            try:
                m = json.loads(q.read_text())
            except ValueError:
                continue
            t = next((x for x in m.get("scene", []) if x.get("role") == "target"), None)
            if t:
                already[t["object"]] = already.get(t["object"], 0) + 1
        print(f"\nalready recorded: " + ", ".join(
            f"{k} {v}" for k, v in sorted(already.items())) or "(nothing)")

    # Stratify rather than shuffle and hope: assign lighting round-robin WITHIN each
    # (object, route) group, so every route gets an equal share of every condition by
    # construction. Leaving it to the shuffle produced a 0.46-level correlation between
    # lighting and route, which would have made an unseen-route split partly an
    # unseen-lighting split -- the exact entanglement this sheet exists to prevent.
    rows = []
    # Counts groups so each starts the two-level axes on a different phase. Round-robin from
    # zero every time is only balanced when the group size is a multiple of the number of
    # levels: at three episodes per group it gave lighting 2:1 and depth 2:1, quietly, in a
    # sheet whose whole purpose is that those are even.
    for vi, v in enumerate(variants):
        for ri, (obj, con) in enumerate(rs):
            # Phase from BOTH indices. A plain group counter advances once per (object, route)
            # pair, so its period is the number of routes -- every group of a given route then
            # shares a phase, and with three episodes per group that route got two thirds of
            # one lighting condition while the sheet's totals looked perfectly even. Summing
            # the two indices makes the phase alternate along both.
            g = vi + ri
            # With --per-object the count is what this object still needs, spread over the
            # routes; without it, the flat number per (object, route) as before.
            if a.per_object:
                need = max(0, a.per_object - already.get(target_object(v), 0))
                # Which routes get the remainder has to ROTATE with the object. Handing the
                # leftovers to the first few routes every time meant an object needing only
                # three episodes appeared on three routes and never the other three -- and
                # since the container's zone comes from the route, its zone then told you
                # which object had been named. The sheet's own checker read 1.42 of 3 levels.
                n_here = need // len(rs) + (1 if (ri - vi) % len(rs) < need % len(rs) else 0)
            else:
                n_here = a.episodes
            for k in range(n_here):
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
                obj_row = ROWS[(k + g) % len(ROWS)]
                con_row = ROWS[(k + g + 1) % len(ROWS)]

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
                second = ""
                if a.second_object:
                    # The second object comes from the distractors, so the mat holds exactly
                    # what the first task's mat holds and only the sentence is longer.
                    second = picked[0] if picked else (others[0] if others else "")
                rows.append({"variant": v, "object2": second,
                             "object_zone": obj, "object_row": obj_row,
                             "container_zone": con, "container_row": con_row,
                             "route": f"{obj}->{con}", "other_container": other_con,
                             "distractors": "; ".join(
                                 f"{o}@{z}" for o, z in zip(picked, dz)) or "(none)",
                             "lighting": a.lighting[(k + g) % len(a.lighting)],
                             "start_nudge": rng.choice(NUDGES)})
    rng.shuffle(rows)                      # order of recording only; the design is already set
    # Spots, and the split. Both are decided after the shuffle so neither correlates with
    # anything the design balanced.
    poly, crop = reachable()
    if a.spots and poly:
        # The spot is drawn INSIDE the cell the design already chose, never the other way
        # round. Sampling coordinates freely and recomputing the cells from them looked
        # equivalent and was not: it discarded every balance this generator exists to enforce
        # -- lighting stratified within each (object, route) group, depth alternating, the
        # container's zone independent of which object was named -- and the sheet's own checker
        # caught all three. Worse, free coordinates produced L->L and C->C routes, and a route
        # that stays in one column is the thing 109 episodes never did: putting it in TRAINING
        # would quietly spend an OOD axis.
        #
        # What is gained is what was actually wrong: within its cell, the spot is anywhere the
        # arm can reach rather than the middle, which is where a person puts things.
        for r in rows:
            tgt = spot_in_cell(poly, crop, r["object_zone"], r["object_row"], rng)
            bowl = None
            for _ in range(60):
                cand = spot_in_cell(poly, crop, r["container_zone"], r["container_row"], rng)
                if cand is None:
                    break
                if tgt is None or far_enough(tgt, cand, MIN_TARGET_BOWL_MM):
                    bowl = cand
                    break
            r["target_xy"] = f"{tgt[0]},{tgt[1]}" if tgt else ""
            r["container_xy"] = f"{bowl[0]},{bowl[1]}" if bowl else ""
        missing = sum(1 for r in rows if not r["target_xy"] or not r["container_xy"])
        if missing:
            print(f"\n{missing} of {len(rows)} rows have a cell with no reachable spot far "
                  f"enough from the other -- those keep the cell name and no crosshair.")
    elif a.spots:
        raise SystemExit(f"--spots needs the marked workspace at {FRAMING}; "
                         f"run mark_workspace.sh first")
    else:
        for r in rows:
            r["target_xy"] = r["container_xy"] = ""

    # What is already recorded, in the same shape as a sheet row, so the balance checks below
    # see the dataset rather than only the new sheet.
    prior = []
    if a.per_object:
        for q in sorted(Path(a.recorded).glob("*.json")):
            try:
                m = json.loads(q.read_text())
            except ValueError:
                continue
            t = next((x for x in m.get("scene", []) if x.get("role") == "target"), None)
            c = next((x for x in m.get("scene", []) if x.get("role") == "container"), None)
            if not (t and c):
                continue
            oz, _, orow = t["zone"].partition("-")
            cz, _, crow = c["zone"].partition("-")
            lg = m.get("lighting") or ""
            prior.append({"variant": t["object"], "object_zone": oz,
                          "object_row": orow or "far", "container_zone": cz,
                          "container_row": crow or "far", "route": f"{oz}->{cz}",
                          "lighting": lg if lg in a.lighting else a.lighting[0]})

    n_eval = int(round(len(rows) * a.eval_frac))
    for i, r in enumerate(rows):
        r["split"] = "eval" if i < n_eval else "train"

    order = ["variant", "object2", "episode", "split", "object_zone", "object_row",
             "container_zone", "container_row", "target_xy", "container_xy",
             "route", "other_container", "distractors", "lighting", "start_nudge"]

    # A fingerprint of the plan, carried on every row and copied into each episode's config.
    # Row numbers only mean something within one sheet: regenerate it and row 8 is a different
    # scene, so a session that resumed "at row 8" would silently record the wrong thing and
    # count it as progress. With this, a sheet that is not the one an episode was recorded
    # against is recognisable rather than assumed.
    sheet_id = hashlib.sha1(
        json.dumps([[r.get(k) for k in order if k != "episode"] for r in rows],
                   sort_keys=True).encode()
    ).hexdigest()[:12]
    for r in rows:
        r["sheet_id"] = sheet_id
    order = order + ["sheet_id"]
    for i, r in enumerate(rows, 1):
        r["episode"] = i
    rows = [{k: r[k] for k in order} for r in rows]

    print(f"\n{a.task}: {len(variants)} objects, {len(rows)} episodes"
          + (f" (levelling every object to {a.per_object})" if a.per_object
             else f" = {len(rs)} routes x {a.episodes}"))
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
                    "the container's zone must not hint at which object was named", prior=prior)
    _report_balance(rows, "object_row", "route", ROWS,
                    "depth must not line up with the route, or an unseen-route split would "
                    "also be an unseen-distance split", prior=prior)
    _report_balance(rows, "lighting", "route", a.lighting,
                    "lighting must not line up with the route, or an unseen-route split would "
                    "also be an unseen-lighting split", prior=prior)

    if a.csv:
        with open(a.csv, "w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]))
            w.writeheader(); w.writerows(rows)
        print(f"\nwrote {a.csv}")


def _report_balance(rows, field, against, levels, why, prior=()):
    """How far apart the groups sit on this axis, over the WHOLE dataset.

    prior is what has already been recorded. A top-up sheet cannot balance on its own -- an
    object that needs three more episodes cannot cover six routes -- and judging it alone
    reported 0.38 on a combination that comes to 0.09 once the 108 episodes already in the can
    are counted. The thing that has to be balanced is the data the model trains on, not the
    sheet that was printed last.
    """
    groups = {}
    for r in list(prior) + list(rows):
        key = short(r[against]) if against == "variant" else r[against]
        groups.setdefault(key, []).append(levels.index(r[field]))
    means = {k: sum(v) / len(v) for k, v in groups.items()}
    spread = (max(means.values()) - min(means.values())) if len(means) > 1 else 0.0
    # A two-level axis at spread 0.33 is a 2:1 split inside some group, which is exactly the
    # entanglement these checks exist to catch -- and 0.35 waved it through.
    ok = spread < 0.15
    scope = f" (this sheet plus the {len(prior)} already recorded)" if prior else ""
    print(f"{field} vs {against}: spread {spread:.2f} of {len(levels)} levels{scope}  "
          f"{'OK' if ok else 'TOO HIGH -- the sheet is entangled, not just unlucky'}")
    print(f"   ({why})")


if __name__ == "__main__":
    main()
