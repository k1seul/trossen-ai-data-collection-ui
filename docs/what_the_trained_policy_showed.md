# What the first trained policy showed about this data

pi0.5 was finetuned on `pick_place_fruit_bowl` (120 episodes) and run on the arm. It failed in
ways that trace back to how the data was collected, not to the model — every number below is
measured from the recordings themselves, and each one is a change to make next round.

The offline evidence that the *model* was fine, so none of this gets misattributed:

- held-out loss with whole **episodes** held out: 0.00294, against 0.00316 on the frame split —
  no generalization gap, so it had not memorised trajectories
- per-joint action error 3–7% of each joint's range, flat across all 16 actions of a chunk
- gripper open/closed agreement 98.7%, and balanced: 97.8% while closed, 99.0% while open
- with every episode's arm within 0.0012 rad of the same pose — so proprioception carries
  nothing — its predicted plans spread across episodes as much as the demonstrations do
  (0.0195 vs 0.0162 rad). **It looks at the camera and commits to what it sees.**

## 1. The container never moved, and its side was a function of the task

| task | object travel (shoulder, rad) | container travel |
|---|---|---|
| orange | RIGHT, 0.95 | LEFT, 0.24 |
| banana | LEFT, 0.85 | RIGHT, 0.52 |
| apple | RIGHT, 1.09 | LEFT, 0.18 |
| peach | LEFT, 1.34 | RIGHT, 0.25 |

The protocol said to randomize the **object** every episode, and that was done — it spans about
a radian of shoulder travel. Nothing said to move the **bowl**, so it stayed put, and it sat on
the opposite side for `banana`/`peach` than for `orange`/`apple`.

The policy therefore learned "banana" to mean "carry to the right" rather than "find the bowl".
Staging a banana trial the way the orange task was demonstrated — bowl left, fruit right — made
the arm reach left for a fruit on the right and then carry it right to a bowl on the left. On the
robot that reads as a grasp failure followed by a placing failure. It is neither.

**Change:** randomize the container too, over a range comparable to the object's, and make sure
its position does not correlate with which object is named.

## 2. There is not one failed grasp in the dataset

All 120 episodes close the gripper exactly once. No misses, no retries, no recovery.

A policy trained only on clean takes has never seen the state it lands in after its own small
error — and small errors are certain, because it acts on an observation that is already 220 ms
old by the time the command reaches the arm. This is the classic limit of behaviour cloning and
no offline metric detects it: all of the numbers at the top of this page are computed by feeding
the policy a *recorded* state.

**Change:** when a grasp misses, let the operator recover **within the episode** and keep it.
"Fail episode" in the UI discards the take; that is the right button for a genuinely spoiled
episode and the wrong one for a miss the operator recovered from.

## 3. A fifth of every episode is the arm sitting still

Episode lengths are 534, 535, 534… (std 3.3%), because `episode_length_s` is a fixed clock —
18 s × 30 fps = 540. Mean joint speed over the last 20% of an episode is 0.00004 rad/frame
against a peak of 0.011. That is **zero motion**, and it is 20% of the training data.

**Change:** the UI already has a **"Finish episode"** button that ends the take early and keeps
it. Press it when the object is in the container. Leave `episode_length_s` as a generous upper
bound rather than the intended length.

## 4. There is exactly one lighting condition

Across 120 episodes, cam_high's mean brightness varied by **0.7%** and its sensor-noise level by
2%. The protocol asks for "consistent, even lighting", and that instruction was followed
perfectly.

The consequence: with the room lights off, the live scene measured −16σ in brightness and
+330σ in noise (the sensor at 5.3x gain), and the policy failed outright on images unlike any it
had trained on. Consistency during collection buys nothing at deployment and costs all
robustness to the room.

**Change:** vary it deliberately — overheads on and off, blinds open and closed, a few sessions
at different times of day. Even three or four conditions is a large improvement on one.

## 5. Every episode starts from the same pose to within 0.0002 rad

Which means any deviation at deployment is immediately outside the training distribution, and
there is nothing in the data about how to get back.

**Change:** nudge the start pose between episodes — a few degrees on each joint is enough.

## 6. `cam_front` is recorded and thrown away

Three cameras are captured; training uses `cam_high` and `cam_wrist`. pi0 has a third image slot
which is currently filled with zeros, because LIBERO is single-arm and this rig matched it.

**Change:** either feed `cam_front` into that slot or stop recording it.

## What was already right

30 fps, 7-DoF joint positions, units consistent across every session, object placement genuinely
randomized, 16 task sentences over 552 episodes. None of that needs changing.
