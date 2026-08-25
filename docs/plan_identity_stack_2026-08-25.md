# IDENTITY STACK — campaign gates (declared 2026-08-25, before any scored run)

One doc, all four gates. Campaign context: three converged measurements
(G-LP-1 55.1 solo MISS; the 33/34-debris gap-card census; R0's zero
score effect) say production's 64.8 rides on identity debris offsetting
detection-dark misses — so any single honest fix scores worse alone,
and the stack lands as ONE measured story: honest identity (B) + honest
evidence (A) + recovered detection (C), same scored arm.

Standing law: no cam2 production write before G-ID-1 ships; every
pillar's flag/recipe stays opt-in until then.

## G-MQ-1 — Pillar A diagnostic (solo arm, NOT a ship gate)

- ARM: MOTION_QUALIFIED_EVIDENCE=1, three cam2 windows, production
  study dumps, fresh scratch workdir. CONTROL: shipped gatesup 64.8
  (67.3/62.0/65.2; approach 44.8).
- EXPECTATION (declared): at or below control — MQE removes
  creep-crossing evidence (minted journeys) without recovering the
  real vehicles. Recorded as decomposition evidence for the G-ID-1
  story; never shipped alone. Readouts: both bars, u-turn count
  ctrl-vs-arm (the creep class mints u-turns — the canary), evidence
  activation per window.
- Known approximation (ledgered at build): _gate_evidence pts are
  index-time; a gap-spanning creep can false-pass the speed floor.
  The u-turn canary covers it.

RESULT (2026-08-25, workdir gmq1_20260825, scores
runs/v2_week1/score_gmq1_cam2_study_*.json): MQE solo pooled
215/330 = 65.2 vs control 214/330 = 64.8 — ABOVE control, against
the declared at-or-below expectation. Per window: 65.4/63.0/67.0 vs
67.3/62.0/65.2 (0700 -1.9, inside the 2.0 floor; 1100 +1.0;
1600 +1.8). The equilibrium lesson does not bind MQE: voiding
creep-crossing evidence removes false journeys without removing true
tracks (the posterior machinery absorbs the degraded evidence).
Approach bar dips 40.6/46.9/37.5 vs 43.8/50.0/40.6 — recorded,
secondary. Evidence activation unchanged (0.562/0.489/0.488 vs
control 0.564/0.487/0.485; all above the 0.45 bar) — no
decomposition contingency. U-turn canary at 1600: EB 15 vs 16,
others equal — the creep class shrinks slightly, no mint. Flag stays
default-off; ship decision belongs to G-ID-1.

## G-LP-2 — Pillar B acceptance (the reserved tracker iteration)

Mechanism: botsort_locked + the online flip-split — the cutter's
validated 120° pinch applied LIVE on completed displacement-chord
pairs, breaks minted in absolute row units, end-of-run flush.

VALIDATION RECORD (the harness was the development loop; iterations
honest, in order):
1. 1/34 severed — harness confounded (proximity test; dense traffic).
2. Path-following harness + flip/dwell classes: FLIP 16/29 severed.
3. Root cause of the carried 13: the split-became-merge bug —
   gate_breaks in tracker-local frames vs dump rows in absolute
   frames; every re-stamp renamed the old track's whole life onto the
   new id. All 15,978 breaks at 1600 degenerated to merges. Plus two
   monitor defects (latest-pair-only judging skipped flips on dense
   movers; window-index watermark froze judging past max_obs
   saturation). Fixed in commit 6b4ddb3.
4. FINAL: FLIP class 26/29 severed. The 3 carried (+2 dwell-class)
   are dwell-time thefts (base speed 0-17 px/s at the theft) — the
   operator's waiting-left-turner class; no flip exists to detect.
   Out of B's scope, ledgered below.

- ACCEPTANCE (standing, re-checked on the G-ID-1 arm dumps): the
  labeled-splice harness on the arm's three dumps must hold FLIP
  severed >= 26/29 at 1600 (and no regression if the operator labels
  more thefts before the gate).
