# MASTER ACCURACY ROADMAP — the living handoff document
# (created 2026-08-18; supersedes options_inventory_2026-08-11 as the
#  entry point. Update the changelog at the bottom when you change it.)

**Read this first if you are new.** This document is the single map of
(1) where accuracy stands, (2) every known lever — tried, untried, or
retired — with an accuracy-gain hypothesis, (3) the operating laws
that keep measurements honest, and (4) how to run everything. Deep
history lives in the per-block plan docs it links to.

---

## 1. WHERE WE STAND (measured 2026-08-18, live production)

**Two bars, both measured, neither passed** (the finding of
2026-08-18 — docs/finding_two_bar_inversion_2026-08-18.md):

- **Movement bar** (engineering standard): per movement-cell per
  15-min bin, |ours−ref| ≤ max(5/bin, 5%·ref). **Average 65.6%.**
- **Approach bar** (PRD §7.2 as written): per approach-TOTAL per bin,
  same tolerance family; a window passes at ≥95% compliant bins.
  **Average 43.4%, 0/13 windows pass.**

  window            movement   approach      window            movement   approach
  cam1 study_0700     60.5%      62.5%       cam4 study_0700     75.4%      37.5%
  cam1 study_1100     78.5%      71.0%       cam4 study_1100     73.5%      41.7%
  cam1 study_1600     54.5%      40.6%       cam4 study_1600     75.8%      66.7%
  cam2 study_0700     55.8%      25.0%       cam5 study_0700     66.4%      50.0%
  cam2 study_1100     55.0%      46.9%       cam5 study_1100     71.7%      40.6%
  cam2 study_1600     49.5%      31.2%       cam5 study_1600     63.1%      21.9%
  cam3 study_0600     72.6%      28.0%  (14 h window)

Best-ever anywhere, any basis: 87.5% movement-bar (held-out FM51
site, replay-isolated dev arm). No recorded score on any bar has ever
reached 90%. Artifact: runs/v2_week1/two_level_scores_2026-08-18.json.

**The inversion that sets strategy:** the approach bar is WORSE
because same-sign volume errors accumulate where misattribution
cancels, and big approach-bins lose the ±5 absolute grace. The gap to
the PRD is **missing vehicles, not missorted ones** (e.g. cam2-1600
EB approach nets −287, −17%, after all internal cancellation).
Consequence: every lever below carries TWO hypotheses — one per bar.

**Credit where due:** the operator called undetected vehicles the
hole repeatedly from 2026-07-06 onward (58%-recall diagnosis, the
Detector De-risk Spike commissioned as "the new top lever",
hand-marking undetected vehicles on 07-20). The campaign redirected
onto attribution after an early spike concluded "recall is not the
bottleneck; association is" — a conclusion the inventory itself
flagged as premature (E4) and never re-tested. The two-bar
measurement confirms the operator's diagnosis at the product bar.
LESSON FOR THE NEXT PERSON: when the operator's field observation
contradicts an instrument conclusion, re-test the instrument's
premises before building on them.

**Production applies shipped by the campaign** (all through the blind
apply gate; docs/apply_record_2026-08-13_ppt2.md):
cam2 study_1600 44.0→49.5 · cam2 study_1100 50.4→55.0 ·
cam4 study_1100 69.4→73.5 (movement bar).

**Running right now (2026-08-18):** busy-window auto-calibration on
cam2, 17:00–18:00 sample (~20k trajectories vs the 57 the original
midnight sample had). Its proposal lands as a PENDING suggestion —
nothing applies without an operator click. Decision tree in §5.

---

## 2. THE ERROR MASSES (what the remaining points are made of)

| Class | Symptom | Bar it hurts | Prime levers |
|---|---|---|---|
| Missed vehicles (the "birth wall", thrice-confirmed: detector conf 0.10–0.35 band births no tracks; queue fragmentation) | approach-bins net −5..−17%; cam1 NB_thru −175 residual | **approach**, movement | review add-missed; A2 motion-mask; queued/stopped mechanism; A4 1280 |
| Misattribution (gates/paths/banks built from a 57-trajectory midnight sample; cam5 mouths 160 px apart; cam2 EB pair frozen) | movement cells failing in mirrored pairs | **movement** | calibration wave (running); PPT round 2 on clean geometry |
| Duplicates/echoes (track fragments re-counted; ~101/day one movement one camera) | both bars, + direction | dwell-aware dedup; embedding twin; review Del-reject |
| Label defects (cam4 n==2 T-branch mislabels (34,33) left→through) | movement only (volume-neutral) | deterministic backend fix |
| Reference noise + optics (sub-1080p; Miovision itself imperfect) | both, irreducibly | better cameras at capture; nothing in software |

