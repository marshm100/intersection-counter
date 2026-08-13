# GATE-AG2 — a RE-ATTRIBUTION adjudication mode for the apply gate
# (2026-08-13, operator-approved "Go for GATE-AG2")

The apply gate's recall-mode guards (headroom / flood / recovery)
assume candidates compete on ADDED mass; a zero-mass re-attribution
candidate fails `no_recovery` by construction (measured: PPT-2 stood
down x3, preflight_ppt2.json) and its `d_cov` degenerates to
"census-excess reduction" — fulls-biased AGAINST the truncation-hit
cells re-attribution correctly fills. This block adds `mode=
"reattribution"` with guards a blind gate can honestly enforce, under
the gate's own validation discipline. The recall mode is untouched
byte-identically (parity-gated).

## What a blind gate CAN verify about a re-attribution (the guard set)

1. **mass_change** — n_cand == n_inc exactly, else stand_down. This
   single guard also structurally enforces COMPOSE-ON-INCUMBENT: a
   candidate composed on the wrong base (e.g. PPT-2-on-base at the
   applied 0700/1100 windows: 5497 vs live 5815, 4203 vs 4426) fails
   here — correctly, since it would discard the incumbent's applied
   gains.
2. **endpoint_integrity** — the gate RECOMPUTES, from the window's own
   dump through the pinned gates (late-imported two_pass machinery,
   the gate's existing census pattern): for every MOVED cell-changing
   event, the track's proven gate endpoints must be preserved
   (entry_only: origin unchanged; exit_only: destination unchanged)
   and gate-verified FULL tracks must not be moved at all. ANY
   violation → stand_down. A garbage re-attributor breaks this
   massively; a legitimate one never touches proven evidence.
3. **moved_share** — Σ|cand_c − inc_c| / 2 / n_inc <= REATTR_MOVED_MAX
   (runaway re-attributors move far more than decisive-fit ones).
4. **concentration** — max single-cell gain / moved mass <=
   REATTR_CONC_MAX (the adversarial same-endpoint dump-into-one-cell
   shape; endpoint integrity alone cannot catch it).
5. **saturated_geometry** — unchanged from recall mode (contrast still
   gates trust in the census machinery the integrity check rides on).

What the gate CANNOT verify blind — the correctness of the re-decided
UNPROVEN endpoint — remains the mechanism's instrument-gate burden
(PPT: 0.980/0.967 held-out, committed) plus the operator's per-window
adjudication. Recorded honestly, not papered over.

## Constants: frozen by DECLARED CHOICE RULE, not swept

REATTR_MOVED_MAX and REATTR_CONC_MAX are set as the tightest round
values that pass the positive validation candidate with >= 1.5x margin
— then every constructed negative must still fail. If no such values
exist, the mode FAILS validation. (The AG1 frozen-constant precedent.)

## GATES

- **G-AG2-p (parity):** with the code present and mode unset, the AG1
  validator (scripts/v2_apply_gate_validate.py) reproduces the
  committed runs/v2_week1/apply_gate_validation.json verdicts
  EXACTLY (12/12 rows, decisions and reasons), and the full test
  suite stays green.
- **G-AG2-v (validation, ALL verdicts must match expectation; Miovision
  consulted only AFTERWARD per the AG1 pattern):**
    P1  ppt2_1600 vs live (live==base there; zero-mass eligible)
        → expected APPLY (yardstick afterward: 49.5 > 44.0)
    N1  ppt2_0700-on-base vs live      → STAND_DOWN (mass_change)
    N2  ppt2_1100-on-base vs live      → STAND_DOWN (mass_change)
    N3  random re-attribution of ppt2_1600's moved events (same count,
        random target cells, seeded)   → STAND_DOWN (endpoint_integrity)
    N4  adversarial same-proven-endpoint concentration (entry_27
        events moved 27→29 into 27→28, one attractor cell)
                                       → STAND_DOWN (concentration)
    N5  mass impostor (ppt2_1600 minus one event)
                                       → STAND_DOWN (mass_change)
  6/6 required. FAIL any → the mode does not ship; ledger.
- **After G-AG2-v:** re-run PPT-2@1600 through the validated mode
  (record=False) as the live candidacy read; any actual apply remains
  operator-adjudicated per window. The 0700/1100 candidacy requires
  COMPOSE-ON-LIVE candidates (re-attribution of the applied tables on
  the v2c dumps) — a NAMED follow-up, not this block.

## Deliverables

backend/services/apply_gate.py (mode param + pure reattribution rule +
integrity helper, late imports), backend/config.py (two frozen
constants), backend/tests/test_apply_gate_reattr.py,
scripts/v2_gate_ag2_validate.py (builds N3/N4/N5 from the P1 DB,
runs all six + the AG1 parity rerun), validation JSON, verdict here.
