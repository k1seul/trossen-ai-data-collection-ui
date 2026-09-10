# Data Collection Curriculum & Protocol

Robot: **trossen_ai_solo** (single arm — the only robot config with real
hardware set up; `trossen_ai_stationary`/`trossen_ai_mobile` are still
placeholders). Cameras: `cam_high`, `cam_wrist`, `cam_front`.

Props on hand: colored wooden blocks, bowl, pot (냄비), orange/banana/apple/peach
(fruit props), colored tape rolls, and a cutting mat with a whiteboard sheet
on top that can be marked for fixed positions/zones. (The small stand prop
is no longer used by the curriculum below.)

Block colors: **red, blue, green, yellow** (confirmed — no purple).
Tape colors: **red, blue, green, purple, yellow** (5 colors).

## Curriculum (easy → hard)

Each row is one task in `tasks.yaml` — one Hugging Face repo
(`k1seul/<task_name>`) holding every object/variant listed, tagged
individually via lerobot's per-episode task metadata (not separate repos).

| Tier | Task (`task_name`) | Instruction pattern | Object/variant count | Why it's this difficulty |
|---|---|---|---|---|
| 1 — Easy | `pick_place_block_bowl` | "Pick up the {color} block and place it in the bowl." | 4 colors | Single object type, large forgiving target |
| 2 — Easy | `pick_place_block_pot` | "...place it in the pot." | 4 colors | Same skill, adds container-shape variety |
| 3 — Easy-medium | `pick_place_fruit_bowl` | "Pick up the {fruit} and place it in the bowl." | 4 fruits | Different shapes/sizes force grasp adaptation |
| 4 — Medium | `stack_tapes` | "Pick up the {A} tape and stack it on top of the {B} tape." (full sentence per pair, both colors always named explicitly) | 5 ordered tape-color pairs (minimal cycle, not all 20 combos) | Precise alignment + gentle release; unambiguous pick/base pairing |
| 5 — Medium-hard | `sequential_two_blocks_bowl` | "Pick up A ... then pick up B ..." (full sentence per variant) | 4 ordered pairs | Two-step compound task in one episode |
| 6 — Hard | `pick_specific_item_from_clutter` | "Pick up the {item} ... Do not touch the other items." | 8 items (blocks+fruit) | All props on the mat at once — discrimination |
| 7 — Hardest | `place_object_in_marked_zone` | "Pick up A and place it in zone X." (full sentence per variant) | 5 combos | Precise spatial placement at a marked location, not "anywhere in a container" |

Current overall target: **1030 episodes** across all tiers (see
`data_collection_plan.md` for the live per-variant breakdown).

Recommended starting targets (edit `target_episodes` in
`~/.trossen/trossen_ai_data_collection/plan/data_collection_plan.csv`
directly — the app never overwrites what you set there):

- Tiers 1–3: **~30 episodes** per object/variant
- Tier 4 (tape stacking): **~40 episodes** per pair (precision task needs more data)
- Tier 5: **~30 episodes** per ordered pair
- Tier 6: **~25 episodes** per item (relies on scene diversity, not per-item volume)
- Tier 7: **~30 episodes** per combo

Collect tiers roughly in order — each one reuses skills/scenes from the
previous tier, so early mistakes in technique get caught before they're
baked into a harder task's data.

## Setup (once per session)

1. Don't move the cameras once you start a tier — keep framing consistent
   across all episodes of the same task so the visual input distribution
   stays stable. If you must adjust framing, treat it as a deliberate
   decision (extra visual diversity is fine in moderation, but don't do it
   mid-batch without noticing).
2. **Vary the lighting deliberately between batches** — overheads on, overheads off with a
   lamp, blinds open, different times of day. The previous round held brightness constant to
   0.7% across 120 episodes, and the policy then failed outright in a dimmer room (-16 sigma
   brightness, 5.3x sensor noise). Still avoid strong shadows or backlighting that
   changes through the day.
3. Clear the mat of anything not part of the current task (except Tier 6,
   which intentionally wants everything out).
4. Click **HARDWARE RESET CAMERAS** before starting for a clean camera state.
5. For Tier 7, mark zones A/B/C on the whiteboard sheet now (tape outline or
   marker) so they stay fixed and consistent for every episode of that tier.
   Note: Tier 4's tape rolls are the *stacking objects themselves*, not the
   Tier 7 zone markers — keep the two uses of tape mentally separate.

## Before each object/variant batch

