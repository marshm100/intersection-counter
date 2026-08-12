# Research synthesis — queued/stopped vehicles, trajectory completion,
# turn-specific fragmentation (2026-08-12)

The Tier-2 sweep of the options-inventory campaign, scoped by the
2026-08-11 operator decision to run BEFORE the Tier-3 tubelet build.
Four questions the 2026-08-03 synthesis did not cover: stopped/queued
vehicle tracking, trajectory imputation as its own literature,
turn-specific fragmentation, and the last ~10 weeks. 23 numbered facts,
each tagged to the build option it informs. Facts marked CONTRADICTS
overturn a current campaign assumption. Sourcing caveats at the end are
part of the record.

## What this changes for our blocks (the campaign-impact digest)

1. **A1+B2 confirmed as the right first Tier-3 build, with named
   mechanisms**: tracklet-similarity confidence boosting with adaptive
   thresholds for coasting tracks (F6, BoostTrack/++, SOTA MOT20),
   pre-NMS temporal detection aggregation (F7, YOLOV/++, +8-9 AP50 in
   the flicker regime), speed-gated zero-velocity state with
   missed-detection-as-positive-evidence (F2, the move-stop-move radar
   literature — the strongest conceptual precedent for B2).
2. **A2 is viable ONLY as a dual-rate design** (F3 CONTRADICTS the naive
   plan): single-rate background subtraction absorbs stopped vehicles
   into the background — a plain motion mask would delete exactly our
   queued targets. Dual-rate (fast + slow background) turns "stopped
   vehicle" into a first-class foreground class; stop-bar presence
   detection misses ~0-9 of 7,000+ stopped vehicles (F4).
3. **H1's shape is validated, wholesale tracker swaps are not** (F16,
   F18, F19): per-movement best-source selection cut error 13.8%→7.3%;
   tracker rankings flip on curved motion (DeepSORT > ByteTrack at a
   roundabout); speed-conditioned Kalman parameters beat fixed ones. Our
   event-level movement partition IS per-movement source selection — the
   block proceeds as designed, and "per-regime parameters" is the named
   fallback family if the tracker-level hybrid fails its gate.
4. **A new option class surfaced — count the fragment, don't complete
   it** (F14, F15, F16): likelihood-map fragment-to-movement
   classification cut TMC error 16%→4-5% vs gate-crossing classification
   and works on tracks that never cross both gates; turn intent is
   classifiable 2 s ahead at ~91.5% from kinematics alone. This
   PARTIALLY CONTRADICTS our box-crossing precondition for fragmented
   tracks and is the most direct literature answer to the EB-left queue
   fragments. Filed as [new-option: fragment-to-movement classifier] for
   the checkpoint.
5. **The I-24 postprocessing recipe is the quantified C-revival anchor**
   (F10): min-cost circulation stitching (60-77% of fragments stitched)
   + convex-QP imputation/smoothing, MOTA 0.32→0.74 — physics/QP, not
   learned; a reference implementation exists.

---

## Q1 — Stopped/queued vehicle tracking and counting

**F1.** The I-24 team's own tracker benchmark quantifies how badly
generic MOT collapses at long stationary/slow durations: best HOTA 9.5%,
average 47.9 distinct IDs per ground-truth object; the authors conclude
the benchmarked trackers "do not perform sufficiently well at the long
temporal and spatial durations required for traffic scene
understanding." The citable anchor that no off-the-shelf tracker family
fixes it. Source: "So you think you can track?", WACV 2024,
arXiv:2309.07268. Tag: motivates [C-revival] over tracker swaps.

**F2.** The "move-stop-move" GMTI radar literature (stopped targets fall
below minimum detectable velocity and produce NO detections — the exact
analog of our birth/continuation gap) solves stops with: (a) an explicit
stopped-target mode (zero velocity, near-zero process noise) in an IMM
mode set; (b) STATE-DEPENDENT mode-transition probabilities — transition
into the stop mode permitted only when estimated speed falls below a
threshold; (c) "negative information" — a MISSED detection at the
predicted position is positive evidence FOR the stopped mode, not track
death. Sources: IEEE TAES 2011 (doc 5937281); SPIE 4048 (2000); SPIE
5429 (2004). Tag: [B2 zero-velocity hypothesis] — strongest precedent,
including the speed-gated entry and missed-detection-as-evidence.

