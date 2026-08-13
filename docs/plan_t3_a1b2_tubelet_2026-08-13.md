# Tier-3 Block — A1+B2: tubelet stabilization with a zero-velocity
# hypothesis, RESCORE-ONLY iteration 1
# (2026-08-13)

Operator-approved at the Tier-1 checkpoint. The only lever aimed at the
tracker BIRTH GATE — the wall every Tier-1 block confirmed from a
different side: ft2 doubled raw detections and they did not convert
(insufficient-track counts ~2x, E4); a different tracker did not convert
them either (H1); the twin channel that would dedup them is dead (B1).
Literature mechanisms (research_synthesis_queued_2026-08-12): F6
BoostTrack-style tracklet-similarity confidence rescoring with adaptive
treatment for coasting tracks; F7 YOLOV pre-NMS temporal aggregation
(low-conf candidates deliberately preserved); F2 move-stop-move: an
explicit stopped state entered only below a speed threshold, with missed
detections treated as evidence FOR the stop, not track death; F5 the
ByteTrack-family birth rule (only unmatched HIGH-conf detections birth
tracks) — the documented design property we are compensating for.

## Scope discipline

ITERATION 1 IS RESCORE-ONLY: the stabilizer changes detection CONFIDENCE
values only. No synthetic boxes, no gap interpolation, no NMS changes.
Row count and every non-conf column byte-preserved (pinned by the
instrument's parity check). Gap interpolation (synthetic coasted boxes)
is the PRE-NAMED iteration 2, taken only if iteration 1's instrument
shows the recovery ceiling is missing FRAMES rather than low conf.

## The target class, measured precisely (2026-08-13 exploration)

The tracker's REAL thresholds (verified in supervision 0.17.1 / boxmot 18
source + live calib): BoT-SORT (cam1/2/3) associates from
track_low_thresh 0.10 (hardcoded), first-round splits at activation
(cam2: 0.25), but BIRTHS only from detections >= new_track_thresh —
cam2's calib leaves it NULL so the wrapper default **0.30** applies
(cam3: 0.18 by calib). ByteTrack (cam4/5) births at activation + 0.1 =
**0.35** (supervision hardcodes det_thresh = track_thresh + 0.1).
So cam2's associate-but-never-birth band is (0.10, 0.30) — **~38.5% of
its cached detections** (33.0% in [0.10, 0.25) + 5.5% in [0.25, 0.30)),
and the diagnosed birth_gate orphan clusters are ANCHORLESS: conf_max
< 0.25 for the whole cluster (diagnose_fast_misses verdict rule).
CONSEQUENCE FOR THE DESIGN: an anchor-required boost rule would be
blind to exactly the failing class. Eligibility must be STRUCTURAL.
Detections below 0.10 do not exist in the cache (detect floor 0.1) and
are invisible to every backend — no rescue below 0.10 is possible.

## Mechanism

1. Per-window SELF-CALIBRATION from the window's own BASE pass-1 dump
   tracklet table (fit_motion_residual: v_stop, zv_radius, alpha/beta) —
   the anti-frozen-constant mechanism, reused at detection level.
2. TUBELET LINKING over the raw detection stream, best-per-frame,
   reusing the retired v2_tubelet matcher shape (predicted-center greedy
   with gate 0.7*diag + 0.6*|v|*dt — proven code, scripts/v2_tubelet.py
   :93-116) plus the B2 ZERO-VELOCITY hypothesis: when the tubelet tail
   speed < v_stop, the association radius is zv_radius and missed frames
   do not terminate the tubelet (coast 1.0 s moving / 3.0 s stationary —
   the fit_motion_residual stopped-run bound). All bounds time-based.
   NOTE the framing correction vs the retired v2_tubelet: that script
   died as a REPLACEMENT tracker ("association too weak — floods
   30-32%; BoT-SORT association quality is load-bearing"). This build
   is cache-in / cache-out: BoT-SORT still does ALL tracking.
3. RESCORE RULE (structural eligibility — the anchorless-class fix):
   a tubelet is boost-eligible iff span >= 1.5 s AND >= 8 members (the
   v2_tubelet N-of-M precedent, time-scaled) AND member density >= 0.5
   per frame over its span AND motion-coherent (net path >= its own
   bbox diagonal OR ZV-stationary: tail speed < v_stop with residual
   inside zv_radius). Every member with conf below the camera's
   EFFECTIVE BIRTH FLOOR (backend-derived at runtime: botsort
   new_track_thresh, bytetrack activation+0.1 — never hardcoded) is
   raised to birth_floor + 0.02. Boost only upward, only within
   eligible tubelets, value capped (no tubelet-relative inflation).
   The false-birth bound is the instrument's DECOY gate, not an anchor
   requirement — the ledger's warning stands ("raises detection volume
   without converting" is the measured failure mode of both ft2 and
   the retired v2_tubelet; the phantom guard + decoy gate police it).