1. Select the task in **TASK SELECTION**.
2. Set **OBJECT / VARIANT** (pick from the dropdown — it already lists
   presets plus anything recorded before — or type a new one) and check the
   **Instruction:** preview matches what you intend to demonstrate.
3. Check `data_collection_plan.md` for how many episodes are already
   recorded vs. the target for this variant.

> **Amended after the first trained policy.** See
> [what_the_trained_policy_showed.md](what_the_trained_policy_showed.md) for the measurements
> behind the changes below. In short: randomizing the object was done and worked; not
> randomizing the **container** taught the policy to carry each fruit to a fixed side, one
> lighting condition made it fail in a dimmer room, and a fixed episode clock left a fifth of
> every recording motionless.

## Object AND container placement — randomize every episode

This matters more than anything else for a policy that generalizes:

- Before each episode, physically move the target object to a **new**
  position/orientation within a reasonable region — never the exact same
  spot twice in a row.
- For Tier 6 (clutter), also shuffle the distractor objects' positions each
  episode.
- For Tier 7 (marked zones), randomize the object's **start** position, but
  keep the target zone boundaries fixed as marked.
- Start the robot from the same neutral/home pose each episode (let the
  warmup phase settle into it) — vary the object, not the robot's starting
  configuration.

### Use the staging sheet

```bash
python scripts/staging_plan.py --task pick_place_fruit_bowl --episodes 30 --csv plan.csv
```

It names a mat cell for the object **and** for the container each episode, rotates the lighting,
and nudges the start pose. It also checks that the container's position has not ended up
correlated with which object is named — the defect that produced "banana means carry right".

## Recording an episode

1. Click **START RECORDING SESSION**. Warmup isn't recorded — use it to
   double check camera framing and that the object is actually visible
   before the episode starts.
2. Perform the task naturally, at a normal pace. If the red
   **"⚠ MOVING TOO FAST"** banner appears, slow down — jerky fast
   demonstrations make for lower-quality training data.
3. Once the task is visibly done, either let `episode_length_s` run out, or
   press **FINISH EPISODE NEXT** to save early and move on (recommended for
   the easier/shorter tiers to avoid dead time at the end of every episode).
4. If something goes wrong mid-episode:
   - Minor slip you want to immediately redo → **RE-RECORD LAST EPISODE**.
   - Want to abandon it and move to the next episode instead → **FAIL
     EPISODE NEXT**.
5. Reposition the object **and the container** during the automatic reset phase, following
   the staging sheet, and apply the start-pose nudge.
6. **Press "Finish episode" as soon as the object is in the container.** Do not wait out the
   clock: the previous round ran every episode to its full `episode_length_s`, and the last
   20% of each one was the arm sitting motionless — a fifth of the training data.
7. **If a grasp misses, recover within the episode and keep it.** "Fail episode" discards the
   take, which is right for a spoiled episode and wrong for a miss the operator recovered
   from. The previous dataset contains 120 clean takes and not one recovery, which is the one
   thing a behaviour-cloning policy most needs to see.

## Periodic long reset (every 10 episodes)

Every task is configured with `long_reset_interval: 10` and
`long_reset_time_s: 60` — after every 10th completed episode, the reset
phase runs for 60s instead of the normal `reset_time_s`, so there's real
time to re-set-up the scene (re-check prop positions/orientations, wipe the
mat, re-mark zones if they drifted, etc.) rather than just repositioning
one object. The log shows **"Long environment reset (60s)..."** when this
happens so it's obvious it's not the usual short pause.

You don't have to wait out the full 60s: once you're done setting up,
click **SETUP DONE — START NEXT EPISODE NOW** (enabled only while a reset
is in progress) to start the next episode immediately. This works for the
normal short resets too, not just the long ones.

## Switching object/variant

Just change the **OBJECT / VARIANT** field — no need to stop the session
unless you're switching to a different task family entirely.

## Wrap-up

1. Click **END RECORDING SESSION**.
2. Check `data_collection_plan.md` for per-variant progress against target.
3. `push_to_hub: true` is set on all tasks above, so data uploads
   automatically at the end of each save interval.

## Quality checklist before calling a task "done"

- Every object/variant has a roughly similar episode count — no color/fruit
  left far behind the others.
- Any episode where you deviated from the stated instruction was marked
  FAIL or re-recorded, not left in as mislabeled data.
- Object positions/orientations show real variation across episodes, not
  the same spot repeated.
