# Plan — SPLIT THE G-A3 CONFOUND (2026-08-11)

Block 0 of the raw-machine accuracy campaign
(`.claude/plans/ok-so-please-look-keen-melody.md`, operator decisions
2026-08-11: the bar is RAW PIPELINE 5/95 vs Miovision with no human-queue
credit; near-zero human labor on a new site; corridor-only validation).

This block runs FIRST because it is the cheapest experiment available and
it re-prices the campaign's central negative result plus nine stood-down
windows. It needs no new code — only environment variables the harness
already supports.

## The finding that launched it

The G-A3 corridor sweep (`plan_v2_block2_2026-08-06`, verdict in
commit affb74c) established the APPLICABILITY LAW: "the bundle wins where
journeys are missing, loses where completion manufactures them." Its
evidence was a per-window control-vs-treatment comparison, and the
treatment lost at 9 of 12 windows (cam4 -23.7, cam1 -15.7, cam5 -11.5).

**That comparison moved four variables at once.** From the chain script
that produced it (`runs/v2_week1/ga3_chain.ps1`, lines 20-30), verbatim:

    # control: base dump, flags off
    $env:V2_DEMOTION = "0"; $env:V2_MERGE_RESCUE = "0"
    py -X utf8 scripts/v2_run_pass2.py --camera $c --variant $v
    ...
    # treatment: v2c dump, flags on
    $env:V2_DEMOTION = "1"; $env:V2_MERGE_RESCUE = "1"
    py -X utf8 scripts/v2_run_pass2.py --camera $c --variant "v2c_${v}"

So control -> treatment changes: (1) the dump gains extension rows,
(2) V2_DEMOTION goes on, (3) V2_MERGE_RESCUE goes on, and — the one
nobody declared — (4) **the evidence-gate ACTIVATION PRECONDITION flips**.

Extension raises blind gate coverage past `EVIDENCE_ACTIVATION_COVERAGE
= 0.45` at every camera that was previously below it, so the treatment
arm also silently switches on the gate+posterior attribution pair. Read
from the sidecars in `data/projects/97a7849a/_replay_scratch/v2_week1/`
(`result.evidence_activation` and `result.replay`):

  window                 base cov  act    v2c cov  act    tracks base/v2c
  cam1 study_0700          0.265   off     0.563   ON      6728 / 6728
  cam1 study_1600          0.438   off     0.613   ON      8938 / 8938
  cam3 study_0600          0.431   off     0.525   ON     46388 / 46388
  cam4 study_0700          0.304   off     0.741   ON      7664 / 7664
  cam4 study_1100          0.442   off     0.754   ON      4970 / 4970
  cam4 study_1600          0.318   off     0.696   ON      8986 / 8986
  cam5 study_0700          0.330   off     0.579   ON      8960 / 8960
  cam5 study_1100          0.441   off     0.587   ON      6572 / 6572
  cam5 study_1600          0.402   off     0.625   ON     10196 / 10196
  cam2 study_0700          0.564   ON      0.623   ON      8320 / 8320
  cam2 study_1100          0.487   ON      0.528   ON      7489 / 7489
  cam2 study_1600          0.485   ON      0.575   ON     11247 / 11247

Two things to note. **Track counts are identical in every row** —
extension preserves track ids by construction, so the coverage rise is
purely numerator (`origin_evidenced`). And **cam2 is the only camera
whose activation state does NOT change**; every gain the campaign banked
at cam2 is therefore uncontaminated, while every loss at cam1/4/5 is.

The applicability law may be true. It may also be a description of what
the activation flip does to cameras that were deliberately standing down.
Nothing on record separates them.

## The three arms

Arms A and B already exist on disk and are NOT re-run. Only arm C is new.

  arm  dump   V2_DEMOTION / V2_MERGE_RESCUE   evidence pair   status
  A    base            0 / 0                  OFF (below bar) recorded
  B    v2c             1 / 1                  ON  (flipped)   recorded
  C    v2c             1 / 1                  **OFF (forced)**  NEW

Arm C environment:

    $env:V2_DEMOTION = "1"; $env:V2_MERGE_RESCUE = "1"
    $env:EVIDENCE_ACTIVATION_ENABLED = "0"

`EVIDENCE_ACTIVATION_ENABLED=0` makes `run_pass2` (`two_pass.py:1019-1021`)
call `replay_camera` with no `evidence_mode`, which
`pass2_replay.py:170-172` documents as "legacy module-flag semantics
(harness env overrides)". `ORIGIN_EVIDENCE_GATE_ENABLED` and
`ORIGIN_POSTERIOR_ENABLED` both default OFF, so the pair is off. This is
a designed dev-sweep path, not a hack.

**The decomposition:**

  A -> C  =  the effect of EXTENSION ROWS alone   (pair off in both arms)
  C -> B  =  the effect of the ACTIVATION FLIP alone (v2c dump in both)
  A -> B  =  the recorded G-A3 delta               (= sum of the two)

## Why arm D was dropped

