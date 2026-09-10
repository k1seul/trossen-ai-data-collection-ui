# Collecting `pick_place_fruit_bowl` for an OOD generalization experiment

The previous round could not measure generalization, because nothing was held out. Object
position was randomized (good) and everything else was fixed, so a policy that memorised the
route scored the same as one that looked. This round deliberately withholds three things, so
"does it generalize" becomes a number rather than an impression.

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

## What is held out, and why

### 1. Compositional — two of the six routes

The object and the container each go in a zone, and never in the same one, giving six routes.
**Record four. Never record the two long crossings.**

| route | object | container | |
|---|---|---|---|
| L → C | L | C | record |
| C → L | C | L | record |
| C → R | C | R | record |
| R → C | R | C | record |
| **L → R** | **L** | **R** | **HELD OUT — evaluation only** |
| **R → L** | **R** | **L** | **HELD OUT — evaluation only** |

Every zone is demonstrated in both roles: the policy sees objects picked from L, C and R, and
containers approached at L, C and R. Only the *pairing* is new at evaluation. A policy that has
learned "find the object, then find the container" handles it; one that memorised routes does
not. That is exactly the failure this dataset produced last time, when the container never moved
and "banana" came to mean "carry right".

### 2. Appearance — one lighting condition

Record under **two** conditions, alternating between episodes:

- **A**: overheads on (the previous round's condition)
- **B**: overheads off, desk lamp on

Hold **C: blinds open, overheads off** for evaluation only. The previous round held brightness
constant to 0.7% across 120 episodes and the policy then failed outright in a dimmer room, so
this axis is worth measuring rather than assuming.

### 3. Semantic — one object (optional, recommended)

Record **orange, apple, peach**. Hold out **banana** entirely.

The instruction sentence is the only thing that identifies the object, so this asks whether the
policy grounds a word it has seen in other contexts. It costs a quarter of the episodes. If the
session runs short, drop this axis before dropping the other two — but note it in the dataset
description, because a later reader cannot tell from the files.

---

## Session plan

```bash
python scripts/staging_plan.py --task pick_place_fruit_bowl --episodes 10 \
    --split train --csv train_sheet.csv
python scripts/staging_plan.py --task pick_place_fruit_bowl --episodes 4 \
    --split eval  --csv eval_sheet.csv
```

The sheet names a zone for the object and the container, the lighting condition and a start-pose
nudge, for every episode. It refuses to emit a held-out route in the train split and emits
**only** held-out routes in the eval split.

**Volume**: 3 objects × 4 routes × 10 episodes = **120 training episodes**, matching the previous
round. At ~16.5 s of motion plus the reset, budget about 35 s per episode: roughly 70 minutes of
cycle time, so a half-day session with staging changes.

The evaluation set is recorded the same way but kept **separate** — a different repo id, e.g.
`k1seul/pick_place_fruit_bowl_ood`. Do not mix it into training.

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
6. **Press "Finish episode" as soon as the object is in the container.** Do not wait out the
   clock. The previous round ran every episode to its full 18 s and the tail was motionless —
   14.7% of all frames, teaching the arm to sit still.

## Keep recording all three cameras

`cam_high`, `cam_wrist` and `cam_front`. Training currently uses the first two, and pi0's third
image slot is zero-filled, but `cam_front` looks down the arm's axis from the opposite side and
sees the object when the arm occludes it in `cam_high`. It costs about 350 MB per dataset, and
not recording it forecloses the option permanently. Record it in **every** task this round, so
the choice to use it is not blocked by half the datasets lacking it.

## What to check before calling the session done

- [ ] The container's zone is not correlated with which fruit is named — the staging sheet
      prints this check; it is the defect that broke the last round
- [ ] No episode in the training set uses route L→R or R→L
- [ ] Both lighting conditions appear roughly equally, and condition C appears nowhere
- [ ] At least a few episodes contain a recovered grasp
- [ ] Episodes end when the task ends: lengths should vary, not all be 18 s
- [ ] The eval set is in its own repo id
