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
| A2 | **Motion-mask fusion** (background subtraction vs existing detection cache; decode-bound ~realtime) | never built; the one detection lever not ledgered dead (options_inventory §A2; tier3 handoff "alive") | +0/+2/+5 | +0/+3/+7 | days |
| Q1 | **Queued/stopped-vehicle mechanism** (dwell-aware dedup + trajectory completion; revives F2M under its named conditions + the surviving tubelet linker from plan_t3_a1b2) | research sweep running (agent) | +0/+1.5/+4 | +0/+2/+5 | 1–2 wk |
| K1 | **Conservation as CORRECTION** (corridor link balance is measured today as QA only; matrix-balancing / constrained TMC adjustment literature) | research sweep running (agent); conservation family history in §C below | +0/+0.5/+2 | +0/+2/+6 | days–wk |
| E1 | **Embedding twin dedup** (ReID embeddings exist per-camera; image-space pairwise channels exhausted, embedding channel never gated — options_inventory C-named #4) | never built | +0/+1/+2 | +0/+1.5/+3 | days |

### Tier 3 — expensive / later

| id | element | status | movement | approach | cost |
|---|---|---|---|---|---|
| A4 | Scale-matched 1280 fine-tune (train AT inference scale on upscaled frames) | never done; 640-trained ft2 closed | +0/+1/+3 | +0/+1.5/+4 | GPU-days retrain |
| A5 | Far-ROI crops | zero code | small | small | days |
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
HIGH ~85. Whether ±5%-in-95%-of-bins is reachable AT ALL on sub-1080p
footage without review is exactly what R0 + the industry-practice
research agent decide. Estimated hard ceiling with this footage:
high-80s (reference noise + optics own the last ~10 points).

---

## 5. WHAT IS RUNNING / IMMEDIATELY NEXT (as of 2026-08-18 evening)

1. cam2 busy-window auto-cal (17:00–18:00 sample) — completing;
   compare proposal vs known gaps, then the W1 procedure. DECISION
   TREE: paths cover (26,29)+(28,26) and legs 4/4 → proceed to
   backup/apply/replay-score; missing → the wave hypothesis weakens,
   record and stop.
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
   mid-session (scratch lives in data/projects/<id>/_replay_scratch).

---

## 7. RESEARCH ADDENDA (agent reports, 2026-08-18)

> PENDING — four agents running: (a) small-vehicle detection recall,
> (b) queued/stopped tracking + trajectory imputation, (c) flow-
> conservation correction + embedding dedup, (d) industry accuracy
> practice + review economics. Their ranked findings replace this
> block when they land.

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
