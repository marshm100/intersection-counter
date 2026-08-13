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

---

## ITERATION-1 RESULT (2026-08-13) — G-PPT-i PASSED (first instrument
## pass of Tier 3: precision 0.980/0.967, coverage 0.913/0.921);
## G-PPT-a FAILED (a2) at the staged window

study_0700 composition: 252 events re-attributed of 5,497 (zero-mass
held). **5/95 58.4 vs control 53.4 (+5.0) — the campaign's largest
clean single-window gain**: NB_left err 63→6, NB_thru 52→3, WB_left
36→3, WB_right 73→38, EB_left 14→12. BUT the binding (a2) cells both
WORSENED: EB_right err 142→194, EB_thru 85→98 — the position scorer
falls into the same EB-right attractor (36 SB_thru + 26 EB_left + 11
EB_thru events re-decided into 28→29). Block stopped before 1100/1600
per the staged rule. **FINDING: the EB through/right pair is
image-space UNRESOLVABLE at this camera — three independent feature
families (bank-shape guess, heading dynamics, position likelihood) now
fail on exactly that pair.** Everything separable, PPT separates.

## PPT-2 — the successor (operator-approved; the D1→C-1 pattern:
## exclude the proven-unresolvable, keep the proven-separable)

MECHANISM = iteration 1 with a FREEZE: no re-decision may read OR
write an origin-28 cell (skip when the event's current origin is 28 or
the proposed cell's origin is 28). The EB attribution stays exactly as
the control produced it — untouched, not worsened; what cannot be
fixed is not touched.

**G-PPT2-a (binding, ALL, per window, all three windows):**
  (b1) event count identical to control (zero-mass, asserted);
  (b2) the four origin-28 cells BYTE-EQUAL to control (by construction
       + asserted at score time);
  (b3) 5/95 >= control + 1.0 at EACH window (>=54.4 / >=43.9 / >=45.0);
  (b4) no cell's |err| grows by > 5 counts vs control;
  (b5) full movement matrix + census reported.
PASS all three → apply-gate candidacy per the standing process
(preflight vs live incumbents read-only; operator adjudicates any
apply). ANY miss → ledger; iteration budget closed.

---

## PPT-2 RESULT + OPERATOR RULING + CANDIDACY OUTCOME (2026-08-13)

Measured, all three windows (controls 53.4/42.9/44.0):
  study_0700  61.2 (63/103)  **+7.8**   beats LIVE production (55.8)
  study_1100  49.0 (51/104)  **+6.1**   under LIVE applied (50.4)
  study_1600  49.5 (54/109)  **+5.5**   beats LIVE production (44.0)
(b1) zero-mass held; (b2) EB cells byte-equal at all three; (b3)
cleared everywhere; **(b4) missed at 2 windows by 7-11 counts** at
already-deficient SB cells whose bins were already non-compliant (the
count-error guard proved blunter than the per-bin customer bar it
protects — the bar itself rose at every window).

**OPERATOR RULING (recorded): the (b4) miss is ACCEPTED as an
operator-approved deviation**; candidacy proceeded per the standing
process.

**Blind apply-gate adjudication vs LIVE incumbents (record=False):
STAND_DOWN x3** — 0700 [no_headroom, no_recovery], 1100 [no_recovery],
1600 [no_headroom, event_flood 0.259, no_recovery]. Evidence:
runs/v2_week1/preflight_ppt2.json.

**STRUCTURAL FINDING — the apply gate cannot pass a re-attribution
candidate BY CONSTRUCTION:** `no_recovery` fires on any zero-mass
candidate (the gate's evidence model assumes candidates compete on
added recall), and its flood metric cannot distinguish precision-0.98
attribution movement into census-thin cells from garbage movement. The
gate is behaving correctly BY ITS OWN RULES and those rules predate
the existence of attribution-class candidates. Per the standing
process, gate refusal is binding: PPT-2 DOES NOT SHIP today.

## Where this leaves it (for the operator / next session)

1. PPT-2 stands as the campaign's first mechanism to clear its
   instrument gate AND deliver headline gains on the customer bar at
   every window (+7.8/+6.1/+5.5 over base; +5.4/+5.5 over LIVE at
   0700/1600), blocked only by the gate's structural blind spot.
2. The legitimate path: **GATE-AG2 — a re-attribution adjudication
   mode for the apply gate** (its own block, its own pre-declared
   validation: the 12 known pairs must still adjudicate 11/11, plus
   re-attribution-specific guards — e.g. movement-matrix mass bounds,
   census-consistency of net cell deltas, zero-mass verification —
   validated blind before any live use). The gate is the protection
   layer; it gets extended with the same rigor it enforces.
3. NOT legitimate: applying around the gate. The 2026-08-10 precedent
   applied THROUGH the gate; the gate exists because manual judgment
   failed before it.
4. At 1100 the correct candidate would compose PPT-2 ON TOP OF the
   applied artifact (re-attribute the live table, not the base) —
   noted for GATE-AG2's candidate-preparation step.
