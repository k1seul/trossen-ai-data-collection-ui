# Collecting `pick_place_fruit_bowl` for an OOD generalization experiment

The previous round could not measure generalization, because it did not *cover* enough to split
on. Object position was randomized (good) and everything else was fixed, so a policy that
memorised the route scored the same as one that looked.

This round records **everything, evenly**, and the OOD splits are drawn afterwards from the data
itself. Nothing is withheld while recording.

Read [what_the_trained_policy_showed.md](what_the_trained_policy_showed.md) first if you have
not: it is the evidence for why each choice below is what it is.

---

## The workspace: three zones

The arm's shoulder joint spans **−0.67 to +0.67 rad** in the recordings; that is the reachable
band. Divide the mat across it into three zones of roughly equal width:

```
        L                 C                 R
  |---------------|---------------|---------------|
 -0.67          -0.22          +0.22          +0.67      (shoulder, rad)
   left of the arm      in front        right of the arm
```

Mark the two boundaries on the mat with tape. The operator only ever needs to know **L, C, R**.

## Nothing is held out while recording

The split is made **later, on the recorded data**. Every attribute an OOD split needs is
recoverable: the route from where the gripper closes and next opens, position from the joint
angles, lighting from the frame brightness, the object from the task index.
`real_robot/ood_split.py` in the training repo does this and writes the episode ids.

Withholding at collection time would cost episodes and, worse, tangle the axes: an evaluation
set recorded in its own session carries that session's lighting and staging with it, so an
"unseen route" result would also be an unseen-room result. One evenly covered recording, split
afterwards, keeps them separable and lets the same data answer several questions.

What collection has to deliver instead is **coverage** and **decorrelation**.

### Coverage: every route, every condition, every object

The object and the container each go in a zone, never the same one, giving six routes. **Record
all six**, evenly:

```
L->C   C->L   C->R   R->C   L->R   R->L
```

For contrast, the existing recording covers these very unevenly — `L->R` and `R->L` account for
67 of 120 episodes because the bowl sat on one side, and **`R->C` never happened at all**. No
split can hold out a route that was never recorded, which is what makes even coverage the job.

Three lighting conditions, in equal share:

- **A**: overheads on
- **B**: overheads off, desk lamp on
- **C**: blinds open, overheads off

All four fruits.

### Decorrelation: the axes must not line up with each other

The staging sheet assigns lighting round-robin *within* each object-and-route group, so every
route gets an equal share of every condition by construction. Leaving that to a shuffle produced
a 0.46-level correlation between lighting and route on the first attempt — enough that holding
out a route later would partly have been holding out a lighting condition. It also checks that
the container's zone carries no hint about which fruit was named, which is the defect that broke
the previous round.

Both checks print with the sheet; both should read 0.00.

## Session plan

```bash
python scripts/staging_plan.py --task pick_place_fruit_bowl --episodes 6 --csv sheet.csv
```

4 objects x 6 routes x 6 episodes = **144 episodes**, a little more than the previous 120 and
spread over every route instead of two. At ~16.5 s of motion plus the reset, budget about 35 s
per episode: roughly 85 minutes of cycle time, so a half-day session with staging changes.

Fewer episodes per cell is fine as long as every cell is filled — `--episodes 4` is 96 episodes
and still covers everything. An empty cell is what cannot be fixed later.

Record it all into **one** repo id. The splits come afterwards:

```bash
python real_robot/ood_split.py --repo-id k1seul/pick_place_fruit_bowl_v2      # what it covers
python real_robot/ood_split.py --repo-id ... --hold-out route:L->R,R->L --out route_split.json
python real_robot/ood_split.py --repo-id ... --hold-out task:banana --out object_split.json
python real_robot/ood_split.py --repo-id ... --hold-out "brightness:<112" --out light_split.json
```

## The round fruits are near the gripper's limit

Measured from the demonstrations — the gripper opening while carrying is the object's width at
the jaws, and the widest the jaws were ever commanded is 43 mm:

| object | width held | of the 43 mm opening | clearance per side |
|---|---|---|---|
| apple | 36.4 mm | 85% | **3.3 mm** |
| orange | 35.7 mm | 83% | **3.7 mm** |
| peach | 34.0 mm | 79% | **4.5 mm** |
| banana | 10.2 mm | 24% | 16.4 mm |

The policy's own joint errors on held-out frames are 0.024–0.030 rad on the two joints that
carry the gripper laterally, which at a 30–40 cm reach is roughly **7–12 mm** at the jaws. That
is two to three times the clearance the round fruits leave, and well inside the banana's. The
teleoperator closes a loop with their eyes at millimetre scale; the policy does not.

Two things follow, and they pull in different directions:

**Demonstrate the miss.** With a tolerance the policy cannot reliably hit, a failed grasp is not
an exception, it is the normal case. The demonstrations must show what to do about it: jaws
close on nothing or knock the fruit, **reopen, back off, re-approach, grasp**. All 120 existing
episodes are clean first-try successes, so the policy has never seen the state it spends most of
its time in.