The obvious fourth cell — base dump with the pair forced ON — is
CONTAMINATED and must not be used. Forcing it requires
`ORIGIN_POSTERIOR_ENABLED=1`, which additionally switches `expected` from
the legacy corpus-QA derivation to `census_expecteds` and enables
`conserve_pass` (`two_pass.py` ~:980 and ~:1130). Neither recorded arm used
those. Arm D would move three things, so it cannot isolate anything. The
three-arm design already yields a complete decomposition; arm D would only
answer the secondary question of whether the pair behaves differently on a
base dump, and it cannot answer even that cleanly.

## Clean windows vs interacting windows

Demotion's cell selection is read from the sidecars
(`result.demotion.cells`). Where it selected NOTHING, variables (2) and
(3) are inert and the comparison is genuinely two-variable:

  CLEAN (demotion cells = [], rescue tiny):
    cam1 study_0700   A 60.5  B 44.8   (-15.7)   rescue 7
    cam1 study_1600   A 54.5  B 43.6   (-10.9)   rescue 13
    cam4 study_1100   A 69.4  B 64.4   ( -5.0)   rescue 2

  INTERACTING (demotion selected cells; read second):
    cam4 study_0700   A 75.4  B 60.3   (-15.1)   cells [[34,34]]
    cam4 study_1600   A 75.8  B 52.1   (-23.7)   cells [[34,34],[34,35]]
    cam5 study_0700   A 66.4  B 55.2   (-11.2)   3 cells
    cam5 study_1100   A 71.7  B 63.0   ( -8.7)   cells [[36,39]]
    cam5 study_1600   A 63.1  B 51.6   (-11.5)   3 cells
    cam3 study_0600   A 64.1  B 72.6   ( +8.5)   cells [[31,31],[31,32]]
    cam2 study_0700   A 53.4  B 55.8   ( +2.4)   3 cells (activation
    cam2 study_1100   A 42.9  B 50.4   ( +7.5)   3 cells  unchanged —
    cam2 study_1600   A 44.0  B 45.8   ( +1.8)   3 cells  see G-0)

The interaction is real and named in advance: demotion's trigger includes
`posterior_source is None` (`pipeline.py:1426`), so with the pair OFF fewer
tracks carry a posterior source and demotion can reach FURTHER in arm C
than it did in arm B. Demotion is a SIBLING of the posterior block, not
nested inside it (both at the same indentation, `pipeline.py:1335` vs
`:1426`), so turning the pair off does not disable demotion — it can
amplify it. At the three clean windows this cannot happen (zero cells).

## Pre-declared gates

- **G-0 (instrument sanity, blocking, run FIRST).** Re-run arm B verbatim
  at cam4 `study_1100` (the smallest window, 4970 tracks) with the recorded
  G-A3 environment and score it. It must reproduce
  `runs/v2_week1/score_twopass_cam4_v2c_study_1100.json` — 64.4% on 59
  cell-bins. If it does not, the harness is not reproducing the runs this
  block reasons about, and NOTHING downstream is interpretable: STOP,
  diagnose the drift (calibration fingerprint, bank rebuild, dump meta),
  and record it. This is the replay-parity discipline applied to the
  experiment itself, and it is cheap.

  Secondary observation, not a gate: cam2 is the only camera whose
  activation state is unchanged between A and B, so arm C there measures
  something the confound never varied. Its value is diagnostic — it prices
  what the pair is worth at a camera that has always had it — and it must
  not be read as a control for this block's question.
- **G-C1 (the question).** On the three CLEAN windows, decompose A->C->B.
  - If |A->C| is small (<3 pts) and C->B carries the loss, the recorded
    regressions are the ACTIVATION FLIP, not extension. The applicability
    law is an artifact of a confounded experiment, and the next block
    targets the 0.45 bar (which was calibrated on base dumps only, as the
    midpoint of a [0.387, 0.510] gap chosen to reproduce an existing
    decision set — it has never been validated against extended dumps).
  - If A->C carries the loss, extension genuinely over-completes at
    cam1/4/5, the applicability law STANDS as written, and Block 1 ships
    `V2_EXTEND` default-OFF as planned.
  - A split result (both contribute) is the likely real answer and must be
    reported as a magnitude per camera, not as a verdict word.
- **G-C2 (no production contact).** Every run is `apply=False` into
  `data/projects/97a7849a/_replay_scratch/v2_confound/`. Production
  `vehicle_events` byte-unchanged, verified by row counts before and
  after. The three applied windows (cam2 0700/1100, cam3 0600) are
  untouched.
- **LEDGER either way.** A null result — the pair explains nothing and
  extension explains everything — is a deliverable: it converts the
  applicability law from an association into a controlled finding, which
  is strictly more than it has today.

## What this block does NOT claim

