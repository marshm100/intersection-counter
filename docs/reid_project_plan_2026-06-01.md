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
