# Handoff — 2026-07-02 (low-light lever disproven → spot-window stratification shipped)

Branch `claude/accuracy-impl-2026-05-27`. Continues `docs/handoff_2026-07-02.md`
(rebuild_flags perf). This session took the **§3-D low-light** lever from
MASTER_PLAN §4, **disproved it with a diagnostic-gated experiment**, and shipped the
fix the negative result pointed to: **stratified spot-count windows + a
segment-coverage acceptance gate** (MASTER_PLAN §5 open risk).

## The arc (each step gated the next; every negative result narrowed the problem)

1. **Phase 0 diagnostic — the FM51 PM sag is a DETECTION-recall loss, not what
   "low-light" implied.** Funnel decomposition (Miovision GT → raw detections from
   the stored cache → emitted events), total-level so the mislabeled 4-leg
   calibration can't confound it:
   - PM deficit **−10.8%** (vs −4.7% AM control), real and calibration-independent.
   - **Not confidence** (PM raw conf 0.402 > AM 0.371), **not tracking** (events/1k
     raw dets 22.5 > 21.4), **not rejection/attribution** (0 rejected, 0 null-origin).
   - It's **per-frame recall on the W approach**: track length 31→24 pts (−26%; E
     flat), W-corridor raw dets −40% across ALL confidence bands (no faint reservoir
     to recover). Visual: FM51 is a long rural highway receding to the horizon;
     missed vehicles are tiny specks near the vanishing point.

2. **Tier 1 recovery experiment — the miss is a 640×480 SOURCE-RESOLUTION WALL,
   unfixable in software.** Ran 4 detector configs through the real `VehicleDetector`
   on the iGPU over ~250 sag+control frames (harness reproduced production
   **byte-for-byte**: C0-fresh ROI 81 == cache 81):
   - **CLAHE enhancement HURTS** (−6%) — a band-aid the diagnostic caught before it
     shipped.
   - **yolo26l@1280 (Accurate) only +6%** in the sag, and a *similar* +13% in the
     good control → uniform uplift, **not** a distant-vehicle recovery. Reason: the
     source is 640×480; 1280 inference just upscales — it can't recover detail never
     captured. Confirmed visually: every resolvable vehicle is already boxed at 960.

3. **Blind-QA verification — the coverage feeder can't auto-catch it, and neither
   can any signal I could find.** Ran `feed_suspected_gaps` on FM51: **0 flags**.
   Transparent why: the worst W bin is only 15% below its rolling-median baseline
   (S2 needs 60%) because a *gradual* sag drags its own baseline down. I tested a
   candidate rescue signal (per-interval track-length / continuity anomaly) — **it
   failed** (±20% noise at 15-min granularity, indistinguishable from AM good-window
   variation). So the documented "honest limit" in `coverage_qa.py` is robust: **no
   blind auto-signal reliably catches this gradual sag without crying wolf.**

4. **The fix the negatives pointed to.** The only mitigation for an unfixable,
   auto-invisible miss is a **human spot-count of the hard window** — but
   `propose_window` picked **uniformly at random** and the gate passed on **any one**
   spot count, so an all-AM sample shipped the −20% PM sag undetected (exactly
   MASTER_PLAN §5's named risk).

## What shipped (this session)

**`backend/services/spot_check.py`**
- `_processed_segments()` — splits a camera's footage into coverage segments:
  contiguous event blocks (a >20-min hole splits AM vs PM trims) via a 5-min
  active-bin `GROUP BY` (index-only on the OneDrive DB), long blocks subdivided into
  ≤4 parts of ~3h. Blind — the run's own coverage/time structure, no GT.
- `propose_windows()` — one spot window per segment (stratified), so the sample
  covers the run's range of conditions incl. the hardest. Single-block run → one
  window (== old behaviour).
- `acceptance()` spot_count item — now reaches **`pass` only when a spot count lands
  in EVERY segment**; uncovered segments keep it at **`review`** and NAME the window
  ("also sample 16:00-18:00 …"). `_rec_offset_seconds` / `_clock_label` label
  segments in wall-clock.

**`backend/routers/qa.py`** — new `GET …/qa/spot-windows` (stratified list); the old
singular `…/qa/spot-window` kept for back-compat.

**`frontend/js/setup.js`** — QA panel shows **Coverage: N/M segments spot-checked**
+ the guidance note; "Propose a spot window" now fetches the stratified windows and
**steers to the first un-covered segment** (so a multi-trim run gets the PM sampled);
the count form labels "segment k of M". (NOT live-tested — app-launch is RAM-bound on
this box; JS passes `node --check`.)

**`backend/config.py`** — caveat on the `imgsz=1280` comment (upscaling a 640×480
source does not recover distant vehicles; the mitigation is spot coverage, not a
detector knob).

## Validation
- **Unit:** `test_spot_check.py` 14/14 (3 new stratified tests + 11 existing incl.
  the single-block `pass` path — nothing regressed).
- **Real FM51 data:** `_processed_segments` → **2 segments, 07:00-09:00 + 16:00-18:00**
  (matches the trims); `propose_windows` → one window each (17:33 lands in the sag);
  an AM-only spot count → gate **"review — also sample 16:00-18:00"**, not ship.
- Dependent suites `test_flags` + `test_database` + `test_interval_metric`: **61/61
  green** (the acceptance-gate fold-in and spot_counts table are unaffected).

## Follow-ons / notes
- **Frontend not live-tested** (RAM/app-launch limit). Verify the QA panel renders
  the coverage line + the "Propose" steering on a real app run.
- **Richer spot-count UX** (a per-segment coverage checklist with click-to-count each
  window) is a natural next slice; this session did the steering + note, not a full
  multi-window picker.
- **The FM51 miss itself remains** (−10.8% PM) — it is a *camera resolution* limit,
  not our software's to fix. The product's honest answer is now enforced: the gate
  makes the operator spot-count the PM window rather than silently shipping it.
- Governing principle held throughout: BLIND DEPLOYMENT (no GT at the site; the fix
  is a blind stratification) + VALIDATE-BEFORE-SHIPPING (the diagnostic killed the
  low-light fix and a CLAHE regression before either shipped).
