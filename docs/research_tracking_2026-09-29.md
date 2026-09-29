# Tracking research synthesis (2026-09-29)

Operator brief: "fan out research agents to try and solve this problem ... our default is not holy,
solving the problem and 5/95 rule is." Five parallel research agents, one per area. Each read our
code read-only and the literature. Full reports are in the session transcript; this file keeps the
findings that change what we build, with their sources.

Standing rules this plan must obey: ONE default for every site, every camera judged on it
(ruling 2026-09-29); a vehicle's movement only from what the video shows for THAT vehicle
(ruling 2026-09-29); ship only on the 12-window fleet 5/95 letter against the true default
control (80.81 movement / 56.83 approach, every camera on the new-site tracker).

## What the five areas found

### 1. AI City Challenge vehicle counting (2020-21 Track 1)
- Every top team: detect -> track -> MERGE BROKEN TRAJECTORIES -> assign movement from the vehicle's own
  path (entry/exit zones or match to operator/typical paths).
- The single largest ablation gain in any paper was fragment post-processing: DiDi +6.87
  effectiveness (82.03 -> 88.87). Code: github.com/Jilliansea/DTTM-Vehicle-Counting.
- Useful, rule-compatible pieces: Zero-VIRUS route scoring against operator polylines (proximity /
  box diagonal, completeness slope, stability; +0.055 from completeness); Comenius acceptance rule
  (max completeness > 0.3 AND progress > 0.25 of route); SKKU per-vehicle "counted" state (ours
  already); Baidu: stubs that die stopped inside the entry line are not counted; HCMIU forward
  directional gate on matching (anti-theft).
- Caveats: their metric scored cumulative totals (errors cancel), their video was >= 1280x960,
  most fine-tuned detectors on labelled frames of the test cameras, several tuned per camera.
- Rule conflicts: DiDi's remaining-time from other vehicles' average journey time; "typical paths"
  k-means-clustered from other vehicles (our corpus path bank has the same character: audit).

### 2. Offline / global tracklet linking
- No published linker solves "same car continuing vs next car in the queue" out of the box.
- Transferable: HUNGARIAN / min-cost assignment of tracklet tails to heads with explicit BIRTH and
  DEATH costs (Zhang/Huang), instead of our greedy chain_tracks; the physical discriminator: a
  continuation is born where the leader WOULD BE (death + velocity x gap), a follower where the
  leader WAS; an AFLink-style link classifier trained per video with no labels, but with NEGATIVES
  that are real follower pairs mined from our own dumps (stock AFLink never saw one).
- StrongSORT AFLink (GPL-3.0) / GSI; BoxMOT (AGPL-3.0): reimplement ideas, do not copy code.
- Proposed pass-2 stage: RTS-smoothed endpoints; gates in seconds and box sizes (frame-rate and scale
  free); two-way prediction residual; birth/death costs from operator geometry (cheap at lines and
  image edge, expensive mid-box) replacing the "incomplete journeys only" veto; hierarchical passes
  (<= 0.5 s, <= 3 s, stationary <= 60 s); scipy linear_sum_assignment; RTS/GSI gap fill.
- It would REPLACE chain_tracks, the fracture rule, the bound-chain guard and the turn merge (the
  merge decides by expected volumes, which conflicts with the no-inference ruling). Keep twin dedup
  as a pre-step for now. Effort ~2-3 weeks. No new dependencies (scipy, sklearn).

### 3. Appearance (vehicle re-identification)
- Our BoT-SORT comes from boxmot 18.0.0 with a PERSON ReID model (osnet_x0_25_msmt17) that stretches
  vehicle crops to 256x128 portrait. Camera-motion compensation was never on (cmc_method=None).
- As installed, appearance is fused as min(iou_dist, emb_dist) and only when IoU distance <= 0.5:
  it can only make a match EASIER and only for already-overlapping boxes. It cannot bridge a 1-3 s
  occlusion and cannot veto a theft. That explains the small ReID gains measured in July.
