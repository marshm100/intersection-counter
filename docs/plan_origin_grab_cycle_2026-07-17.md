# Plan — the far-field origin-grab cycle (2026-07-17)

Opened as the second half of the detector-promotion decision (option C,
operator): the fine-tuned detector ships with a KNOWN residual — its earlier
far-field births get their ORIGIN claimed by the nearest side leg. Full gate
discipline; Miovision = dev scorer only.

## The class, unified (three independent sightings)

1. **FM51 (the promotion residual)**: births near the T-stem claim the side
   leg — S-left 3→54, S-right 67→76, S-through 2→97 (geometrically
   impossible; the through-gate kills those but cannot RESTORE the vehicles
   to SB, hence SB −6.5%). Side road +73 vehicles absolute.
2. **cam4 Wall C (item 8, characterized)**: 71 mid-block arterial births
   grabbing the driveway anchor ((34→33) +31; the anchor-move fix measured
   worse and was reverted).
3. **cam1 sweep run 1 (fixed differently)**: exit stubs claiming turn paths
   via proximity — the per-candidate veto killed that sub-class; the birth-
   side sub-class is what remains.

One family: **origin claimed from spatial PROXIMITY by a track whose birth
lies beyond/inside the mouth it claims** — amplified by the promoted
detector precisely because it now sees far-field vehicles earlier.

## Why not the origin-evidence gate as-is

Measured negative on FM51 (2026-07-17): entry-gate evidence coverage there
is 5.5% AM / 1.9% PM (vs cam2's 80%) — the gates' geometry never intersects
the traffic. The evidence machinery is sound but requires per-camera
geometry QA before it means anything. That QA (n_evidenced/n_tracks as a
calibration-time health check + gate placement tooling) is a candidate
INSIDE this cycle, not a prerequisite excuse.

## Phase 0 — diagnosis (the autopsy pattern, ~1 session)

On the FM51 fine-tuned dumps (exist: ftv1_am/ftv1_pm) + cam4's study dumps:
bucket every side-leg-origin event by BIRTH GEOMETRY — distance from the
claimed mouth along/across the road axis, birth bearing vs the main road.
Deliverable: the numeric boundary between genuine side-leg entries and
main-road grabs (the mid-block signature measured, not assumed).

**DONE 2026-07-17 — `phase0_origin_grab_2026-07-17.md`.** The signature is
`d_main < 25 AND d_mouth > 60` (born ON the crossing road, away from the
claimed mouth's throat): 94%/93% of FM51's certain/near-certain grabs, 86%
of cam4's watch-cell claims, 24% of the mostly-genuine group. `s_in` alone
is site-dependent (fails at cam4's driveway geometry) — the plan's
"beyond-the-mouth" phrasing generalizes as the composite rule. Bonus
finding: the grabs ride the TIER-0 POLYLINE match, not anchor proximity
(their births are nearest the MAIN-ROAD anchor already), so the veto's
fallback lands the correct origin naturally. Constants D_MAIN=25/M=60
frozen there for phase 1.

## Phase 1 — one mechanism (candidates, evidence-ordered)

1. **Beyond-the-mouth origin gate** (item-8 mechanism ②, now with its
   motivating data): a track BORN past the claimed mouth (s beyond the box
   edge + margin, geometry from operator legs — no new time constants) may
   not take that origin from proximity; it falls to the next candidate
   origin or lands origin-uncertain (flag queue, conservative). Structurally
   different from the retired anchor move: it gates CLAIMS, not anchors.
2. **Gate-geometry QA + the evidence filter where healthy**: calibration
   screen surfaces per-camera evidence coverage; where ≥ threshold-by-
   construction (gates verified to see the mouths), the PROVEN filter half
   activates. Blind: coverage is camera-intrinsic.

## Phase 2 — the gate (cheap: every dump already exists)

- FM51 replay (ftv1 dumps): side road → ~60±small, SB restored toward
  −0.3%, NB holds ≥ +4.6%'s accuracy class, total stays ≤ ~±2%.
- Corridor sweep via replay: cam4 (34→33) watch cell sheds toward 111/live;
  cam3 3.2 tripwire; no cam2 regression.
- PASS → ship in the promoted-detector config. FAIL → retirement entry;
  the promoted detector keeps shipping with the residual flagged to the
  §3-B queue (side-leg cells at ≥2x corpus expectation light up).

## Interim surveillance (already live)

Until this cycle lands, the flag queue's conservation/coverage feeders are
the guard: a side leg counting far above its corpus expectation produces a
suspected-gap/uncertain card for operator review on every study.
