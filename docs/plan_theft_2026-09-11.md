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

## Step 1 result (recorded 2026-09-11): MISS — appearance does not see the theft at this resolution

scripts/theft_appearance.py, osnet_x0_25 on every frame's crop of the
17 ruled tracks. Two statistics: the largest 1 s-window break, and
the best any-point split (sees a break at the very end).

  class   n   break: min / median / max     split: min / median / max
  THEFT   8   0.070 / 0.265 / 0.398         0.174 / 0.253 / 0.368
  clean   9   0.000 / 0.135 / 0.333         0.141 / 0.198 / 0.388
  best threshold (break) 0.070: thefts 8/8 above, clean 6/9 above
  best threshold (split) 0.174: thefts 8/8 above, clean 7/9 above

No separation. The waiting right (17526) splits at 0.388, above every
theft; the corner-spawn right (22270) breaks at 0.333, above 7 of 8
thefts; the "launched in reverse" theft (332755) breaks at 0.070,
below every clean track but two. WHY: the median box side on these
tracks is 14-38 px (640x480 source). An embedding of a 20-px crop
carries little identity; a clean vehicle changes appearance through
perspective, lighting and partial occlusion as much as a theft
changes it through the vehicle. On cam2 alone (near-field, 25 fps)
the three thefts (0.262-0.398) sit above the four clean tracks
(0.135-0.233) on the window statistic — a margin of 0.03 on seven
tracks, not a rule.

CONSEQUENCE (the declared MISS clause): the appearance instrument
does not reach the theft class at this camera resolution; neither did
three path signals nor the tracker veto. The class is, for now, the
FLOOR of this corridor's footage: ~8 of 20 ruled defects. The one
lever left is pass-1 (the tracker's association under occlusion),
where the emergence guard has already missed twice; a ReID-assisted
tracker would lean on the same 20-px embeddings measured here. Not
pursued further without new footage or a higher-resolution source.

The remaining fleet points are elsewhere: cam4 (62.2 morning:
NB_thru +313 over Mio, SB_right 4x) and cam5 (red on two windows),
where the defect class is not yet diagnosed on film.