- Literature and our own probes agree: at 13-40 px appearance is near useless (our AUC 0.399 across
  depths). Vehicle-trained models (clip_veri.pt already in boxmot's registry; FastReID VeRi) may
  help at >= 40 px.
- Role: a gated, per-video-calibrated VETO / tie-breaker inside the offline linker, only on clean
  crops above a measured size floor. Not an appearance-first default.
- cam2 gap hypotheses (cheap ablations): the fork's per-frame add-ons (position recovery reach, weak
  births, confirm-by-position, score fusion) get 2.5x more chances per second at 25 fps and were not
  converted by FPS_AWARE; score fusion (fork on, BoT-SORT off); XYWH vs XYAH Kalman state;
  ground-plane association (UCMCTrack / SparseTrack pseudo-depth) as a frame-rate-free alternative
  to IoU.

### 4. Small far-field detection (measured on our GPU, 300 frames of one camera)
- Production: yolo26l @ 1280, conf 0.08, FP32. The installed ultralytics runs the END-TO-END head, so
  iou=0.45 is ignored and the head can emit a car AND a truck box from one anchor: 2.40 duplicate
  pairs per frame. agnostic NMS on the one-to-many head: 0.00, with no small-box loss.
- Flicker of < 15 px boxes (~7-8% vanish next frame) is unchanged by any setting.
- Stock SAHI / far-band upscaling: no gain at 640x480 (upscaling adds only weak, less persistent
  boxes). Test-time augmentation is a silent no-op on end-to-end models.
- FP16: ~1.5x faster, free. TensorRT optional.
- Fine-tune only scale-matched (yolo26l trained at 1280 on 2x-upscaled frames), pseudo-labels from our
  own confirmed tracks; public datasets are mostly non-commercial. The earlier ft2 failed because it
  changed model size AND inference scale at once.
- Temporal rescue on the existing caches (REPP / Seq-NMS style rescoring, MOG2 motion evidence) may
  EXTEND existing chains through flicker, never create births or gate crossings on its own.

### 5. Ground truth and evaluation
- Months of drag come from judging tracking only through fleet 5/95 scores (errors cancel) and a
  home-made proxy.
- Cheapest first step: JOURNEY labels (per vehicle: entry leg, exit leg, crossing frames, class,
  a click at each crossing) on 5 x 3-minute clips across cameras, clip windows chosen before
  looking at tracker output: ~1-3 min of labour per minute of video, so a few operator hours.
- Full box/ID labels (CVAT self-hosted via Docker/WSL2, import CVAT-video XML with sparse keyframes,
  Merge / Split for breaks and thefts): 20-40 min per minute of video, 6-12 hours for 15 minutes.
- Harness: TrackEval (needs a numpy patch or separate venv) or py-motmetrics; IDF1, ID switches,
  fragmentations, one-track-per-journey rate; plus per-movement count check by replaying GT and
  candidate dumps through our own pass 2. A tracker idea then costs minutes, not a fleet arm.
- The fleet 5/95 arm stays the ship gate; FM 51 stays held out.

## The integrated plan (in order)

0. EVALUATION FIRST. Journey-label 5 x 3-minute clips (cam2, cam4 16:00, cam5 07:00, cam1 07:00,
   cam3 dawn), build the scoring harness. Everything after is judged here first, then by the fleet.
1. CHEAP TRACKER ABLATIONS FOR cam2 on the new-site tracker: frame-rate-aware recovery reach and
   birth rules, score fusion off, XYWH Kalman state. Judged on the labels, then the fleet.
2. GLOBAL TRACKLET LINKER in pass 2 (the biggest lever, per areas 1-3): replaces chain_tracks,
   fracture rule, bound-chain guard, turn merge. Includes the no-inference audit (turn merge's
   expected volumes, the corpus path bank, branch-1 posterior, entry-only rescue supports).
3. DETECTOR: FP16 plus the duplicate-box fix (one cache regeneration, new basis); temporal rescue on
   caches; later a scale-matched fine-tune.
4. APPEARANCE as a gated veto inside the linker, only if the labels show a residual it can reach.
Dual trackers: a consensus linker (fork + plain BoT-SORT) stays in reserve if step 2 leaves a
measurable fragment residual.
