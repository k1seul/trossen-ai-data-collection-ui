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

- [ ] `ood_split.py --repo-id <new>` lists **all six** routes, none missing
- [ ] Both balance checks on the staging sheet read 0.00
- [ ] Brightness spread across episodes is several units, not near 1 (one condition)
- [ ] At least a few episodes contain a recovered grasp
- [ ] Episodes end when the task ends: lengths should vary, not all be 18 s
- [ ] Everything is in one repo id — the splits are made later, not by separate recordings
