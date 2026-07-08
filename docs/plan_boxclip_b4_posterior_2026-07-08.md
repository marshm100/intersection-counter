# Plan — box-clip B4: lane-posterior assignment of ambiguous pieces (2026-07-08)

B3 (168406d): net −9.8% / MAE 17.4%, NB 1.7% PASS. Remaining error = two named
confusions: SB-thru −387 + SB-right −288 (ambiguous pre-divergence pieces
rejected to NEITHER cell), EB-right +184 ↔ EB-thru −112 (template starvation).

## Design revision: raw volume priors are BIASED — add the lane observation

The naive fix (split ambiguous pieces by resolved full-journey ratios) has a
measurable flaw: full-journey ratios are distorted by DIFFERENTIAL
FRAGMENTATION. Our resolved SB thru:right is ~13:1; Miovision says 3.65:1 —
because right-turners fragment differently. Assigning 93% of ambiguous SB
pieces to thru would leave SB-right at ~−250. Same story worse for EB-thru
(7 fulls ≠ 119 real).

But there is a GT-free signal the truncated pieces DO carry: **the lane they
crossed the gate in** (the crossing position projected on the gate axis).
Right-turners enter in the curb lane; throughs spread across lanes. That is
observed for every entry piece (and symmetrically, exit-lane position for exit
pieces), it survives truncation, and its per-cell distributions come from our
own resolved journeys. This is the (s,d) curvilinear matcher's d-coordinate
(MASTER_PLAN §2b lever ②) arriving by the shortest path.

**Posterior assignment:** for a piece ambiguous among tied cells S (fit ≤ 30 px
and within 1.43× of best): w(c) ∝ resolved-count prior (Laplace +1) × Gaussian
lane likelihood (μ,σ from resolved journeys' crossing positions at that gate;
σ floor 8 px; uniform if <3 samples). Deterministic proportional assignment
(credit accumulation, frame-ordered — no RNG), so counts match posterior mass
without per-vehicle pretence. Prior-assigned pieces still enter same-cell
entry/exit pairing (the double-count guard must not care how a cell was
chosen). Stubs: unchanged — no gate crossing means no lane observation; their
ambiguous stay rejected.

## EB-thru template: not a bootstrap — a support-floor fix

EB-thru has 7 full journeys; discovery requires 10. The bank builder's own
--min-support default is 5. Lower discovery min_support 10 → 5: EB-thru gets a
real data template from its 7 fulls, its fits become honest, and the pieces
EB-right has been stealing either flip or become ambiguous (where the lane
posterior decides). No feedback loop — discovery still uses ONLY full
journeys, never attributed members.

## Implementation order
1. classify() also returns origin/dest crossing POSITIONS → recs carry
   o_pos/d_pos (needed for lane stats and lane likelihood).
2. Lane stats per (gate, cell, side) from resolved full+chain journeys.
3. attribute() returns the tied set instead of rejecting on margin; posterior
   machinery assigns; source tag 'prior' (new matrix column).
4. min_support 5.
5. Ablations: (a) B3 + min_support only; (b) + posterior. Full trim + 30-min
   cut. Watch: SB-right recovers materially, EB mirror collapses, NB stays
   ≤2%, WB ≤ B3, u-turns stay ≤ ~25, phantom classes flat.

## Gate criteria (after B4 — then STOP adding mechanism)
- Gate A (cam2): beat live baseline net −4.5% / MAE 9.8% on full trim + 30-min.
- Gate B: freeze every constant; blind cam3–5 sweep + cam1 blind-gate
  re-validation. Only a Gate-B pass justifies app wiring (§4 item 5).
- If far-field approaches still fail post-B4 across cameras: the residual is
  detection recall (SB-right measured 58% once) — escalate to the detector
  workstream, not more pass-2 logic.
