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

## G-P1 VERDICT (2026-08-11) — FAILED. BLOCK STOPPED, SELECTOR LEDGERED.

`scripts/v2_pair_selector_probe.py`, all 12 windows, arms B (pair on) and
C (pair off) already on disk. No pass-2 runs, no backend change — the cheap
kill worked as designed.

  window            hours   gapB    gapC   gapC-gapB  5/95 delta  sign  n
  cam1 study_0700   07-09  0.247   0.225    -0.022       -9.3      OK   2
  cam1 study_1600   16-18  0.135   0.041    -0.095       -2.2      OK   2
  cam2 study_0700   07-09  0.194   0.195    +0.001       +2.2      OK   4
  cam2 study_1100   11-13  0.201   0.069    -0.132       +8.4    MISS   4
  cam2 study_1600   16-18  0.071   0.089    +0.017       -0.8    MISS   4
  cam3 study_0600   peaks  0.170   0.160    -0.009      +11.5    MISS   4
  cam4 study_0700   07-09  0.216   0.092    -0.123       +2.5    MISS   4
  cam4 study_1100   11-13  0.201   0.091    -0.110       +7.0    MISS   4
  cam4 study_1600   16-18  0.210   0.102    -0.108       -8.5      OK   4
  cam5 study_0700   07-09  0.114   0.077    -0.038       -7.7      OK   2
  cam5 study_1100   11-13  0.159   0.116    -0.043       -4.2      OK   2
  cam5 study_1600   16-18  0.125   0.095    -0.031      -13.2      OK   2

  G-P1 sign agreement 7/12          (gate >= 9/12)        FAIL
       on |delta| >= 7.0  4/7       (gate ALL)            FAIL
  G-P2 Spearman rho -0.210          (gate >= +0.60)       FAIL

**LEDGERED: corridor link agreement does not track attribution quality at
window scale on this corridor.** 7/12 is barely above the 6/12 chance line,
and it misses on cam3 (+11.5), cam2 study_1100 (+8.4) and cam4 study_1100
(+7.0) — three of the five windows a selector would exist to FIND.

**HOW it fails is more useful than that it fails.** `gapC - gapB` is
NEGATIVE at 10 of 12 windows: turning the pair ON makes link agreement
worse almost EVERYWHERE, whether the pair helps accuracy or hurts it. That
is a systematic bias, not a noisy signal. The mechanism is visible in what
the pair does: it BINDS origins to gate-evidenced legs, which shifts the
per-cardinal in/out balance in one direction; corridor links compare
exactly that balance. **The signal measures how much the origin
distribution MOVED, not whether it moved in the right direction.** Any
future selector built on cardinal in/out balance inherits this defect —
that is the transferable finding, and it disqualifies a family, not just
one metric.

Two method notes worth keeping, both measured here and both non-obvious:
- UNSCOPED corridor links are dominated by COVERAGE, not counting: on
  production the shipped check reports 0.58-0.64 gaps on every link
  touching intersection 3, purely because cam3 is the 24-hour camera
  (34955 events) and its neighbours cover only peaks. Anyone using
  `corridor_consistency` to compare RUNS rather than to flag a site must
  scope it, and must scope it on `timestamp_real` — `_cardinal_volumes`
  uses `timestamp_video`, which is not comparable across cameras with
  different recording starts.
- Per-hour coverage (production): cam1/2/4/5 carry events only in 07-09,
  11-13, 16-18; cam3 carries 06-20. cam3's study_0600 is therefore
  scoreable against neighbours ONLY on the peak overlap, which is what the
  probe does rather than dropping the window that carries the prize.

**Consequences.**
1. `EVIDENCE_ACTIVATION_COVERAGE = 0.45` STANDS as the honest best
   available rule. It is unchanged, and Block 0's finding that it is
   mostly right (correctly denying cam1 and cam5) is what makes that
   acceptable rather than merely unavoidable.
2. cam3's +11.5 remains real and remains unreachable blind. It is reachable
   only via extension's coverage lift, which costs -3.0 there — a net +8.5,
   which is exactly what production already has. **The corridor is at its
   measured optimum under the current mechanisms**; there is no free +11.5.
3. The block does NOT proceed to the adjudicator wiring (sequencing step 3
   was pre-conditioned on G-P1/G-P2 passing).

**Untried, and deliberately NOT pursued in this block** (the gate said
stop, and pre-declared gates that get relitigated in the same breath stop
meaning anything): `reverse_balance` as an alternative blind signal. It is
per-intersection rather than cross-intersection, so it does not obviously
inherit the cardinal-balance defect above — but it needs its own block with
its own pre-declared gates, and it should only be spent if something makes
the pair worth chasing again.

## Explicitly NOT in scope

Changing `EVIDENCE_ACTIVATION_COVERAGE`. Changing any flag default.
Re-running pass-2. Touching the applied production tables. Reviving
extension (LEDGERED closed in the confound-split doc — its only surviving
role is cam2, already applied, and the cam3 coverage lift whose value this
block is trying to reach directly instead).
