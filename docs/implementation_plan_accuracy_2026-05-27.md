# Technical Implementation Plan — Closing the Sunnyvale Accuracy Gap

**Date:** 2026-05-27
**Author:** Claude Code, developed in a two-turn working session with Grok (read-only plan mode).
**Source research:** `docs/methodology_research_2026-05-26.md` (the "what/why"). This doc is the "how".
**Status:** In progress (branch `claude/accuracy-impl-2026-05-27`). See Progress log below.

---

## Progress log

**2026-05-27 session (Claude + Grok):**

- ✅ **Step 2 — joint partial-Fréchet scorer: CODE COMPLETE, validated as far as data allows.**
  - `score_path_joint` implemented (`trajectory_classifier.py`), wired into
    `_finalize_vehicle_data` behind `USE_JOINT_PARTIAL_FRECHET_SCORER`; reads origin off the
    winning path; legacy scorer is the fallback. Commits `bba5bde`, `4ebd678`, `d4cdb17`.
  - Grok reviewed the implementation (read-only): confirmed the Fréchet/coverage math, agreed
    suffix-only is right for v1, and flagged the coverage floor (lowered 0.45→0.28).
  - **Key data-driven finding:** smoke-testing on the 144 surviving real trajectories matched
    only 3/144 — sup-norm discrete Fréchet is too brittle (one jittery point spikes it; real
    best-match ran ~82 px median). Switched the cost metric to robust **DTW-mean** (true mean
    coupled distance), which lands real data at ~29 px median — the scale the proven Stage A
    scorer used. Joint now attributes ~61% of the sample, rest to fallback. `max_cost=35`
    calibrated on 144 events — **RE-TUNE against B0 once trajectories are regenerated.**
  - `replay_attribution_changes.py --joint` added for the tuning loop.
  - **Still pending (data-gated):** weight/threshold tuning on the regenerated set.
- ✅ **Step 1.1 — detection cache module: CODE COMPLETE + round-trip tested.** Commit `b93a68e`.
  - `detection_cache.py` (blake2b hash, Parquet writer/reader, dict reconstruction),
    `videos.content_hash` migration, `pyarrow` dep, 8 round-trip tests.
  - **Still pending:** pipeline write-through + consumption wiring (only exercisable during a
    real run), and a headless reprocess driver.

**Gated on a decision / resources (not startable autonomously in a chat session):**
- The **repopulating reprocess** (Step 1 run) — hours of CPU on the 8 GB laptop.
- **Step 0 audit** — needs the regenerated detection data.
- **Step 3 (OC-SORT)** — needs `boxmot` + is conditional on the Step 0 verdict.
- **Step 4 (OpenVINO)** — needs `openvino` + target-hardware parity run.
- **Step 5** — needs all of the above + an overnight run.

---

---

## 0. Verified starting state (checked against the live tree + DB, 2026-05-27)

- **Tracker:** `backend/services/tracker.py` wraps `supervision==0.17.1` `sv.ByteTrack`. `TRACKER_LOST_BUFFER=150` (5 s) already. No motion-gap recovery.
- **Attribution:** two separate scorers — `score_origin_by_polyline` (`origin_detector.py:280`, with the Stage A 25° bearing gate) then `score_destination_by_polyline` (`trajectory_classifier.py:270`, Hausdorff mean, radius tightened 40→20 px).
- **Stage A interim patch is live** (`config.py:138,146` + `pipeline.py` Driveway exclude). Took replay per-cell error 94.58% → 69.88%, but over-suppresses **L25 right (27 vs 895 manual)**. It is a band-aid to be superseded.
- **Root cause:** vehicles enter YOLO's FOV mid-turn, so polyline **entry tangents are unreliable**; trajectory **tails are reliable**.
- **Data model facts:** `videos` table has `file_size_bytes` + `total_frames` but **no `content_hash`** column. Camera 1 has **10** `intersection_paths`.
- **No detection cache, no OpenVINO, no boxmot, no Fréchet libs** in `requirements.txt`.

### The constraint that reshaped this plan
The Stage A reprocess **deleted the original 9,785 trajectories**; only **144** `vehicle_events` with `trajectory_data` remain, and **no backup exists** (DB is 72 MB of mostly deleted-but-unvacuumed pages). `evaluations/A1_baseline.json` is a per-*cell* snapshot, **not** the trajectories — so it cannot be replayed against.

