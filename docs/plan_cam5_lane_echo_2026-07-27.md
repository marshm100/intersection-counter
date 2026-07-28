# Plan — LANE + ECHO discipline (cam5 mechanism cycle, 2026-07-27)

The combined mechanism plan the SB-insuf diagnosis mandated: the lateral
acceptance fix and same-vehicle echo suppression are ONE plan, because
un-dropping the 20-px lateral casualties alone overshoots SB-thru
+7.5/+8.7% — fragment echoes of the same vehicles already count
(`plan_cam5_eb_bankhole_2026-07-27.md`, SB-INSUF DIAGNOSIS + PHASE-0
FINDINGS; evidence runs/cam5_wall/*.json — all numbers below cite those
files; replayed-minutes basis throughout unless named otherwise).

## Targets and non-targets

Targets (cam5 pooled, ours vs Mio):
- **NB-left 39→38 +646 (1.85×)** — stub-fed 229/194 per audited window:
  same-anchor far-field stubs claiming the NB-left path's shared entry
  segment.
- **SB-thru 37→39 −417 (0.93)** — the three-population compose: 257/430
  adjacent-lane full journeys dropped by
  `score_destination_by_polyline(max_avg_distance_px=20.0)`
  (trajectory_classifier.py:292/:326; dropped tracks ride 20–40 px off
  the lane-biased fit, end gap ~11 px) + ~800/660 fragment-echo events
  partially backfilling.
- **WB phantom mass ~+350/day** (sub-REF_FLOOR; reported, not scored) —
  same stub family.
- Echo multiplicity generally: 45% of ≥4-pt tracks are same-anchor stubs;
  geo 39>39 alone emits 1,051 events @0700.

Non-targets (stay on their own tracks): **EB-right −207** (journey
formation — capability/tracking class; 13/21 real-geometry tracks per
window; nothing here fixes that), EB-thru/NB-right bank holes (retired,
fa053ab), cam2-EB occlusion splits (different mechanism; see Generalize).

## The invariant that gates everything — NB-THRU PROTECTION

cam5's NB-thru is CORRECT BY FRAGMENTS: 2,468 events @0700 = 1,839
far-band fragments + 467 stubs + 140 full journeys, vs Mio 2,379 (+89).
SB-thru mirrors it (929 full + ~800 echoes vs 1,868). The fragment feed
is load-bearing. ANY arm that moves NB-thru's or SB-thru's pooled ratio
by more than ±3 points of its BASE value FAILS, whatever it does
elsewhere. This is the hard stop that killed filter-only ideas (the
evidence gate rightly stands down at cam5, coverage 0.387) and it is
pre-declared here so no arm can pass by trading the main street away.

## Mechanism — three components, ablated separately

**E — echo suppression (chain-level counting).** Basis: the REVIVAL-READY
item-8 machinery — `backend/services/track_chains.py` (`chain_tracks` +
`build_chain_map`, STITCH_* constants FROZEN since Gate B 2026-07-08,
tested in test_conservation.py) and the `conserve_replay_additions`
write-then-reject pattern. The dedup-ceiling lesson is already baked in:
only journey-INCOMPLETE tracks chain — a box-complete journey never
chains, so a 1–2 s-headway follower cannot merge into its leader (the
guard against the 2026-07-09 concurrent-dedup failure, which ate real
NB-thru vehicles).
GENERALIZATION built here: extend chain policing from posterior-additive
events to ALL replay events — at most one counted event per chain;
preference: journey-complete member's event > longest-coverage member's;
the chain's UNION coverage becomes the claim basis (an echo can complete
the divergence evidence no single fragment had). Zero new chaining
constants.

**L — lateral acceptance.** Parameterize the fallback gate per cell:
`max_avg_distance_px` for THROUGH paths scaled to the measured lane
spread (candidate: kept-median × k, giving ~45 px at cam5-SB; the
kept/dropped bimodality 10-vs-26 px with a 20.1 floor is the setting
evidence). Origin filtering bounds cross-direction magnets (opposing
lanes at 33–41 px are origin-mismatched); the residual hazard is
same-origin TURN cells (SB-left 98, SB-right 273/day) — phantom-gated.
L ships only WITH E (the coupling), never alone.

**C — claim eligibility for chain-orphan stubs.** A chain whose union
coverage never reaches its claimed path's divergence (where sibling
paths of the same origin separate by > amb px — reuse the builder's
ambiguity_px=30, no new constant) may not claim a TURN cell. The
pre-divergence default is the THROUGH sibling when one exists (the
no-turn geometric prior — explicitly NOT corpus-proportional allocation,
the "counting by popularity" risk that killed the ft2 posterior at
17.3%); no thru sibling → no event + S-flag card (queue-visible, the
designed outcome for ambiguity). Kills the NB-left stub claims WITHOUT
new magnet surface; the displaced stubs must be absorbed by E (chained
onto counted vehicles), NOT re-land on NB-thru — the invariant watches
exactly this.

## Budget + discipline

Two iterations, then ship-or-retire with numbers (the item-8 standing
rule). Plan doc first (this), measured ablation per component, frozen
constants before any blind sweep, FM51 never tuned on, negatives are
deliverables, name the basis on every number. New flags default OFF;
flag-off byte-parity proven before any measurement (816-suite + the
OFF-parity reproduction of 7.2/16.1/17.3/5.1).

## Phase 0 — infrastructure + the blind census (no mechanism)

1. Chain census over cam5's three stock windows: chains, echo
   multiplicity (tracks/chain), % of events in multi-track chains,
   union-coverage gain (how many pre-divergence fragments become
   divergence-complete at chain level). Extends cam5_sbinsuf_diag/fate
   harnesses; evidence runs/cam5_wall/chain_census_*.json.
2. The same census on cam1/2/3/4 stock + FM51 — the future ACTIVATION
   PRECONDITION candidates (echo multiplicity + offset bimodality are
   GT-free, computable from any site's own replay; evidence-activation
   C=0.45 is the precedent shape). No decisions yet — just the numbers.
3. Divergence-point computation per origin from the applied bank
   (sibling-separation > 30 px), unit-tested geometry.

## Phase 1 — ablation on cam5 (prototype 0700; 1100/1600 held out)

Arms vs BASE (the OFF-parity replays), all replay-only, whole-camera
per-cell + per-approach scored, each arm's constants frozen before
running its held-out windows:

| arm | expected signature | key gates (pre-declared) |
|---|---|---|
| E alone | SB overshoot guard appears (echo dedup); NB-left partially deflates | no protected-cell breach; per-cell abs total improves |
| L alone (diagnostic only, never ships) | SB-thru recovers ~257 then OVERSHOOTS ≈ +7.5% | measures the coupling; expected FAIL on SB ratio — recorded, not shipped |
| L+E | SB-thru toward 1.0 WITHOUT overshoot (recovery + dedup); the compose resolves | SB-thru ratio in [0.95, 1.05]; NB/SB-thru invariant; no turn-cell phantom >1.15× Mio |
| L+E+C | + NB-left toward 760 | NB-left ratio ≤ 1.15; displaced stubs do NOT re-land on NB-thru (invariant); WB phantoms shrink (reported) |

Camera-level pass bar for the winning arm: cam5 pooled per-approach —
NB and SB both improve, EB not worse (EB's wall is out of scope), total
< 7.2, per-cell abs total materially down (> the ±2-noise class), zero
protected-cell breaches, phantom gate ≤1.15× on every touched turn cell.

## Phase 2 — frozen-constant blind sweep + ship gate

Constants frozen from phase 1. Sweep: cam1 (0700), cam2 (×3), cam4 (×3)
stock replays + cam3 study_0000 (3.2 tripwire — regression is a HARD
STOP) + FM51 both window-DBs (held-out; 3.0 MAE / +2.0 net reference).
The mechanism runs everywhere it activates by its own census — if the
census stands a camera down, that camera must measure byte-identical to
flag-off. Pass: no camera worse on its honest cut, cam5 keeps its
phase-1 win, FM51 within noise of its reference. Then: wire into pass-2
behind `LANE_ECHO_ENABLED` (default OFF), measure-then-apply on cam5
through the real pass-2 (production interval-scorer basis reported
alongside), operator ✓, own commit. FAIL at any stage → verdict +
retirement entry with numbers; the census + chain infrastructure stay
(they feed §3-B regardless).

## Costs

Phase 0–1: replays only (~2–5 min/window; the stock BASE DBs for cam5
are kept in scratch), CPU-bound. Phase 2: ~11 corridor windows + FM51
replays. No detection, no training, no iGPU.

## Hazards ledger (pre-named, with their tells)

- **Magnet widening** (measured ×3 at cam5) — tell: any turn cell >1.15×
  Mio in an L arm. Phantom gates on every touched cell, every window.
- **Dedup eats real vehicles** (2026-07-09 lesson) — tell: protected
  thru ratios drop; the journey-complete-never-chains rule is the
  structural guard, the invariant the measured one.
- **Counting by popularity** (ft2 posterior, 17.3%) — C's thru-default
  is geometric, never proportional; any corpus-share allocation idea is
  out of scope by construction.
- **Cancellation masquerade** (bank-D, promo-A/B) — every arm reports
  per-cell AND per-approach; an approach win with a corrupted cell is a
  FAIL by gate, not judgment.

## PHASE-0 FINDINGS, part 1 — the cam5 chain census (2026-07-27, same
day; evidence runs/cam5_wall/chain_census.json, harness
scripts/lane_echo_phase0.py; BASE replays re-derived into
data/projects/97a7849a/_replay_scratch after a Windows Temp purge ate
the originals mid-session — OFF-parity re-proven EXACT on the new
copies first: 7.2 / 16.1 / 17.3 / 5.1)

Frozen-constant chaining over the three stock windows, joined to BASE
events. GT appears nowhere in the census itself (Mio used below only to
interpret it — dev yardstick).

- **E's prize is real: 1,625 excess events/day** (630/388/607 per
  window) across 595/374/580 multi-event chains. NB-left: 554 of its
  1,406 events sit in multi-event chains; its singleton population is
  dominated by FULL-journey tracks (249/147/166 ≈ the real turners —
  Mio 335/185/240). Dedup alone projects NB-left from 1.85× toward
  ~1.3× pooled; the remaining ~290 singleton orphans (entry_only /
  no_crossing / exit_only) are C's load. E is necessary, not
  sufficient.
- **DEFECT CAUGHT in the frozen chaining — cross-direction false
  links:** 174 chains carry BOTH an SB-thru and an NB-thru event
  (85/21/68). At the compressed far band one direction's death sits
  pixels from the opposing direction's birth, and `chain_tracks` gates
  on time+distance+tags only — no heading. Dedup on a false chain eats
  a real vehicle (the 2026-07-09 hazard, new clothing).
  **AMENDMENT 1:** a direction-consistency gate on chain edges (A's
  end-tangent vs B's start-tangent within the bearing-tol class
  constant, 55°), unit-tested, ships inside E — measured by the same
  census (the 174 must go to ~0 without the same-cell pair mass
  collapsing).
- **NB-thru's +89 is itself a cancellation compose:** 222/89/186
  same-cell NB-thru echo pairs per window mask ~133 genuinely-missing
  NB vehicles at 0700 (2,468 − 222 = 2,246 vs 2,379). An honest dedup
  breaks the naive ±3-of-BASE invariant. **AMENDMENT 2:** the
  protection invariant is vs TRUTH on the dev windows — post-arm
  NB-thru and SB-thru ratios must land in [0.97, 1.03] — not vs BASE's
  flattered ratio. **AMENDMENT 3:** chain-union recovery is REQUIRED,
  not optional: zero-event chains whose union geometry is claimable are
  the −133's candidates; census them (count + union-claimability)
  before phase 1 arms.
- **The SB dropped laterals are clean losses, not echoes:** dropped /
  no-event real-geometry SB tracks sit in a counted chain 2/0/0 times
  out of 257/311/430. The +7.5/+8.7% overshoot arithmetic stands
  numerically, but its mechanism is the fragment feed covering OTHER
  vehicles — so L's recovery is genuinely additive, and the L+E arm
  measures the net compose empirically.

## PHASE-0 FINDINGS, part 2 — corridor + FM51 census; PHASE-1 arms 1–3
(2026-07-27, same session; evidence runs/cam5_wall/chain_census_*.json,
e_arm.json, ec_arm.json, lec_arm.json)

**Corridor + FM51 baselines (excess events / total events per day):**
cam5 11.8%, cam4 ~12% (35→33 same-cell alone 1,181/day — plausibly its
whole SB overcount; STAT-rule queue-follower risk NAMED for the sweep),
cam1 7.5% (top class = 22↔23 flips), cam2 ~8% (plus 1,070 uncounted
FULL journeys/day — its own future recovery pool), FM51 25–31% (785/day
almost pure 1↔2 flips at 167–180°), cam3 (24 h, passing) 4.0%.
**The activation signal is the COMPOSITION, not the rate** (FM51's 28%
is harmless today precisely because nothing dedups; a naive dedup would
have eaten ~785 real FM51 vehicles — the direction gate is
load-bearing, proven on the held-out site before any arm ran).

**Arm results (cam5, replayed-minutes, whole-camera):**

| arm | pooled | NB-thru | SB-thru | NB-left | per-cell abs |
|---|---|---|---|---|---|
| BASE | 7.2 (EB 16.1/NB 17.3/SB 5.1) | 1.088 | 0.933 | 1.85 | 2405 |
| E-alone (diagnostic) | "2.9" — cancellation | 0.95 ✗ | 0.893 ✗ | 1.72 | 2231 |
| EC (divergence-aware survivor) | 2.9* | **0.991 ✓** | 0.894 ✗ | 1.40 | **1745** |
| LEC (+45 px L, +R) | 7.9* | **1.007 ✓** | 1.093 ✗ over | 1.40 | **1673** |

(*approach MAEs remain compose-sensitive while SB is off-truth; the
per-cell cut is the honest arm comparator.)

- E-alone proved the pre-declared lesson: cell-agnostic keep-one lets
  stub LEFTS survive over their vehicle's THRU (820 vs 100 rejections).
  The divergence-aware survivor (EC) fixes it: NB-thru in band, NB-left
  sheds 340 echoes, −27% per-cell abs, direction gate cuts 10,195
  false edges/day.
- LEC: L admitted +1,052 events; recovery R added +237; NB-thru stayed
  in band (recycled mass balanced) but SB-thru overshot to 1.093 —
  **the widen rescues unchained echo fragments too. NEXT ITERATION
  (design, not knob): compose L with E — the widened acceptance applies
  only to tracks whose CHAIN carries no counted event** (rescue
  uncovered vehicles, never additional fragments of counted ones).
  NB-left's remaining +302 is the SINGLETON orphan class = C-proper
  (divergence-eligibility on unchained turn claims), still unbuilt.

**PROCESS CORRECTION (on the record):** arms 1–3 scored all three
windows; the plan reserved 1100/1600 as held-out. No constant was
per-window fitted, but from here the discipline is enforced properly:
LEC-v2 + C-proper fit on 0700 ONLY → constants frozen → 1100/1600
held-out confirmation → the corridor sweep.

## ITERATION-1 VERDICT (2026-07-27 — PARTIAL; evidence
runs/cam5_wall/lec2_arm_fit_l40r3fc.json + lec2_arm_heldout.json)

Frozen constants (declared at fit, 0700 only): bearing gate 55°; L = 40 px
fallback widen, THROUGH winners only, journey-complete tracks only, +
concurrent-duplicate cut (≥1 s overlap at ≤35 px mean) against counted
tracks; C-proper divergence reroute on singleton turn claims; R = ≥3-member
zero-event chains, union-full or thru-default at ≥60 px span.

| cut | fit 0700 | held-out 1100+1600 |
|---|---|---|
| NB-left vs truth | 356/335 = **1.06** | 456/425 = **1.07** ✓ HOLDS |
| per-cell abs | 711→397 (**−44%**) | 1699→1064 (**−37%**) ✓ |
| SB-thru band | **1.027 ✓** | 1.054 ✗ |
| NB-thru band | 0.969 (edge) | **1.085 ✗** |
| NB approach MAE | 10.9→5.1 | 20.5→7.4 |

**What generalized:** the NB-left phantom closure (the cycle's primary
wall), the per-cell abs collapse, the direction gate, C-proper, and the
WB phantom shrink. **What didn't:** the protected-thru truth bands. The
miss is systematic, not scatter — the held-out windows carry FAR more
base NB-thru inflation (1.12×) than the fit window (1.04×), and the
frozen balance under-removes there. The residual class is UNCHAINED
CONCURRENT same-cell echoes: invisible to sequential chaining (E),
untouched by C (thru claims), and the concurrent cut only ran on
L-admits. **The corridor sweep does NOT run (its own gate).**

**Iteration 2 (the budget's last) — named candidate + named trap:**
extend the concurrent-duplicate rule to all counted events — which is
the RETIRED 2026-07-09 concurrent-dedup in new clothing, and its
failure mode is on the record (far-band followers sit < 35 px apart in
image space; the pass ate real NB-thru at every setting). The iteration-2
design must be lane/arc-aware (same-lane + overlapping path-s-ranges,
the (s,d) machinery) or it will re-fail. Own session, full design
first; this session ends iteration 1 with the partial on the record.

## Generalize (after the corridor, not before)

If the mechanism ships at cam5: the same census decides cam1/cam4 (their
ft2 re-baseline failures are fragment floods — this is the "attribution
hardening" the ft2 disposition named as the precondition for ever
re-detecting the corridor with the promoted head), and cam2-EB's
occlusion-split double-attribution is a candidate SECOND application of
E (concurrent-split chains) under its own plan. None of that is claimed
by this cycle.

---

## ITERATION-2 DESIGN (2026-07-27 — the budget's last; declared before
implementation)

**CD — concurrent dedup over ALL counted events.** Two counted events'
tracks are the same physical vehicle iff during their co-life:
1. shared frames >= 1.0 s (CONC_MIN_OVERLAP_S, reused from iteration 1);
2. **mean box-IoU over shared frames >= IOU_MIN** (NEW constant,
   candidate 0.30 — two boxes of one vehicle cover the same pixels; the
   v2 dump carries bw/bh, cols 4-5);
3. **lockstep**: std of the same-frame center distance <= LOCKSTEP_STD_PX
   (NEW constant, candidate 10 px — a double-box is welded to its
   vehicle; a follower's headway breathes).
Keep-one preference as in iteration 1 (full tag, then longer track).
CD runs after C-proper, before R (a CD-removed twin's chain stays
event-covered, so R cannot resurrect it).

**Why this is not the retired 2026-07-09 pass:** that pass used center
proximity alone and ate compressed far-band FOLLOWERS. Followers fail
BOTH new conditions — sustained IoU >= 0.3 for a full second means the
boxes cover the same pixels throughout, and follower gaps fluctuate
where double-boxes are rigid. The residual risk (extreme compression
where two real vehicles' boxes genuinely merge for seconds) is
adjudicated by the pre-existing gates: if CD eats real vehicles the
protected bands UNDERSHOOT and iteration 2 fails per its own gate.

Everything from iteration 1 stays frozen (bearing 55 deg, L=40
full-only + concurrent cut, C-proper, R rmin=3). Fit protocol: the two
new constants fit on 0700 ONLY from their candidate values, frozen,
then held-out 1100/1600. Bands met -> the corridor sweep + FM51
(phase 2, finally). Bands failed -> the cycle CLOSES with iteration-1's
partial standing and a retirement entry; whether NB-left's closure
ships alone is then an operator decision informed by the sweep-less
evidence.

---

## ITERATION-2 VERDICT + CYCLE CLOSE (2026-07-27 — FAIL AT FIT; evidence
runs/cam5_wall/lec3_arm_fit*.json)

CD was implemented as designed (all-events concurrent dedup, sustained
IoU + lockstep, spatio-temporal prefilter; the R-resurrection defect —
concurrent twins live in DIFFERENT sequential chains, so R re-recovered
CD-removed vehicles — was caught and fixed before fitting). **The
constants have no discriminating regime:** IoU 0.30/0.40 and lockstep
10/6/4 px all catch the same ~93–99 pairs at 0700, of which ~42–46 are
NB-thru — and removing them drives NB-thru to 0.95, BELOW the band, at
the fit window whose base inflation (1.04×) is mild. The caught pairs at
the far band are predominantly REAL adjacent vehicles with genuinely
overlapping boxes, not double-boxes. **The 2026-07-09 conclusion is
re-confirmed with a strictly stronger discriminator: image-space
concurrency tests cannot separate far-band twins from real neighbors.
Iteration 2 FAILS at fit; the held-out windows were never run; the
two-iteration budget CLOSES the cycle.**

### The cycle's standing result (what future work inherits)

- **Iteration-1 PARTIAL stands:** NB-left (the +646 wall) closed and
  held-out-proven (1.85 → 1.06/1.07); per-cell abs −44% fit / −37%
  held-out; both protected thrus moved TOWARD truth on held-out
  (NB 1.122→1.085, SB 0.93→1.054 in |err| terms) but did not reach the
  [0.97, 1.03] band — so the corridor sweep never ran and NOTHING is
  wired or shipped. Flags do not exist; production untouched.
- **Retired by measurement (do not retry as-is):** cell-agnostic
  keep-one (E-alone); ungated chaining at fragment-heavy sites (FM51's
  785 flip-pairs/day); all-events image-space concurrent dedup (CD —
  twice-confirmed dead); R without the CD-chain guard.
- **Revival-ready, evidence-backed:** the direction-gated chain builder,
  divergence-aware survivor selection, C-proper eligibility reroute,
  L full-journey lateral rescue + concurrent cut, R rmin=3 — the LEC2
  frozen bundle, one honest band-miss from its own bar.
- **Named future candidates (new mechanism class, own plan + budget):**
  (a) appearance-based twin detection (ReID embeddings exist per-camera
  for botsort+reid recipes — a twin test on embedding similarity is
  image-space-compression-immune); (b) per-window composition-adaptive
  rejection (the fit/held-out inflation delta 1.04× vs 1.12× is
  measurable blind from the census — an activation-style scaler, needs
  its own gate); (c) the operator decision recorded in the plan: whether
  LEC2's sweep-less partial justifies a relaxed-bar corridor sweep is
  an explicit bar change, not a default.

---

## OPERATOR-AUTHORIZED DELIVERABLE-TRUTHFULNESS SWEEP (2026-07-28 —
"handoff then sweep"; an explicit bar change, on record)

The cycle's dev bands ([0.97,1.03] protected thrus) were missed held-out
and the cycle is CLOSED. The operator has authorized re-judging the
frozen LEC2 bundle at the bar the §3-B claim structure validated — what
the DELIVERABLE needs — over the corridor + FM51:

**Pre-declared per-camera bar (replayed-minutes basis, LEC2 vs BASE on
identical replays):**
  (1) per-cell abs error total (cells with GT >= 10) strictly improves;
  (2) NO cell with GT >= 30 worsens by more than max(10 veh, 20% of GT);
  (3) net-total: |net_after| <= max(|net_before|, 5%) — certifiability
      never lost;
  (4) per-approach MAE not worse by > 0.3 points on any approach;
      cam3 = HARD STOP at any worsening beyond that noise band;
  (5) FM51 (ftv2n replay basis, held-out): same bar.
Constants: the frozen LEC2 bundle exactly as committed (bearing 55,
L=40 full-journey-only + concurrent cut 1s/35px, C-proper divergence
reroute, R rmin=3). No re-fitting anywhere.

PASS on a camera -> that camera joins the ship set; the ship step
itself (measure-then-apply through the real pass-2, production
interval-scorer reported alongside, operator ✓) is a separate follow-up.
FAIL anywhere -> that camera stays base; a cam3 or FM51 failure kills
the ship set entirely. All numbers land here; negatives included.

### SWEEP VERDICT (2026-07-28 — evidence runs/cam5_wall/sweep_deliverable.json;
harness scripts/lane_echo_sweep.py, fidelity proven cell-exact vs the
committed arm evidence before the run)

| camera | abs err | net | MAE | bar | verdict |
|---|---|---|---|---|---|
| cam1 | 542→498 | −0.1%→−4.5% | 4.0→5.2 | (4) | FAIL |
| cam2 | 4609→4273 | −4.2%→−6.9% | 4.1→7.4 | (3)(4) | FAIL |
| cam3 | 4709→3956 | −10.1%→−8.8% | 39.7→40.1 | (2) | **FAIL — HARD STOP** (E-right +74→−113, N-left −33→−69) |
| cam4 | 771→**1807** | +4.6%→−5.9% | 4.7→5.4 | (1)(3)(4) | FAIL — the STAT queue-follower trap REALIZED (~1,000 real vehicles eaten; the phase-0 watch item decided) |
| cam5 | 2423→1313 | +6.8%→+4.5% | 7.2→5.5 | (4) | FAIL (E 16.1→17.9: removing phantom EB-rights that flattered the approach; S +0.8 overshoot) |
| **FM51 (held-out)** | 257→228 | +5.4%→**−0.8%** | **5.4→1.8** | all pass | **PASS** |

**SHIP SET: EMPTY — the cam3 hard stop kills it per the pre-declared
terms, FM51's pass notwithstanding.** Under the operator-authorized
deliverable-truthfulness bar, the frozen LEC2 bundle does NOT generalize
as a corridor blanket: five cameras fail for four DISTINCT measured
reasons (compensating-phantom MAE dependence at cam1/cam5; undercount
deepening at cam2; turn-cell over-removal at cam3; queue-follower STAT
dedup at cam4 — the dedup-ceiling hazard in new clothing).

**What the FM51 pass means (recorded, not chased):** the mechanism's
true class is FM51-shaped — far-band flip-heavy sites with no signal
queues and no compensating-phantom dependence — where it is a clean,
large win on the held-out site (MAE 5.4→1.8 on the ftv2n replay basis).
The phase-0 census composition signals (flip share, same-cell echo
share, STAT-link share) are exactly the blind activation statistics that
could gate it per-site (evidence-activation C=0.45 precedent). Wiring a
census-gated activation is a NEW cycle needing its own plan, budget, and
operator authorization — named here, not started. The LANE+ECHO arc is
now fully closed: nothing ships, every claim measured, three retirement
classes and one site-class win on the record.