**F3.** CONTRADICTS (naive A2): classical single-rate background
subtraction ABSORBS stopped vehicles into the background within
seconds-to-minutes — a motion mask would delete exactly our queued
targets. The stopped-vehicle/AID literature uses DUAL background models
at different learning rates: foreground against the slow model but
background against the fast model = temporarily stopped object; robust
to partial occlusion and illumination change; the mechanism behind
commercial AID cameras. Sources: AVSS 2007 "Real time detection of
stopped vehicles"; FLIR TrafiBot Dual AI; US patent 12,062,280. Tag:
[A2 motion-mask fusion] — dual-rate or not at all.

**F4.** Stop-bar zone PRESENCE detection is near-perfect on stopped
vehicles precisely where tracking-by-detection fails: field evaluation
(Autoscope/Peek/Iteris) missed 2/9/0 vehicles of >7,000; dominant error
was stuck-ON calls, i.e. over-holding presence. Per-lane occupancy needs
no track birth. Inverts our failure profile; supports a per-lane
queue-presence channel as independent evidence for protected-left
cells. Source: TRR 2005, "Evaluation of the Accuracy of Stop Bar Video
Vehicle Detection at Signalized Intersections". Tag: [A2] /
[new-option: stop-bar presence backstop].

**F5.** Our birth-gate blame is documented, named ByteTrack-family
behavior: new tracks initialize ONLY from unmatched high-confidence
detections; low-confidence boxes only associate to EXISTING tracks;
confirmation needs `minimum_consecutive_frames` consecutive matches — a
queued vehicle producing only flickering low-confidence detections can
never be born, by construction. Mitigation direction in the same docs:
lower match_thresh, raise track_buffer. Source: Roboflow Trackers
ByteTrack docs. Tag: [B2] framing — design property, not tuning
accident.

**F6.** Detection-confidence RESCORING against tracklets is a published
plug-and-play fix for "true object stuck below threshold": BoostTrack
boosts detections whose similarity to existing tracklets is high;
BoostTrack++ adds a soft vote (shape, Mahalanobis, boosted IoU) plus
ADAPTIVE thresholds for tracklets with infrequent updates (coasting
tracks — our stopped cars). First among online methods on MOT17/MOT20
HOTA. Related: the NSA Kalman filter (StrongSORT) scales measurement
noise by detection confidence R~=(1-c)R so flickering boxes update a
locked track weakly instead of breaking it. Sources: BoostTrack, MVA
2024; BoostTrack++ arXiv:2408.13003; StrongSORT NSA ablation. Tag: [A1]
(rescoring half) + [B2] (confidence-scaled updates).

**F7.** Detection-level temporal aggregation has current, quantified
instantiations: YOLOV/YOLOV++ aggregate per-frame candidate features
across reference frames, adjusting classification AND IoU scores;
YOLOV++ drops NMS pre-aggregation to keep low-confidence candidates
(deliberately preserving the flicker we lose). Up to 92.9-93.2 AP50 on
ImageNet VID at 30+ FPS on one 3090 — roughly +8-9 AP50 over the
still-image baseline, biggest gains on deteriorated frames. Sources:
YOLOV AAAI 2023 arXiv:2208.09686; YOLOV++ arXiv:2407.19650. Tag: [A1
tubelet stabilization] — strongest direct evidence for stabilizing
detections BEFORE the tracker.

**F8.** An intersection-specific ByteTrack adaptation (Electronics 2024,
13(15):3033) for the stop-start regime: Soft-NMS for dense queues,
modified Kalman state/covariance for nonlinear stop-start motion, and
Gaussian-Smoothed Interpolation (from StrongSORT) as lightweight
in-tracker gap-fill. Tag: [B2] + light [C-revival].

**F9.** Queue length on low-res urban video is measurable WITHOUT
long-lived tracks: YOLOv4+DeepSORT with a displacement-based
stopped-vehicle test reports 73% count-based / 88% pixel-length queue
estimation accuracy. "How many vehicles are stopped in this lane" is a
far easier target than per-vehicle identity — usable as a per-cycle
cross-check on turn cells (a queue discharging during a protected-left
phase belongs to the left cell). Source: Processes 9(10):1786, 2021.
Tag: [new-option: queue-occupancy cross-check].

## Q2 — Trajectory imputation / completion

**F10.** The I-24 MOTION postprocessing paper is the fullest published
fragment-soup-to-trajectories recipe, with numbers: raw tracking
produces 4.66-8.93 fragments per GT vehicle; online min-cost network
circulation stitches 60-77% of fragments into trajectories 3-4.5×
longer; a per-trajectory convex QP then simultaneously imputes missing
segments, removes outliers (L1), and smooths (L2 on accel+jerk) under
kinematic constraints. MOTA 0.32→0.74, precision 0.71→0.90, recall
0.56→0.83; 3.5 h to process 4 h of 276-camera data. Source: TR-C 2024,
arXiv:2212.07907; reference impl github.com/I24-MOTION/
I24-postprocessing-lite. Tag: [C-revival] — the flagship quantified
pipeline; imputation is physics/QP, not learned.

