# MASTER PLAN — Intersection Counter

**From a validated counting stack to an operator-ready Miovision replacement.**
Living roadmap; supersedes nothing but consolidates everything. Last updated 2026-06-29.

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
| 4 | **Side-road over-count** | WB Co Rd 4699: ours 105 vs Miovision 60 (+75%). | ASSIGNMENT |

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

## 3. Roadmap — operator-readiness

The shift: from "research pipeline + Claude's CLI scripts" to **a product an operator runs
start-to-finish**. Five workstreams.

### A. Productize the pipeline (no CLI, nothing to ask Claude)
The *logic* exists in scripts; it's just not wired into the app. Same move as the
cache-writer fix.
- **"Confirm & process" does the whole thing automatically:** process a sample window →
  `build_bank_gtfree` → `apply_bank` → process the full window → classify. No CLI.
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
- **Articulated classification** — add the FHWA 8–13 bucket (#2). Validate vs Miovision's
  102; ship as automatic.
- **Per-camera tuning** — keep develop-time tuning that generalizes; explicitly avoid
  tuning per-site against the answer (the overfit trap).

### E. Miovision-parity deliverables
- **Light / Medium / Articulated** in the output — mostly a **FHWA→bucket mapping**
  (Lights 1–3, Mediums 4–7, Articulated 8–13); the data's already captured (modulo the
  articulated detection gap in D).
- **Excel = exact Miovision format** — example in hand:
  `docs/historic data/26097 TIA for Wise County, TX/Cam 1 FM51-CORD4699/*.xlsx`.
- **PDF report like Miovision** — example in hand: the `*.pdf` in the same folder. We
  already produce the data; this is a rendering layer.

---

## 4. Sequencing (proposed)

1. **B-coverage diagnostic + the flag queue model** — highest leverage: it's the blind
   accuracy assurance, and it directs all review work. Without it, deployment can't be
   *trusted*, only *measured*.
2. **C review UX** — pairs with B; turns flags into a fast resolved count.
3. **A productize bank + classification + export gating** — removes the CLI dependency so
   an operator can actually run it solo.
4. **D-articulated** + **E deliverables (L/M/A, Excel, PDF)** — parity + the one real
   classifier capability.
5. **D-low-light detection** — the hardest/most-research-y; informed by what the coverage
   diagnostic (B) shows about *where* detection sags.

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
