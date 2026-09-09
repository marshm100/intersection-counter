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

## Iteration 2 verdict (recorded 2026-09-09): PARTIAL — MISS on the
## letter of the gate, the channel restored everywhere, cam2 morning
## and midday the best they have ever scored

TRAP FIRST: the first iteration-2 "run" finished every window in 1 s
with iteration-1's numbers — the sidecar reuse keyed on the flag
fingerprint, and the law changed without a flag moving (the same
trap as 2026-09-08, one layer down). flags_fingerprint now digests
entry_gates.py's source; the six scratch sidecars were deleted and
the arm recomputed (stem sm2, log _replay_scratch/gsm2b.log).

  window       fleet arm   SM iter1   SM iter2   cov     gate
  cam1 0700       83.5        75.0       83.8    0.464   PASS floor (+0.3, channel back ON)
  cam1 1600       95.3        95.1       95.1    0.569   FAIL floor by 0.2
  cam2 0700       70.5        71.4       76.2    0.576   +5.7  EB_right 316 -> 286 (Mio 167)
  cam2 1100       73.9        34.6       77.7    0.495   +3.8  EB_right 477 -> 438 (Mio 351)
  cam2 1600       72.3        32.1       68.8    0.495   -3.5  EB_right 991 -> 849 (Mio 699)
  cam3 0600       85.4        86.6       85.1    0.575   FAIL movement by 0.3; SB_uturn 38 -> 27 (Mio 0)

Against the declared gate:
1. cam1 floors: 0700 clears (83.8 vs 83.5; coverage 0.391 -> 0.464,
   events 4,676 -> 4,904, SB_thru 1552 -> 1753 restored). 1600 does
   NOT (95.1 vs 95.3) on either iteration: EB_right 501 (Mio 497),
   NB_thru 2118 vs shipped 2128, SB_thru 2544 vs 2541 — a 0.2 slip
   with no cell moving more than 10. FAIL on the letter.
2. cam2: EB_right SHRINKS on all three windows (316/477/991 ->
   286/438/849 against Mio 167/351/699) and EB_uturn collapses to
   1/0/0 (Mio 2/0/1). But NB_uturn on 1600 grows 3 -> 5 (Mio 0) and
   SB_uturn there 8 -> 9 (Mio 12) — "u-turn cells must not grow" is
   broken by +2 on one sub-10 cell. Movement: two windows up by the
   largest margins recorded (+5.7, +3.8), 1600 down 3.5 (SB_thru
   2069 vs Mio 2247, SB_right 389 vs 341: the evening excess is a
   different signature, as flagged in plan_cam2_rights).
3. cam3: SB_uturn 38 -> 27 (the plan's target, met; note 27 equals
   production, i.e. the class the fleet flags inflated 27 -> 88 is
   fully undone), NB_uturn 28 -> 16, but movement 85.1 is 0.3 under
   the fleet arm's 85.4 and EB_right grew 176 -> 208 (Mio 155).
   EB_uturn 7 -> 8. FAIL on the letter.
Phantom-slack: FAIL on every window except cam2-0700 — always by 1-2
on a sub-10-Mio cell (cam1-0700 EB_thru 1 -> 2, cam1-1600 NB_uturn
0 -> 1, cam2-1100 NB_uturn 0 -> 1, cam2-1600 NB_uturn 3 -> 5, cam3
EB_uturn 7 -> 8). None is a class; all are within the noise the
check exists to catch, reported as declared.

WHAT THE RULE DID: coverage is back above the bar on all six windows
(the born-across clause was the whole entry loss); the evidence
channel activates everywhere. The waiting-vehicle class (cam2 EB_right
wobble exits) shrinks 30-142 events per window. The cam3 SB u-turn
phantom class is halved against the first-exit rule and returned to
production's level. The costs are marginal (0.2 / 0.3) on two
windows and real (-3.5) on cam2 evening.

NOT SHIPPED. Per-window ship is the operator's call; candidates on
the numbers are cam2 0700 (76.2 vs live 70.4), cam2 1100 (77.7 vs
71.3) and cam1 0700 (83.8 vs 83.5). Both cam1 windows would run under
this flag INSTEAD of GATE_GROUND_ANCHOR + GATE_EVIDENCE_EITHER_CORNER
in _gate_evidence (STRAIGHT_FRAGMENT_RULE still applies). The
born-across clause itself is agent inference awaiting his ruling.

OPERATING NOTE: scripts/fleet_flags.py now runs windows in parallel
(FLEET_WORKERS, default 6; operator go 2026-09-09). Expected arm wall
time ~15 min (cam3) instead of ~28.

