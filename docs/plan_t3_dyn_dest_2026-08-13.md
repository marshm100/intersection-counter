# Tier-3 — DYNAMICS-FIRST destination classification (operator-directed)
# (2026-08-13)

OPERATOR DESIGN DIRECTION (verbatim intent, recorded): channels are
GENERAL LAYOUT GUIDELINES for a computer that cannot see — not strict
borders, not parameters of what is or is not a vehicle in motion, not
boundaries of where a car can exist. Cars use the SAME MOUTH to turn —
the movement is identified by the PATH OF THE CAR OVER TIME, not by
which mouth or lane it enters. This supersedes the parked G-CHAN-a
entry-point drag (retracted un-run: it would have encoded lane
discipline INTO geometry — the opposite of the direction).

The ledger already supports this: "drawn-channel attribution as an
assignment target" is four-times measured dead (snap-magnet), and E2
records that --heading-lock was killed on an aggregate instrument now
known too blunt — dynamics approaches are owed a re-test with today's
instruments. The sweep supplies the ceiling (F15: turn intent from
kinematics alone, 91.5% two seconds AHEAD of the maneuver; F16:
whole-track likelihood beats gate-crossing on fragments).

## The measured defect this attacks

cam2 entry_28 kept events (origin gate-proven, destination GUESSED):
99 right vs 14 through against a Miovision reality that heavily favors
through — implied through-recall of the current guesser ~12%. One
defect, two cells: EB_right +142 / EB_thru −85 at study_0700, with the
same signature at 1100/1600. Same machinery guesses destinations at
every origin and camera.

## Mechanism (iteration 1 = INSTRUMENT ONLY; counting arm only if it
## passes)

Features per track, from its OWN motion, no channels: heading profile
over the in-box portion — net heading change Δθ(f) at prefix fractions
f ∈ {0.4, 0.6, 0.8, 1.0} of the visible in-box points (heading = local
direction over KIN-point windows), plus cumulative SIGNED curvature.
Templates SELF-CALIBRATED per origin from the window's own strict
fulls (split-half): per movement, the held-in median Δθ profile;
held-out fulls classified by nearest template. GT-free end to end;
channels appear NOWHERE in the decision.

TRUNCATION REALISM: held-out fulls are classified from PREFIXES (the
first f of their in-box points) — measuring exactly the
truncated-track case the pipeline guesses on today.

## GATES — declared before any run

- **G-DYN-i (instrument kill gate):** on cam2 study_0700 AND
  study_1600 (density transfer): held-out destination accuracy from
  the 0.6-prefix >= 0.85 for origin 28's movements, and macro-average
  >= 0.75 across all four origins; at the 0.4-prefix, origin-28
  accuracy >= 0.70. (Anchors: the status-quo guesser's ~12%
  through-recall; F15's 91.5% kinematics ceiling; 0.85 at 60%
  visibility is "decisively deployable".) FAIL → ledger "heading
  dynamics cannot separate this camera's movements from truncated
  prefixes"; iteration 2 (one pre-named change: add signed lateral
  displacement relative to entry heading as a second feature) only if
  the failure is left/right confusion rather than through/turn.
- **G-DYN-a (counting gate, only if G-DYN-i passes; declared now):**
  composition arm (the F2M pattern: WAL-safe control-DB copy;
  RE-DECIDE the destination of kept entry-only/no-crossing events via
  the dynamics classifier; movement updated via derive_movement; score
  with stems `dyn_cam2_<win>`): EB_thru |err| strictly reduced AND
  EB_right |err| strictly reduced on all 3 cam2 windows; 5/95 >=
  control (53.4/42.9/44.0) on all 3 AND >= +1.0 on at least one;
  phantom guard (no new non-compliant slots beyond newly-compliant);
  per-cell deltas reported in full. PASS → apply-gate candidacy per
  the standing process.
- Iteration budget 2 from zero; scope = the destination decision ONLY
  (the operator's broader principle — demoting channels to weak priors
  wherever they act as hard boundaries — is recorded as the direction
  for FUTURE blocks, one seam at a time, each gated).

## Deliverables

scripts/v2_dyn_dest_instrument.py + runs/v2_week1/dyndest_*.json;
verdict here; then the composition arm per G-DYN-a if earned.

---

## VERDICT (2026-08-13) — G-DYN-i FAILED; heading is the wrong FEATURE
## at this projection, not the wrong PRINCIPLE

Measured (held-out, split-half, both gate windows):
  origin 28 @0.6-prefix: 0.760 / 0.565 (bar 0.85 both)   FAIL
  macro    @0.6-prefix: 0.661 / 0.666 (bar 0.75)          FAIL
  origin 28 @0.4-prefix: 0.613 / 0.628 (bar 0.70)         FAIL
  origin 28 @1.0 (complete track): **0.947 / 0.829** — the principle
  WORKS on complete geometry.

The physics: at cam2's oblique projection, an away-directed RIGHT turn
maps to ~zero image-space heading change (through −7.6° vs right −7.3°
at the 0.6-prefix; full-track right totals only −12.5°) while lefts
rotate −107°+. Image-space Δθ cannot see the world-frame rotation of
exactly the movement pair (through/right) the 99-vs-14 defect confuses
— the same projection wall that killed velocity-continuity and
appearance channels. Iteration 2's pre-named feature (signed lateral
displacement) does NOT fire by its own trigger (the confusion is
through/right, not left/right). Iteration 1 spent; LEDGER: "image-space
heading dynamics cannot separate through from right at truncated
prefixes under this camera's projection."

## The two directions this leaves (operator's call — both honor the
## path-over-time principle; they differ in FEATURE SPACE)

(a) POSITION-based path-over-time: score the truncated track's visible
    points against per-cell mean paths from the site's own fulls (the
    F16 whole-track-likelihood family; measured 0.957 held-out
    precision on fulls in the F2M instrument — position survives
    projection where heading does not). Applied to the DESTINATION
    RE-DECISION of kept entry-only events — a NEW seam (the F2M
    closure was the fragment-INSERTION composition, not this scorer).
    Would need its own block + gates (the G-DYN-a shape transfers).
(b) Stop: accept the projection wall for truncated destination
    assignment at cam2 and re-aim the campaign (A2 dual-rate / A4
    scale-matched 1280 remain the un-run Tier-3/4 builds).