- Meters at 1600 (final tracker): splice-shaped tracks 10.7% -> 1.4%;
  tracks 10,196 -> 22,491; median life 5.3s -> 2.4s. The
  fragmentation is the honest cost — volume recovery is C's job, the
  stack gate adjudicates.
- OPERATOR ACK: demo 4 ("Flip-Split Demo" artifact) — the severed
  labeled same-leg theft + two turners kept whole. Ack pending; ack
  gates the G-ID-1 run, not the C1 probe (machine work, no
  production touch).
- G-LP-1 measurement note (ledgered): the 55.1 MISS arm ran with the
  split-became-merge bug — that measurement was of a tracker whose
  splits were all merges. G-LP-2 is not a re-run of G-LP-1; the solo-B
  diagnostic inside G-ID-1 supersedes it.

LEDGERED RESIDUAL (its own future plan, NOT built in this campaign):
the stopped-claim hole — a stopped identity may claim a detection
already moving at speed (through traffic passing within
STITCH_STAT_DIST of a waiting left-turner). Candidate rule: stopped
re-claims require the claimed motion to resume from rest. Designed
constraint: the waiting turner's identity must SURVIVE the dwell (the
bus law) — refuse at-speed grabs, never kill stationary tracks.

## C1 — the recall probe (record; operator reviews before C2)

Bin: cam2 16:15-16:30 (frames 1462450-1484950), the worst deficit
cell (SB short ~270). Recipes vs production (yolo26s@960 c0.10):
id_l1280 / id_l960 / id_s1280, conf floor 0.08, CUDA, vehicle classes
{2,3,5,7}. Measurement: detector_zone_recall pattern — SB-right
failing channel + NB-thru control, dets/frame at conf 0.10/0.25,
entry-third density, NOVEL dets (no production det within 25 px).
CUDA rate recorded per recipe -> full re-detect cost.

RESULT: (filled when the probe lands)

C2 decision (operator): best zero-training recipe -> full three-window
re-detect into id_ caches, cost from the measured rate. C3 (fine-tune)
only if C1 shows the ceiling demands it.

## G-ID-1 — the decisive stack gate

- ARM: id_ detector caches (C2 recipe) -> pass-1 botsort_locked +
  flip-split, calib buffer 750 (runner-injected; production calib
  untouched) -> replay TRACK_FINALIZE_GAP_FRAMES=650 +
  MOTION_QUALIFIED_EVIDENCE=1. Fresh scratch workdir, copy-to-stem
  scoring, armed-verification via dump metas (backend
  botsort_locked, lost_buffer, gate_breaks present, id_ cache
  lineage) before any scoring.
- CONTROL: shipped gatesup — pooled movement 64.8 (214/330);
  67.3/62.0/65.2; approach 44.8 recorded secondary.
- PASS: arm pooled movement > 64.8 AND no window more than 2.0 below
  its control (floors 65.3/60.0/63.2).
- DIAGNOSTICS (recorded, never shipped alone): solo-A (G-MQ-1 above),
  solo-B (s4_ dumps + grace 650, MQE off) — the decomposition pair
  that tells which pillar carries the change.
- Readouts: both bars per window; evidence activation (control
  0.564/0.487/0.485 vs the 0.45 bar; if any window flips, the
  ft2-precedent flag-off decomposition pair runs); u-turn canary;
  gate_full populations; duplicate-tid census; labeled-splice harness
  on the arm dumps (the G-LP-2 acceptance); QD law — added volume in
  deficit cells triggers a human-review sample sheet.
- SHIP on PASS, operator go: productization = PROCESSING_MODES entry
  for the C2 recipe, cam2 calib flip (backend + buffer), grace
  decision WITH the operator, dump rebuilds (old .tracks dirs renamed
  aside), pre-ship VACUUM backup, Confirm & process + force_once
  ladder. MISS: ledgered; everything stays opt-in; the pillar assets
  stand (harness, meters, MQE flag, tracker recipe).