It does not re-open the three production applies (they stand on their own
measured gains, and cam2's activation state never changed). It does not
propose changing `EVIDENCE_ACTIVATION_COVERAGE` — that would be its own
block with its own gates. It measures one thing.

## Sequencing

1. This plan doc (commit 1).
2. Arm C on the three CLEAN windows; score; read G-0 at cam2 first
   (commit 2).
3. Arm C on the nine interacting windows; full decomposition table;
   verdict appended here; `plan_v2_week1_verdict.md` and `MASTER_PLAN`
   §2e amended (commit 3).


## G-0: PASS (2026-08-11)

Arm B re-run verbatim at cam4 `study_1100` in a fresh workdir reproduced
the recorded run exactly — replay stats byte-equal (tracks 4970, events
4075, insufficient 853, merge_kept 137, merged_away 30) and 5/95 64.4% on
59 cell-bins, matching `runs/v2_week1/score_twopass_cam4_v2c_study_1100.json`.
The harness reproduces the runs this block reasons about.

Trap recorded for anyone repeating this: `sidecar_reusable` keys on dump
meta + calibration + schema and does NOT encode the env flags, so a second
arm sharing a workdir silently returns the FIRST arm's result. Each arm
gets its own workdir (`_replay_scratch/v2_confound/armC`, `armC2`).

## VERDICT — CLEAN WINDOWS (2026-08-11)

  window            A            C            B      ext(A>C) act(C>B)  total
  cam1 study_0700  60.5  49/81  54.1  59/109 44.8  47/105  -6.4    -9.3  -15.7
  cam1 study_1600  54.5  48/88  45.8  54/118 43.6  51/117  -8.7    -2.2  -10.9
  cam4 study_1100  69.4  34/49  57.4  31/54  64.4  38/59  -12.0    +7.0   -5.0

**G-C1: the applicability law STANDS IN DIRECTION — extension is negative
on its own at all three clean windows (-6.4, -8.7, -12.0). But the
recorded per-window magnitudes are WRONG IN BOTH DIRECTIONS, and the
activation flip is not a uniform harm.**

- cam1 study_0700: the record blames extension for -15.7; extension's own
  cost is -6.4. The flip carried -9.3, i.e. **the larger half**.
- cam4 study_1100: the record shows a mild -5.0; extension's own cost is
  -12.0 and the flip **RESCUED +7.0** of it. The bundle looked twice as
  safe here as the mechanism actually is.
- The flip's sign is inconsistent (-9.3, -2.2, +7.0). It is not "damage
  the 0.45 bar was protecting against"; it helps at cam4 and hurts at
  cam1. No blanket statement about the activation bar survives this, in
  either direction. Changing `EVIDENCE_ACTIVATION_COVERAGE` is NOT
  supported by this evidence and is not proposed.

## THE REAL FINDING — "regression" is mostly DENOMINATOR GROWTH, and it
## decomposes into TWO separately-fixable defects

`rule595.score_cells` scores the UNION of (bin, cell) slots present in
either source; a slot where Miovision reports 0 and we report >5 in a bin
is scored and fails. So a candidate that counts where Miovision is silent
enlarges its own denominator. Measured with `scripts/v2_phantom_diag.py`
(new, this block), control vs arm C:

  cam1 study_1600:  48/88 -> 54/118.  30 slots ADDED, **all 30 PHANTOM**
                    (Mio = 0), 154 vehicles; 0 recoveries; 17 shared slots
                    went right->wrong.
  cam1 study_0700:  49/81 -> 59/109.  30 added, **all 30 PHANTOM**, 99
                    vehicles; 0 recoveries; 18 right->wrong.
  cam4 study_1100:   34/49 -> 31/54.   5 added, 6 vehicles (negligible);
                    13 right->wrong.

Note what this means at cam1: the absolute number of CORRECT slots ROSE
(48->54, 49->59) while the percentage fell. Extension is not destroying
counts there; it is adding wrong ones.

**Defect 1 — PHANTOM TURNS (cam1's signature).** The added slots cluster
in turn movements, and u-turns alone are ~40% of the phantom mass:

  cam1 study_1600   SB left 44 · SB uturn 43 · WB right 23 · NB uturn 19
  cam1 study_0700   SB left 36 · SB uturn 28 · WB left 12 · NB uturn 11

This is the MANUFACTURED-ENTRY class: the backward endpoint walk curves
across the conflict zone and the track's entry gate reads on the wrong
leg. It is exactly what `--heading-lock` was built for (block-2 item 2:
"46% of extended W-origin fulls had NO W-origin in the base dump") — that
experiment FAILED its gate, but it was judged on aggregate 5/95, which
cannot see a defect worth ~100-150 vehicles in a 6000-event window.
Phantom-slot count is the instrument that can. Untried lever with the
right shape: `v2_extend_dump.py --directions fwd` never touches origins
at all, and the day-5 addendum already recorded that forward-only keeps
most of the NB-left recovery (348 -> 380 of 413).

**Which path manufactures them — ANSWERED, and my first guess was WRONG.**
I wrote above that the phantom u-turns "likely arrive via the posterior".
They do not. Counted events at cam1 `study_1600`, grouped by
`posterior_source`:

  arm A control   u_turn  11   ALL (direct)
  arm C           u_turn 134   ALL (direct)
  arm B           u_turn 128   ALL (direct)
                  through 5178  (direct) 4421 · rescue_full 361 ·
                                 branch1 251 · rescue_supports 145
                  right    706  (direct) 500 · branch1 111 · rescue_full 95
                  left     574  (direct) 376 · branch1 183 · ...

The posterior branches produce throughs, rights and lefts and **not one
u-turn**, in the arm where they were active. Every manufactured u-turn
comes from the DIRECT path (joint scorer, or the fallback chain — the
week-1 cam1 transfer verdict recorded that cam1 attribution rides the
FALLBACK chain, which is consistent).

**Where they land.** origin->destination for counted u-turns:

  arm A   24->24:6   22->22:3   23->23:2                    (11)
  arm C   23->23:61  22->22:58  25->25:8   24->24:7        (134)

119 of 134 sit on legs 23 and 22. A u-turn here means origin_leg ==
destination_leg, i.e. the track crossed the SAME mouth gate twice —
in and back out. Extension lengthens tracks at both ends, so more of them
re-cross their own mouth. (Suggestive but NOT established: the gate-axis
verdict's surviving genuine outliers on the corrected axial measure were
"cam1 legs 22/25 (42 / 88 deg)". Leg 22 matches; leg 23 was never flagged
and leg 25 contributes only 8. Do not build on this correlation without
measuring it.)

**Why the existing guard misses them.** `entry_gates.classify` demotes a
same-leg pair to `entry_only` unless dwell >= `UTURN_MIN_S` (5 s),
excursion >= `UTURN_MIN_PX` (40) and lateral shift >=
`UTURN_MIN_LANE_SHIFT` (25) — the guard whose comment records it killing
100 phantom SB u-turns. But that guard governs the GATE TAG, not the
counted movement, and the direct path does not consult it. With the
evidence pair off (arm C, and cam1's normal state below the 0.45 bar),
`classify`'s output feeds only the census. So the counted u-turn is
produced by `derive_movement`/the joint scorer with no dwell, excursion
or lane-shift requirement at all.

Fix shape for the follow-up block, to be gated normally: require gate
corroboration for a counted u_turn on the direct path — the same evidence
`classify` already computes, applied to the movement rather than the tag.
Prize at this one window: ~10 of the 30 phantom slots.
Also note extension does not merely ADD at cam1 — it RECLASSIFIES:
through 4811 -> 4585 (-226) while right +188, left +152, u_turn +123.
Straight tracks are becoming turns, which is the manufactured-entry
signature stated in counting terms.

**Defect 2 — THRU INFLATION (cam4's signature).** Phantoms are negligible
(6 vehicles) but 13 shared slots flip right->wrong, and every one is a
LARGE THRU cell inflating ~10-11%:

  bin    cell      Mio   A     C
  11:00  SB thru   195   201   223
  11:15  NB thru   175   172   192
  11:15  SB thru   204   205   220
  11:30  NB thru   182   186   205

At ref 195 the 5/95 tolerance is 9.75 (relative branch), so A's +6 passes
and C's +28 fails. This is the TWIN/DUPLICATE class — extension completing
both halves of a split track — the same mechanism as cam2's EB-right
flood, on a different movement family.

**Consequence for the campaign.** "The bundle wins where journeys are
missing and loses where completion manufactures them" is true but not
actionable. It resolves into two defects with different signatures,
different cameras, and different levers: origin manufacture (fix:
forward-only walks / origin evidence) and twin completion (fix: journey
dedup on the inflated thru family). Neither says extension should be
abandoned; both say it should be filtered. That is a materially better
starting point than the law it replaces.

## CORRECTION (same session) — "TWO DEFECTS" IS WRONG, AND SO WAS THE
## U-TURN RECOMMENDATION. It is ONE defect: shared-cell inflation.

The section above reasoned from phantom MASS (154 vehicles, ~40% u-turns)
and concluded there were two camera-specific defects, with a u-turn guard
as cam1's fix. Both conclusions are REFUTED by measurement, and the error
was mine: **phantom mass is not phantom damage.** `tolerance(0) = 5.0` per
bin, so a slot where Miovision reports 0 and we report <= 5 in that bin
PASSES. Most manufactured slots are small and pass.

Symmetric ablation — u_turn events dropped from BOTH arms, cam1:

  window            as-is (A / C)   u-turns removed (A / C)   gap
  study_0700         60.5 / 54.1        58.4 / 51.6         6.4 -> 6.8
  study_1600         54.5 / 45.8        51.8 / 45.0         8.7 -> 6.8

Removing u-turns strips 18 slots from arm C but 12 of them were ALREADY
COMPLIANT, so the gap does not close — at study_0700 it widens. A u-turn
guard is not the lever.

Direct damage decomposition (non-compliant slot deltas, control -> arm C):

  window          non-compl.  added slots FAIL (u-turn)  shared net  dominant
  cam1 study_1600   40 -> 64        13  (5)                  +11     ~equal
  cam1 study_0700   32 -> 50         4  (2)                  +14     SHARED
  cam4 study_1100   15 -> 23         0  (0)                   +8     SHARED

**The dominant damage at every window is SHARED slots going right->wrong
— cells that already existed, inflated past tolerance.** And the failing
cells are the SAME FAMILY across cameras:

  cam1 study_1600   EB left 4 · NB right 3 · NB uturn 3 · SB left 2 ·
                    SB right 2 · NB thru 2
  cam1 study_0700   EB left 5 · SB right 4 · SB thru 4 · NB uturn 4
  cam4 study_1100   SB thru 8 · NB thru 4 · EB left 1

with the magnitudes already shown (EB left 11->23, SB right 13->27,
SB thru 195->223): cells roughly DOUBLING at low volume and inflating
~10% at high volume. That is one mechanism — **extension completing
duplicate/twin fragments of vehicles already counted** — and it is the
same class as cam2's EB-right twin flood, which the week-1 verdict
identified and four pairwise channels failed to separate.

**Revised consequence.** cam1 and cam4 do NOT have different defects.
They share the duplicate-completion defect; cam1 additionally manufactures
phantom slots, which are real but are the SMALLER half and mostly do not
even fail the rule. The campaign's target is therefore duplicate
suppression on extended tracks, not origin manufacture.

Standing prior art to build on rather than re-spike:
`scripts/v2_journey_dedup.py` exists with its criterion OPEN, and the
day-5 pair-geometry probe found cam2's EB duplicates are NOT tight-riding
co-temporal twins (2/92 under 40 px, entry-gap median 9.8 s). So the naive
"same gate pair + co-temporal + close" criterion is already measured dead
on cam2's population. Whether cam1/cam4's inflated THRU family has a
different, separable geometry is UNMEASURED and is the next diagnostic —
not a new mechanism, one probe on an existing script.

Retained from the earlier section: the manufactured-entry finding itself
(through 4811 -> 4585 while turns +463 at cam1) stands, as does the
u-turn path attribution (direct, never posterior) and the observation that
`classify`'s u-turn guard governs the tag and not the counted movement.
Those are true and worth knowing; they are simply not where the 5/95
damage is.

### Confirmed across all six clean+interacting windows measured so far

  window          added FAIL   shared net   dominant
  cam1 study_0700      4          +14       SHARED
  cam1 study_1600     13          +11       added, narrowly
  cam4 study_0700      0          +13       SHARED
  cam4 study_1100      0           +8       SHARED
  cam4 study_1600      1          +11       SHARED
  cam5 study_1100      0           +9       SHARED

Shared-cell inflation dominates at five of six. Two further facts, both
stronger than anything in the first read:

**1. "MISS ok" — a slot Miovision reports and extension newly gets RIGHT —
is ZERO at every window.** Every single added slot across all six windows
is a phantom. At cam1/4/5 extension buys NOT ONE recovered cell-bin. Its
recall gains are real (NB-left 348->413 at cam2) but they land inside
cells that already existed; they do not open new correct slots here. Any
future claim that extension "recovers missing journeys" must be stated per
camera — on this evidence it does not do so at cam1, cam4 or cam5 at all.

**2. `EB left` is the most consistent failing cell in the corridor.**
right->wrong counts by cell:

  cam1 study_0700   EB left 5 · SB right 4 · SB thru 4 · NB uturn 4
  cam1 study_1600   EB left 4 · NB right 3 · NB uturn 3 · SB left 2 · ...
  cam4 study_0700   NB thru 5 · SB thru 5 · EB left 3 · SB right 1
  cam4 study_1600   EB left 8 · SB thru 3 · NB thru 2
  cam5 study_1100   EB left 7 · EB thru 6 · EB right 2 · NB left 2 · SB left 2

EB left fails at EVERY window, on THREE different cameras with three
different geometries and three different calibrations. A defect that
survives that much variation is not per-camera geometry.

### THE MECHANISM, FOUND IN CODE (2026-08-11) — and two separate defects

The queue hypothesis below is no longer just a hypothesis; the code path
that produces the duplicates is identified, and it splits into two findings
that stack.

**Finding A — the conservation pass NEVER RAN in any measured arm.**
`two_pass.py:1133` gates `conserve_pass` on `ORIGIN_POSTERIOR_ENABLED`,
whose default is `""` -> False (`config.py:419`). The G-A3 chain set only
`V2_DEMOTION` and `V2_MERGE_RESCUE`, and `EVIDENCE_ACTIVATION_ENABLED`
passes `evidence_mode` explicitly to the REPLAY only — it does not touch
this module flag. Confirmed from the artifacts: no arm A / B / C sidecar
contains a `conservation` key.

`conserve_replay_additions` is the mechanism that enforces at most one
counted event per fragment CHAIN. It was built and proven in
`plan_conservation_pass_2026-07-15`, and it is switched off.

**CORRECTION to Finding A, before it misleads anyone (including me — I
wrote "this is the single most likely explanation" and it is not).**
Enabling it would NOT have fixed the damage measured here.
`conserve_replay_additions` (`two_pass.py:322-324`) only ever rejects
events whose `posterior_source` is in `_ADDITIVE = ("branch1",
"rescue_full", "rescue_supports")`:

    additive = [e for e in evs if e[1] in _ADDITIVE]
    if not additive:
        continue          # legacy multi-counts pre-date us

A chain carrying only DIRECT events is skipped by design. Arm C is 100%
direct (the evidence pair is forced off, so no posterior source is ever
written), so the conservation pass is a structural no-op on arm C's
duplicates no matter what the flag says. The "legacy multi-counts pre-date
us" scoping is deliberate and defensible — it is what stopped the pass
from re-litigating the legacy chain — but it means **the corridor has NO
dedup at all for direct-path duplicates**, which is the population
extension creates.

So Finding A's accurate form: the conservation pass is off AND, when on,
does not cover this class. Finding B is the load-bearing one.

**Finding B — when it IS on, extension DISABLES it.** `chain_tracks`
(`track_chains.py:47-48`) gates on tags: `A_OK = ("entry_only",
"no_crossing")`, `B_OK = ("exit_only", "no_crossing")`, with the comment
"A full journey never chains" (ungated chaining once merged complete NB
vehicles into followers, fulls 3459->2951). Its STATIONARY rule
(`a_slow` under 10 px/s, gap <= `STITCH_STAT_GAP_S` = 50 s, dist <= 35 px)
exists precisely for a vehicle stopped at a stop bar.

Endpoint extension's entire purpose is converting `entry_only` /
`exit_only` fragments into FULL journeys (fulls 3459 -> 4162, +20%). A
`full` track fails BOTH gates and can never chain. **So extension
systematically destroys the chain for exactly the fragments the stationary
rule was written to rejoin**, and each half then counts separately.

And the wiring makes it worse: `two_pass.py:1134` passes the EXTENDED
`rows` to `conserve_pass`, while ten lines earlier (`:1044-1054`) the
demotion census deliberately swaps to BASE-dump rows because "the base
dump is extension-proof". The same extension-proof principle is applied at
`gate_census_inputs` (`:1277`) and MISSED on this sibling call. So the
moment anyone enables the conservation pass on a derived variant, it will
chain on tags extension already overwrote.

**Predicted, and consistent with every measurement above:** extension does
not find new vehicles at cam1/4/5 (MISS-ok = 0 everywhere) — it SPLITS
existing ones into two counted journeys, concentrated in queue-prone
movements (EB left at every window; SB/NB thru at cam4's signal).

**Next experiment, offline, no pass-2 re-run** (the
`v2_demotion_counterfactual.py` pattern): build the chain map from the
BASE dump tags, apply "one counted event per chain" to arm C's events, and
re-score. That measures the ceiling of Finding A + the Finding B fix
together, on data already on disk. Do that before proposing any flag change.

### RESOLVED — it is MISATTRIBUTION, not duplication (2026-08-11)

Third and final revision of the mechanism in this block; each step was
measured and each narrowed it. Recorded in full because the two discarded
readings are both plausible and someone will re-derive them otherwise:
(1) "phantom turns, fix the u-turn guard" — refuted by the symmetric
ablation; (2) "duplicate/twin completion, dedup it" — refuted below.

**Finding B is structurally REAL but is NOT the damage.** Chain-duplicate
probe (`scripts/v2_chain_dup_probe.py`, new), cam1 `study_1600`:

  MULTI-TRACK CHAINS   base 1071 -> ext 747   (-324, i.e. 30% destroyed)

  arm              counted  chains  multi  EXCESS  same-cell
  A control           5778    5392    380     386        152
  C ext, pair off     6015    5214    413     450        151
  B ext, pair on      6586    5581    529     591        219

Extension does destroy 324 of 1071 multi-fragment chains, exactly as the
tag-gate argument predicts. But arm C gains only **+64** chain-duplicates
over control and its SAME-CELL duplicates are FLAT (152 -> 151), against
~950 new counted events. Chain destruction explains ~7% of the movement
and cannot be the cause of the cell inflation. (Caveat that also matters:
`EXCESS` is an upper bound, not a clean duplicate count — chaining cannot
separate a fragment continuation from a 1-2 s-headway follower, which is
the dedup-ceiling lesson and the very reason
`conserve_replay_additions` declines to touch legacy multi-counts.)

**What it actually is.** Per-track event provenance, arm A vs arm C,
cam1 `study_1600`:

  tracks newly counted in C            806   (events 806)
  tracks that STOPPED counting         569
  tracks counted in BOTH, RECLASSIFIED 411

  top reclassification flows (A cell -> C cell)
    (22,23,through) -> (24,23,left)     56     ORIGIN 22 -> 24
    (23,22,through) -> (23,25,left)     51     DEST   22 -> 25
    (22,23,through) -> (23,23,u_turn)   31     ORIGIN 22 -> 23
    (23,22,through) -> (24,22,right)    29     ORIGIN 23 -> 24
    (22,25,right)   -> (22,23,through)  27
    (22,23,through) -> (22,22,u_turn)   26     ORIGIN 22 -> 22
    (24,23,left)    -> (22,23,through)  19
    (22,23,through) -> (25,23,right)    18

  top cells among the 806 NEWLY counted (the genuine recall gain)
    (23,22,through) 233 · (22,23,through) 219 · (24,22,right) 100 ·
    (22,25,right) 70 · (23,24,right) 38

**Extension MOVES THE GATE CROSSINGS of tracks that were already
correctly attributed.** The endpoint walk carries a track across a
different leg's gate, so the box-clip origin (or destination) changes and
a through becomes a turn. That single mechanism explains every
observation in this block at once:

- through 4811 -> 4585 (-226) while right/left/u_turn gain +463;
- `EB left` failing at every window on three cameras — it is the
  destination of the dominant through->left flow;
- MISS-ok = 0 everywhere — the "new" slots are RELABELLED old counts, not
  recovered vehicles, so they open no correct slot;
- same-cell chain duplicates flat — because nothing is being duplicated.

**Scope limit on the above, measured — do not over-read it.** The
reclassification is real and universal, but its DIRECTION is per-camera,
and neither rate nor direction predicts the net score:

  camera/window   reclassified   dominant flow          extension net
  cam1 study_1600   411 (7.1%)   through -> turn 167    -8.7
                                 turn -> through  46
  cam4 study_1100   157 (4.9%)   turn -> through 106    -12.0
                                 through -> turn  35
  cam5 study_1100   238 (7.0%)   turn -> through        -4.5
  cam5 study_1600   383 (6.9%)   turn -> through  98    **+1.7**
                                 through -> turn  48

So the "through becomes a turn" story is cam1's signature specifically;
cam4 and cam5 reclassify predominantly the OTHER way (turns becoming
throughs) and still lose at cam4 and GAIN at cam5 study_1600. The claim
that survives is the narrow one: **extension rewrites the origin/dest
attribution of ~5-7% of tracks that were already counted, at every
camera** — which is undocumented, unintended, and orthogonal to the recall
gain it was built for. The claim that does NOT survive is that this single
flow direction explains the corridor-wide score pattern.

**cam5 study_1600 is the counterexample to keep in view:** extension alone
is +1.7 there (65/103 -> 81/125, sixteen more correct slots) and the
recorded -11.5 is carried ENTIRELY by the activation flip (-13.2). Any
statement of the form "extension always hurts" is false; it is negative at
7 of 8 windows measured and positive at one.

**The fix has an exact precedent in this codebase.** `chain_tracks` will
not touch a completed journey ("a full journey never chains", A_OK/B_OK
tag gate) because a mechanism that helps fragments must not be allowed to
rewrite something already whole. Endpoint extension violates the
analogous rule: it extends EVERY track's endpoints, including tracks that
already had a clean gate-to-gate journey in the base dump.

Proposed rule for the follow-up block, GT-free and cheap:
**extension may not alter the gate-crossing set of a track that was
already tag `full` in the BASE dump** — extend only `entry_only`,
`exit_only` and `no_crossing` tracks, the same three tags `chain_tracks`
admits.

PRE-DECLARED PREDICTIONS (all falsifiable, all on data already on disk):
1. Reclassification of already-counted tracks drops by >=70% at every
   camera (it is the direct target).
2. The newly-counted population largely survives — those tracks were not
   `full` before, by definition, so the rule does not touch them.
   Quantified: >=80% of cam1 study_1600's 806 and cam5 study_1600's 1364
   newly-counted tracks still count.
3. Net 5/95 improves versus unrestricted extension at the windows where
   extension is currently negative, and does NOT regress at cam5
   study_1600 where it is currently +1.7.
If (1) holds but (3) does not, the reclassification is NOT the damage
mechanism and this whole line is LEDGERED — that is the honest failure
mode and it is worth knowing either way, because it would mean the loss
lives in the 806/1364 newly-counted tracks rather than in the rewritten
ones.

This is one condition in `dump_extend`/`v2_extend_dump.py` (the tag is
already computed by `entry_gates.classify`, which `track_chains` calls),
measurable without a re-detect, and it should be Block 1's FIRST
experiment rather than a productization detail.

**Hypothesis now SUPERSEDED (kept for the record).** Left-turners
queue. A queued vehicle is slow or stopped, is occluded by the queue ahead
of it, and fragments into several tracklets; endpoint extension then
completes EACH fragment into its own journey, and one vehicle is counted
several times. This is the stopped-vehicle failure the I-24 MOTION work
names explicitly (switches 0.04 -> 0.52 in congestion) and which the
research synthesis answers with a ZERO-VELOCITY link hypothesis — already
scheduled as part of Block 2's linker. If true, the same mechanism
explains SB/NB thru inflation at cam4 (through queues at a signal) and
cam2's EB-right flood, and it predicts the inflation concentrates in the
bins with the longest queues. That prediction is testable on data already
on disk and should be the first thing measured, before any fix is built.

## FINAL VERDICT — ALL 12 WINDOWS (2026-08-11)

  window            A            C            B     extend  ev-pair  recorded
  cam1 study_0700  60.5  49/81  54.1  59/109 44.8  47/105   -6.4    -9.3   -15.7
  cam1 study_1600  54.5  48/88  45.8  54/118 43.6  51/117   -8.7    -2.2   -10.9
  cam2 study_0700* 53.4 55/103  53.6  59/110 55.8  63/113   +2.4    +2.2    +2.4
  cam2 study_1100* 42.9 45/105  42.0  47/112 50.4  57/113   +7.5    +8.4    +7.5
  cam2 study_1600* 44.0 48/109  46.6  55/118 45.8  55/120   +1.8    -0.8    +1.8
  cam3 study_0600  64.1 307/479 61.1 327/535 72.6 337/464   -3.0   +11.5    +8.5
  cam4 study_0700  75.4  43/57  57.8  37/64  60.3  41/68   -17.6    +2.5   -15.1
  cam4 study_1100  69.4  34/49  57.4  31/54  64.4  38/59   -12.0    +7.0    -5.0
  cam4 study_1600  75.8  50/66  60.6  43/71  52.1  38/73   -15.2    -8.5   -23.7
  cam5 study_0700  66.4 71/107  62.9  78/124 55.2  69/125   -3.5    -7.7   -11.2
  cam5 study_1100  71.7 76/106  67.2  80/119 63.0  75/119   -4.5    -4.2    -8.7
  cam5 study_1600  63.1 65/103  64.8  81/125 51.6  64/124   +1.7   -13.2   -11.5

BASIS NOTE (encoded in `scripts/v2_confound_table.py`, not just written
here): the evidence pair's state in arm A DIFFERS by camera. At cam1/3/4/5
it is OFF in A (below the 0.45 bar), so extension = C-A and pair = B-C. At
cam2 (*) it is already ON in A (coverage .485-.564), so extension = B-A and
pair = B-C. Reading cam2's C-A as "extension" mixes an ADDED mechanism with
a REMOVED one and inverts the answer.

### THE HEADLINE — the campaign's largest shipped win is NOT extension

**cam3 study_0600, the +8.5 applied to production on 2026-08-10 and
described in the apply record as "the campaign's largest single win",
decomposes as extension -3.0 and evidence pair +11.5.** Extension HURT at
cam3. What it actually did was raise blind coverage 0.431 -> 0.525, pushing
the camera past `EVIDENCE_ACTIVATION_COVERAGE` and buying it admission to
the gate+posterior pair. Its value there was as a COVERAGE LEVER, not as a
recall mechanism.

Note the shape of the two mechanisms at cam3, which is diagnostic:
extension INFLATES the denominator (479 -> 535 scored slots, +56) while the
pair SHRINKS it (479 -> 464) and raises compliant counts 307 -> 337. The
pair produces fewer, better-attributed slots; extension produces more,
worse ones.

### What this says about the 0.45 bar — and what it does NOT say

Checking the pair's measured worth against the bar's verdict on BASE dumps:

  camera  base coverage   bar     pair actually worth
  cam2    .485-.564       admit   +8.4 / +2.2 / -0.8
  cam1    .265 / .438     deny    -9.3 / -2.2            correct
  cam5    .330-.441       deny    -7.7 / -4.2 / -13.2    correct
  cam4    .304-.442       deny    +2.5 / +7.0 / -8.5     mixed
  cam3    **0.431**       deny    **+11.5**              WRONG

**The bar is mostly right.** It correctly denies cam1 and cam5, where the
pair is genuinely harmful — and it denies them for the right reason, since
those are the cameras where the pair costs the most. Its one clear error on
this corridor is cam3, 0.019 below the line and worth +11.5.

So the earlier statement in this doc — "no blanket claim about the
activation bar survives, changing it is NOT supported" — STANDS, and is now
supported by stronger evidence rather than weaker: a global threshold
change would hand cam3 +11.5 and cam4 +2.5/+7.0 while handing cam5
-7.7/-4.2/-13.2 and cam1 -9.3/-2.2. Net negative. **Do not lower the bar.**

What IS supported: the pair's value is per-WINDOW (it ranges +8.4, +2.2,
-0.8 across three windows of cam2 alone), and a single global coverage
threshold is the wrong shape of decision for it. The project already owns
the right shape — per-window adjudication under the apply gate. Turning the
evidence pair into an adjudicated candidate rather than a threshold gate is
a well-formed follow-on block, and cam3's +11.5 is the prize that justifies
measuring it.

### Consequences for the plan

1. Extension is positive at cam2 (all three windows, +1.8..+7.5) and at
   cam5 study_1600 (+1.7); negative everywhere else, worst at cam4
   (-12.0..-17.6). It is NOT the corridor-wide gain the campaign recorded.
2. The three production applies remain sound as OUTCOMES — cam2's gains are
   genuinely extension, and cam3's +8.5 is real even though its cause was
   mis-attributed. Nothing needs rolling back. But the apply record's
   sentence "extension — the largest contributor" is WRONG for cam3 and
   should be read with this verdict.
3. The `--skip-full` experiment (task 8) is still the right first move for
   extension, and cam3 now gives it a second pre-declared prediction:
   if extension's value at cam3 is purely the coverage lift, then gating it
   to non-full tracks should PRESERVE the coverage lift (those tracks were
   not full, so they still get extended) while removing the -3.0.

## G-C2: PASS (verified, not asserted)
All runs `apply=False` into `_replay_scratch/v2_confound/`. Checked after
the clean-window arms: cam2 `study_1600` over its exact dump window
(frames 1439950-1619950 -> t=[57598, 64798] s) under the
`window_cell_counts` predicate reads **6835**, matching the apply record
exactly (the candidate's 7279 never landed); `project.db` mtime is still
2026-08-10 13:45 with no `-wal` pending. The three applied windows were
never re-adjudicated.
