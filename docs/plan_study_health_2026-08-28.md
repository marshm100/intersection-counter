# STUDY HEALTH — the self-diagnosis campaign gate doc (declared 2026-08-28)

Operator mandate: "the goal is to have the machine beat the 5/95
standard on its own and whatever is left over be solvable with a human
operator... on new videos we will not know what is broken unless the
machine can identify it." Plan: the approved SELF-DIAGNOSIS CAMPAIGN
(plan file 2026-08-28). Read-only instrumentation; no counting-path
changes anywhere in this campaign.

## v1 thresholds (DECLARED; S2 replaces with the calibrated set)

- activation.activated == False        -> RED (evidence channel off)
- guessed_share >= 0.55 RED, >= 0.35 AMBER
  (guessed = posterior_source in branch1/rescue_full/rescue_supports/
   demoted/dest_tie)
- turn-cell flow divergence >= 2.0x bank-expected at n >= 30 -> RED
- twin_rate (twin_pairs / counted) >= 0.03 -> AMBER
- entry_coverage < 0.35 RED, < 0.50 AMBER
- echo_share >= 0.04 -> AMBER (footage_rating's frozen fair line)
Verdict = worst; reasons listed. classify_signals is pure.

FIRST LIVE READING (S1 smoke, shipped cam2 study_1600 @ 70.3): the
battery fired RED on the EB_right fisheye cell at 6.05x historical
flow (968 counted vs ~160 bank-expected; Miovision truth 699 — the
cell IS genuinely overcounted). First blood: the instrument flagged a
real disease on our best-shipped camera with zero reference access.

## S2 calibration (to run): the truth table over every corridor
camera-window with known measured accuracy + the known-bad arms
(cam5-1100 NB_left flood, cam4 collapses, cam1 morning). Thresholds
chosen from observed separation; two-iteration budget; no threshold
fishing.

## G-SD-1 (the acceptance, declared): masked-corridor — the battery
separates known-bad from known-good windows with at most one miss
each way; the operator's review of ONE rendered report + its cards
finds no false-confidence window. Accept ships the feeder + endpoint
into the standard flow; reject ledgers and iterates within budget.