## OPERATOR: "nothing more than requiring more debugging and visual
## analysis on our part ... part of the natural process of making headway"

Nothing ships. Four reels in order, then build on all four rulings:
  1. born-across entries (cam1 0700)         -- the unruled clause
  2. cam2 evening regression                 -- what moved away from Mio
  3. cam3 EB_right growth 176 -> 208         -- what the entry rule admitted
  4. cam3's 27 surviving SB u-turns          -- the open class

## REEL 1 — born-across entries, cam1 study_0700 (2026-09-09)

scripts/viz_born_across.py: 531 in the window, 5 even-spread, filmed
as screenshots/born_across_{n}_{tid}.gif; reel page
https://claude.ai/code/artifact/b18558f0-955c-4a46-b380-2076b15241fc

OPERATOR RULINGS (his words):
  1  tid 2      "the bounding box spawned with one of the corners in
                 the intersection already. it is a clean track for a
                 through vehicle but that was the error."
  2  tid 4829   "detection occurs late because of the sun glare and
                 detection is lost mid intersection due to sun glare
                 but it is a through vehicle."
  3  tid 9205   "there is a massive occlusion caused by an 18 wheeler
                 and I am not sure if the correct vehicle was picked
                 up again after the 18 wheeler moved but a vehicle was
                 picked up and then was prevented from being viewed as
                 crossing the exit bar due to another large box
                 vehicle occluding the view of the tracked vehicle but
                 regardless the vehicles moving that were being
                 tracked were through movements."
  4  tid 14948  "the same story, a box truck occluded view near the
                 exit and redetection did not fire in time to catch
                 the through vehicle being tracked to complete the
                 movement."
  5  tid 22270  "a corner spawn error where the corner spawns in the
                 intersection preventing the mouth from being
                 triggered by our rule but it correctly tracks a right
                 hand turn of a single vehicle."

FIVE OF FIVE ARE REAL VEHICLES AND REAL ENTRIES. The born-across
clause is doing what it was built for on this sample. Two mechanisms
in his rulings: the CORNER SPAWN (clips 1, 5 — the box is born with a
corner already inside; near-field) and LATE DETECTION under glare /
occlusion (clips 2-4 — far-field S mouth, the entry is real, the EXIT
is then lost to glare or a large occluder so the track is entry-only).
The clause stays; his phrase "corner spawn error" names the mechanism.
Clip 3 carries an open doubt about identity after the 18-wheeler.

## REEL 2 — cam2 study_1600 regression (2026-09-09)

Track-level diff of the G-FX-1 arm vs SM iteration 2 (working DBs):
317 tracks change cell. The dominant transition, 112 tracks:
      W_right -> S   became   N_through -> S
plus 37 W_right->S -> N_right->W, 15 W_left->N -> N_right->W, 12
W_through->E -> N_left->E. ONE MECHANISM: the W ENTRY IS REFUSED,
the S exit is kept (exit_only), and with no witnessed origin the
posterior fallback guesses N (0.60-0.76 vs W 0.24-0.40). That is
the -3.5: real W-origin vehicles rebooked as N-origin. (Both EB_right
and SB_thru totals moved TOWARD Mio, which hid it in the cell table;
SB_right +62 and EB_thru/EB_left -27/-22 are where it shows.)

Why the W entry is refused (scripts/viz_pair_reel.py ledgers): the
two corners cross the W line 4-23 s apart — far outside the 2.5 s
pairing window — and in between one corner wobbles OUT over W
repeatedly (tid 9031: nine times in 20 s). Neither crossing pairs,
neither is born-across (the other corner has an earlier W crossing),
the track continues, so every W crossing is refused. These are the
WAITING-TO-TURN vehicles at the W mouth: the 17526 shape. The rule
that killed 17526's four false W exits also kills these real W
entries — the same signature, opposite truth.

Filmed 5 of the 112 even-spread (screenshots/c2_origin_{n}_{tid}.gif,
tids 112 4383 9031 18964 26259); reel page for his ruling.

Full-frame WebM reel pages (his ruling: NEVER crop a review clip):
  part 1 https://claude.ai/code/artifact/1dcdc600-0d35-4d01-a717-8c7e0c6fddc7
  part 2 https://claude.ai/code/artifact/a84350be-e237-4e40-a385-ae9728e0a681

