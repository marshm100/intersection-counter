# THE THEFT CLASS — APPEARANCE (2026-09-11) — G-TH-1 declared

Operator, 2026-09-11: "we can work on 1" (the theft class first).

## What is known

Twenty ruled clips on 2026-09-09: 8 are thefts — a waiting or slow
box is taken by cross traffic inside the intersection, the id either
lingers until it dies or is launched along the thief's road
(docs/plan_state_machine_2026-09-09.md, reels 2 and 4). Everything
tried on the box's PATH has missed: the emergence-guard tracker veto
(G-LT-1, twice, over-fires by orders of magnitude), the speed
discontinuity (clean stop-and-go launches look the same), the back-
projection of the launch heading (a right turn traces back to its
exit). The path does not carry the theft; what changes at a theft is
WHAT IS IN THE BOX.

Appearance machinery exists: osnet_x0_25 ReID embeddings via boxmot
(scripts/build_reid_cache.py; cam1 runs botsort+reid in production;
sidecars exist for cam1/cam2 study_0700 only). Weights are local.

## G-TH-1 (declared before any measurement; two steps)

STEP 1 — SEPARABILITY on the 17 ruled clips (8 thefts, 9 clean,
including the occlusion re-acquisitions and corner spawns that must
NOT read as thefts). For each track: embed the box crop on every
frame (osnet_x0_25, the production model); the signal is the largest
appearance BREAK along the track — the cosine distance between the
mean embedding of the k frames before a point and the k after it,
maximised over the track (k = 1 s). Also report where the break sits
relative to the machine's crossings.
PASS = a single threshold separates: all 8 thefts above it with at
most 1 of 9 clean tracks above it. If the occlusion re-acquisitions
(reel 1 clips 3-4, ruled "through vehicle" but "not sure the correct
vehicle was picked up again") sit with the thefts, that is reported,
not hidden — his ruling on those decides which side they belong to.
MISS = the appearance instrument does not see the theft either; the
class goes back to the tracker (the ReID-enabled tracker on cam2/cam3
becomes the candidate, a pass-1 change).

STEP 2 (only on a step-1 PASS) — the VETO as a default candidate: a
journey with an appearance break above the threshold ends at the
break (the state machine treats it as EXITED with no legitimate exit
— the box changed vehicle). Needs embeddings for every track in a
window: build the ReID sidecar for the six scoring windows (hours of
GPU), then one fleet arm against 75.86, the G-DEF-1 letter.

## Step 1 result

(to be recorded)
