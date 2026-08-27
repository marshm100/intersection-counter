# Waste-reel operator diagnosis (2026-08-27) — rulings + findings

Operator reviewed all 8 scenes of the waste reel (solo-C 0700 arm).
Rulings recorded in review_log, card waste_reel_0700. What they
establish:

## The double-count engine, named (scenes 1-3)

Operator mechanism, verbatim class: vehicles arriving at the RED
LIGHT. Motion stops -> track 1 stops -> residual motion births
track 2 on the same vehicle -> green light, motion resumes -> track 1
reactivates, track 2 dies -> BOTH counted. The stop-fracture-
reactivate cycle at signal queues is the dup engine behind the
overcounted cells. "Should be collapsed into one vehicle."

## The thief mechanism, generalized (scene 5)

Two cars parked at the stop bar; the tracker "anxious to find
movement" jumps to the neighbor's motion, then snaps back. Loss of
motion becomes a thief. Root observation: the tracker does not know
WHAT vehicle it is tracking, what it looks like, or what it looks
like parked.

## THE PERTINENCE LAW (operator design ruling, scene 5)

Detected vehicles on the periphery (parking lots, long-term parked)
are fine to detect — but a vehicle is pertinent to the study IF AND
ONLY IF IT ENTERS THE INTERSECTION. "That is the difference between
what we have and what is required." Candidate consequences: counting,
theft-opportunity, and confidence machinery should key on
intersection entry, not on everything in frame.

## The counting layer discards correct answers (scenes 4, 7 + census)

- Scene 4 (tid 71): tracked accurately through an 80 s red-light
  wait, classified FULL as EB_left — event #471318 minted CORRECTLY,
  then REJECTED at trajectory_confidence 0.23 (the dwell crushes the
  confidence score).
- Census (0700 window, arm): 177 SB_right events rejected vs a
  141-vehicle SB_right deficit; 129 EB_left rejected vs an 84
  deficit. THE REJECTION PILE MATCHES THE DEFICIT CELLS. A large
  share of "missing" vehicles are seen, tracked, classified, then
  discarded.
- Scene 7 (tid 18506): bus occlusion handled perfectly by the
  tracker (operator: "working great") but the track never registered
  an exit-gate crossing -> entry_only -> never counted.

## Selector corrections (scenes 6-7)

The "lost attribution" selector assumed production labels = truth.
Operator: scene 6's arm label (EB_through) is CORRECT and
production's EB_left was wrong — the arm IMPROVED attribution there.
Any future truth-grounded selector must use Miovision or operator
eyes, not production.

## Instrument ruling (standing)

Never highlight with colors that read as concrete (light green on
pavement). High-contrast only, black-outlined. Applied in
viz_detection_gap.py (blue boxes black-outlined, yellow dots).

## Open evidence (detection-gap reel, published)

Operator claim under test: 50-70% total detection in problem zones.
Two 15 s clips of the 8:00-8:15 SB-right corridor (Mio 69 vs our 33)
with every track + every raw detection overlaid — unmarked movers =
invisible. Artifact: Detection Gap Reel. Rulings pending.
