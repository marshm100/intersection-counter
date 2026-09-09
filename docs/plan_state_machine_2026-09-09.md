# THE JOURNEY STATE MACHINE (2026-09-09) — G-SM-1 declared

Operator rules (his ruling of cam2 track 17526, end to end):
  R1 a crossing counts only when BOTH bottom corners cross the line
  R2 EXITED IS TERMINAL — once a vehicle has left, its id can never
     re-enter
  plus his approved split: accept a single-corner crossing when the
  TRACK ENDS there (truncated by tracking loss, not by the vehicle
  staying put).

Measured basis — solo (one-corner) crossings by what follows:
                  corner gap        ends <1s      continues >100f
  cam1 (10fps)  med 2f p99 21f        50%              9%
  cam2 (25fps)  med 9f p99 64f         6%             79%
The cameras are mirror images: cam1's solos are departures (which is
why either-corner earned it +8.5/+9.1), cam2's are wobble. The
truncation split is the single rule correct on both.
Straddle signature (corners disagree on direction over one line): 28
on cam1, 96 on cam2 — impossible for a genuine crossing.

Constants: CORNER_PAIR_WINDOW_S = 2.5 (p99 of the observed gap on
both cameras), CROSSING_TRUNCATION_S = 1.0 (where the two populations
separate 50% vs 6%).

SUPERSESSION: this flag subsumes GATE_GROUND_ANCHOR,
GATE_EVIDENCE_EITHER_CORNER and JOURNEY_FIRST_EXIT. It is validated
against the SHIPPED combination, never against bare defaults.

## G-SM-1 (declared before any scoring; two iterations)

1. cam1 0700 + 1600 — SHIPPED. HARD CONSTRAINT: neither may fall
   below 83.5 / 95.3.
2. cam2 x3 — EB_right excess (+169/+93/+310 vs Mio) must shrink and
   u-turn cells must not grow.
3. cam3 0600 — SB u-turns (38 vs Mio 0) must shrink; movement must
   beat the fleet arm's 85.4.
Cell tables + phantom-slack check mandatory on every arm. Coverage
and activation reported per window (cam1-0700 sits at 0.474 vs the
0.45 bar). Named checks: track 17526 must yield NO W crossings and a
single S exit; 16722 must stay OCCUPYING(W) -> EXITED(S).

## Build (2026-09-09)

backend/config.py: JOURNEY_STATE_MACHINE (default OFF),
CORNER_PAIR_WINDOW_S = 2.5, CROSSING_TRUNCATION_S = 1.0.
backend/services/entry_gates.py: pair_crossings() (the crossing law:
pair / straddle veto / truncation exemption) and classify_pair()
(ENTERING -> OCCUPYING -> EXITED, exit terminal), returning
classify()'s 7-tuple. The u-turn admission block lifted to
_uturn_admissible() and shared, not copied. A same-leg exit failing
the u-turn tests is jitter and the machine keeps looking (the
first-exit ruling, subsumed).
backend/services/pipeline.py: _gate_evidence dispatches to
classify_pair under the flag; flag off is byte-identical.
backend/tests/test_state_machine.py: 15 tests (iteration 1); full
suite 1192 green.
scripts/sm_named_checks.py: 17526 -> 1 valid crossing before the
exit, OUT over S; W crossings none; the 2 post-exit crossings retired
(exit_only — it LOSES its W entry exactly as predicted above, since it
crept over the line while stopped). 16722 -> OCCUPYING(W) ->
EXITED(S). BOTH NAMED CHECKS PASS.

## G-SM-1 iteration 1 verdict (recorded 2026-09-09): MISS