4. OUTPUT: `a1_<window>.parquet` + meta.json (source variant, stabilizer
   constants, calibration, boost census; schema = the 7-column cache
   contract: frame_idx, bbox_x1..y2, confidence float32, class_id) →
   standard pass-1 (variant name is the entire selector; cache_exists
   checks file+sidecar only; modified conf flows to the tracker
   untouched — verified end to end) → pass-2 → score. Zero backend
   changes; the measurement chain is the shipped one. Pre-tracker NMS
   (cam2 0.85) sorts by conf — boosted (≈0.32) never displaces real
   high-conf boxes.

## GATES — declared before any build completes; numbers final

- **G-A1-i (flicker instrument kill gate — BEFORE any pass-1 compute):**
  `scripts/v2_flicker_instrument.py`: donors = confident full tracks
  from the base dump; their cache detections located by frame + IoU
  match; a contiguous flicker window of duration {1, 3, 8 s} per donor
  gets conf suppressed into the sub-activation band; decoys = cache
  detections in the same conf band matched to NO dump track (isolated
  background flicker). Run the stabilizer on the modified cache.
  PASS requires, on cam2 study_0700 AND study_1600:
    - recovery (suppressed detections re-boosted to >= activation)
      >= 0.60 aggregate AND >= 0.40 in every duration bin;
    - decoy false-boost rate <= 0.05;
    - parity: row count identical, non-conf columns byte-identical,
      no boosted detection outside a matched tubelet.
  Anchors: 0.60 must decisively beat do-nothing (0.0) for the flicker
  class the band analysis names; 0.05 mirrors the B1 decoy bar; the
  duration bins stop a trivial only-short-flicker pass. FAIL → block
  stops before a single tracking run (iteration 1 spent), ledger
  "rescore-only stabilization cannot recover the flicker class".
- **G-A1-a (counting gate, cam2 x3 vs committed d1ctrl 53.4/42.9/44.0):**
  5/95 >= control on all 3 AND >= +1.0 on at least one; EB_left err
  strictly reduced on all 3; NB_left reduced on >= 2 of 3; EB_right
  watch cell reported; phantom guard (added non-compliant phantom slots
  <= newly compliant slots, v2_phantom_diag).
- **ACTIVATION GUARD (standing law, activation-coupling-law):** the
  stabilizer changes track composition BY DESIGN → coverage WILL move.
  Record result.evidence_activation per arm; state flip vs control →
  that window VOID under default flags; run flag-off pairs
  (EVIDENCE_ACTIVATION_ENABLED=0 both sides; e4ctrlx controls already
  committed for 1100/1600, a fresh 0700 flag-off control exists as
  e4ctrlx too) and gate on the flag-off pair, reporting both frames.
- **Iteration budget 2 from zero.** Iteration 2 = gap interpolation,
  ONLY per the scope-discipline trigger above.

## Cost and mechanics

Stabilizer run: minutes/window (pure pandas/numpy over the parquet).
Pass-1 botsort cam2: ~15-30 min/window x3 (detached + Monitor); pass-2
~6-8 min x3; instrument minutes. Sequential (memory). Copy NOTHING: the
a1_ parquet is a new file; pass-1 resolves the cache by the a1_ variant
name (the parquet exists → no re-detect). Workdirs
`_replay_scratch/a1_tubelet/<arm>_<win>/`, stems `a1_cam2_<win>` /
flag-off `a1x_cam2_<win>`. WAL-safe copies; delete twopass_ originals
after scoring. All chain scripts + score JSONs committed.
