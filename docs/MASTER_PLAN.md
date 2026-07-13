# MASTER PLAN — Intersection Counter

**From a validated counting stack to an operator-ready Miovision replacement.**
Living roadmap; supersedes nothing but consolidates everything. Last updated 2026-07-13.

Companion docs (still authoritative for their topics):
- `docs/architecture_research_2026-06-11.md` — why the approach is SOTA-sound
- `docs/implementation_plan_architecture_2026-06-11.md` — the Phase 0–4 macro plan (done)
- `docs/new_site_runbook.md` — the operating procedure (the deliverable)
- `docs/dress_rehearsal_findings_2026-06-23.md` — the dry-run findings
- `docs/phase{2,3,4}_*` — bank bootstrap / conservation QA / spot-check

---

## 0. The governing principle — BLIND DEPLOYMENT

The product's job is to count an intersection **accurately with no ground truth at the
site**. That single constraint decides everything below.

- **Ground truth (Miovision / manual counts) is DEVELOPMENT data, not a deployment
  dependency.** We use it to *learn the failure modes once* (low-light detection,
  articulated trucks, calibration pitfalls) and fix them so they **generalize** — the
  same way you train a detector on labeled data then run it unlabeled.
- It becomes illegitimate the moment we **per-site overfit** knobs against the answer.
  The corridor's per-camera tuning is exactly this risk; treat it as suspect.
- **Deployment accuracy assurance comes from BLIND QA** — the operator-produced spot
  count, conservation checks, and confidence/coverage diagnostics — never from a
  Miovision we won't have.

Litmus test for any proposed fix: *"Would this work, and would we know it worked, at a
site where Miovision never ran?"* If no, it's research, not product.

---

## 1. Where we are (validated)

- **Accuracy ceiling proven.** On the Sunnyvale corridor the detection→tracking→
  assignment stack hits **−1.5% / +2.2% net** vs an independent human count (cam1 beat
  Miovision) — i.e. the stack *can* pass the TxDOT ≤5% bar. See
  [[project_manual_count_triangulation]].
- **New-site procedure runs end-to-end.** Dress rehearsal on a fresh project: calibrate →
  process in the app → detection cache written live → GT-free bank → apply → overnight
  full run → TMC Excel. Validated 2026-06-29.
- **Cardinal = position convention** shipped project-wide (approach = bound = opposite;
  diagonals first-class). See [[project_cardinal_position_convention]].
- **Recent enabling fixes:** live pipeline writes the detection cache; `apply_bank`
  retrack de-hardcoded from the corridor; #9 preflight warnings; #10 `--project`
  generalization.
- **Audit tooling:** `scripts/triangulate_manual.py` (vs manual), `scripts/audit_fm51.py`
  (vs Miovision XML, reusable for any site), `scripts/interval_metric.py` (the metric below).

---

## 1b. The acceptance metric — AVG |err| ≤ 5% per 15-min interval

Net counts hide per-interval error (a run nets ~0% while individual bins blow past
5%). So the bar is **mean-ABSOLUTE per-15-min-interval error, ≤ 5%**, vs ground truth
— `scripts/interval_metric.py` (`summarize_bins` / `per_interval`, unit-tested).

- **This is a DEVELOPMENT-VALIDATION metric** — it needs ground truth (manual or
  Miovision) which we will NOT have at a real site. The **blind deployment proxy is
  the §3-B acceptance gate** (spot-count error + flag queue); we validate that the
  gate tracks this metric, then trust it blind. Litmus per §0.
- **Timing floor:** bin-edge timing means even a perfect counter shows a few %/interval
  (Miovision itself sits ~2.8% vs manual on cam1) — which is why the bar is ≤5%, not ≤1%.
- **Report two cuts:** the TOTAL (the headline) AND **per-approach** — errors cancel at
  the total level, so per-approach is where the real work shows.

**Baseline (2026-06-30), vs Miovision per interval:** total squeaks PASS on cam1 4.9% /
cam2 2.6% / cam4 3.6% / cam5 2.5%, but **per-approach FAILS on nearly every camera**
(EB/NB/SB > 5% — cancellation flatters the total). The one true-GT check, **cam1 vs the
hand count = 7.1% FAIL** (Miovision benchmark 2.8% PASS) — the honest number says we are
NOT yet at the bar. cam3 (24h) reads 39.7% but is a night low-volume + coverage-edge
artifact (the tool flags the no-coverage bins); a peak-window cam3 cut is the fair compare.
→ The lever is **per-approach attribution**, which is exactly what the §3-B flag queue
(per-approach gap feeder) and §3-D tuning target.

---

## 2. The accuracy gap — FM51-CORD4699 audit (2026-06-29)

Our overnight run vs the Miovision deliverable on the **same footage** (405051,
2026-04-30, AM+PM peaks = 240 min): **Miovision 3,469 vs ours 3,188 = −8.1% miss.** It
decomposes into four distinct problems — NOT one monolithic "algorithms are bad":

