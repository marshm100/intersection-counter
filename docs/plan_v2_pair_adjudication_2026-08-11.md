# Plan — THE EVIDENCE PAIR AS A PER-WINDOW ADJUDICATED CANDIDATE
# (2026-08-11)

Successor to `plan_v2_confound_split_2026-08-11.md`. Block 0 measured what
the gate+posterior attribution pair is actually worth, window by window,
and the answer is that a single global coverage threshold is the wrong
shape of decision for it.

## The prize, measured

5/95 delta from turning the pair ON, all 12 corridor windows (Block 0,
arm B vs arm C — same dump, same V2 flags, pair the only difference):

  cam3 study_0600   **+11.5**      cam2 study_1600    -0.8
  cam2 study_1100    +8.4          cam1 study_1600    -2.2
  cam4 study_1100    +7.0          cam5 study_1100    -4.2
  cam4 study_0700    +2.5          cam5 study_0700    -7.7
  cam2 study_0700    +2.2          cam4 study_1600    -8.5
                                   cam1 study_0700    -9.3
                                   cam5 study_1600   -13.2

Range +11.5 to -13.2, and it varies WITHIN a camera (+8.4 / +2.2 / -0.8
across cam2's three windows). `EVIDENCE_ACTIVATION_COVERAGE = 0.45` is a
per-camera-window threshold on a blind coverage proxy; it cannot express
this.

**The bar is nevertheless mostly RIGHT and must not be lowered.** On base
dumps it denies cam1 (-9.3/-2.2) and cam5 (-7.7/-4.2/-13.2) — the two
cameras where the pair is most harmful — and admits cam2, where it mostly
helps. Its one clear corridor error is cam3: coverage 0.431, 0.019 short,
worth +11.5. A global threshold change is net-negative. This block does
not propose one.

## The design question this block exists to answer

> Is there a GT-FREE signal, computable per window, that predicts the sign
> (and ideally the magnitude) of the pair's 5/95 effect?

If yes, the pair becomes an adjudicated candidate under the existing apply
gate and cam3's +11.5 becomes reachable without extension's -3.0. If no,
the 0.45 bar stays as the honest best available rule and this block
LEDGERS a measured-dead selector — which is still worth knowing, because
it closes the question rather than leaving it as a standing "we should
probably adjudicate this".

## THE CIRCULARITY CONSTRAINT (binding — read before proposing a signal)

The obvious selector is the gate-evidence census (`strict_full_census` /
`cell_census`), and it is DISQUALIFIED. The pair attributes USING gate
evidence, so a pair-on result agrees better with a gate-evidence census by
construction. `entry_gates.cell_census` already carries an explicit
circularity guard for the same reason ("never allocated by bank supports
or the posterior's output"). Any selector built on gate evidence measures
the mechanism against itself.

The apply gate's own guards (headroom / flood / covered-mass) are all
computed against that census, so **the apply gate as it stands cannot
adjudicate this candidate.** That is the central difficulty of this block
and must not be papered over: the gate is the right ARCHITECTURE (per
window, blind, audited, with dispositions) but its current EVIDENCE is
circular for this particular choice.

## The candidate signal: corridor link consistency

`conservation_qa.corridor_consistency` compares adjacent intersections on
their shared links (A.out_north ~ B.in_south). It is structurally
independent of any single camera's attribution mechanism — the neighbour's
count is produced by a different camera, different geometry, different
calibration. That independence is exactly what the census lacks.

Already shipped: `conservation_qa.py:271`, constants `CORRIDOR_WARN=0.15`,
`CORRIDOR_FAIL=0.30`, `MIN_LINK_VOLUME=30`; consumed by
`spot_check.acceptance` and `coverage_qa.localize_corridor_gaps`. The
research synthesis lists corridor link cross-validation as standard vendor
QA (item 5) and wrongly records it as unbuilt.

**Feasibility, checked:** a pass-2 working DB is a copy of project.db with
only the replayed camera's events swapped, so all five cameras and all
five intersections are present (verified: cam1 14141 / cam2 17643 / cam3
29961 / cam4 4075 / cam5 15499 events in `twopass_cam4_v2c_study_1100.db`).
Both arms exist on disk for all 12 windows. **The whole experiment needs
NO new pass-2 runs.**

**Obstacle to design around, not ignore:** `_cardinal_volumes`
(`conservation_qa.py:133`) aggregates over ALL events for an intersection.
The replayed camera covers a 2-hour window; its neighbours carry full-day
production. Unscoped, the link gap is dominated by that mismatch and the
signal is swamped. The block must add a wall-clock window scope to the
volume query (a `WHERE timestamp_real BETWEEN ...` on both sides), which is
a new parameter on an existing shipped function and must default to
today's unscoped behaviour so `acceptance`/`export_gate` are byte-unchanged.

**Second caveat to state in the verdict:** the neighbours' production
events for cam2 and cam3 are now the APPLIED v2c tables (2026-08-10). That
is a fixed reference across arms B and C, so it is sound for a within-window
comparison, but it means the link reference is not a pristine baseline and
the block must say so rather than imply independence it does not have.

## Pre-declared gates

- **G-P1 (the entry gate — does the signal predict anything?).** Across
  the 12 windows, the change in corridor link gap (pair-on minus pair-off)
  must correlate with the measured 5/95 delta with the CORRECT SIGN on at
  least 9 of 12 windows, and must get the sign right on all three windows
  where |5/95 delta| >= 7.0 (cam3 +11.5, cam2 study_1100 +8.4, cam5
  study_1600 -13.2, cam4 study_1600 -8.5, cam1 study_0700 -9.3). A
  selector that cannot call the big ones is useless regardless of its
  average.
  *FAIL -> LEDGER: "corridor link agreement does not track attribution
  quality at window scale on this corridor." The 0.45 bar stands as the
  honest best rule, and the block stops. This is a real possible outcome:
  the corridor's links are ~2400 vehicles/window and the pair moves
  hundreds, so the signal may simply be below the noise floor.*
- **G-P2 (magnitude, not just sign).** Rank correlation (Spearman) between
  link-gap improvement and 5/95 delta >= 0.6 across the 12 windows.
  *FAIL but G-P1 PASS -> the signal is a usable GATE (ship/stand-down) but
  not a usable SCORE; adjudicate with a threshold, do not rank with it.*
- **G-P3 (no regression to the shipped QA).** With the new scope parameter
  defaulted off, `conservation_qa.corridor_consistency`,
  `spot_check.acceptance` and `export_gate` return byte-identical results
  on the corridor, and the full suite stays green (baseline 929).
- **G-P4 (independence honesty).** The verdict states, per window, whether
  the link reference on each side is production-original or an applied v2c
  table, and repeats G-P1 on the SUBSET whose neighbours are untouched by
  the 2026-08-10 apply (cam1, cam4, cam5 neighbours). If the correlation
  holds only where the reference is applied-v2c, it is an artifact.
- **Scope guard:** read-only throughout. No flag defaults change in this
  block. No pass-2 re-runs. Production untouched.

## Sequencing

1. This plan doc (commit 1).
2. Window-scoped volume query + `scripts/v2_pair_selector_probe.py`
   computing, per window per arm, the corridor link gaps for the replayed
   camera's intersection against its neighbours; correlate with the Block-0
   5/95 table (commit 2). Read G-P1 FIRST — it is the cheap kill.
3. Only if G-P1/G-P2 pass: design the adjudicator wiring (a sibling of
   `apply_gate.adjudicate_counts` taking link agreement instead of census
   guards), with its own pre-declared gates in a follow-on block. NOT in
   this block — this block only answers whether a blind selector exists.

## Explicitly NOT in scope

Changing `EVIDENCE_ACTIVATION_COVERAGE`. Changing any flag default.
Re-running pass-2. Touching the applied production tables. Reviving
extension (LEDGERED closed in the confound-split doc — its only surviving
role is cam2, already applied, and the cam3 coverage lift whose value this
block is trying to reach directly instead).