**F11.** TrajGAT (TR-C 141:103787, 2022): real-time imputation of
ROADSIDE-perception trajectories lost to occlusion using a map-embedded
graph attention network — lane geometry constrains where the unseen
vehicle can be (directly applicable to a protected-left pocket). Best
across metrics vs SOTA baselines, robust across missing rates. Tag:
[C-revival] / [new-option: map-constrained learned imputation].

**F12.** "Offline Tracking with Object Permanence" (IEEE IV 2024,
arXiv:2310.01288): Re-ID match across the occlusion, then a track
COMPLETION module regresses the missing middle conditioned on
vectorized lane-map context; SOTA 3D MOT on nuScenes by improving the
online result. Transferable idea: completion conditioned on lane
geometry, run only where a Re-ID link was accepted. Tag: [C-revival].

**F13.** Generative trajectory completion under extreme sparsity exists
but on GPS/human mobility, not intersection video: ProDiff
(arXiv:2505.23048) reconstructs a full trajectory from ONLY two
endpoints via prototype-guided diffusion (+6.28% over DiffTraj on
WuXi); TRACE (WWW 2026, arXiv:2603.19474) adds state-propagation
memory, >26% claimed improvement. Structurally our
pre-queue-fragment→post-discharge-fragment gap. Tag: [new-option:
generative gap completion] — capability high, domain transfer unproven;
F10's physics/QP is the safer first build.

**F14.** Counting BROKEN tracks by matching fragments to canonical
movement paths is competition-grade: AI City Track-1 line (CVPRW 2020
"Robust Movement-Specific Vehicle Counting", CVPRW 2021 successor,
S1=0.9467 rank 1 AICITY2021) assigns each possibly-partial trajectory
to a movement via shape similarity to movement templates; Shirazi &
Morris (ITSC 2014) counted broken trajectories by LCSS distance to
typical paths, trajectory module adding ~15% counting accuracy over
zone-only counting, explicitly reconnecting tracks of vehicles that
STOPPED at the intersection. Tag: [C-revival] / [new-option:
fragment-to-movement classifier] — a fragment need not be completed to
be counted; it needs a movement posterior. (Caveat: the 15% figure and
S1 table rest on abstract-level statements.)

**F15.** Turn intent is classifiable from a PARTIAL approach trajectory
2 s ahead of the event: INTENT (July 2026, arXiv:2607.08316) — plain
LSTM over 11 kinematic features, 91.5% test accuracy on inD; ablations
show bidirectionality and depth HURT. An EB-left fragment that dies in
the queue still carries a classifiable turn signature (pocket-lane
position + deceleration). Tag: [C-revival] fragment-classification leg;
also a Q4 item.

## Q3 — Turn-specific / maneuver-dependent fragmentation

**F16.** The strongest per-movement evidence found (Elder group, IEEE
ITSC 2024, arXiv:2511.12342, YOLO+ByteTrack on three datasets):
(a) per-movement error under ONE tracker ranges 0-7.6% on some
movements to 33-400% on others — error concentrates per movement,
matching our per-cell pattern. (b) PARTIALLY CONTRADICTS our gate
design: pure entry-exit gate-crossing classification was the WORST
method everywhere computable (CityFlow 16.0% error) and UNCOMPUTABLE on
the limited-FOV dataset because fragmented tracks never cross both
gates; classifying the whole available track against per-movement
Gaussian-KDE likelihood maps cut error to 5.1% camera / 4.0% ground
plane AND works on fragments. (Our in-box shape matching mitigates
partially; the box-crossing precondition is the vulnerable part.)
(c) Per-movement best-camera fusion cut error 13.8%→7.3%, bias
+5.2%→+0.1%. Tags: [C-revival] likelihood fragment classification,
[H1] per-movement source selection validated, CONTRADICTS gate-only
classification for fragments.

**F17.** Maneuvering-vehicle tracking at junctions is a FILTER-MODEL
failure too: "vehicles turn quickly, and a single filter approach
cannot cover the dynamic range"; ICRA 2020 (arXiv:1912.00603) runs an
IMM whose mode-transition matrix is modulated by ROAD CONTEXT
(maneuvers allowed only where geometry permits), IMM a-posteriori
residual as association cost. Warning recorded: maneuver-oriented
association increases ambiguous cross-model matches — per-maneuver
hypotheses need strong gating. Our operator-drawn channels ARE that
road context. Tag: [H1] / [B2].

