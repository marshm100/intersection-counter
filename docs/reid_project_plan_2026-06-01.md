# ReID project — scoping plan (2026-06-01)

## Why this project
The OC+BoT position-based hybrid reached **net 15.8% / per-min gross 27.3%** (cam1,
docs/ocbot_hybrid_results_2026-06-01.md) and stalled there. The residual is no longer
attribution — it's two **appearance-shaped** problems that no motion-only tracker can
solve at this scene, because the missing signal is *which box is the same car*:

1. **Through over-track** — SB-thru +61 (OC-SORT ID-switches spawn duplicate through
   tracks). dedup_ceiling.py showed NO kinematic signal separates a fragmented
   continuation from a 1–2s headway follower on this dense arterial.
2. **Through under-recall** — NB-thru −66, the `min_hits=3` price (the gate that
   suppresses the duplicates in #1 also trims real short/low-conf throughs).
3. **EB-right sharp turn** — raw BoT sustains 11 EB→NB tracks but the pipeline event
   layer keeps only 2; the curve coast breaks the track and the exit fragment is
   never re-joined.

**Hypothesis:** an appearance embedding (ReID) is the single missing signal for all
three — it can (a) MERGE duplicate through fragments that kinematics can't tell from
followers, (b) let us LOWER `min_hits` to recover trimmed throughs WITHOUT
re-inflating duplicates (appearance now guards against the over-count), and (c)
RE-ASSOCIATE the EB-right exit fragment to its entry across the coast gap. This is the
lever memory has flagged for weeks as "the real remaining gain… but heavy, weak at
20–40px."

## The make-or-break risk (decide FIRST, cheaply)
Vehicles here are **20–40px** wide at 640×480. ReID backbones are trained on
256×128 crops; at <40px the embedding may carry too little texture to separate
vehicles → no usable signal, all of this fails. **memory says ReID is weak at this
size.** So Stage 0 is a pure go/no-go discriminability probe BEFORE any integration.
If it fails, we STOP, document, and route the residual (esp. EB-right) to human
review — the honest outcome, not months of integration on a dead signal.

## Grounded constraints (verified 2026-06-01)
- **boxmot 18.0.0 already ships ReID**: `boxmot.reid` has OSNet / OSNet-AIN / CLIP /
  LMBN backbones and backends incl. **OpenVINO** (the Iris-Xe iGPU path, ~3.7× like
  the detector — project_gpu_openvino_deferred). Integration = `BotSortBackend(
  with_reid=True, reid_model=<weights>)`, NOT new tracker code.
- **ReID needs REAL frames.** The current fast loop runs on the bbox-only detection
  cache with a dummy black image (`tracker.py` BotSortBackend `self._img = zeros`).
  ReID embeds the *crop*, so it must decode the video and cut crops per detection.
  **This breaks the ~10-min cache iteration loop** — each retrack must re-decode +
  crop + embed. Budget every iteration at multiples of the cache loop. Mitigation:
  cache embeddings per (frame,bbox) to a parquet sidecar so re-runs are cheap (build
  once, iterate on association params against cached vectors — restores a fast loop).
- Scene: 640×480 @ **10 fps** (not 30 — so `TRACK_FINALIZE_GAP_FRAMES=60` is 6s),
  30-min window = 18,000 frames. CPU-only i5-1135G7 / Iris Xe / 8GB, no CUDA
  (user_hardware_constraints) → small model (osnet_x0_25) on OpenVINO is the only
  realistic config; CLIP-ReID is too heavy for this box.
- Metric stays per-minute GROSS via od_accuracy.py; corrected labels {22:NB,23:SB,
  24:EB,25:WB}. Baseline to beat = OC+BoT hybrid 27.3% gross / 15.8% net.

## RESULTS 2026-06-01 (Stages 0-3 run; ReID delivered on the through tension)

| config | net | per-min gross |
|---|---|---|
| OC-SORT baseline | 21.8% | 30.7% |
| OC+BoT position hybrid | 15.8% | 27.3% |
| BoT motion-only | 24.4% | 32.0% |
| BoT+ReID (default thresh) | 16.1% | 30.6% |
| **BoT+ReID throughs + BoT-motion turns + intra-turn merge** | **10.0%** | 27.6% |
| **…same, events timestamped at ENTRY not finalization** | **10.0%** | **22.8%** |
| **+ EB-right path from raw tracks (Stage E)** | **7.7%** | 25.4% |
| **FINAL: + EB-right path + entry-timestamp** | **7.7%** | **20.8%** |

### Stage E — EB-right recovered (DONE 2026-06-01): the pipeline-loss fix
Diagnosed (`scripts/diagnose_ebright_loss.py`): the pipeline PRODUCES 13 EB-right
(L24→L22) tracks and assigns all 13 origin L24 — but **11/13 are DROPPED at
destination attribution** (pipeline.py:812): with no EB-right path in the bank the
joint scorer won't match them to the EB-left path, and the fallback `derive_movement`
returns insufficient_data. Chicken-and-egg: the path is needed to KEEP the tracks, but
the dropped events can't DERIVE the path. **Fix:** derive the EB-right polyline from the
RAW BoT tracker tracks (which sustain 13), bypassing the event-layer loss, and add it to
the bank (`scripts/add_ebright_path.py` → `recal_cam1_odturns_ebr.json`). EB-right
**1 → 38** in the turn arm (manual 36), **26** after the intra-turn merge. This is the
general fix for sparse cross-street turns the post-pipeline derivation misses.
Final combine: net **7.7%** / gross **25.4%** (20.8% with entry-timestamp), robust on
sub-windows (gross 26.5 / 24.5). **Residual now = genuine NB-thru recall (542 vs 595,
−53; the harder glare side ReID only partly recovers) + EB-right slightly under (26 vs
36) + timing.** All committed; nothing applied to production (visual gate pending).

- **Stage 3 (through tension) SOLVED by ReID — the main prize.** BoT motion-only badly
  under-counts low-conf throughs (SB-thru 346, NB-thru 492 vs manual 425/595); ReID
  re-associates them across gaps → **SB-thru 346→429 (≈exact), NB-thru 492→542.**
  BoT+ReID throughs now BEAT OC's (OC over-counts SB to 486). This is exactly the
  "recover throughs without the min_hits penalty" win memory predicted.
- **Best tracker config = BoT+ReID for throughs + BoT-motion for turns + intra-turn
  merge** (`scripts/hybrid_ocbot.py --oc-db botreid.db --bot-db botsort_fresh.db
  --no-dedup --merge-turns`). Net **10.0%** (from 21.8%), robust on sub-windows
  (gross 27.4 / 27.8). ReID turns are slightly dirtier (NB-right phantom 24 vs motion's
  9), so motion turns win the turn regime; ReID wins throughs.
- **Stage 2 (EB-right) — ReID is NOT the lever; it's PIPELINE-bound.** Raising
  proximity_thresh to 0.9 did not recover EB-right (still 1) and over-merged throughs.
  Geometric EB-right trajectories in the event DB: motion 2 → ReID 4-5, but raw BoT
  sustains 11 — the loss is the pipeline EVENT layer (sharp-cross-street finalize/
  no-origin), which a tracker-level appearance fix can't reach. The 4-5 that survive
  are now mis-attributed (no EB-right path in bank) — a small attribution gain is
  possible (derive an EB-right path from the 5), but the dominant EB-right gap needs a
  separate PIPELINE fix. Routes to human review until then.
- **TIMESTAMP artifact found (big, cheap, general).** Events are timestamped at
  `frame_number/fps` = the FINALIZATION frame (pipeline.py:830), which lags the actual
  crossing by transit + up to `track_buffer=150`/10fps = 15s, mis-binning vehicles into
  later per-minute (and 15-min TMC) bins. Re-binning by ENTRY (`start_frame`) drops
  gross with NO change to net (same counts, correct bins): ReID-mix 27.6→**22.8%**, and
  it generalizes (OC 30.7→27.7, hybrid 27.3→24.9). **This is a real product
  correctness bug** (a 07:14:58 crossing counted in the 07:15 bin), not just a metric
  trick — recommend timestamping events at the origin-crossing frame.

**Net from OC baseline → ReID-mix + entry-timestamp: 21.8%→10.0% net, 30.7%→22.8%
gross.** Remaining gross = EB-right (pipeline-bound, ~3%) + residual entry-vs-stopbar
timing + genuine count error. The 15% gross target is closer; the next levers are the
EB-right pipeline fix and tightening the crossing timestamp (origin_frame vs start_frame).

## SHIPPED 2026-06-01 — cam1 in production at net 7.2% / gross 18.8%
Executed the approved follow-on plan (C:\Users\onkar\.claude\plans\greedy-growing-rabbit.md):
- **Phase A** (commit ffae271): crossing-timestamp fix (pipeline.py — `timestamp_video`
  from `origin_frame`, not finalization), volume-gated intra-turn merge, generalized
  raw-track path derivation. cam1 **7.2% / 18.8%** native (from 7.7/20.8 re-bin). 520 tests pass.
- **Phase B** (commit e64bbf4): `scripts/process_camera_reid.py` B-batch orchestrator
  (cache→embed sidecar→retrack BoT+ReID + BoT-motion→combine_regimes→final events;
  `--apply` backs up + swaps events + applies bank). Fresh end-to-end reproduces 7.2/18.8.
  **ReID GPU = dead end** (osnet on Iris-Xe 0.86×, parity 1.0000; commit 1fdccac).
- **Phase C** (commit 4883319): `scripts/visual_gate.py` overlay → engineer APPROVED →
  applied to production. Live project.db verified: net 7.2 / gross 18.8, cardinals
  {22:N,23:S,24:E,25:W}, 6 paths incl EB-right. Backup backups/20260512_pre_reid_apply_cam1.db.
- **Phase D (cam2-5): NOT STARTED.** Heavy: those cameras have NO detection cache yet, so
  each needs a full-video detection pass (hours/CPU) before embed/retrack. Check the 180°
  mislabel per camera first.

## Staged plan (each stage has a hard kill-gate)

### Stage 0 — Embedding discriminability go/no-go  *(DONE 2026-06-01 → GO)*
**Result (`scripts/probe_reid_separability.py`, osnet_x0_25, 07:00–07:30, 400
high-purity greedy tracks):** appearance IS discriminative at this scene's size.
Judged on the REALISTIC cross-gap case (same-vehicle embeddings 5–15 frames apart vs
distinct vehicles co-present same frame):

| size | same-med | diff-med | cross-gap AUC |
|---|---|---|---|
| 20–30px | 0.865 | 0.614 | **0.886** |
| 30–40px | 0.863 | 0.573 | **0.872** |
| >40px | 0.811 | 0.609 | 0.758 |

Both gate buckets pass (≥0.85 @30-40, ≥0.75 @20-30). Consecutive-frame AUC is higher
still (0.95/0.93). The "ReID weak at 20–40px" worry is disproven *for discriminability*
— osnet_x0_25 cleanly separates same-vehicle (sim ~0.86) from a co-present different
vehicle (~0.61). (>40px is lower — trucks/buses look alike / more pose change — but
that's not the dominant vehicle size and not a gate cell.) **VERDICT: GO → Stage 1.**
Caveat: discriminability ≠ end-to-end win; Stages 2–3 still have to convert this
signal into association gains without new false-merges on the dense arterial.

### Stage 0 (original spec) — Embedding discriminability go/no-go  *(cheap, ~½ day, DO FIRST)*
Build `scripts/probe_reid_separability.py`:
- Take a few hundred high-confidence GREEDY/BoT tracks (link_detections) over the
  07:00–07:30 window — these are trusted "same vehicle" sequences.
- Decode the real video, cut the crop for each (frame,bbox), embed with osnet_x0_25
  (OpenVINO). Stamp each crop with its track_id and bbox size bucket (20–30 / 30–40 /
  >40 px).
- Compute, per size bucket: **intra-track** cosine distance (same car, consecutive
  frames) vs **inter-track** distance (different cars co-present same minute). Report
  the same/different **ROC-AUC** and the distance histograms.
- **GATE:** AUC ≥ ~0.85 in the 30–40px bucket AND ≥ ~0.75 in the 20–30px bucket →
  proceed. Below that, ReID can't reliably merge/split here → **STOP**, write the
  null result, route EB-right + through residual to human review, recommend the
  detection/resolution path (higher-res capture or super-res) as the only real lever.

### Stage 1 — Frame-backed retrack + embedding sidecar  *(~1 day, only if Stage 0 passes)*
- Add a frame supply to the retrack path: a `FrameProvider` that yields decoded
  frames aligned to the cached detections (reuse the video decode already in the
  pipeline; the cache gives frame indices). Wire BotSortBackend to receive the real
  frame instead of the dummy when `with_reid=True`.
- Build `scripts/build_reid_cache.py`: embed every cached detection once → parquet
  `reid_<variant>.parquet` keyed by (frame, bbox). Association experiments then read
  vectors, not pixels → fast loop restored.
- Deliverable: a BoT+ReID retrack that reproduces (within noise) BoT-only on motion
  alone, proving the frame/embedding wiring is correct before turning ReID weight up.

### Stage 2 — ReID for EB-right (sparse, strongest case)  *(~1–2 days)*
- Turn `with_reid=True` on BoT; tune `proximity_thresh` / `appearance_thresh` so the
  EB-right exit fragment re-joins its entry across the curve coast.
- Measure EB-right events recovered (target from 2 toward the raw-track 11; cell gross
  35 → ideally ≤15). Watch for NEW false merges on the dense arterial (the risk ReID
  is supposed to reduce, but verify).
- **GATE:** EB-right materially recovered with no net regression elsewhere → keep.
  Otherwise ReID helps turns but not enough — fold back to the 27.3% hybrid for turns.

### Stage 3 — ReID for the through tension (bigger payoff, harder)  *(~2–3 days)*
- With appearance guarding against duplicates, LOWER `min_hits` (3→2→1) and/or add an
  appearance-gated merge of overlapping through tracks. Goal: NB-thru up toward 595
  (recover the −66) while SB-thru stays near 425 (kill the +61) — the two move in
  opposite directions today, which is exactly what an appearance gate should let us
  decouple.
- Sweep on the embedding cache; validate the operating point isn't a knife-edge.
- **GATE:** combined through gross (currently 205) drops materially without new
  phantoms.

### Stage 4 — Re-integrate + validate + visual gate  *(~1 day)*
- Decide architecture: (a) ReID-augmented BoT *alone* may now fix BOTH regimes →
  retire the two-tracker hybrid (simpler); or (b) keep OC throughs + ReID-BoT turns.
  Measure both end-to-end vs 27.3% / 15.8%.
- Robustness: merge/assoc param sweep + 07:00–07:15 vs 07:15–07:30 stability.
- Engineer visual-gate overlay (paths follow road, no phantoms). Then, and only then,
  consider applying to production + extending to cam2–5 (heavier: each needs a frame
  decode + embedding cache build; OpenVINO speed lever applies).

## Honest cost / expected value
- **Best case** (Stage 0 passes well): a unified ReID-BoT could plausibly reach the
  ~15% gross target — through tension + EB-right are ~80% of the residual and all
  appearance-shaped. This is the only identified path to the target.
- **Likely case:** partial wins (EB-right recovered, through tension eased) →
  somewhere ~20–24% gross; still a real improvement over 27.3%, at real iteration cost.
- **Worst case** (Stage 0 fails at 20–40px): we spend ~½ day, get a definitive null,
  and stop chasing ReID — equally valuable as a decision, and it redirects effort to
  the only remaining lever (detection resolution) instead of burning weeks.
- **Iteration cost is the tax**: frames + embeddings are far slower than the bbox
  cache; the embedding sidecar (Stage 1) is what keeps this tractable on this box.

## Recommended immediate next step
Execute **Stage 0** only. It's cheap, it's the gate everything else depends on, and it
turns "ReID is heavy and maybe weak at this resolution" from a guess into a measured
go/no-go. Nothing else should be built until Stage 0 says the signal exists.