Arms: shipped flags + JOURNEY_STATE_MACHINE, pass-2 over the existing
dumps, stem sm (scripts/fleet_flags.py FLEET_STEM=sm), scored by
v2_score_dev. NOTE ON THE BASIS: the on-disk score_ff_* files were
overwritten by yesterday's G-FX-1 arm, so the cell columns below
compare against G-FX-1 (shipped flags + first-exit); the fleet-arm
headline numbers come from plan_first_exit / plan_fleet_flags.

  window       shipped/fleet   G-FX-1   SM iter1   cov    channel
  cam1 0700        83.5          83.3      75.0    0.391    OFF   FAIL (hard floor)
  cam1 1600        95.3          95.3      95.1    0.522    ON    FAIL (hard floor, -0.2)
  cam2 0700        70.5          68.2      71.4    0.502    ON    EB_right 336 -> 292 (Mio 167)
  cam2 1100        73.9          75.2      34.6    0.440    OFF   channel lost
  cam2 1600        72.3          69.9      32.1    0.382    OFF   channel lost
  cam3 0600        85.4          86.2      86.6    0.507    ON    SB_uturn 38 -> 46 (Mio 0) FAIL

1. HARD CONSTRAINT BROKEN on both cam1 windows. cam1-0700 lost the
   evidence channel (coverage 0.474 -> 0.391 against the 0.45 bar)
   and fell to 75.0 — the pre-flag standing. cam1-1600 held the
   channel but slipped 0.2.
2. cam2: where the channel stayed on (0700) the target moved the
   right way: EB_right 336 -> 292, EB_uturn 4 -> 1, movement +0.9 over
   the fleet arm, approach 31.2 -> 46.9. The other two windows fell
   under the activation bar and their cell tables are the channel-off
   collapse, not the rule (SB_uturn 2 -> 27 / 8 -> 62 there is what
   the non-evidence path does, cf. cam5's history).
3. cam3: movement 86.6 beats 85.4, but SB_uturn GREW 38 -> 46
   against Mio 0 and EB_uturn 6 -> 7. The u-turn phantom class is not
   what this rule reaches. Phantom-slack check FAILS on cam3 and on
   both cam1 windows (cam1-1600 NB_right 15 -> 17, SB_uturn 1 -> 3).

WHY (scripts/diag_sm_solo_entries.py, pass-1 rows, solo INWARD
crossings the machine refused, by where the OTHER corner was):

                     refused   born      still     straddle  beyond
                     entries   ACROSS    OUTSIDE   veto      seg end
  cam1 0700 (10fps)    632     531 (84%)   90        11        0
  cam1 1600            537     385 (72%)  138        13        0
  cam2 0700 (25fps)    951     684 (72%)  217        36       12
  cam2 1100            824     461 (56%)  302        28       31

"Born across" = the other corner was already INSIDE the gate on the
track's FIRST frame and never crossed it. The vehicle was detected
with its box already straddling the threshold — far-field detection
latency — so the leading corner's crossing was never observable. The
truncation split anticipated tracks that END at a crossing; this is
the same truncation at the START. It is 18% of all witnessed entries
on cam1-0700, and it is the whole coverage loss.

The "still OUTSIDE" column (90-302 per window) is the wobble/creep
class the rule was built to refuse; whether every one of those is
truly a non-entry is not established (some may be slow real entries
that never complete within the track).

## G-SM-1 iteration 2 (declared 2026-09-09, before scoring)

AGENT INFERENCE, NOT AN OPERATOR RULING — put to him with the tables:
BORN-ACROSS EXEMPTION. A solo INWARD crossing also counts when the
other corner was inside that gate on the track's first frame and has
no earlier crossing of it. Entries only — an outward solo never earns
it (17526 would otherwise book a false W exit: its right corner was
outside at birth when the left corner crept out). Named checks re-run
under the clause: 17526 unchanged (no W crossings, single S exit),
16722 unchanged. 3 new tests (born-across accepted; a corner that
crept out earlier refused; never applies to an exit).

Same gate, same arms, stem sm2: cam1 floors 83.5 / 95.3; cam2
EB_right shrinks and u-turns do not grow; cam3 SB_uturn shrinks
below 38 and movement beats 85.4; cell tables + phantom-slack on
every arm; coverage per window.

## Iteration 2 verdict

(to be recorded)