OPERATOR RULINGS, reel 2 (his words):
  1  tid 112    "a thief, the detector was doing a good job maintaining
                 lock while through traffic was passing but then a
                 through vehicle (N to S) stole the lock while the car
                 was waiting for traffic to clear to make a move."
  2  tid 4383   "clean right turn its likely just a spawn error where
                 the detection spawns the corner beyond the mouth gate
                 and then closes properly at the exit gate, so this
                 affects the criteria for transitioning from entering
                 to occupying."
  3  tid 9031   "a vehicle occlusion theft. The target vehicle is
                 occluded by a box truck and a normal truck moving N
                 to S at the same time, the box truck blocks the
                 vehicle and the normal truck is the thief."
  4  tid 18964  "same type of corner spawn error"
  5  tid 26259  "occlusion theft error"

REEL 2 TALLY: 3 thefts (1, 3, 5) + 2 corner spawns (2, 4). The
112-track class is TWO problems: (a) the waiting car's box is stolen
by a N->S through — anti-theft territory (EMERGENCE_GUARD /
CONCEALER_ORIGIN_INHERITANCE, docs/plan_anti_theft_2026-09-06.md),
where the machine's refusal of the W entry is a symptom, not the
cause; (b) a real right turn whose box spawned with a corner beyond
the W mouth and wobbled — the born-across clause must survive the
spawned corner's later wobble (his words: "affects the criteria for
transitioning from entering to occupying").

NOTE ON 1 AND 3: the thief IS a N->S through, so the machine's
posterior guess "N_through->S" happens to describe the thief's
movement — but the lifecycle is wrong (the waiting car's W entry was
real; the S exit belongs to another vehicle) and the earlier arm's
"W_right->S" was wrong too (a phantom right made of two vehicles).
Neither booking is a count of what the waiting car did.
NOTE ON 2: the spawn put a corner beyond the W gate, then that corner
wobbled OUT over W twice, so the born-across clause (which requires
no earlier crossing by the other corner) did not fire. His reading:
the ENTERING -> OCCUPYING criterion must tolerate a spawn beyond the
mouth even when the spawned corner later wobbles.

## REEL 3 — cam3 study_0600 EB_right growth 176 -> 208 (2026-09-09)

Track diff G-FX-1 arm vs SM iter 2: 576 tracks change cell. Into
W_right->S: 23 new events + 19 that were N_through->S (out: 13). Also
noted, not this reel's target: 290 N_through->S events present in the
earlier arm are ABSENT in iter 2 (NB_thru 13960 -> 13854 net), and 52
S_through->N became N_through->S.

Filmed 5 of the 42 even-spread (tids 22390 129183 158835 227763
313316; screenshots/c3_ebright_{n}_{tid}.webm). ONE SHAPE, 5 OF 5:
box at birth 266x268 .. 378x313 px — a near-field giant — and its two
bottom corners cross DIFFERENT gates in the same frame: R corner IN
over W, L corner IN over N. The W crossing is accepted by the
born-across clause because the L corner is on the "inside" half-plane
of the W line — it is actually sitting on the N gate, outside the W
segment's lateral extent. Then both corners OUT over S, paired, and
the machine books W -> S. The earlier arm booked 3 of these N -> S.
tid 313316 is a 6-row, 0.5 s flash of a 378x313 box.

CANDIDATE FIX (not built, awaiting his ruling): born-across requires
the other corner to lie within the gate SEGMENT's lateral extent
(projection in [0, 1]), not merely on the inside half-plane. The
cam1 reel-1 clips all satisfy that; these cam3 clips all fail it.
Reel page: https://claude.ai/code/artifact/d195fda2-4bb6-45bf-8f91-6634f8e33771

OPERATOR RULING, reel 3 (his words): "All five are what I am calling
WIDE BODY CORNER ERRORS. basically all of these are the same error,
the vehicle is so large in the frame the bounding box corners exist
beyond the drawn lines of the intersection, thus both corners do not
cross the mouth section and in some instances also do not cross the
exit section. The only one unclean is detection drops in clip 5 mid
intersection. But in all five the main error is the same the bounding
box is so large one of the corners sits beyond the intersection
line's length and cannot be hit with the intersection line as drawn."

