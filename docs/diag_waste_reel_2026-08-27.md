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

## Detection-gap reel rulings (operator, 2026-08-27, card detgap_reel_0700)

Both clips, worst deficit corridor (SB-right, 8:00 bin, Mio 69 vs 33):
- NO untracked visible vehicles; ZERO yellow dots (no detected-but-
  untracked class exists here). Detection is NOT the hole.
- The gap is OCCLUSION: large trucks/vans physically hide vehicles;
  turners wait hidden behind queues. Detection resumes the instant
  the blocker clears.
- The 50-70%-undetected hypothesis is REVISED by the operator's own
  review: the vehicles are seen whenever they are visible; the
  deficit lives in (a) occlusion windows at entry (birth past the
  mouth -> no entry evidence -> discarded/insufficient) and (b) the
  counting layer's rejection pile (177 SB_right rejected vs the 141
  deficit).

## OPERATOR MECHANISM PROPOSAL — flow-informed origin inference

The system should learn the direction of traffic from the dominant
trajectory flows it already observes. A vehicle that appears
mid-scene without crossing the mouth (it was occluded at entry) had
to come from somewhere: infer its origin from where it materialized
plus the flow structure — likely right turns (right-on-red arrivals
appear mid-turn behind queues), "yet to be proven." This is the
counting-layer companion to the pertinence law: occlusion-birth
tracks should be attributed by reasoning, not discarded for missing
entry evidence.

## The complete diagnosis (operator + measurement, one page)

1. Detection layer: SOLID where visible (operator eyes, both reels).
2. Dup engine: red-light stop-fracture-reactivate (both fragments
   counted). Tight signature: track B births at stopped track A's
   rest position, dies when A reactivates at green.
3. Theft engine: anxious tracker at stop bars (loss of motion ->
   neighbor's movement claims the lock).
4. Discard engine: dwell-crushed trajectory confidence rejects
   CORRECT events at the deficit-cell scale (177 vs 141); occlusion
   births die entry-less.
5. Design laws: pertinence (counts iff it enters the intersection);
   flow-informed origin inference for occlusion births; identity
   collapse for stop-fracture pairs.
