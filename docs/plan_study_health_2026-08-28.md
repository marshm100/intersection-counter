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

## S2 CALIBRATION RECORD (2026-08-28, one iteration per budget)

Changes from v1, chosen from the observed truth table:
- Divergence needs ratio AND materiality: RED ratio>=2.0 &
  excess_share>=0.035; AMBER ratio>=1.5 & excess_share>=0.025
  (ratio alone flagged the good b145 arm at 2.02x/1.3% while the real
  NB_left flood ran 2.39x/3.9%).
- twin_pairs demoted to informational (the dedup CAUGHT those pairs;
  cam3 at 83.7 carried 10% handled twin pressure).
- Operator-ruled divergence exceptions: cam1 leg 25 (the driveway
  ruling).

FINAL TABLE (battery blind to scores): every known-bad window/arm =
RED or AMBER (zero false-confidence greens — including cam2-0700 at
28.1 approach, caught AMBER via the near-band EB_right divergence);
known-good: cam3 83.7 GREEN, cam5-b145 70.8/81.2 GREEN,
cam1-1600 86.2/78.1 RED — the ONE miss, and its mechanism is
instructive: EB_right counts 492 vs a bank prior of 52 recorded when
that cell was UNDERCOUNTED by ~210. The flow prior indicts the
present because it memorized the broken past.
G-SD-1's separation bar (at most one miss each way): MET at
calibration.

CHARTERED FOLLOW-UP (not this campaign's build): BANK REFRESH — after
a shipped accuracy change, re-derive intersection_paths
supporting_count/sample_window_seconds from the shipped basis so the
flow priors describe the current truth; until then the health report
annotates divergence flags on recently-improved cameras.

## S2 ITERATION 2 (final; the two-iteration budget is now consumed)

The no-prior alarm split by PROVENANCE, measured on the two anchor
cases: the cam5 phantom cell ran 92% gate_full (the gates overrode
the path match — inflated boxes manufacturing witnessed journeys)
while cam3's genuine unsampled cell ran 2% (path-agreeing real
traffic). Rule: no-prior turn cell with gate_full share >= 0.5 = RED
"geometry phantom suspect"; below = AMBER "bank gap (unsampled real
traffic)". KNOWN IMPRECISION, accepted by design: a real cell whose
path is absent from the bank can also run high gate_full (cam2
WB_left ~84%, Miovision-confirmed real) — the card asks the operator
and resolves in a minute; "whatever is left over be solvable with a
human operator" is the mandate's own remedy.

FINAL SEPARATION (G-SD-1 bar: at most one miss each way): every
known-bad window/arm RED or AMBER, including the briefly-shipped cam5
phantom arm (now RED with the phantom named); zero bad windows pass.
One good window over-flagged: cam1-1600 (the stale-prior lesson; bank
refresh chartered). BAR MET. Further threshold work requires
redesign, not tuning.

## S4 OPERATOR REVIEW (2026-08-28, card health_reel_s4)

Six scenes ruled:
- Scenes 1-2 (Town East W_left "phantom suspect"): REAL left turns.
  The phantom-vs-bank-gap classifier over-fired exactly as the
  documented imprecision predicted (no bank path -> inflated
  gate-override share on real traffic). The card cost the operator
  ~a minute — the mandate's own remedy held.
- Scene 3 (fisheye 6x cell): the sampled vehicle is a real right
  turn (the cell's overcount is in its volume, not every member).
- Scene 4: inconclusive — INSTRUMENT NOTE: clips must run the full
  movement for slow vehicles.
- Scene 5 (Bluffview bank gap): real right turn — the gentle flag
  class is correct.
- Scene 6 (Barnes Bridge "W_left bank gap"): **A MISCOUNT FOUND** —
  a THROUGH counted as left. Operator spotted the mechanism on
  video: a dark car passes into shadow, detection stops, the
  truncated track completes wrongly. NEW NAMED DISEASE:
  LIGHT/SHADOW-BASED DETECTION DROPOUTS (same family as cam1's
  morning-light break) — chartered as a future lever, not built.
  The health card's flag led the operator's eyes straight to it:
  the instrument's end-to-end loop WORKED.