---

## 3. THE BACKLOG — every lever, status, and per-bar hypothesis

Gains are corridor-average points (low/mid/high), pre-registered
2026-08-18. OVERLAP WARNING: volume-class levers (review, A2,
queued/stopped, A4, dedup) draw from the same missed-vehicle mass —
their sum overstates; see §4 scenarios for discounted totals.

### Tier 0 — decisive, near-zero cost, DO FIRST

| id | element | status | movement | approach | cost | notes |
|---|---|---|---|---|---|---|
| R0 | **Measure one full review pass end-to-end** (operator works one window's flag queue to clean; score before/after on both bars) | never done — the review flow's real impact is unmeasured | +2/+4/+7 (that window) | +4/+8/+14 (that window) | operator ~1–2 h, zero code | Decides the product claim (pure-ML vs ML+review). The queue estimates 2,126 missed at cam2 alone. |
| CERT | **Review-as-certification instrument** (DISCount-style importance sampling of intervals — by conservation violation, confidence, count weight — + VDV-457-style equivalence test with a stopping rule; §7d) | never built; research provides the full statistical design | — (certifies, doesn't count) | enables the ±5%/95% CLAIM at 0.5–1.5 review-h/day once ML ≥~85% | 1–2 wk after R0 | The differentiated product story: auditable QA math no incumbent publishes. |
| L1 | **Land the two-level scorer** in scripts/v2_score_dev.py (harness proven in scratchpad 2026-08-18) | pending server-idle moment (reload kills in-flight jobs) | — | — | 30 min | Every future score reports both bars. |
| C0 | **cam4 T-junction label fix** (trajectory_classifier.py:1153-1164; n==2 branch labels (34,33) 'through', truth 'left') | never built; own gated block w/ 5-camera label-parity tests | +0.3/+0.6/+1.3 | ~0 (volume-neutral) | small | Near-certain; production bins events into a Mio-zero cell today. |

### Tier 1 — in flight / next: the calibration wave

| id | element | status | movement | approach | cost |
|---|---|---|---|---|---|
| W1 | **Busy-window auto-cal → apply → replay-score, per camera** (cam2 RUNNING; then cam5, cam1, cam3, cam4). New feature: operator sets wall-clock start + duration (15 min–15 h, default 07:00–18:00); parallel jobs; ETA. | cam2 sample completing 2026-08-18 | +3/+5.5/+10 | +0.5/+1.5/+3 | ~3 h GPU per camera-hour sampled + replay ~10 min/window |

Procedure per camera (pre-registered): (1) compare proposal to known
gaps; (2) BACKUP db; (3) apply suggestion; (4) run_pass2 apply=False
replay per window; (5) two-level score vs current production; (6)
better → ship via Confirm & process, worse → restore backup. The
coupling law (§6) applies in full: new geometry = new basis; the
per-camera frozen constants and freeze sets must be re-derived if the
wave ships broadly.

Known per-camera targets: cam5 (mouths 38↔39 160 px, 36↔37 162 px on
dominant through exits — 21–31% contradiction rate; the structural
prize: predict +8/+15 movement there alone); cam1 (paths table has
ZERO East-leg rows; EB_right −210 at 1600); cam2 (missing E→S and
W→E path rows; the frozen EB pair); cam3 (never studied).

### Tier 2 — build next (research agents reporting 2026-08-18)

| id | element | status | movement | approach | cost |
|---|---|---|---|---|---|
| E4R | **Re-test "recall is not the bottleneck"** — the never-run G-A4 re-test of the 07-08 spike's conclusion, now under today's assembly + the two-bar instrument. Cheapest form: per-approach detection-recall audit (cached detections vs Mio volume per approach-bin) — no new mechanism, just the measurement the operator's diagnosis has been owed since July | OWED; pre-declared gate never reached (inventory E4) | informs all | informs all | ~1 day |
| A2 | **Motion-gated band recovery** (MOG2/KNN mask + tubelet persistence + confirmed birth over the cached 0.10–0.35 band; refined by §7a — ceiling = the band-visible fraction of misses, measured by E4R first) | never built; research CONFIRMS mechanism + kill gates (§7a #1) | +0/+2/+5 | +0/+3/+7 | days |
| TU | **Tracker low-confidence upgrades** (BoostTrack++ similarity boost, TrackTrack TAI birth suppression, BUSCA capped persistence — the safety plumbing for A2; §7a #3) | never built | +0/+0.5/+1.5 | +0/+1/+3 | days |
| QD | **Discharge-event counting reframe** (count exit-mouth crossings during discharge; short-trace/channel origin; inferred green-window prior; headway sanity flags — §7b #1; pure policy on existing data) | never built; research: production-precedented (GRIDSMART/NCHRP), structurally kills dwell double-counts | +0/+2/+5 (queue turn cells) | +0/+2.5/+6 | days |
| Q1 | **I-24-style physics reconciliation** (MCF with time-growing variance + stopped-state arcs + channel-projected dynamics + QP imputation; §7b #2 — re-explains our dead MCF as cost design) | revival with a NEW cost model; own gates | +0/+1.5/+4 | +0/+2/+5 | 1–2 wk |
| E1 | **Embedding fragment split+merge dedup** (ReID embeddings exist per-camera; image-space channels exhausted, embedding channel never gated) | never built; research CONFIRMS (§7c: ReMOT/GTA/AFLink lineage, +2–4 IDF1 plug-in, self-supervised). MUST RUN BEFORE K1 — echoes are biased noise that balancing would redistribute | +0/+1/+2.5 | +0/+2/+4 | days |
| K1 | **Conservation as variance-weighted GLS correction** with ℓ1-recoverability gating + priced sink slack (NOT equal-trust redistribution — the named fix for why the family was retired; §7c) | research CONFIRMS mechanism + gates; conservation family history in revival ledger | +0/+0.5/+2 | +0/+3/+7 | days–wk |

### Tier 3 — expensive / later

| id | element | status | movement | approach | cost |
|---|---|---|---|---|---|
| A4+A5 | **Far-ROI scale-matched re-detection** (ONE coupled item per §7a #2: far-band crop, plain 2–3× upscale, detect only there with a 1280-fine-tuned scale-matched model; motion-gated schedule ≈2–6 h/cam-day) | never done; the only path to zero-cache-evidence vehicles; SNIP-class evidence | +0/+1.5/+4 | +0/+2.5/+6 | GPU-days retrain + runtime |
| A3 | S3 split (cut mixed-identity tracklets on motion discontinuity; only pre-merge was ever tried) | zero code | +0/+0.5/+2 | +0/+0.5/+2 | days |
| P2 | PPT re-attribution round 2 on post-wave geometry (transferred nowhere on dirty prototypes; cap+admission shipped in PPT-3) | contingent on W1 | +0/+1/+3 | ~0 | days |

### Tier 4 — small mechanisms (each tiny, some die at gates)

- Origin-veto site-activation precondition (options_inventory D2) —
  the sibling idea that shipped for the evidence gate; never built
  for the veto.
- Per-window composition-adaptive rejection (C-named #5).
- Per-window prototype floors (plan_ppt3 follow-up; cam4-0700's
  below-floor SB_right drain is the motivating case).
- Compression-relative constants (C-named #3) — road-width-normalized
  replacements for every frozen pixel constant; needs a phase-0
  measurement pass, not a knob sweep.
Portfolio: +0/+1/+2.5 per bar combined.

### Revival-ready ledger (closed under the two-iteration budget; code
### + tests intact; revival CONDITIONS named in their docs)

- **F2M fragment-to-mouth** (plan_t3_f2m_*): real recovery (+2.9/+1.9)
  but EB_left contamination; revive after redraw/wave + dwell-aware
  guard.
- **Conservation family** (C1/C2, plan_conservation_pass,
  plan_v2_conserve_activation, D1 block): mechanism proven at cam2
  (9.1→3.3%); retired non-blind-deployable; activation precondition
  since shipped; D1 re-test FAILED G-D1b 2026-08-13 — read that
  verdict before any third attempt.
- **Regime tracker hybrid** (plan_h1_hybrid): pre-V2 evidence
  (throughs from ByteTrack + turns from OC-SORT); V2 re-test closed.
- **Tubelet linker** (plan_t3_a1b2): 0.70–0.74 anchorless recovery,
  reusable component; rescore-only application DEAD (converts to
  phantom counts).
- **Heading-lock** (E2): killed on aggregate 5/95 BEFORE the
  phantom-slot instrument existed; a retry would use the right
  instrument.

### Genuinely dead — do not re-spike (evidence multiple times over)

See options_inventory_2026-08-11 §F verbatim: SAHI@VGA, super-
resolution, feature-level VOD, four image-space pairwise twin
channels, velocity-continuity at 640×480, drawn-channel assignment,
chain-economics MCF, ×-scaled merge expecteds, bank-D path fill,
V2_TIMELOCAL, V2_GATE_AXIS, endpoint extension at cam1/4/5. Plus
(2026-08-13→17): A1 rescore-only, ft2 basis both scopes, cardinal-
balance selectors, confusion metric (structurally unsound), naive
threshold lowering.

---

## 4. PORTFOLIO SCENARIOS (overlap-discounted, pre-registered)

**Movement bar** (from 65.6%): LOW ~70 · MID ~78 · HIGH ~85.
**Approach/PRD bar** (from 43.4%): pure-ML LOW ~48 · MID ~57 · HIGH
~68; **with a thorough measured review pass per study**: MID ~70 ·
HIGH ~85. The industry research (§7d) settled the open question:
nothing in the 2020–2026 record shows pure-ML holding ±5%/95% on
sub-1080p footage — every vendor that sells that grade runs humans
in the loop, and OUR target exceeds what any of them actually
promise. Estimated hard ceiling with this footage: high-80s pure-ML
(reference noise + optics own the last points); the CERTIFIED claim
is reached via review, priced at 0.5–1.5 h/intersection-day once ML
compliance is ~85%.

**THE STRATEGIC SEQUENCE (synthesis of all four research reports +
the two-bar finding):**

1. **Audit before building** — E4R miss audit (band-visible fraction
   of misses) + QD's origin-recoverability measurement + R0 review-
   pass measurement. Three cheap measurements that size every lever.
2. **Volume ladder (approach bar 43% → ~85%)**, in the researched
   order: E1 embedding dedup (biased noise OUT first) → QD
   discharge-event counting (the production-precedented reframe;
   kills dwell double-counts structurally) → K1 weighted-GLS
   conservation balancing (now on ~unbiased residuals) → A2
   motion-gated band recovery (+ TU safety plumbing) → A4+A5 far-ROI
   only for the zero-cache-evidence remainder the audit shows.
3. **Movement-bar track in parallel**: calibration wave (running) →
   C0 label fix → P2 re-attribution on clean geometry.
4. **Certification layer (the product story)**: once approach
   compliance ~85%, CERT turns the review screen into a VDV-457-
   style certification instrument with DISCount importance sampling
   — "±5%/95% per approach, certified per study, at 0.5–1.5
   review-hours/day, auditable" — a claim no incumbent publishes the
   math for. Miovision's own unreviewed sensors measured 26–42%
   RMSE; the human layer is what makes their marketing true. Ours
   will be measured, not marketed.

---

## 5. WHAT IS RUNNING / IMMEDIATELY NEXT (as of 2026-08-18 night)

1. cam2 busy-window auto-cal 17:00–18:00. **Attempt 1 completed and
   exposed an INSTRUMENT defect, not a hypothesis verdict**: 90k
   frames, 23,393 raw → 4,876 kept trajectories — and the zone stage
   collapsed to 1 zone / 1 path, because pure single-linkage-at-cut
   lacks DBSCAN's core-point density rule: queue-fragment endpoints
   form sparse bridges that CHAIN all mouths into one mega-cluster at
   busy-window density (the midnight 57-trajectory regime never hit
   this). FIXED same night (commit: dbscan_like true core/border
   semantics + border-band fallback + trajectory persistence so a
   2.6 h collection is never repeated to retry clustering; synthetic
   verification 4/4 · 3/3 legacy · 4/4 at 20k points). **Attempt 2
   RUNNING with the fix** (~2.6 h). DECISION TREE unchanged: paths
   cover (26,29)+(28,26) and legs 4/4 → W1 backup/apply/replay-score;
   missing → the wave hypothesis weakens, record and stop.
2. Four research agents (detection recall / queued+stopped /
   conservation+dedup / industry practice) — reports land in §7.
3. L1 two-level scorer landing + this doc's upkeep.
4. R0 review-pass measurement — needs the OPERATOR (1–2 h on one
   window's queue). Highest decision-value per hour on the board.

---

## 6. THE OPERATING LAWS (how this project measures — do not skip)

1. **Gate discipline**: numeric gates DECLARED before any run; a miss
   is a ledgered deliverable; two-iteration budget per mechanism
   family; production changes ONLY through the blind apply gate
   (backend/services/apply_gate.py) with operator adjudication —
   never around it, no matter how good the dev number looks.
2. **Activation-coupling law**: ANY detection/tracker/geometry change
   moves everything downstream (pair activation, constants, freeze
   sets). Comparisons across a basis change are VOID; re-derive.
3. **Scoring-basis discipline**: name the basis of every number
   (replay-isolated / production pass-2 / live-legacy; movement bar /
   approach bar; which window). OFF-parity reproduction proves a
   basis matches. Numbers from different bases are incomparable.
4. **GT is dev-only**: Miovision/manual counts never reach runtime
   decisions. Mechanisms must self-calibrate from the video/geometry
   (split-half floors, census ratios, conservation).
5. **Traps** (each cost a session-hour once): scorer parses cam+
   variant from the DB filename STEM; uvicorn reload=True kills
   in-flight server jobs on ANY watched .py edit; killing the uvicorn
   parent orphans the reload worker holding port 5000 (kill by
   commandline match); sqlite connect() CREATES empty files on typo'd
   paths; WAL-safe copies via the backup API only; %TEMP% is swept
   mid-session (scratch lives in data/projects/<id>/_replay_scratch);
   an auto-cal job's initial VIDEO SEEK (deep into a 24 h file) can
   starve the dev server's API for 30-45 min — a dark UI during a
   job's first phase does NOT mean a dead job; verify with process
   CPU (Get-Process, delta over 10 s) before killing anything;
   AND THE STALE-MODULE TRAP (2026-08-18, cost one 40-min attempt):
   the uvicorn reloader can WEDGE during a GIL-heavy job and silently
   stop picking up .py edits, while lazy module imports pin job-side
   code to the process's first-import version — after editing any
   job-side module, VERIFY the serving process's birth time is
   younger than the edit (Get-Process StartTime) or bounce the server
   explicitly before relaunching a job.

---

## 7. RESEARCH ADDENDA (agent reports, 2026-08-18)

### 7d. Industry practice + review economics (landed 2026-08-18)

**Headline: NO commercial vendor guarantees anything close to
±5%-per-approach-per-interval-in-95%-of-intervals — our PRD target is
STRICTER than what the incumbents promise. And Miovision's "95%" is a
HUMAN-IN-THE-LOOP number: every study gets technician configuration,
a manual review pass, and corridor cross-checks (their published
check — "±5 vehicle accuracy or 95% match between common links" — is
literally our conservation QA, operationalized). Independently
measured WITHOUT that human layer, Miovision permanent sensors ran
26–42% RMSE per movement, with through movements "significantly
underestimated" by far-field sensing failure — our exact failure
mode. The human layer, not the model, makes their claim true.**

Decision-grade facts:
- Independent pure-ML video TMC: WMAPE 1.4–33.7% by vendor/site
  (NCHRP WOD 436); per-movement 85–96% in decent conditions;
  occlusion / entry-exit truncation / lighting are the universal
  residuals. Nothing in the 2020–2026 record shows pure-ML holding
  ±5%/95%-of-intervals on sub-1080p single-camera footage.
- **Certification precedent exists: VDV 457** (German transit APC) —
  certifies ≤5% relative error at ≥95% confidence via SAMPLED manual
  reference counts + an EQUIVALENCE TEST. The statistical machinery
  to turn our review screen into a certification instrument.
- **DISCount (AAAI 2024)**: importance-sampled human counting with
  provably unbiased estimators + confidence intervals + a stopping
  rule ("review until the CI is inside tolerance, stop with a
  certificate") — 9–12× review-labor reduction. The blueprint for
  routing our flag queue (sample intervals by conservation
  violation, low confidence, count weight).
- **Review-hours math**: full manual ≈ 21 counter-min/video-hour
  (4–13 h per intersection-day). At 85–90% ML compliance, a
  CERTIFIED ±5% estimate needs humans on ~8–11% of intervals ≈
  **0.5–1.5 review-hours per intersection-day**. At our current 43%
  approach-bar compliance the math inverts (2–4+ h/day, approaching
  manual cost) — so the ML must close the systematic-miss gap to
  ~85% BEFORE review-certification is economical.
- Manual review itself errs >5% in a majority of controlled cases
  and fatigues — "send everything to humans" certifies nothing.

**Positioning recommendation (adopt): sell ML + MEASURED,
statistically-targeted review-hours — "±5%/95% per approach,
certified per study by an equivalence test, at ~0.5–1.5
review-hours/intersection-day, auditable against your own video."
Miovision cannot show its QA math; we can. Pure-ML numbers belong in
the roadmap narrative (shrinking review-hours per release), not the
product guarantee.**

### 7b. Queued/stopped vehicles (landed 2026-08-18)

**Headline: NOBODY tracks identity through a 90-second red and wins
— the best-instrumented system in the world (I-24 MOTION) measures
online SOTA at HOTA 9.5% in dense traffic (47.9–53.3 IDs per real
vehicle) and recovers only via OFFLINE physics reconciliation, while
every production intersection counter that ships (GRIDSMART,
stop-bar video zones, AI City winners) SIDESTEPS the problem: count
exit-crossing events during discharge, when every vehicle is moving,
and assign movement from geometry + short traces — not full-journey
identity.**

1. **Discharge-event counting reframe (NEW ITEM QD) — highest
   leverage per unit risk.** Count = exit-mouth crossing event (our
   box perimeter already IS the gate set); origin from a short
   backward trace (2–6 s) or channel/lane mapping where the trace
   dies in the queue; per-approach green windows INFERRED from our
   own data (cluster start-of-motion at the stop-bar band) as an
   assignment prior; discharge-headway arithmetic (sat. headway
   ≈1.9 s/veh) as a runtime-legal per-cycle sanity flag. Structural
   properties: dwell double-counting becomes IMPOSSIBLE by
   construction (one exit event per vehicle); never-completing
   throughs stop mattering (a discharging through crosses the exit
   mouth moving). Production evidence: NCHRP WOD 436 (2025) video
   TMC WMAPE 1.4–33.7% — best-in-class is low single digits.
   Estimate: 50–80% error reduction in queue-dominated turn cells.
   PRE-WORK (measure first): share of exit events whose backward
   trace dies with ambiguous shared-lane origin. KILL GATES: shared
   thru+left lanes; RTOR/permissive lefts (phase = prior, never a
   hard mask); spillback vehicles stopping ON the gate (crossing
   hysteresis). Pure policy on existing data — testable within days.
2. **Intersection-adapted I-24 physics reconciliation (refines Q1).**
   Min-cost-flow fragment association with NLL edge costs under
   TIME-GROWING Brownian uncertainty (variance α+βΔt — a stopped
   vehicle's dwell hypothesis falls out naturally), explicit
   stopped-state arcs (Δx≈0, Δt ≤ max-red), channel-projected 1D
   dynamics, then QP gap imputation between LINKED endpoints only.
   Literature gains: fragmentation ↓60–92%, MOTA +0.15–0.42 (TR-C
   160, 2024; production at 276-camera scale on 64 CPU cores — our
   5-camera scale is trivial). **Re-explains our dead MCF: cost
   design, not framework** — ours lacked the time-growing variance
   and stopped-state hypothesis. Estimate: 30–60% of queue fragments
   merged → 20–50% cell-error reduction standalone. KILL GATES:
   imputation hallucination across box sides (NEVER extrapolate
   unlinked stubs; impute only between fixed endpoints; merged-track
   movement disagreement must beat the fragment baseline).
3. **Stationary-hardened tracker replay (folds into TU).** BYTE
   low-score pass + dwell-scale buffers + v≈0 Kalman freeze +
   ground-plane association gating (UCMCTrack-style — we HAVE the
   operator calibration) + birth suppression over stationary tracks
   + GSI infill. A multiplier, not a fix (I-24 caps expectations):
   20–40% fewer queue fragments. KILL GATE: ID-transfer rate in
   queue windows must not rise (ghost tracks stealing the
   neighboring queued car during creep = wrong movement, worse than
   a fragment).
4. **Dwell-aware dedup, the right shape:** the ±2 s guard was wrong
   — the correct predicate is near-zero displacement between
   fragment A's end and B's start, NO gate crossing between, Δt ≤
   max-red → same vehicle at ANY Δt (AFLink-structure specialized
   with a stationary hypothesis). KILL GATE: same-slot impostor (car
   B stops in car A's slot next red) — the no-crossing-in-between
   condition is load-bearing.

Caveat recorded by the agent: our "0.04→0.52 ID-switch" figure
could not be independently confirmed (direction confirmed
everywhere; likely from I-24 3D per-scene splits). Two paywalled
2025 sources worth manual retrieval: TR-C S0968090X25003377
(fragment reconstruction) and DOT rosap 86975 (AI intersection
analytics).

### 7a. Small-vehicle detection recall (landed 2026-08-18)

**Headline: attack the MEASURED failure — 32% of cached detections
sit in the 0.10–0.35 band the tracker cannot birth from — with
motion + persistence + confirmed-birth evidence, at near-zero
marginal compute. But run the miss AUDIT first (= E4R): scan the
cache along known GT-window miss trajectories; the band-visible
fraction of misses is the ceiling of the cheap path and decides
whether the expensive path is a follow-on or co-requisite.**

1. **Motion-gated band recovery (refines A2).** Three co-attesting
   evidence sources, none sufficient alone: MOG2/KNN background-
   subtraction foreground masks (decode-bound ~realtime; CUDA MOG2
   ~570 fps HD) + REPP/Seq-NMS-style tubelet persistence over the
   cached low-band boxes (CPU minutes/camera-day; REPP: YOLOv3 68.6→
   75.1 mAP as pure post-processing) + ConfTrack-style confirmed
   birth (init at conf 0.1, require N consecutive matched frames).
   Satellite-video tiny-vehicle literature (Sensors 2025, SDM-Car,
   DeTracker) consistently shows MOTION evidence, not appearance, is
   what makes few-pixel vehicle detection work (+4–8 recall pts).
   Estimate: closes 1/3–2/3 of the worst-approach deficit IF misses
   are band-visible (−17% → −6..−12%). KILL GATES: shadows/headlight
   beams (exclude MOG2 shadow class; veto luminance-only blobs at
   night); stopped queues absorb into background (motion is
   BIRTH-ONLY evidence — never suppress an existing track); camera
   shake (global-motion tripwire); swaying vegetation (monotone
   displacement along approach + row-size prior). Pre-declared
   surplus-event budget (the +747 lesson) + near-field OFF-parity.
2. **Far-ROI scale-matched re-detection (merges A4+A5 into ONE
   coupled item).** Crop the operator-calibrated far band, plain-
   upscale 2–3×, detect ONLY there with a model fine-tuned AT 1280 on
   scale-matched chips. Not SAHI-redux: the fine-tune is the
   load-bearing half (SNIP CVPR 2018; VisDrone YOLOv8 640→1280 =
   +25% relative vs +6% for a P2 small-object head — resolution
   beats architecture). The only path to vehicles with ZERO cache
   evidence. Motion-gated scheduling lands it ~2–6 h/camera-day
   (vs ~20 h full re-detect). Estimate: closes ~half the
   far-approach gap standalone; overlaps heavily with #1 — treat as
   substitutes until the miss audit splits the population. KILL
   GATES: seam double-count (cross-scale NMS, zero net near-cell
   change); fine-tune drift (ROI-confined contribution; held-out
   camera first); corridor overfit (fine-tune data excludes corridor
   GT); plain resize only (GAN-SR died for hallucination).
3. **Tracker-side low-confidence upgrades** (BoostTrack++ soft
   boost — adopt the tracklet-similarity term, SKIP the new-object
   term (phantom generator); TrackTrack Track-Aware Initialization —
   strictly reduces false births, free safety; BUSCA persistence
   capped to short gaps). Small alone (+1–3 far-approach net); the
   safety plumbing that makes #1's promoted band countable. KILL
   GATES: zombie tracks — persisted/interpolated boxes NEVER satisfy
   gate crossings alone; ≥K real detections required each side of a
   crossing.

Deprioritized with reasons: YOLOV++ (needs full re-detect for gains
#1 approximates on cache); density-map counting (volumes, not turns
— useful only as a far-band audit signal); CountingMOT (crowd
domain, retrain-class; watch); detector swaps (survey 2025: tiny-
object AP still 20–40%; resolution beats architecture); deep BGS
(MOG2/KNN suffice for a gating signal). Full citations in the agent
report (session transcript) and inline above.

### 7c. Conservation-as-correction + embedding dedup (landed 2026-08-18)

**Headline: the retired conservation pass failed for a KNOWN, NAMED
reason with a KNOWN, NAMED fix — and the duplicate problem has a
direct, cheap, never-tried-in-repo attack that must run FIRST.**

1. **Embedding fragment split+merge (E1) — run BEFORE any balancing.**
   Offline tracklet split-and-connect on the per-camera ReID
   embeddings we already compute; the ReMOT / GTA (arXiv 2411.08216)
   / StrongSORT-AFLink lineage adds +2–4 IDF1/HOTA as pure
   post-processing, self-supervised (no GT — fits our runtime law).
   Fragmentation is documented as the dominant counting-error source
   (up to ~48 fragments/vehicle in dense traffic, TR-C 2025). Expected
   10–30% relative net-volume reduction on duplicate-driven links
   (the measured ~101/day echo class). CPU-cheap (cosine over
   tracklet-mean embeddings). KILL GATES: same-color platoon false
   merges (inverts error sign — the per-cell 5/95 catches it, net-MAE
   would not); pose rotation through turns; far-field crop noise
   (gate on crop size — which re-creates a far-field blindspot,
   record it).
2. **Conservation as VARIANCE-WEIGHTED constrained least squares
   (K1), not equal-trust redistribution.** 45-year-old
   count-balancing field (Kikuchi/van Zuylen TRR 1717; NCHRP 765;
   process-engineering data reconciliation). The cure for "damages
   low-evidence cameras": (a) weight each count's deviation penalty
   by measured confidence (evidence_activation → variance) so
   uncertain counts ABSORB adjustment instead of exporting it;
   (b) an ℓ1-recoverability score (Yin et al. 2017, arXiv 1704.02052)
   computable from corridor topology alone decides WHICH links may be
   corrected — the continuous version of our activation precondition;
   (c) a priced slack term so real driveways/sinks are not
   "corrected" into fiction. Modern practice (2026 GNN+EnSRF fusion,
   R²=0.80 network-wide, no runtime GT) enforces conservation the
   same soft weighted way. Expected 20–40% corridor-wide relative
   net-volume reduction (our own 9.1→3.3% cam2 result sits at the
   literature's upper end). Tiny QP per bin, CPU. KILL GATES:
   unmodeled real sinks; correlated same-direction bias at both ends
   (conservation satisfied by wrong numbers — silently does
   nothing); platoon bin-edge misalignment (likely the actual G-D1b
   failure — use overlap-windowed constraints).
3. **Cross-camera ReID: per-vehicle matching is INFEASIBLE at our
   resolution** (rank-1 ≈42%, most crops <200 px at DOT camera
   class) — but high-threshold SAMPLED matching runs at up to ~95%
   precision, usable ONLY as a survival-rate signal that tells the
   balancer which side of a 59–64% link gap is lying (allocates the
   gap between A-overcount and B-undercount). 5–20% relative, last
   priority, feeds #2's weights.

**Ordering law from the agent (adopt as-is): dedup → balance → ReID
weights.** Echoes are BIASED noise; every reconciliation method
assumes ~unbiased noise, so balancing un-merged duplicates
redistributes echo mass instead of deleting it.

---

## 8. HOW TO RUN THINGS (for the next person)

- Server: `py start_server.py` → http://127.0.0.1:5000 (that port
  only). Desktop wrapper: `python run.pyw`. The dev reloader watches
  ALL .py — don't edit while jobs run.
- Tests: `python -m pytest backend/tests/ -v` (967 green 2026-08-18).
- Score a window (two-level after L1 lands):
  `py -X utf8 scripts/v2_score_dev.py <working.db>` — stem must be
  `..._cam<N>_<variant>.db`. Interim two-level harness: the 2026-08-18
  session scratchpad `score_two_level.py` (copy in git history of
  this doc's commit if the scratchpad is gone).
- Replay control: `py -X utf8 scripts/v2_run_pass2.py --camera N
  --variant <v>` (~8.5 min/window, ~460 MB in _replay_scratch).
- Audited apply: `scripts/v2_apply_reattr.py` (quiesce server first,
  incl. the orphaned reload worker).
- Production verification (run at every session end): count
  vehicle_events per camera×window; expected as of 2026-08-18:
  cam1 4600/3321/5778 · cam2 5815/4426/6835 · cam3 5643/3790/6613 ·
  cam4 4956/3335/5652 · cam5 5067/3669/6047.
- Operator guide (how to drive the UI): docs/Operator_Guide_
  2026-08-18.pptx + the published web version.
- Key docs: finding_two_bar_inversion_2026-08-18.md ·
  options_inventory_2026-08-11.md (historical backlog) ·
  handoff_2026-08-13_tier3.md · plan_ppt3_2026-08-17.md ·
  apply_record_2026-08-13_ppt2.md · plan_gate_ag2_2026-08-13.md.

---

## CHANGELOG

- 2026-08-18: created. Two-bar finding recorded; 13-window two-level
  baseline; backlog consolidated from options_inventory + tier3
  handoff + ppt3 follow-ups with per-bar hypotheses; calibration
  wave running at cam2; four research agents dispatched.
- 2026-08-18 (later): all four research reports folded in (7a-7d);
  backlog re-ranked — new items QD (discharge-event counting), CERT
  (review-as-certification), TU (tracker safety plumbing); E1/K1
  refined with the dedup-before-balance ordering law; A4+A5 merged;
  strategic sequence added to section 4. Provenance corrected: the
  volume finding confirms the operator's July diagnosis (E4R owed).
- 2026-08-18 (night): auto-cal attempt 1 exposed the clustering
  density collapse (1 zone from 19k trajectories); core-point rule +
  border fallback + trajectory persistence shipped; two-level scorer
  landed in v2_score_dev (L1 DONE); attempt 2 relaunched.