HIS IDEA (his emphasis: "could, key word is could ... only an idea and
it needs to be redteamed and tested"): the program extends each drawn
line along its own trajectory to the edge of the frame — the operator
draws the lines as they exist, the code "mentally" extends them — so
line LENGTH stops being a problem.

TWO CANDIDATE DIRECTIONS, BOTH UNTESTED, for the build phase:
  (a) agent's: born-across requires the other corner within the
      segment's lateral extent — REFUSES the wide-body entry (the
      entry then comes from elsewhere or not at all);
  (b) operator's: extend the lines to the frame edge — makes the far
      corner's crossing OBSERVABLE so the pair forms on the right gate.
  Red-team questions for (b): an extended W line runs across the N
  approach / the far field — what else does it intersect? Do
  extensions of adjacent gates cross each other inside the frame, and
  what does a corner crossing the extension of a gate it is not
  approaching mean? Must be measured on all three cameras' geometry
  before any arm.
  INFERENCE, not stated by him: the true movement of these five is
  N -> S through (the earlier arm booked 3 of 5 that way). To confirm
  before building.

## REEL 4 — cam3 study_0600 surviving SB u-turns (2026-09-09)

16 unrejected S->S u_turn events in the iter-2 working DB (the cell
table's 27 counts destination==origin over Mio minutes; the movement
label differs on the rest). Filmed 5 even-spread (tids 14634 154504
281674 302741 332755; screenshots/c3_sbuturn_{n}_{tid}.webm).

Provenance under the machine:
  3 of 5 ENTRY-ONLY (14634, 154504, 332755): both corners IN over S,
    paired; then NO legitimate exit witnessed. The u-turn destination
    is the POSTERIOR's guess (S 0.65 / 0.73 / 0.74 vs W 0.20-0.35,
    N ~0). 154504 is the telling one: its L corner crossed OUT over N
    solo (refused, track continues) — a probable S->N through whose N
    exit only one far-field corner witnessed.
  2 of 5 GATE_FULL (281674, 302741): both corners IN over S and both
    OUT over S 5-10 s later, passing dwell / excursion / lane shift.
All five are far-field boxes at the S mouth (8x7 .. 32x15 px).
Reel page: https://claude.ai/code/artifact/93c8d39b-7d22-4195-8ef2-e93f6fd85027

OPERATOR RULINGS, reel 4 (his words):
  1  tid 14634   "a complete theft error opposite theft traffic (N to
                  S) disrupts the lock and then doesn't steal it and
                  run away but the disruption makes the lock get lost
                  and then it lingers in the intersection till it dies."
  2  tid 154504  "a last minute theft, right as the target vehicle is
                  about to cross the N exit it gets stolen and pulled
                  into the intersection before it sits and dies."
  3  tid 281674  "Same story, tracking failure mid intersection and
                  then lingers until a cross traffic vehicle steals it
                  and runs away."
  4  tid 302741  "unique detection misfires in the initiation
                  detecting an exiting vehicle far off in the horizon
                  N to S, it then lingers until it finds a far off
                  vehicle moving S to N to track, it tracks it to the
                  S mouth before there is a theft mid intersection and
                  then it runs off with it N to S."
  5  tid 332755  "a cross traffic thief error, the target car moves
                  into the intersection and then is waiting to make a
                  left turn while stopped the detector holds on
                  correctly for a majority of the cross traffic (N to
                  S) but then at the very end it is stolen and then
                  launched in reverse by a fast moving cross traffic
                  vehicle"

REEL 4 TALLY: 5 of 5 are theft / lost-lock inside the intersection.
Not one is a vehicle that turned around. The two "gate_full" u-turns
(281674, 302741) are a stolen box carried back out over S by cross
traffic — the gates witnessed a genuine both-corner S exit by the
WRONG vehicle. R2 (terminal exit) cannot help: the theft happens
BEFORE any exit.

## FOUR REELS, ONE TABLE (2026-09-09)

  reel  class                          real  spawn/  theft/  wide
                                             born    lost    body
  1     born-across entries (cam1)      5/5    5       0       0
  2     W refusals -> N thru (cam2)     2/5    2       3       0
  3     new EB rights (cam3)            0/5    0       0       5
  4     surviving SB u-turns (cam3)     0/5    0       5       0

Two problems, cleanly separated by his rulings:
  GEOMETRY (7 of 20 + reel 1's 5): the box is born or sits with a
    corner past a line's END or beyond the mouth; the drawn segment
    cannot be hit. Born-across is right for reel 1's shape and wrong
    for reel 3's. His idea: extend the drawn lines to the frame edge.
  THEFT (8 of 20): cross traffic takes the box inside the
    intersection. The machine's rules act on crossings; a theft
    before the exit hands the machine a genuine crossing by the wrong
    vehicle. Anti-theft territory (plan_anti_theft_2026-09-06.md,
    EMERGENCE_GUARD default off) plus his 2026-09-08 lead: a large
    speed discontinuity within one journey means the box changed
    vehicles ("launched in reverse by a fast moving cross traffic
    vehicle").
