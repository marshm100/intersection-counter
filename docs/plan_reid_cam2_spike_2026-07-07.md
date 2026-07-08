# Plan — CMC fix + cam2 ReID-generalization spike (2026-07-07)

## The question this answers (the only reason to do it)
**Does the proven cam1 ReID recipe close cam2 per-approach WITHOUT per-camera GT tuning?**
That is the load-bearing assumption of blind deployment (MASTER_PLAN §2b lever ①). If ReID only
works when hand-tuned against Miovision per camera, it can't carry a new site — and we need to know
now, cheaply, before building the product on it. cam1 shipped at 21.8→7.2% net with ReID; cam2 has
never had it. GT here is the dev yardstick only.

---

## Phase 0 — CMC fix (quick, unblocks speed; do FIRST)
**Root:** `tracker.py:233` sets `cmc_method="ecc"`. On a static camera fed a BLANK image
(`self._img = zeros`), ECC fails to converge every frame → returns identity (a no-op) but still
burns cycles and spews warnings — the hang we hit. boxmot 18's `get_cmc_method(None)` returns
`None` = *disabled* (verified in source). The earlier failed attempt passed the **string** `'none'`
(a ValueError); Python `None` is the supported disable.

**Change:** `tracker.py` BotSortBackend `_kwargs`: `cmc_method="ecc"` → `cmc_method=None`; update the
docstring (it already states the intent is `'none'`). Applies in BOTH motion-only and ReID modes —
`update()` passes the blank `_img` regardless, so GMC never had real frames to use.

**Verify (A/B):** retrack a short window twice (ecc vs None) →
- track count + centers **byte-identical** (GMC was already a no-op on blank frames), and
- wall-clock materially faster, no ECC warnings.
If tracks differ, STOP — that would mean GMC was doing something and the change isn't free.

**Risk:** none expected; the A/B is the proof. **Files:** `backend/services/tracker.py` (+ a note in
the ByteTrack default path — this only touches BoT-SORT).

---

## Phase 1 — Build cam2's ReID embedding sidecar (the heavy pass)
**Command:**
```
py scripts/build_reid_cache.py --camera 2 --variant study_0700 --start-hms 07:00:00 --minutes 30
```
**What:** decode cam2 video over 07:00–07:30, crop every cached detection, embed with
`osnet_x0_25` (CPU — the iGPU is a measured dead end), write `<parquet>.reid.npz` (frames, bboxes,
embs[N,512] f16) aligned to the detection cache. Built ONCE; retracks then read vectors, not pixels.

**Pre-checks (de-risked):**
- Window alignment ✓ — `groundtruth.VIDEO_START = 2026-05-12T00:00:02` matches cam2's
  `recording_start`, and `f_lo` uses cam2's fps (25) from the DB. Confirm the run prints a sane
  `total_dets` and frame span `[629950, 674950)`.
- **RAM (8 GB):** the study_0700 parquet is the full 2 h (~2.5 M rows); the reader windows to 30 min,
  but confirm the crop/embed loop is streaming, not loading all frames at once. If it OOMs, embed in
  frame chunks.

**Cost:** hours on CPU. Run in the **background/overnight**; it ties up the machine. Scope to the
**30-min window first**, not the 2 h trim.

**Output:** the sidecar npz next to `study_0700.parquet`.

---

## Phase 2 — Run the cam1 recipe UNCHANGED on cam2
**Command:**
```
py scripts/process_camera_reid.py --camera 2 \
   --bank evaluations/gtfree_bank_cam2_direct.json \
   --start-hms 07:00:00 --minutes 30 --workdir <system-temp, NOT OneDrive>
```
**What:** the shipped B-batch orchestrator — retrack **BoT+ReID (throughs)** + **BoT-motion (turns)**
→ regime combine + volume-gated intra-turn merge → final crossing-timestamped events → a **working
DB** (NO `--apply`). The regime-split + merge params are **cam1's, used verbatim** — that IS the
generalization test; do NOT tune them for cam2.

**Bank = the drawn-direct cam2 bank** (best cam2 attribution), so this isolates *tracking* quality on
top of good channels — not confounded by a weak bank.

**Gotchas to handle:**
- `PROJECT="97a7849a"` is correct (cam2 lives in this project); `--camera 2` drives the context.
- Its built-in `_measure()` / `combine_regimes` reporting uses cam1's `LEG_IDX` → **ignore the printed
  number; measure separately in Phase 3.** The retrack/combine themselves are camera-parameterized
  (`hybrid_ocbot` line 126), but **verify the run completes clean for `--camera 2`** — any cam1 leg
  hardcoding that surfaces is a real deploy-generalization bug worth fixing here.
- `--reid-cache` auto-locates the sidecar via `sidecar_path`; if it can't find the study_0700 one,
  pass `--reid-cache <path>` explicitly.
- Confirm the bank JSON format is what the orchestrator's apply/attribution expects (gtfree
  `{paths:[…]}` — same shape `apply_bank` consumes).

---

## Phase 3 — Measure vs Miovision + DECIDE
Take the Phase-2 working DB's cam2 events, window 07:00–07:30, per-approach vs Miovision (reuse the
`interval_metric` / windowed-cell comparison from this session).

**Baselines to beat (live drawn-direct-less bank, same window):** per-approach MAE ~7.9% (stored),
net −4.5%; the collinear cells **EB-right +31 / SB-thru −43 / NB-left −66 / EB-thru −27**.

**GATE (the decision):**
- **PASS** — ReID materially closes the collinear cells (EB double-count down, SB/NB throughs
  recovered) with the cam1 recipe UNCHANGED, no new phantoms → **tracking-by-default is viable** →
  Phase 4.
- **FAIL** — it needs per-camera tuning to help, or introduces new errors (watch NB-right; cam1's
  ReID turns were dirtier) → **blind-deployment blocker found early**; document, and pivot to lever ②
  (coverage-aware matching) or re-scope tracking.

Also report: does ReID change the *count* sanity (total vs GT) and the fragmentation (track count vs
the ~1,400 real)?

---

## Phase 4 — ReID-BoT as the default *(GATED on Phase 3 PASS — separate, bigger lift)*
Only if the spike passes:
- Make BoT+ReID the app's default processing path (retire the plain-ByteTrack default in
  `pipeline.py:160`), or the per-camera default where it wins.
- Wire the **sidecar build into the app's processing flow** (build once per video, like the detection
  cache) so an operator gets it with no CLI.
- Extend to cam3–5; each its own validation. This is app wiring + per-camera rollout — scoped after
  the gate, not now.

---

## Sequencing & cost
`Phase 0 (minutes)` → `Phase 1 (hours — overnight)` → `Phase 2 (tens of minutes, faster post-ECC)` →
`Phase 3 (minutes) → DECIDE`. To the decision: **one overnight embed pass + ~a day** of run/measure.

## Explicit non-goals
- **No tuning cam2's recipe against Miovision** — that defeats the whole generalization test.
- **No `--apply`** — spike only; measure on a working DB, production untouched.
- **No box-clip / coverage-matcher work yet** — it's lever ②, gated behind tracking landing.