| # | Problem | Evidence | Class |
|---|---------|----------|-------|
| 1 | **Detection/tracking miss, time-localized** | AM ~−3%; **PM 16:30–18:00 = −12% to −20%** (worst −19.6% @17:15). On the **NB FM 51** approach: 1,348 vs 1,668 (−19%); the other through (SB FM 51) was dead-on (1,735 vs 1,741). Likely low afternoon sun / glare / shadow on that approach. | DETECTION |
| 2 | **Vehicle classification broken** | Articulated **0 vs 102** (all lumped into Mediums → Mediums 211 vs 92). No FHWA-8+ bucket. | CLASSIFIER |
| 3 | **Calibration didn't match the site** | Real intersection is a **3-leg T** (SB FM 51 / NB FM 51 / WB Co Rd 4699); our calibration had **4 legs** (phantom SE = 0 traffic) and mislabeled directions. | OPERATOR PREP |
| 4 | **Side-road over-count** — **FIXED 2026-07-06 (105→72)** | WB Co Rd 4699: ours 105 vs Miovision 60 (+75%). Root cause: short fragments of main-road W→E throughs, origin mis-read onto the adjacent side-road leg, labelled an impossible "through from a T-stem" (duplicating already-counted main-road vehicles). Fix = `services/through_gate.reject_invalid_throughs` (reject a 'through' between a pair the bank labels a TURN); PER-CAMERA validated tool (the corridor regression showed cam3 has 691 LONG real left-turners on a bank-left pair — NOT a blind default). Residual +12 = excess rights + 2 phantom-SE throughs (audit #3). | ASSIGNMENT |

### Honest hindsight vs preparation split (the key question)
- **Only knowable with the answer key (hindsight):** the *magnitudes* — −8.1%, the −19%
  on NB, the PM degradation curve, the 102 articulated. Blind, we would not have those
  numbers. **This is the one genuinely answer-dependent thing**, and the lesson is that
  **our blind QA must be able to catch a time-localized miss without Miovision.**
- **Preparation / process / development (blind-deployable):** the GT-free **bank needs no
  Miovision** (built from the site's own traffic — the 5-min bank was a rehearsal
  shortcut, not a ground-truth gap); **calibration** comes from the operator reading the
  site/video/map; **articulated** is a capability gap found by auditing the classifier's
  own coverage. Three of four fixes generalize and deploy blind.

---

## 2b. Session re-diagnosis + re-prioritization (2026-07-07)

Working cam2 with the operator's OWN drawn channels re-diagnosed the per-approach gap and
re-ordered the roadmap. Full synthesis: [[project_box_clip_direction_2026_07_07]].

**The error is a STACK that bottoms out in TRACKING — not drawings, not the matcher:**
1. **Drawings are good; the code was discarding them.** Cars sit 12–25px on the operator's drawn
   curves (90%+ within 25px); curvature separates movements the auto-bank could not (drawn NB-left
   40→105 vs GT 103). Bug was ours — `build_bank_gtfree` refit + dedup-dropped channels before use.
   **FIXED: drawn-direct** (centerline used verbatim as the UI Bézier `_chCtrl`/`_chQuadAt`; u-turn
   reversal-fraction gate; `--refit-channels` escape hatch; `test_channel_centerline.py`). The
   earlier "collinear WALL / corridors can't separate collinear" conclusion is OVERTURNED.
2. **Attribution: shape-matching is right, but COVERAGE-BLIND.** Point-to-zone (nearest-anchor /
   box-crossing) is a snap-magnet — 43–55% vs shape's 10.8% (re-validates "NO exit zones").
   `_mdh_cost` hard-wires coverage=1.0, so movements sharing an origin- or exit-leg run collinear
   and scramble regardless of drawing quality. Lever = **coverage-aware matching**: box-clip-with-
   SHAPE (not zone), or a road-aligned **(s,d) curvilinear matcher** (perpendicular cross-sections →
   coverage = s-span fixes u-turn/graze/collinear; forecast = extend s at constant d).
3. **Tracking is the floor.** Far-field cars birth LATE (births 6.7× deeper into frame than deaths;
   the birth gate drops 32% of real faint detections at the oblique frame's top) → the
   DISCRIMINATING entry/exit segment is truncated → collinear becomes unattributable BY
   CONSTRUCTION. Lowering the gate just fragments (3,621 tracks for 1,387 cars). Fix = appearance
   re-association, **ReID** — BUILT, measured discriminative at 20–40px (AUC 0.87–0.89), SHIPPED on
   cam1 (21.8→7.2% net, `reid_project_plan_2026-06-01`), but **never applied to cam2–5**; the live
   app still defaults to plain ByteTrack. Also: BoT-SORT's `cmc_method="ecc"` (should be `none` on a
   static camera) silently wastes processing time (`tracker.py:233`).

**Blind reframe (governs all — see §0):** we have been tuning cam2 AGAINST Miovision; those
per-camera `calib_*` knobs do NOT transfer to a GT-free new site. Reliable blind ≤5% needs tracking
good BY DEFAULT (ReID, not per-camera babysitting) + attribution robust to those tracks + a TRUSTED
blind acceptance gate (§3-B). GT is a one-time validator, never a per-site input.

**Re-prioritized levers (highest first):** ① tracking by default (ReID + cam2–5; prove it
generalizes without per-camera GT tuning; fix ECC) → ② coverage-aware attribution
(box-clip-with-shape / (s,d)) → ③ GT-free defaults (the `calib_*` knobs were GT-tuned) → ④
calibration UX (drawings already good enough — mechanics are NOT the current blocker; auto-cal's
midnight sample window is the one real weak spot) → ⑤ trusted blind gate.

**SUPERSEDED 2026-07-08 (§2c):** the lever-① spike RAN and FAILED its gate — and overturned the
"bottoms out in TRACKING" diagnosis above for cam2's event-level counts. The 2×2 isolation showed
the collapse follows the BANK/attribution gate, not the tracker; lever ② is now the top lever,
inside the two-pass architecture. §2c is authoritative; the ECC fix and the drawn-direct repair
above remain shipped and valid.

---

## 2c. Spike verdict + the TWO-PASS reframe (2026-07-08) — AUTHORITATIVE

The §2b lever-① spike ran end-to-end (`docs/spike_reid_cam2_results_2026-07-08.md`; the
spike plan doc is removed — git history has it): cam1's BoT+ReID recipe UNCHANGED on cam2,
drawn-direct bank, 07:00–07:30 window, working DB only. **GATE: FAIL — and it corrects
§2b: cam2's per-approach error bottoms out in ATTRIBUTION, not tracking.**

**The 2×2 that isolates it** (net error / SB-thru delta, Miovision 310 = truth):

| tracker + bank | net | SB-thru |
|---|---|---|
| ByteTrack + live (data-driven) bank — the baseline | −4.5% | −43 |
| ByteTrack + drawn-direct bank (bank swapped) | −18.5% | −187 |
| BoT motion + drawn-direct (tracker swapped) | −20.8% | −198 |
| BoT+ReID + drawn-direct (the recipe) | −18.3% | −182 |

Tracker family moves cam2 a few percent; bank choice moves it ~15 points. The missing
SB/WB vehicles emit NO event — their far-field-truncated tracks match no channel shape.
**Shape-matching-as-GATEKEEPER is the defect**: drawn-direct's verbatim centerlines don't
lie where truncated tracks lie (fitted channels do — why the live bank catches 267/310).
ReID stays shipped on cam1, but it recovers only +16 SB-thru on cam2 and is NOT the cam2+
lever. Do NOT roll BoT+ReID out as the default.

**Also found (fixed, commit 9490361):** `od_accuracy.leg_idx()` was 180°-flipped for every
cam≠1 caller (poisoned the merge volume-gate + `_measure` for cam2+); and `combine_regimes`'
volume gate consumed **Miovision at runtime** — cam1's shipped 7.2% partially leans on GT
through it (EB-right lands +30 GT-gated vs +57 blind). The GT-free gate (bank
`supporting_count` via `expected_by_cell`) is now injectable. **cam1 must be re-validated
with the blind gate before any blind-deployment claim.**

### The architecture going forward — TWO-PASS processing (adopted 2026-07-08)

- **Pass 1 — at ingest, calibration-independent.** Full-frame detect+track over the
  ENTIRE trim set (this study: 07:00–09:00 + 16:00–18:00), zero semantics — needs no
  legs, cardinals, channels, or intersection box, so it runs unattended the moment video
  lands, even before calibration starts. Heavy compute happens once, cache-backed (cam2's
  full-trim detection caches already exist). **Pad each trim edge ~1–2 min** of tracking
  so vehicles mid-intersection at the boundary aren't truncated; bin events by their
  box-crossing timestamp so counts land in the right interval.
- **Pass 2 — all semantics, cheap and re-runnable (minutes from cache).** Cardinal
  labeling, path discovery pooled over the FULL corpus (rare cells finally have enough
  data — NB-right had 2 tracks in 30 min), then classify + count everything in one go
  against the complete path set. Operator relabels a cardinal or redraws a channel →
  re-run pass 2 only; the tracking is never repaid.
- **Order of authority in pass 2:** box-side crossings decide origin/destination for
  EVERY track (box-clip — nothing is ever dropped for shape mismatch) → channels (drawn
  + discovered) only DISAMBIGUATE ambiguous in-box geometry → discovered supporting
  counts feed the turn-merge volume gate (scaled to the counting window). Fully GT-free.
- **No cold-start hazard** — verified empirically: detection is stateless and tracking
  has no cross-vehicle memory (first-3-min capture ratio 0.93 vs 0.81 for the remaining
  27 min). The only place a "blue-water" effect could exist is *incremental* path
  discovery, which the two-pass order structurally forbids: no vehicle is classified
  until the pattern base is complete.

**GATE B VERDICT (2026-07-08 — `docs/gateb_boxclip_blind_sweep_2026-07-08.md`):** the
box-clip pass-2 prototype reached live-baseline parity on cam2 (net −4.7% vs −4.5%, NB
PASS 2.2%) but **FAILED the frozen-constants blind sweep** on cams 1/3/4/5 (net −15 to
−52% vs live baselines of 3.2–8.7% MAE, cams 3/4 PASSING). Box-clip is NOT the
replacement counter; it demotes to the §3-B blind-QA cross-check signal (two
independent GT-free counters disagreeing = the "suspected gap" feeder — it would have
flagged cam2's SB-thru/EB-right exactly). The sweep also REFRAMED the problem: the
per-approach crisis is CONCENTRATED (cam2 + cam5-EB + cam1-NB), not corridor-wide, and
cam2's worst cells are detection-bounded → the §3-D detector fine-tune is the lever.
**(REFINED same-day by the detector de-risk spike, `docs/detector_derisk_spike_2026-07-08.md`:
the failing cells are DOWNSTREAM-bounded — detection contributes ~10% on cam2 SB-right and
nothing on cam5-EB/cam1-NB; cam5-EB's live bank is missing its EB-thru path entirely.)**
The two-pass architecture itself stands (pass-1 dumps exist for all 5 cams; pass-2
re-runs in ~1 min). cam1 blind-gate re-validation: **RESOLVED 2026-07-08** — no blind
collapse; honest blind cam1 = ~10% per-cell abs vs 6.7% GT-gated (total net +2.2% vs
−0.4%), the whole delta being the turn-merge volume gate on NB-left (bank expected 110
→ no merge → +38). Same accuracy class; the gate weakness is a §3-B flag-queue feeder
case. Details in the sweep results doc.

---

## 2d. The two-pass shipping arc (2026-07-08 → 07-13) — AUTHORITATIVE STATUS

The §2c architecture went from plan to product in one week. Full trail:
`plan_twopass_productize_A` → `pass2_parity_A2` → `a4a_turn_merge_gate` →
`cam2_fullday_twopass` → `plan_corridor_twopass` (all dated docs).

- **Pass 1** (semantics-free raw-track dump, format v2) productized in
  `backend/services/two_pass.run_pass1` with per-camera recipes
  (`calib_pass1_backend`: cam1 botsort+reid, cam2/cam3 botsort, rest
  bytetrack), live-parity tracking input, and resume. **Pass 2** (corpus
  discovery → replay-classify on the APPLIED bank → volume-gated turn merge →
  window-scoped apply → flag-queue rebuild with S5) behind `TWO_PASS_ENABLED`
  (default OFF); endpoints are the dry-run surface.
- **Fidelity proven:** replay-from-dump ≡ retrack-from-cache at |Δ| ≤ 2/cell
  on all five cameras (three at |Δ| = 0). The gate caught and fixed two real
  dumper divergences (pre-track NMS; the empty-frame tracker schedule).
- **Corridor scoreboard (per-approach MAE, each camera's honest window):**

| cam | live | two-pass | disposition |
|---|---|---|---|
| 1 | 8.7% | **7.6%** | APPLIED (07–09; NB 13.3→5.9) |
| 2 | 9.8% (30 min only) | **8.1%** | APPLIED full study day; SB-right recall 0.58→**1.07** (the #1 corridor deficit, fixed); net −8.8% honest vs +1.5% cancellation-flattered |
| 5 | 8.7% | **7.1%** | APPLIED |
| 3 | **3.2%** | **3.2%** | APPLIED full day (2026-07-13 re-gate on the botsort dump: tier-1 |Δ|=0 AND tier-2 vs live |Δ|=0 — the recipe diagnosis exact; gate met to the decimal) |
| 4 | 4.6% | 5.1% | HOLD — RECLASSIFIED 2026-07-13 after the frame/track review: the leg-sanity flag is an ARTIFACT (mid-block arterial births mis-binned to the driveway anchor produce the 267° consensus; even live origin-34 events start mid-road at bearing ~81°). Heading 119° is plausibly correct; the anchor-move fix was A/B-measured WORSE (5.5% vs 5.1%) and reverted. cam4's +31 EB-left residual = the mid-block-birth origin-assignment wall — §4 item 8 research, NOT operator work. cam4 keeps its live table (which passes the product bar). |

- **Blind QA validated end-to-end:** the retrospective's reachable targets are
  CAUGHT AT RANK 1 of their worklists (T2 bank-hole impact 179; T4
  merge-borderline impact 87 — emitted by the production S5 path); T1
  dissolved because its mechanism was actually fixed; flood control holds
  (queues in the 18–36 card range per intersection).
- **STANDING RULES (paid for in measurements — do not relitigate):**
  1. Drawn channels feed bank BUILDS (claiming/expecteds/QA) but NEVER enter a
     fitted bank's applied attribution path-set (measured 4×: §2c −18.5%,
     cam5 audit ×2, bank-D retest EB-right +316).
  2. Turn-merge expecteds must be corpus-window scale-1 — never extrapolated
     from a shorter sample (A4a run 1).
  3. A two-counter QA signal needs the second counter within ~2× of the live
     counter's accuracy class (S3 blocked on this).
- **Retirements ledger:** box-clip as counter (Gate B), ReID blanket rollout
  (§2c), concurrent-duplicate dedup (dev-gate fail), bank-D drawn-path fill
  (twice), ×-scaled merge expecteds, per-camera detection-profile config lever
  (detector spike).

---

## 3. Roadmap — operator-readiness

The shift: from "research pipeline + Claude's CLI scripts" to **a product an operator runs
start-to-finish**. Five workstreams.

### A. Productize the pipeline (no CLI, nothing to ask Claude)
The *logic* exists in scripts; it's just not wired into the app. Same move as the
cache-writer fix.
- **"Confirm & process" does the whole thing automatically, in the §2c two-pass shape:**
  pass 1 full-trim track at ingest (calibration-independent, edge-padded) → pass 2: path
  discovery over the full corpus → box-clip classify + count in one go. No CLI, and no
  sample-window bootstrap ordering (the old sample→bank→full-window flow is superseded).
- **Gate the export:** a deliverable can't be printed until the bank exists AND
  classification (incl. articulated) is populated AND the QA gate is satisfied.
- *Reuse:* `build_bank_gtfree.py` / `apply_bank.py` / `hybrid_prototype.retrack` logic.
  *New:* orchestration inside `_run_v3_pipeline` (or a post-process step), export gating.

### B. Blind QA — the two-feeder flag queue (THE accuracy mechanism)
A confidence queue alone is insufficient: **it only catches what the system is unsure
about, not what it missed entirely** (an undetected vehicle emits no event → no flag — the
FM51 −8% would be invisible). So two feeders:
1. **Uncertain events** → low detection / trajectory / destination confidence; ambiguous
   class (articulated vs medium). Operator confirms or fixes.
2. **Suspected gaps** → a **no-ground-truth detection-coverage signal** (detection rate or
   mean confidence dropping vs the run's *own* rolling baseline) + conservation-QA flags.
   Produces a directed **"this interval/approach looks under-counted — review here"** →
   add-missed task. *This feeder is the blind-deployment hardening from §2.*
- **Non-blocking:** the count completes and produces a *draft*; flags accumulate in a
  queue; the deliverable finalizes only as the queue is worked down to the accepted CI.
- **Impact-ordered:** high-volume movements/intervals first.
- *Reuse:* `low_confidence_segments` table, per-event confidence fields, `conservation_qa`,
  `spot_check`. *New:* the coverage/baseline diagnostic, the queue model + API.

### C. The review UX — make editing FLOW, not surgery
**Principle: the app is the source of truth; the Excel/PDF is GENERATED from corrected
data and never hand-edited.** To make resolution feel seamless:
- **Worklist, not a hunt** — the system serves one flagged item at a time, with progress.
- **Everything for the decision on one screen** — looping video clip + drawn trajectory +
  the system's guess + *why it's flagged*.
- **One keystroke per item, auto-advance** — `Enter` accept, `1–4` set movement, `Del`
  reject phantom, `A` add-missed (scrub + click), `→` next. No dialogs, no mouse hunt.
- **Live count + a stopping rule** — show the running total and spot-check CI as they
  edit, so they know *when they're done* (the ±5% TxDOT gate), not grind forever.
- **Batch the obvious** — "14 tracks: origin ambiguous W↔SE — resolve all as W?" one key.
- *Reuse:* the Review screen (add-missed, trajectory overlay, fix-attribution — Phase 9).
  *New:* the queue-driven flow, keyboard model, live CI/stopping rule.

### D. Algorithm / capability gaps (generalize — do NOT overfit)
- **Low-light / dusk detection** — the PM miss (#1). Develop against FM51 + corridor
  labeled data; the fix must generalize (better low-light recall), not a per-site knob.
- **Articulated classification** — add the FHWA 8–13 bucket (#2). **SHIPPED 2026-07-06** as a
  view-invariant SIZE post-pass (truck length vs the local car-size baseline; bbox aspect ratio
  fails at approach-angle cameras). Honest FM51 result: ~70% recovery (71 vs Miovision's 102,
  full population) — bbox size can't perfectly split a short semi from a long box truck. Detector
  fine-tuning below is the path past ~70%. See `project_articulated_classification_2026_07_06`.
- **Per-camera tuning** — keep develop-time tuning that generalizes; explicitly avoid
  tuning per-site against the answer (the overfit trap).

**Per-approach attribution — the last hurdle.** **UPDATE 2026-07-07 (§2b):** re-diagnosed with the
operator's drawn channels — the mechanism is coverage-blind matching on far-field-TRUNCATED tracks,
and the fix is **ReID-by-default + coverage-aware matching**, not more image-space features. The
2026-07-06 synthesis below stands (no image-space silver bullet) but is now subsumed by §2b.
**UPDATE 2026-07-08 (§2c):** the spike split that pair — ReID-by-default FAILED to move cam2
(attribution, not tracking, is the event-level bottleneck); **coverage-aware box-clip inside the
two-pass architecture is the lever**, ungated on any tracking work.

_(research synthesis 2026-07-06)._ Two independent
deep-research passes (papers/GitHub + X community) converged: there is NO public silver bullet for
the collinear-swap, AND the SOTA image-space hybrid (Jana et al. arXiv 2111.09171 — min-directed
Hausdorff + angular + end-proximity) is ALREADY what our `mdh` cost implements. So more image-space
shape features won't move it: the confused pairs share the exit and are near-identical in-image, and
the only discriminator (the entry) is FOV-clipped. **UPDATE 2026-07-06: BEV is DE-RISKED NEGATIVE
(solid). A RIGOROUS GT-anchored diagnosis (Miovision per-minute correlations, no geometry;
`docs/cam2_perapproach_diagnosis_2026-07-06.md`) then RESOLVED the cam2 per-approach mechanism — and it
is NOT an attribution "swap." It is TWO independent tracking/detection defects that partially cancel:
(1) SB-RIGHT is MISSED −461 (58% recall, the single biggest error, does not leak); (2) EB is
DOUBLE-COUNTED +769, driven by SB-thru occlusion splitting EB tracks (corr 0.58 with SB-thru volume;
305 confirmed concurrent ID-splits). ⇒ the lever is TRACKING/DETECTION QUALITY (recover missed SB-right
+ EB occlusion-dedup), which vindicates why the attribution levers (BEV, anchor) all failed. The earlier
"entry-starvation swap" mechanism was over-concluded on flawed geometric tests and is corrected.**
- **BEV / inverse-perspective-mapping** *(DE-RISKED 2026-07-06 → NEGATIVE; NOT the lever)*. The idea:
  the swap overlaps in the IMAGE but is distinct in WORLD space, so project to a metric ground plane
  and match there. The de-risk (cam2, data-in-hand, both a zone-diamond and a proper vanishing-point
  rectification; `docs/bev_derisk_cam2_2026-07-06.md`) found: the geometric PREMISE is TRUE — the
  ideal template pair separates 16°→**138°** in a rectified BEV — **but it is unrecoverable on the
  real tracks.** The non-circular test (re-split the tracks by the pipeline's own `_mdh_cost`,
  compared to **Miovision**) shows BEV moves the SB:EB split *AWAY* from ground truth (EB-right 1595
  live → 1711 image → **1781 BEV** vs Mio's **1217**). Reason (homography-invariant): the confused
  tracks are **born downstream of the divergence** (entry-starved), so the separating entry is never
  observed — and a homography adds zero information. Plus the live cost discards the entry anyway
  (partial-Fréchet ignores the uncovered prefix; tail-prior = shared exit), and *using* the entry was
  already DISPROVEN twice (the entry-tiebreak). ⇒ Not the lever.
- **Entry-line volume anchor** *(prototype INCONCLUSIVE 2026-07-06 — NOT proven either way)*. Count
  vehicles at an in-FOV tripwire and anchor the approach total. The quick prototype
  (`scratchpad/anchor_prototype.py`) looked negative (hybrid |dev| worse than pipeline; "swap tracks
  don't cross an entry wire"), but that was an ARTIFACT: the single wire sat on the THROUGH path where
  EB-*right* turners are born, so it missed them, and the "downstream/entry-starved" tracks turned out
  to be normal long EB-approach tracks (born ~(411,113), median 193 pts). So the anchor is UNVALIDATED,
  not disproven — a real test needs per-movement or operator-drawn entry lines placed BEFORE the
  movement divergence. Still plausibly useful as conservation-QA infra.

- **Domain-fine-tuned detector** *(candidate — external-idea review 2026-07-06)*. We run a
  GENERIC COCO model (yolo26s) and lean on downstream cleverness. Fine-tuning the detector on our
  OWN intersection footage (our angles / lighting / distances) is standard production practice and
  hits two gaps at once: distant/low-light recall (the PM miss — though 640×480 source is *partly*
  a resolution wall) and **articulated** — a trained "semi" class would likely beat the ~70%
  bbox-size heuristic above. Blind-deployment gate: train on DIVERSE sites, never overfit to FM51,
  or it won't generalize. A real research spike (label a few hundred crops/site, Colab GPU), not a
  knob. Aim it at articulated first (cleanest win vs the heuristic).
- **Entry-line volume anchor for per-approach totals** *(external-idea review 2026-07-06; prototype
  INCONCLUSIVE — see the "last hurdle" block above)*. The un-scrambleable-tripwire idea is untested:
  the quick prototype used one crude through-path wire per approach (missed turners), so it neither
  proved nor disproved the anchor. Needs per-movement / operator-drawn entry lines before divergence.

### E. Miovision-parity deliverables
- **Light / Medium / Articulated** in the output — mostly a **FHWA→bucket mapping**
  (Lights 1–3, Mediums 4–7, Articulated 8–13); the data's already captured (modulo the
  articulated detection gap in D).
- **Excel = exact Miovision format** — example in hand:
  `docs/historic data/26097 TIA for Wise County, TX/Cam 1 FM51-CORD4699/*.xlsx`.
- **PDF report like Miovision** — example in hand: the `*.pdf` in the same folder. We
  already produce the data; this is a rendering layer.

### F. Calibration studio — the operator's authoring surface (2026-07-07)

The calibration UI is the operator's highest-leverage screen and it's currently cluttered
with legacy overlays that no longer drive the count. An audit against the pipeline (not
guesses) sets the direction.

**Audit — what actually feeds the readings vs. what's stale/fallback:**
- **Primary + perspective-robust:** the **leg origin points**, and the **bank path polylines /
  operator channels**. For a bank-calibrated camera, origin comes from `score_origin_by_polyline`
  / `score_path_joint` (pipeline.py:772, 948) and **movement comes from the bank path's label,
  not the angle classifier** — the code is explicit: *"the reported movement comes from the path
  label (not classification), so counts are unaffected"* (pipeline.py:1019–1021). These work
  because they're defined in the real, skewed image space (clustered real tracks / hand drawing).
- **Fallback-only AND perspective-fragile (retire from the default view):** the **perpendicular
  tripwire** (`tripwire_half_length_px`, Tier-1 fallback, pipeline.py:799) and the **angle-fan
  disks** (`through/turn/uturn` thresholds → `classify_trajectory`, whose movement is discarded
  for bank cameras). Both bake in a **top-down assumption our oblique pole cameras violate**:
  `calibration.js:_computeNodeHeading` literally points each leg's heading at the IMAGE CENTER
  (radial/BEV), and the tripwire is welded perpendicular to it. On an angled view those are
  systematically wrong — which is *why* the system already moved onto image-space polylines and
  why the engineer's edits are mandatory, not cosmetic.

**Design principles:**
- **Review-first, not manual-first.** Auto-cal (`auto_calibrator_v2` / `scripts/auto_calibrate`)
  + the GT-free bank builder do the bulk (find the arms, cluster the paths). The engineer sets
  only what the computer *cannot* know: leg **count + cardinal + road names** (world knowledge),
  and **channels for the movements the sample traffic under-represents** — the QA card tells them
  which (this is exactly the cam2 SB-right −461 case: auto truncated it, a human draws one channel).
- **Everything editable; nothing locked to 90°.** Because the camera is oblique, every auto-derived
  element (leg heading, path vertices, channel handles, any fallback tripwire) stays hand-conformable
  to the real perspective. The human eye reading the tilted video is the perspective-correction
  authority. Auto = a draft to correct, never a locked output.
- **Canvas is the hero; the panel is a quiet stepper.** One accent, one button family, terse copy,
  layer toggles so the road stays visible.

**The studio — one surface, three moments (the target UX):**
1. **During auto-cal — live perception.** The canvas plays the frames the detector is reading, with
   detection boxes + track trails, and the **leg-zone / path clusters visibly assemble** as evidence
   accumulates. (Root cause of today's "looks stuck": `collect_trajectories` computes progress every
   30 s but only *logs* it — `progress_pct` is pinned at 5 % the whole pass; `run()` takes
   `should_cancel` but no `on_progress`. The per-frame view exists in the loop and is thrown away.)
2. **Right after — clusters are the draft.** The detected zones/paths land on the frame as editable
   proposals.
3. **Then — playback editing against motion.** The 15-min sample window becomes a **scoped, playable
   video**; the auto-detected tracks replay **in sync**; the engineer toggles layers (Legs · Paths ·
   Channels · Fallback · detections) off/on and conforms the geometry to the traffic they can *watch*
   — the only way to get an oblique camera's directions right.

**New backend bits this needs:** an `on_progress`/live-preview channel out of `collect_trajectories`;
a **range-served** segment of the sample window for real `<video>` playback (not one-frame decodes);
and **persisting the sample trajectories with timestamps** so they replay in sync.

**Build in 3 shippable stages (each reviewable; do not big-bang):**
1. **Clean surface + layer toggles + strip the stale top-down overlays** (static frame). Road becomes
   visible, panel becomes the review-first stepper, nothing welded to 90°. **SHIPPED 2026-07-07**,
   plus **drawn-direct channels** (operator curves used verbatim — see §2b). *Unblocked cam2
   channel drawing.*
2. **Live auto-cal perception view** — stream frames + detections + forming clusters; fix the
   pinned-progress plumbing.
3. **The playback studio** — range-served window playback + synced track replay + layer-toggle editing
   against moving traffic. The largest piece.

Relates to [[project_per_approach_attribution_2026_06_30]] (the SB-right channel this enables),
[[project_bev_derisk]]/`docs/bev_derisk_cam2_2026-07-06.md` (why oblique-perspective geometry can't be
trusted top-down), and the FM51 operator-prep gap (§2 #3). Frontend: `frontend/js/calibration.js`
(1914 lines, mostly inline-styled → consolidate into `styles.css`).

---

## 4. Sequencing (re-ordered 2026-07-08 post-Gate-B — see §2c verdict)

0. **F1 — calibration clean surface + layers + drawn-direct channels (SHIPPED 2026-07-07).**
   Stale top-down overlays stripped, per-leg × per-type layer matrix, review-first stepper; and
   operator channel curves now used VERBATIM (drawn-direct). Committed. F2/F3 are their own track.
1. **Detector de-risk spike — DONE 2026-07-08 (`docs/detector_derisk_spike_2026-07-08.md`).**
   VERDICT: the per-camera detection-profile config lever is DEAD as the failing-cell fix —
   cam1-NB ×0.91–1.04 uplift (novel dets = stationary flicker), cam5-EB uplift below its own
   control (uniform more-boxes effect), cam2 SB-right the one real zone-specific gap
   (novel 11.2% vs control 1.6%) but sized at ~10% of that cell's miss. Gate B's
   "detection-bounded" framing REFINED → the cells are DOWNSTREAM-bounded: cam2 SB-right =
   tracker birth/association (detection assists ~10%); cam5-EB = bank COVERAGE (live bank has
   NO EB-thru path — re-apply with drawn-direct channels, the cheapest candidate on the board);
   cam1-NB = association/attribution residual. §3-D fine-tune justified at its REAL targets
   (articulated, low-light, edge-clip recall) with a held-out SITE gate — scoped in the doc.
   *(Box-clip counter RETIRED by Gate B — demoted to the §3-B QA cross-check signal. ReID
   rollout retired earlier. Two-pass replay infra stays — it's how all of this gets measured.)*
2. **cam1 blind-gate re-validation (§2c) — DONE 2026-07-08.** Cache restored as
   `balanced30min_restored` (content-hash verified; the default-variant parquet was already
   silently restored — only its meta.json is stale). GT gate 6.7% / blind bank gate 10.0%
   per-cell abs; total net −0.4% vs +2.2%; no collapse — the delta is confined to the
   turn-merge volume gate (NB-left +38 blind). The honest blind number replaces the shipped
   7.2% claim. See the Gate-B sweep doc, RESOLVED section.
3. **B flag queue — VALIDATED + COMPLETED 2026-07-09/10.** B-VAL retrospective run twice;
   S4 + S5 feeders shipped and catching their targets AT RANK 1 in production; S3 blocked
   (standing rule 3, §2d); flood control shipped (3,247 flags → 77 cards). Residual B work:
   S1 sensitivity (the cam2 SB-thru −15% that stayed under threshold) — small, evidence in
   `cam2_fullday_twopass` doc.
4. **A two-pass productization — SHIPPED behind TWO_PASS_ENABLED (§2d).** Corridor: 3 of 5
   applied, both holds root-caused.

**REMAINING, in order (re-sequenced 2026-07-13):**

5. **Close the corridor holds — DONE 2026-07-13.** cam3: re-gated and APPLIED (see §2d). cam4:
   reviewed with frame/track overlays — the calibration-defect theory is DEAD (artifact; details
   in the §2d row); its residual moves to item 8's attribution research. Corridor final: 4 of 5
   applied, cam4 honestly held on research, not operator debt.
6. **Stage 3.4 — the operator surface. DONE 2026-07-13
   (`plan_stage34_operator_surface_2026-07-13.md`).** Trim→window derivation (the contract
   the corridor dumps already followed, now written down + test-fixed to their exact
   numbers), pass-2 sidecar invalidation on a calibration FINGERPRINT (closes the
   stage-3.3 known limitation), card UI (readiness badges + Confirm & process → two-pass
   behind a 404-probe so flag-off is bit-for-bit legacy), detect-at-ingest (first run =
   detect+cache+dump in chunked resumable parts; ~90 s tracker seam warm-up). OPERATOR
   DRY-RUN PASSED on intersection 2: UI-only trims→process→apply reproduced the shipped
   counts EXACTLY (5230/3903/6701, Δ0), backups + fingerprinted sidecars + flag queue +
   export gate all live. **Verdict: GO — and DONE: `TWO_PASS_ENABLED` defaults ON
   (2026-07-13); `TWO_PASS_ENABLED=0` reverts to the legacy pipeline.** Residuals (API
   starvation during bank build, S5 last-window-only, no two-pass cancel) are §4-7
   C-stage items, listed in the plan doc.
7. **C review UX polish** — the worklist works (cards, batch keys); polish = the stopping
   rule surfacing + batch-card ergonomics, driven by the dry-run's feedback.
8. **The attribution walls (research):** cam2 NB-left 0.32 and the EB thru/right collinear
   split — the §2b coverage-aware matcher direction inherits these; any mechanism gets the
   full gate discipline. The §3-D fine-tune (articulated first, held-out-site gate — scoped
   in `detector_derisk_spike_2026-07-08`) is the parallel capability track.
9. **D-low-light** + **E deliverables (L/M/A Excel, PDF)** + **F2/F3 calibration studio** —
   unchanged from prior sequencing.

Each is a self-contained phase; ship and validate before the next.

---

## 5. Open questions / risks

- **Articulated:** is the gap detection (we never see semis) or just classification (we
  see them but bucket as single-unit)? `audit_fm51` says 0 emitted — needs a frame-level
  check before scoping D.
- **Coverage diagnostic without ground truth:** how to set the baseline/threshold so it
  flags real sags (PM sun) without crying wolf on genuine low-volume periods.
- **Overfit guard:** any per-camera knob we add must be justified by a *general* failure
  mode, with a written note, or it's research debt.
- **Spot-count blind spot:** a single AM spot window passed while the PM was bad — the
  stopping rule / spot-window selection must force coverage of the *hardest* conditions.
