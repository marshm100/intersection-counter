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

## Generalize (after the corridor, not before)

If the mechanism ships at cam5: the same census decides cam1/cam4 (their
ft2 re-baseline failures are fragment floods — this is the "attribution
hardening" the ft2 disposition named as the precondition for ever
re-detecting the corridor with the promoted head), and cam2-EB's
occlusion-split double-attribution is a candidate SECOND application of
E (concurrent-split chains) under its own plan. None of that is claimed
by this cycle.