**Implication:** the research roadmap (and Grok's first draft) both assumed a cheap "develop the joint scorer on existing trajectories via the replay harness in minutes" loop. **That loop does not currently exist** — 144 events cannot reproduce the per-cell error distribution or surface the L25-right failure at volume. Regenerating trajectories is therefore a *prerequisite*, not a final step. This is the single biggest change from the original 4-step roadmap.

---

## 1. Revised sequence (with definition-of-done per step)

| # | Step | Definition of done | Effort |
|---|---|---|---|
| **0** | **Detection audit** | Script + report that cleanly separates *"YOLO never emitted a box"* from *"box emitted but track fragmented"* per distance/size band. Recorded decision: is OC-SORT high-ROI, or do we pivot to detector recall? | S (2–3 h) |
| **1** | **Repopulating reprocess (peak trims) + cache write-through** | One run over the AM+PM manual-overlap trims that (a) writes the reference Parquet cache for camera 1, (b) regenerates **≥2,500–4,000** `vehicle_events` under current ByteTrack+Stage-A logic, (c) emits a clean `B0_baseline.json`, (d) restores the replay harness to statistical usability. | M (run: ~2–4 h wall-clock + cache plumbing 2–4 h) |
| **2** | **Joint partial-Fréchet scorer (`score_path_joint`)** | Implemented; wired as the single Tier-0 at finalization for polyline cameras; Stage A gates behind a flag/removed for polyline paths; tuned on the regenerated set via replay; measurable win on worst cells (esp. **L25 right recovery without phantom regression**) diffed vs `B0_baseline`. | M (4–6 h) |
| **3** | **OC-SORT integration (conditional on Step 0)** | `VehicleTracker(backend=...)` factory supports it; public API + pickle checkpoint preserved; retuned on a short clip; *either* demonstrates recovery of the "fragmented" population from Step 0 *or* is explicitly deprioritized. | S (2–3 h + retune) |
| **4** | **OpenVINO FP16→INT8 + parity gate** | Export + INT8 artifacts in `models/`; detector loads with PyTorch fallback; 15–30 min segment shows detection-count + final-TMC parity within tolerance vs PyTorch on identical cached detections. | M (4–6 h) |
| **5** | **Final full validation** | Full 11 h balanced reprocess (fast now: cache + optional OpenVINO); `per_movement_accuracy.py --diff B0_baseline`; published final per-cell number; explicit call on whether residual gap is detector-recall or still attribution/tracking. | overnight + measurement |

**Total: ~10–20 engineering hours + two reprocess runs (one peak-only, one final full).**

Why this order: the expensive reprocess is front-loaded so it does *maximum* work on the first pass (cache + trajectory regeneration + B0 baseline at once), which is what makes every later step's iteration fast. The joint scorer is developed against regenerated trajectories *before* the tracker swap, because the scorer's tuning needs volume; the tracker swap then feeds it cleaner raw material. OpenVINO is orthogonal and can slot in any time after the cache exists.

---

## 2. Step 0 — Detection audit (the cheap decision gate)

Run as a side-effect of / immediately after Step 1's reprocess, while fresh detections are cached. Per trajectory, record:
`first_detection_frame`, `num_yolo_detections` (actual model outputs), `num_tracker_updates` (points in final traj), `max_gap_frames` (longest run of non-YOLO frames while track alive), and an entry distance/size band (pixel-y + bbox height as a far/mid/near proxy).

Classification:
- **"YOLO never emitted":** `num_yolo_detections == 0`, or first detection arrives after a vehicle on that path should already be >40 px tall.
- **"Emitted but association-lost":** `num_yolo_detections ≥ 1` but `num_tracker_updates < ORIGIN_ASSIGN_MIN_FRAMES`, or `max_gap_frames` exceeds the finalize-gap threshold, and the track died before the intersection.

**Output:** per band → (expected manual volume, tracks started, % zero-detection, % started-but-fragmented).
**Decision rule:** if far-band recall < ~40% of expected through volume → the 3,800-event gap is mostly **detector recall**, OC-SORT is low-ROI, and effort pivots to detector (imgsz/crop/fine-tune). Otherwise OC-SORT (Step 3) is worth it.

---

## 3. Detection cache design (Step 1)

- **Key:** `(camera_id, video_content_hash)`. Cache at the **post-YOLO, pre-tracker** layer so ByteTrack ↔ OC-SORT can run against identical detection input.
- **Hash (decided):** `blake2b(file_size_bytes + total_frames + first 128 MiB of bytes)`. Full-file SHA over 11 h video is too slow; header+size+frames is collision-safe at our scale. Store in a new `videos.content_hash TEXT` column **plus a method tag** (e.g. `"blake2b-128m-v1"`) and the file path + mtime in cache metadata (second invalidation signal for in-place file replacement). Computed lazily on first cache write.
- **Layout:** `data/projects/<project_id>/detections/<camera_id>/<content_hash>/balanced_960_skip1.parquet` + JSON metadata sidecar (model, imgsz, conf/iou, skip, counts, created_at).
- **Schema (one row = one detection):** `frame_idx:uint32, bbox_x1/y1/x2/y2:float32, confidence:float32, class_id:uint8, class_name:string` (+ optional `center_x/y, area`). zstd/snappy. ~24 M rows for 11 h → <800 MB.
- **Keying scope (decided):** single reference set only for v1 — balanced `yolo26s@960, skip=1`. Fast/accurate modes subsample or fall back to live.
- **Write-through:** the repopulating reprocess populates the cache for free.
- **Consumption:** new `DetectionProvider` contract — `get_detections_for_segment(camera_id, video_path, start_frame, end_frame, mode_config) -> Iterator[list[dict]]`. On cache hit, bypass `self.detector` and feed cached lists into `tracker.update(...)` at the right frames. Stream via pyarrow with a small ring buffer — **never** load the full parquet (8 GB RAM).
- **Invalidation:** NULL hash / missing parquet → miss; changed file size or mtime → re-hash + rewrite; explicit "invalidate camera" CLI for model swaps/fine-tunes.
- **New dep:** `pyarrow`.

---

## 4. Joint partial-Fréchet scorer (Step 2)

Replaces both `score_origin_by_polyline` and `score_destination_by_polyline` with one `score_path_joint(trajectory, paths, ...)` called **once** in `_finalize_vehicle_data`. **Origin is read off the winning path's stored `origin_leg_id`** — never estimated from the entry tangent again. This makes the 25° gate and prefix/entry-segment logic obsolete for polyline cameras.

Algorithm (per candidate path):
1. **Partial Fréchet** — best matching *sub-curve* of the path polyline vs the full trajectory. Curves are short (traj 20–300 pts, hand-drawn poly ~8–25 pts) → brute-force over (start,end) vertex pairs with `similaritymeasures.frechet_dist` is <10 ms/path. Early-abort when sub-curve length < `min_coverage_frac × poly_len`.
2. **Coverage penalty** — prefer sub-curves covering ≥ `min_coverage_frac` (~0.45) of polyline arc length (rejects matching a tiny segment of many paths).
3. **Tail-direction prior** — cosine similarity between the trajectory's last-`tail_window`-points heading and the matched sub-curve's **exit** tangent. Tails are the trustworthy signal here.
4. **Composite score** = weighted blend of shape term + tail prior + coverage; tie-break by `supporting_count`. Final gate on raw Fréchet cost (`max_cost ≈ 28 px`, replaces both old radii).

Library: **`similaritymeasures`** (PyPI) for `frechet_dist`; ~30–50 lines of custom code for the sub-curve sweep + weighting. Not scipy (no curve-Fréchet). Complexity: ~9,800 tracks × 10 paths × sub-curve sweep ≈ low millions of numpy ops, <500 ms total — no perf blocker.

Wiring: keep the old scorers + Stage A constants behind `USE_JOINT_PARTIAL_FRECHET_SCORER` (config, per-camera capable) as instant-revert fallback for 1–2 weeks. Tune the 3 weights + `max_cost` on the replay harness (now repopulated) against `B0_baseline` until L25-right recovers without re-introducing phantom L22 lefts/rights. Extend `replay_attribution_changes.py` with a `--joint` flag and add Sunnyvale fixtures to `test_polyline_matching.py`.

---

## 5. OC-SORT (Step 3, conditional)

Library `boxmot`. Add as a second backend behind the `VehicleTracker(backend="bytetrack"|"ocsort")` factory — **same public API + pickle checkpoint path** (accept that checkpoint resume across a tracker-type *change* is unsupported in v1; rare). Convert dets to `np.array([[x1,y1,x2,y2,conf,cls],...])`, map params (`track_thresh`≈activation, `track_buffer`=150, `delta_t` matters for skip, keep `use_byte=True`), retune on a 2–5 min clip.

**Honest expectation:** recovers the *intermittent-gap* fraction (literature: 10–30% fragmentation reduction) — realistically **1,200–2,200 of the 3,800**, not all. Vehicles YOLO never emitted (small/distant far-leg through traffic at 960 px) are a **detector recall floor** no tracker can fix. Step 0 decides whether this step is worth doing. Test `boxmot` import + a 30 s clip on the **target Windows machine early** (driver/torch surprises).

---

## 6. OpenVINO (Step 4) — orthogonal, high daily-ops value

Export `yolo26s.pt` → OpenVINO FP16 then INT8 with NNCF/POT calibration on **800–2,000 Sunnyvale-specific frames** (diverse lighting/density). Artifacts under repo-root `models/`, global for v1. `detector.py` loads OpenVINO when present, **PyTorch fallback** otherwise; gate behind `YOLO_INFERENCE_BACKEND` (default pytorch on first rollout). Iris Xe is a first-class OpenVINO/OpenCL target; realistic ~6–7× end-to-end (11 h → ~2 h).

**Mandatory parity gate before trusting it:** 15–30 min segment, compare raw detection count/min + per-(leg,movement) counts after identical tracking+scorer + visual spot-check of 50 distant L22/L23 vehicles. If INT8 drops >8–10% of marginal far-side boxes, ship it as an **optional toggle with a warning** — quantization is most dangerous on exactly the low-contrast distant vehicles we care about.

---

## 7. Risks (where this stalls past Stage A)

1. **The 3,800 gap is mostly detector recall, not association** → OC-SORT underdelivers; far-leg undercount persists. (Step 0 surfaces this before we invest.)
2. **Joint-scorer mistuning** re-creates phantoms or over-suppresses. Mitigation: replay harness + 2–3 weight-search iterations + human review of worst cells, behind a feature flag.
3. **Hand-drawn polylines don't match modal driven paths** → even a perfect matcher prefers the wrong path for some fraction. Data problem, not algorithm.
4. **INT8 silently hurts the target population.** Mitigation: the §6 parity gate.
5. **8 GB RAM pressure** during full reprocess with pyarrow + boxmot state. Mitigation: stream, "low-memory mode" escape hatch.
6. **Hash collision / weak invalidation** → silent wrong detections. Mitigation: blake2b over 128 MiB + size + frames + mtime check.
7. **Over-fitting to replay** ("worked on replay, ship it"). The final full run (§1 Step 5) against ground truth is the only number that counts; everything before is "promising but unproven."
8. **Windows + Intel iGPU driver friction** for boxmot/openvino. Allocate buffer time.

---

## 8. Open items needing a human call (not decided here)

- Which exact AM+PM trim windows to reprocess in Step 1 (must overlap the manual ground-truth CSV in `docs/historic data/`).
- Whether `B0_baseline` is acceptable as the comparison anchor given it's regenerated under current logic (vs the now-unrecoverable A1).
- Whether to VACUUM the 72 MB Sunnyvale DB before/after regeneration.
- Sign-off to add three dependencies: `pyarrow`, `boxmot`, `similaritymeasures` (+ OpenVINO export tooling).

---

## 9. Commit granularity (per CLAUDE.md)

One commit per artifact; never bundle scorer + tracker changes. Suggested: `Step 0 — detection audit script`; `Step 1.1 — detection cache writer/reader + content_hash`; `Step 1.2 — repopulating reprocess + B0 baseline`; `Step 2.1 — score_path_joint + tests`; `Step 2.2 — wire joint scorer behind flag`; `Step 3 — OC-SORT backend`; `Step 4 — OpenVINO path + parity`; `Step 5 — final validation`. Docs: add an "Attribution v2" section to `Implementation_Plan_v3.md` + `TDD.md` when done.