**F18.** CONTRADICTS one-parameterization-fits-all-speeds: SG-LKF
(arXiv:2508.00358) conditions Kalman noise covariances on speed regime
via a small MLP — at low speed, prediction should dominate flickery
observations; at high speed the reverse. 79.59% HOTA KITTI 2D (first
among vision methods), +2.2% AMOTA nuScenes over SimpleTrack.
Complementary (arXiv:2509.11323): constant-velocity KF error SPIKES
transiently on direction changes — queue discharge into a turn is both
regimes at once. Tag: [H1] — supports regime-dependent PARAMETERS
(cheap) over regime-dependent trackers (expensive).

**F19.** CONTRADICTS "ByteTrack-family uniformly best for vehicles": at
a multilane roundabout (pure curvature regime), DeepSORT outperformed
ByteTrack in tracking accuracy and efficiency, 97% turning-movement-rate
accuracy overall — appearance association compensates where the linear
motion prior breaks. The cleanest published instance of tracker ranking
FLIPPING with movement regime — the H1 premise. Source: Green Energy
and Intelligent Transportation 2025, doi:10.1016/j.geits.2025.100340.
(Caveat: abstract-level.) Tag: [H1].

## Q4 — New in the last ~10 weeks

**F20.** Camera-agnostic TMC via unsupervised entry/exit region
discovery (July 12, 2026, arXiv:2607.10949): clusters trajectory
ENDPOINTS into persistent entry/exit polygons, classifies tracks by
point-in-polygon; 25 Bengaluru cameras + UA-DETRAC, 17,100 runs; 3.4%
median movement error, median GEH 2.43; more view-stable than
trajectory-clustering baselines. Relevant as a cross-check /
auto-suggestion for operator-drawn gates (consistent with our
no-benchmark-data constraint). Tag: [new-option: auto-derived gate
regions] (validation aid, not runtime dependency).

**F21.** TAVR-IVD (June 21, 2026, arXiv:2606.22299): stationary-first
surveillance — detect idling vehicles by running MOT then classifying
each TRACKLET with audio-visual reasoning; tracklet-level decisions
"stabilize temporal decisions" for stationary targets. Mechanism:
"stationary vehicle" as a first-class object state with its own
classifier over accumulated evidence. Tag: [new-option:
stationary-object channel] (adjacent to [B2]).

**F22.** New intersection-perception datasets (June-July 2026): RESOLVE
(arXiv:2606.31895, 100k+ images, multi-resolution roadside cooperative
3D detection+tracking), CLIFE (arXiv:2607.16154, edge camera-LiDAR
fusion at signalized intersections), Cross-View Urban Traffic
(arXiv:2606.07708, drone-supervised monocular BEV ground truth). Tag:
evaluation infrastructure only.

**F23.** Likely missed on 2026-08-03: SWIFTraj Part II
(arXiv:2602.21954) — cross-camera trajectory connection via
graph-layout time alignment (within ~0.1 s) + Hungarian matching at
F1≈0.99 — a template for cross-camera dedup cost design. Offline-Poly
(arXiv:2602.13772) — offline "tracking-by-tracking" global
optimization, 77.6% AMOTA nuScenes — offline global optimization
remains the leaderboard top. Tag: [C-revival] periphery / cross-camera
dedup.

## Recommendation ordering for Tier-3 (evidence-backed)

1. A1+B2 as ONE front-end block (F2, F5, F6, F7 — rescoring +
   aggregation + speed-gated stop state).
2. C-revival reshaped: offline stitching + QP imputation (F10) AND
   likelihood fragment-to-movement classification (F14/F15/F16) — a
   queued fragment gets COUNTED, not discarded.
3. A2 only as dual-rate presence/queue channel (F3 kills the naive
   version; F4/F9 are the payoff).
4. H1 (this campaign's Block 4 tests the tracker-level version; the
   literature's validated fallbacks are per-regime parameters and
   per-movement source selection).
5. Gate discipline unchanged: per-movement error spread 0-400% under
   one tracker (F16) is exactly why the 5/95 per-cell per-bin bar must
   stay the pass metric.

## Sourcing caveats (part of the record)

F14's 15% figure and S1 table, and F19's DeepSORT>ByteTrack ranking,
rest on abstract-level statements (tables not inspected). A
"Stationary Sensitive Association" phrase surfaced in one search could
not be traced to a verifiable paper and is EXCLUDED. All other facts
carry mechanism + verified numbers from the cited sources.
