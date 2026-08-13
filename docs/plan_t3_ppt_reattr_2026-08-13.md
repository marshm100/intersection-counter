# Tier-3 — POSITION-BASED PATH-OVER-TIME re-attribution (operator
# direction (a), 2026-08-13)

The operator's design principle (plan_t3_dyn_dest, recorded): the
movement is the path of the car over time — channels are layout
guidelines, never the decision. The heading feature obeys the principle
but dies at this camera's projection (G-DYN-i: 0.947 on complete
tracks, collapse at prefixes for through-vs-right). POSITION survives
projection: score the truncated track's visible points against
per-cell mean paths built from the window's OWN gate-verified full
journeys (real driven paths — NOT drawn geometry; the scorer measured
0.957 held-out free-mode precision on this camera in the F2M
instrument).

## The seam (NEW — distinct from the closed F2M family, recorded for
## budget honesty)

F2M (closed, 2 iterations) INSERTED events for uncounted fragments.
This block RE-ATTRIBUTES counted events whose track has ONE gate-proven
endpoint and one GUESSED endpoint — the measured 99-right-vs-14-through
defect class:
- entry_only track: origin gate-proven → re-decide the DESTINATION by
  scoring the LAST 60% of points against the proven origin's cells;
- exit_only track: destination gate-proven → re-decide the ORIGIN by
  scoring the FIRST 60% against cells into the proven destination.
One rule, applied symmetrically. Event COUNT never changes (zero-mass
invariant, asserted per window) — pure re-attribution between cells.
The scorer only OVERWRITES when its self-calibrated floors accept the
fit decisively; otherwise the existing attribution stands (conservative
by construction). Events whose stored proven-endpoint contradicts the
track's gate evidence are LEFT UNTOUCHED and censused (iteration-2
material at most). no_crossing events (both endpoints guessed) are OUT
of iteration 1 (pre-named iteration 2, only if iteration 1 passes and
the residual implicates them).

## GATES — declared before any run

- **G-PPT-i (instrument kill gate):** split-half on the window's own
  fulls, cam2 study_0700 AND study_1600: held-out precision of the
  CONSTRAINED re-decision (destination-given-origin from last-60%
  prefixes; origin-given-destination from first-60%) >= 0.90 at the
  self-calibrated floors (ATTR_MAX = p95 held-out best-cost; margin =
  weakest ratio reaching 0.95 precision — the F2M calibration,
  re-derived per window), with floor COVERAGE >= 0.60 (accepted share
  of held-out fulls — a scorer that only accepts 20% cannot touch the
  defect). FAIL → ledger; iteration 2 not triggered by an instrument
  miss.
- **G-PPT-a (counting gate; staged — study_0700 first, 1100/1600 only
  if its directional conditions hold):** composed DB (WAL-safe d1ctrl
  copy, events UPDATEd in place, stems `ppt_cam2_<win>`):
  (a1) event count per window IDENTICAL to control (asserted);
  (a2) EB_thru |err| strictly reduced AND EB_right |err| strictly
       reduced, per window;
  (a3) 5/95 >= control (53.4/42.9/44.0) on all 3 AND >= +1.0 on >= 1;
  (a4) no cell's |err| grows by > 5 counts (the robbing-Peter guard —
       re-attribution moves mass between cells);
  (a5) reported: the full from-cell→to-cell movement matrix, floors,
       touched/untouched census. Activation not in play (post-replay).
  PASS all → apply-gate candidacy per the standing process.
- Iteration budget 2 from zero.

## Deliverables

scripts/v2_ppt_reattr.py (instrument + compose modes; prototype/scorer
machinery imported from v2_f2m_pilot — instrument reuse, not family
revival); runs/v2_week1/ppt_*.json diagnostics; score JSONs; verdict
here.