**Consider smaller props for the round fruits.** If the point of this round is spatial and
semantic generalization, a grasp needing millimetre precision becomes the dominant failure mode
and it affects `baseline`, `vision` and `special` alike — so it adds noise to exactly the
comparison the experiment exists to make. At ten trials per arm, a grasp that succeeds a third
of the time regardless of arm cannot distinguish them. A ~25 mm prop leaves 9 mm per side,
inside what the policy can hit, and the OOD axes stay measurable.

Keeping the large fruits is a legitimate choice — it is the harder, more realistic task — but
then **report per-object success separately**, so a grasp bottleneck is not read as a difference
between arms.

## The release: give it slack

This is what the trained policy is failing on right now — it picks the fruit up, carries it, and
never lets go. The reason is in the demonstrations:

| distance from that episode's release pose | opens within 0.5 s |
|---|---|
| 0.00–0.02 rad | 62% |
| 0.02–0.05 rad | 2% |
| **beyond 0.05 rad** | **0% — never** |

Every recorded release happens within about a degree of one exact pose, because the operator
carried the fruit straight to a spot and opened the gripper the instant it arrived (speed at
release is 6% of carry speed). There is no demonstration of releasing from slightly wide, or
slightly high, or while still drifting.

A policy lands where its own small errors put it, not where a human hand did. Arriving 0.05 rad
off, it sees a state the data only ever labels "keep approaching" — so it approaches a pose it
cannot quite reach, and hovers. The gripper is the one action with no second chance.

**So make "over the container" a region rather than a point:**

- Release from a **different spot over the container every episode** — near edge, far edge,
  left, right, dead centre. The bowl is forgiving; the data has to say so.
- Vary the **height**: from just above the rim, and from 10–15 cm up. Both work in reality.
- **Do not line up carefully.** Open as soon as the fruit is over the opening, including while
  the arm is still moving. Half the existing episodes already release in motion; keep that.
- If it lands outside, **pick it up and place it again in the same episode**. That is both the
  recovery data this dataset has none of, and a second release from a different pose.

Check it afterwards:

```bash
python real_robot/ood_split.py --repo-id <new> --no-brightness   # prints the release basin
```

The 0.02–0.05 band should be well above 15%, not 2%.

## Per-episode procedure

1. Read the next row of the sheet. Place the **object** and the **container** in the zones it
   names. Vary position and orientation freely *within* the zone — the zone is the constraint,
   not the exact spot.
2. Set the lighting to the condition the sheet names.
3. Apply the start-pose nudge (a few degrees on the named joint) before starting.
4. Start recording.
5. **If the grasp misses, recover within the episode and keep it.** The previous 120 episodes
   contain not one recovery, and it is the single thing a behaviour-cloning policy most needs to
   see: it will make small errors at deployment, because it acts on an observation 220 ms old.
   Use "Fail episode" only for a genuinely spoiled take (object knocked off the mat, operator
   error).
6. **Press `Space` as soon as the object is in the container.** That is "Finish episode": the
   take is kept and the next one begins. `episode_length_s` is now only an upper bound (45 s
   for this task), long enough for a recovery attempt — it is not the intended length. The
   previous round set it to the intended length, nobody ended early, and the last fifth of
   every episode was the arm sitting still: 14.7% of all recorded frames.

### Keys, so a hand can stay on the leader arm

| key | |
|---|---|
| **`Space`** or `S` | finish the episode now and **keep** it — the object is placed |
| `F` | discard this take and move on — spoiled, e.g. the fruit went off the mat |
| `R` | stop waiting out the reset — the scene is re-staged |

Reaching for the mouse is what made every episode run its clock out last time.

## Keep recording all three cameras

`cam_high`, `cam_wrist` and `cam_front`. Training currently uses the first two, and pi0's third
image slot is zero-filled, but `cam_front` looks down the arm's axis from the opposite side and
sees the object when the arm occludes it in `cam_high`. It costs about 350 MB per dataset, and
not recording it forecloses the option permanently. Record it in **every** task this round, so
the choice to use it is not blocked by half the datasets lacking it.

## What to check before calling the session done

- [ ] `ood_split.py --repo-id <new>` lists **all six** routes, none missing
- [ ] Both balance checks on the staging sheet read 0.00
- [ ] Brightness spread across episodes is several units, not near 1 (one condition)
- [ ] The release basin report is "wide enough", not "NARROW"
- [ ] At least a few episodes contain a recovered grasp, and some a second placement attempt
- [ ] For the round fruits especially: misses are demonstrated, not re-recorded away
- [ ] Episodes end when the task ends: lengths should vary, not all be 18 s
- [ ] Everything is in one repo id — the splits are made later, not by separate recordings
