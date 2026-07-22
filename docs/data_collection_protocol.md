# Data Collection Curriculum & Protocol

Robot: **trossen_ai_solo** (single arm — the only robot config with real
hardware set up; `trossen_ai_stationary`/`trossen_ai_mobile` are still
placeholders). Cameras: `cam_high`, `cam_wrist`, `cam_front`.

Props on hand: colored wooden blocks, bowl, pot (냄비), orange/banana/apple/peach
(fruit props), a small stand (받침), and a cutting mat with a whiteboard sheet
on top that can be marked for fixed positions/zones.

Block colors below are a guess (red/blue/green/yellow/purple) — correct the
`task_objects` lists in `configs/tasks.yaml` to match what you actually have.

## Curriculum (easy → hard)

Each row is one task in `tasks.yaml` — one Hugging Face repo
(`k1seul/<task_name>`) holding every object/variant listed, tagged
individually via lerobot's per-episode task metadata (not separate repos).

| Tier | Task (`task_name`) | Instruction pattern | Object/variant count | Why it's this difficulty |
|---|---|---|---|---|
| 1 — Easy | `pick_place_block_bowl` | "Pick up the {color} block and place it in the bowl." | 5 colors | Single object type, large forgiving target |
| 2 — Easy | `pick_place_block_pot` | "...place it in the pot." | 5 colors | Same skill, adds container-shape variety |
| 3 — Easy-medium | `pick_place_fruit_bowl` | "Pick up the {fruit} and place it in the bowl." | 4 fruits | Different shapes/sizes force grasp adaptation |
| 4 — Medium | `place_block_on_stand` | "...place it on the stand." | 5 colors | Small target area — precision placement |
| 5 — Medium | `stack_blocks` | "...stack it on top of the other block." | 4 colors | Precise alignment + gentle release |
| 6 — Medium-hard | `sequential_two_blocks_bowl` | "Pick up A ... then pick up B ..." (full sentence per variant) | 4 ordered pairs | Two-step compound task in one episode |
| 7 — Hard | `pick_specific_item_from_clutter` | "Pick up the {item} ... Do not touch the other items." | 9 items (blocks+fruit) | All props on the mat at once — discrimination |
| 8 — Hardest | `place_object_in_marked_zone` | "Pick up A and place it in zone X." (full sentence per variant) | 5 combos | Precise spatial placement at a marked location, not "anywhere in a container" |

Recommended starting targets (edit `target_episodes` in
`~/.trossen/trossen_ai_data_collection/plan/data_collection_plan.csv`
directly — the app never overwrites what you set there):

- Tiers 1–3: **~30 episodes** per object/variant
- Tiers 4–5: **~40 episodes** per variant (precision tasks need more data)
- Tier 6: **~30 episodes** per ordered pair
- Tier 7: **~25 episodes** per item (relies on scene diversity, not per-item volume)
- Tier 8: **~30 episodes** per combo

Collect tiers roughly in order — each one reuses skills/scenes from the
previous tier, so early mistakes in technique get caught before they're
baked into a harder task's data.

## Setup (once per session)

1. Don't move the cameras once you start a tier — keep framing consistent
   across all episodes of the same task so the visual input distribution
   stays stable. If you must adjust framing, treat it as a deliberate
   decision (extra visual diversity is fine in moderation, but don't do it
   mid-batch without noticing).
2. Consistent, even lighting — avoid strong shadows or backlighting that
   changes through the day.
3. Clear the mat of anything not part of the current task (except Tier 7,
   which intentionally wants everything out).
4. Click **HARDWARE RESET CAMERAS** before starting for a clean camera state.
5. For Tier 8, mark zones A/B/C on the whiteboard sheet now (tape outline or
   marker) so they stay fixed and consistent for every episode of that tier.

## Before each object/variant batch

1. Select the task in **TASK SELECTION**.
2. Set **OBJECT / VARIANT** (pick from the dropdown — it already lists
   presets plus anything recorded before — or type a new one) and check the
   **Instruction:** preview matches what you intend to demonstrate.
3. Check `data_collection_plan.md` for how many episodes are already
   recorded vs. the target for this variant.

## Object placement — randomize every episode

This matters more than anything else for a policy that generalizes:

- Before each episode, physically move the target object to a **new**
  position/orientation within a reasonable region — never the exact same
  spot twice in a row.
- For Tier 7 (clutter), also shuffle the distractor objects' positions each
  episode.
- For Tier 8 (marked zones), randomize the object's **start** position, but
  keep the target zone boundaries fixed as marked.
- Start the robot from the same neutral/home pose each episode (let the
  warmup phase settle into it) — vary the object, not the robot's starting
  configuration.

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
5. Reposition the object during the automatic reset phase between episodes.

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
