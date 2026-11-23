import os
from pathlib import Path

# Base directories
APP_DIR = Path(__file__).parent.parent
DATA_DIR = APP_DIR / "data"
MODELS_DIR = APP_DIR / "models"
FRONTEND_DIR = APP_DIR / "frontend"

# Database
PROJECTS_DIR = DATA_DIR / "projects"

# Video processing
DEFAULT_FRAME_SKIP = 3
DEFAULT_INTERVAL_MINUTES = 15
MAX_PRESCAN_SECONDS = 600
PRESCAN_CONFIDENCE_THRESHOLD = 0.90
CHECKPOINT_INTERVAL_SECONDS = 120
MAX_CONCURRENT_PIPELINES = 2

# Detection — accurate mode is tuned for accuracy over speed. yolo26l is
# the large variant; imgsz=1280 keeps distant intersection vehicles
# detectable at 1080p capture. Confidence is intentionally low — obvious
# vehicles (e.g., a foreground pickup in glare) sometimes come back at
# 0.10-0.14 from yolo26l, especially when partially backlit.
# CAVEAT (FM51 recovery experiment, 2026-07-02): imgsz only helps when the
# detail is IN the source pixels. On 640x480 footage, running 1280 inference
# just upscales — distant vehicles below the source pixel floor are NOT
# recovered (measured +6% uniform, not a distant-vehicle recovery). A
# low-resolution source is a hard wall; the mitigation is spot-count coverage
# of the affected window (spot_check §5 stratification), not a detector knob.
#
# Fast mode uses the small variant at 640 + every-3rd-frame detection
# (tracker Kalman-interpolates between detections) — ~10-15× faster on
# CPU. Mode is per-project; default is "accurate" so existing projects
# don't change behavior on upgrade.
YOLO_MODEL = "yolo26l.pt"
YOLO_CONFIDENCE_THRESHOLD = 0.08
YOLO_IOU_THRESHOLD = 0.45
YOLO_IMGSZ = 1280

# Class-agnostic NMS applied to cached detections BEFORE the tracker (Stage-2
# anti-duplication, 2026-06-02). The detector double-boxes one vehicle (e.g. a
# 'car' AND a 'truck' box) in ~83% of frames at IoU>0.6 — model-independent
# (yolo26s@960 and yolo26l@1280 both do it). bytetrack tracks each box as its
# own ID, producing parallel duplicate THROUGH tracks (the cam5 NB-thru +162).
# YOLO's own per-class NMS (YOLO_IOU_THRESHOLD) does NOT suppress cross-class
# duplicates, so we collapse them class-agnostically at the tracking input. The
# detection CACHE stays raw (written before _ingest_detections); only tracking
# sees the deduped stream.
# DEFAULT OFF (None): measured per-camera and it is NOT corridor-safe — at IoU 0.7
# it over-merges DENSE but distinct throughs (cam4 NB-thru 728→~644) for only a
# ~0.4pp gain where it helps (cam5). The real Stage-2 through win came from
# REFRESHING stale shipped throughs (apply_hybrid --throughs-db), not NMS. Set to
# a float (e.g. 0.7) to enable for a specific camera's retrack; env override
# PRE_TRACK_NMS_IOU=<float> turns it on per-run.
import os as _os
_nms_env = _os.environ.get("PRE_TRACK_NMS_IOU")
PRE_TRACK_NMS_IOU = float(_nms_env) if (_nms_env and _nms_env != "off") else None

PROCESSING_MODES = {
    # SHIPPED 2026-08-27 (G-CP-1 PASS, docs/plan_counted_path_2026-08-27.md:
    # 70.6 pooled vs 64.8 shipped; SB_right healed 379/378). The corridor
    # production recipe: the large model at 1280 with the production
    # confidence floor.
    "counted_path": {
        "yolo_model": "yolo26l.pt",
        "yolo_imgsz": 1280,
        "yolo_confidence": 0.10,
        "detection_skip": 1,
        "tracker_match_threshold": 0.8,
        "tracker_activation_threshold": 0.25,
        "label": "Counted-path (yolo26l @1280)",
        "description": "The G-CP-1 shipped recipe: large model at 1280 px, every frame, production confidence floor 0.10. CPU-impractical for full days; built for CUDA detects.",
    },
    "accurate": {
        "yolo_model": "yolo26l.pt",
        "yolo_imgsz": 1280,
        "yolo_confidence": 0.08,
        # Detect on every frame — tracker sees full source frame rate.
        "detection_skip": 1,
        # Strict ByteTrack defaults: Kalman has fresh velocity every step.
        "tracker_match_threshold": 0.8,
        "tracker_activation_threshold": 0.25,
        "label": "Accurate",
        "description": "Best accuracy. Large model at 1280 px, every frame. On CPU this is ~60× slower than real-time and is only practical for short clips; for full-day footage use Balanced or Fast.",
    },
    "balanced": {
        # PROMOTED 2026-07-21 (plan_finetune_v2_retrain, held-out FM51 gate
        # vs the v1 native baseline on the identical basis: total +3.8% ->
        # +2.0%, interval MAE 4.0% -> 3.0%, Articulated 22 -> 56, Mediums
        # 7 -> 157): the 4-class corridor head (adds the medium class; ft
        # 2/3 ride the native single-unit id). Fallback = the previous
        # promoted pair (yolo26s_ft1.pt @ 640, class_scheme finetune_v1);
        # pre-ft stock fallback remains yolo26s.pt @ 960, coco. Known
        # residuals, tracked in the plan doc: ~46 held-out semis still read
        # medium (artic<->medium split; ambiguous-class feeder surveils),
        # far-field side-leg origin grab at T-stems (origin-veto retired,
        # conservation feeders surveil).
        "yolo_model": "yolo26s_ft2.pt",
        "yolo_imgsz": 640,
        "yolo_class_scheme": "finetune_v2",
        "yolo_confidence": 0.10,
        "detection_skip": 1,
        # Detection every frame, so strict ByteTrack defaults are appropriate.
        "tracker_match_threshold": 0.8,
        "tracker_activation_threshold": 0.25,
        "label": "Balanced",
        "description": "Recommended for full-day clips. Fine-tuned site-trained 4-class model at 640 px detecting every frame (FM51-validated: interval MAE 3.0%, native articulated + medium classes for L/M/A); fast vehicles track reliably (no skip-frame Kalman mismatch). Full-day footage usually fits in an overnight run.",
    },
    "fast": {
        "yolo_model": "yolo26s.pt",
        "yolo_imgsz": 640,
        # Slightly higher conf floor — small model is noisier at low conf.
        "yolo_confidence": 0.15,
        # Detect every 3rd frame; tracker Kalman-interpolates between.
        "detection_skip": 3,
        # Loosened tracker thresholds for the skip-3 regime. ByteTrack's
        # Kalman assumes consecutive update() calls are 1 frame apart, so
        # at detection_skip=3 it under-predicts motion by 3× and a moving
        # vehicle's new bbox can have ~0 IoU with the predicted bbox.
        # match_thresh=0.95 → match when IoU≥0.05 (vs the 0.8/IoU≥0.2 default).
        # activation_threshold=0.15 lets single-detection fast vehicles
        # start a track rather than dying in the BYTE association queue.
        "tracker_match_threshold": 0.95,
        "tracker_activation_threshold": 0.15,
        "label": "Fast",
        "description": "~10-15× faster. Small model at 640 px with detection every 3rd frame; tracker interpolates. May miss small/distant vehicles. Good for previewing.",
    },
}
DEFAULT_PROCESSING_MODE = "accurate"

# Two-pass counting flow (MASTER_PLAN 2c / plan_A4_stage3_2026-07-10):
# pass-1 raw-track dumps at ingest, pass-2 (bank + replay-classify + turn
# merge + QA) behind "Confirm & process". DEFAULT ON since 2026-07-13: the
# stage-3.4 operator dry-run passed its gate (UI-only run reproduced the
# shipped corridor counts exactly — plan_stage34_operator_surface doc).
# Env override to disable (reverts to the legacy live pipeline, untouched):
# TWO_PASS_ENABLED=0.
import os as _os2
TWO_PASS_ENABLED = _os2.environ.get("TWO_PASS_ENABLED", "1") in ("1", "true", "on")

# V2 census-ratio-conditioned claim demotion (plan_v2_week1_verdict day-6b,
# counterfactually validated 2026-08-05): cells whose DIRECT-attributed mass
# exceeds V2_DEMOTION_RATIO x the gate-evidence census are flooded by
# origin misattribution (cam2 EB-right 220/54 = 4.1 vs healthy EB-left
# 121/149 = 0.8); their direct claims re-route through the branch1
# posterior. Default OFF — dev-measurement flag until the blind held-out
# gate passes. Ratio is a structural constant (ledger), NOT per-camera.
V2_DEMOTION_ENABLED = _os2.environ.get("V2_DEMOTION", "0") in ("1", "true", "on")
V2_DEMOTION_RATIO = 2.0

# V2 merge rescue (block-2 item 1): merged-away turns whose tracks are
# gate-verified FULL journeys in a DIFFERENT cell reclassify to the gate
# cell instead of being deleted (gate evidence outranks the volume prior;
# same-cell rejects keep the volume gate's excess semantics). Default OFF.
V2_MERGE_RESCUE = _os2.environ.get("V2_MERGE_RESCUE", "0") in ("1", "true", "on")

# V2 track-derived GATE ORIENTATION (plan_v2_gate_axis_2026-08-10): the
# gate at a leg mouth must lie ACROSS the road, and both operator-drawn
# sources for that direction are measured unreliable (channel tangents
# 23.8-55.0 deg off actual travel on the CORRIDOR, worse at FM51;
# reference_heading 20-58 deg off elsewhere). With this on, the axis is
# estimated from the window's own tracks instead — axial (doubled-angle)
# averaging, since mouth traffic is bidirectional — and only where the
# support floor is met; every other leg keeps the shipped behavior
# byte-identically. Default OFF until G-OR1..4 pass. OFFLINE paths only:
# the live first pass has no completed track set and is untouched.
V2_GATE_AXIS = _os2.environ.get("V2_GATE_AXIS", "0") in ("1", "true", "on")

# Phase-1 APPLY GATE (plan_v2_apply_gate_2026-08-07): per-window
# candidate-vs-incumbent adjudication under the blind guards — an apply
# must WIN its window; stand-downs keep the incumbent table and land in
# the apply_adjudications audit trail. Product architecture (default ON;
# env kill-switch reverts to unconditional apply). Constants pre-declared
# in the plan doc, validated 12/12 blind on the v2_week1 pairs; the
# saturation ceiling is the demotion contrast guard's shipped 0.25,
# hoisted here so both mechanisms share one constant.
APPLY_GATE_ENABLED = _os2.environ.get("APPLY_GATE", "1") in ("1", "true", "on")

# Gate supremacy (operator ruling 2026-08-24, docs/plan_divergence_arbitration):
# a track whose entry AND exit gate crossings were both observed (tag='full')
# is classified by those crossings — the box sides ARE origin/destination
# (CLAUDE.md hard constraint). Path matching may not override an observed exit.
# Measured before this flag: path matching overrode 146/176/247 full journeys
# per cam2 window, top flip = gate-said-through relabeled right (55/80/139),
# mirroring the Miovision error table. Env-overridable for A/B replays.
GATE_FULL_SUPREMACY = _os2.environ.get("GATE_FULL_SUPREMACY", "1") in ("1", "true", "on")

# Anti-theft campaign (2026-09-06, docs/plan_anti_theft_2026-09-06.md).
# The vanish-zone census + operator scene rulings: ~71% of moving
# mid-scene track deaths are THEFTS — an occluded vehicle emerges next
# to a tracked one and IoU-only assignment hands the moving track over
# (the bus-law gate only judges LOST rows; Tracked rows were never
# questioned). Operator rule: emergence spawns a NEW track, never a
# hand-over; a mid-scene newborn inherits its origin from the
# concealer it was hidden behind (gate-evidenced origins only).
# Default OFF until G-LT-1 passes and the operator ships them.
# ======================================================================
# THE DEFAULT (G-DEF-1 PASS, operator go 2026-09-10 — docs/plan_default_
# 2026-09-10.md). Cams 1-5 are test footage; the deliverable is what the
# software does UNAIDED on a blank intersection. The four rules below
# default ON because, applied blind as one configuration to all 12
# corridor windows, they score 75.70 against the all-off 69.43 and no
# camera or window loses. The env var is an OVERRIDE for experiments
# (X=0 turns a rule off); nothing in production needs it set.
# ======================================================================
# THE THRESHOLD LAW (operator ruling 2026-09-07, confirmed 4/4 on the
# phantom-driveway reel): a gate is a threshold ON THE GROUND. A tall
# vehicle passing IN FRONT of a background gate line must not count as
# crossing it — only the bounding box BOTTOM (the ground-contact point)
# crossing the line counts. Anchors the gate-evidence crossing test at
# (cx, cy + bh/2) instead of the box center. Default OFF until G-C1-1
# iteration 2 passes and the operator ships it.
GATE_GROUND_ANCHOR = _os2.environ.get("GATE_GROUND_ANCHOR", "1") in ("1", "true", "on")
# G-EX-1 (2026-09-08): the both-corners half of the threshold law is
# strictness against a GRAZE; ground anchoring alone kills the
# tall-vehicle illusion. Requiring both corners for gate EVIDENCE
# discards real vehicles rather than preventing false counts —
# measured on cam5 midday it cut witnessed entries 3,100 -> 2,661,
# dropping coverage under the 0.45 activation bar and switching the
# evidence channel off for the whole window (+932 vehicles dropped).
# This accepts a witness from EITHER bottom corner, refusing only on
# conflict (measured: conflicts never occur — 0 of 6,149 tracks).
GATE_EVIDENCE_EITHER_CORNER = _os2.environ.get(
    "GATE_EVIDENCE_EITHER_CORNER", "1") in ("1", "true", "on")

# THE FIRST-EXIT RULE (operator ruling 2026-09-08): "it went from n to
# s, period. End of story." classify() takes the FIRST entry but the
# LAST exit, so a track stolen AFTER its journey finished rewrites the
# destination — on cam3 that manufactures 88 southbound u-turns against
# Miovision's zero (verified: the vehicle exited over S in 4.3 s, then
# the id sat parked in the far-field queue 120 s before a different
# vehicle, box 31x14 -> 75x48, carried it across N). A journey ends at
# its first LEGITIMATE exit; a same-leg exit counts only if it passes
# the u-turn tests, else it is the operator's "jitter over the s".
JOURNEY_FIRST_EXIT = _os2.environ.get(
    "JOURNEY_FIRST_EXIT", "0") in ("1", "true", "on")

# THE JOURNEY STATE MACHINE (operator rulings 2026-09-09, ruling cam2
# track 17526 end to end; docs/plan_state_machine_2026-09-09.md):
#   R1  a crossing counts only when BOTH bottom corners cross the line
#       ("the lower corners need to cross the exiting line before it
#       can be counted as exit");
#   R2  EXITED IS TERMINAL ("once it crosses the exit, that detection
#       ID can no longer be used as a valid ID for crossing because
#       that vehicle is already left");
#   plus his approved split for the one case R1 breaks: a single-corner
#   crossing counts when the TRACK ENDS there — the trailing corner's
#   evidence was truncated by tracking loss, not by the vehicle staying
#   put. Measured: cam1's solo crossings are departures (50% end within
#   1 s, 9% continue >100 f), cam2's are wobble (6% / 79%) — mirror
#   images, and the truncation split is the one rule correct on both.
# SUPERSEDES GATE_GROUND_ANCHOR + GATE_EVIDENCE_EITHER_CORNER +
# JOURNEY_FIRST_EXIT inside _gate_evidence (when on, it takes the
# corner tracks and those three no longer apply there). Validated
# against the SHIPPED combination, never bare defaults. Default OFF
# until G-SM-1 passes and the operator ships it.
JOURNEY_STATE_MACHINE = _os2.environ.get(
    "JOURNEY_STATE_MACHINE", "1") in ("1", "true", "on")
CORNER_PAIR_WINDOW_S = 2.5    # both corners' crossings of one gate pair
                              # within this (p99 of the measured corner
                              # gap: cam1 2.1 s, cam2 2.6 s)
CROSSING_TRUNCATION_S = 1.0   # a solo-corner crossing counts only if the
                              # track ENDS within this of it (departure
                              # window: the two populations separate
                              # 50% vs 6% here)
# G-SM-1 iteration 3 (operator's idea 2026-09-09, red-teamed in
# scripts/redteam_line_extension.py): the machine's crossing law sees
# each drawn gate EXTENDED by this fraction of its length at each end,
# so a wide-body box whose corner sits past the drawn line's end can
# still be hit ("the bounding box is so large one of the corners sits
# beyond the intersection line's length and cannot be hit with the
# intersection line as drawn"). To the frame edge it FAILS (cam3's S
# extension runs into cross traffic: 1420 lone hits); at 0.25 cam3
# completes 937 wide-body pairs for 170 lone hits; the cliff is
# between 0.25 and 0.5. Used ONLY by pair_crossings — classify() and
# the census keep the drawn gates.
GATE_EXTENSION_MARGIN = 0.25

# BORN INSIDE EVERY LINE (operator ruling 2026-09-11, FM 51: "software").
# On a blank site the operator draws the lines at the physical mouths and
# detection begins inside them: 72% of FM51's tracks are born inside all
# four lines (6-38% on the corridor), so no line is ever crossed and the
# evidence channel never activates. When ON: a track with no valid
# inward crossing whose first bottom-centre point lies inside every
# gate's half-plane ENTERED over the gate nearest its birth among those
# whose inward direction agrees with its first BORN_INSIDE_VEL_S of
# travel; a track with no legitimate exit whose last point lies inside
# every gate EXITED over the nearest gate its last BORN_INSIDE_VEL_S of
# travel points at (same leg only if the u-turn tests pass). His
# born-across ruling, extended from one corner to the whole box.
# G-DEF-7 candidate; default OFF until the fleet + FM51 judge it.
BORN_INSIDE_NEAREST_LINE = _os2.environ.get(
    "BORN_INSIDE_NEAREST_LINE", "0") in ("1", "true", "on")
BORN_INSIDE_VEL_S = 1.0
# BORN AT THE MOUTH (2026-10-01, plan step 2; docs/plan_basis_2026-09-11.md
# "late births"): the narrow case of G-DEF-7 (which MISSED by handing every
# track born inside the lines an origin, mid-box births from occlusion
# included). The journey labels show the entry-less vehicles that cost the
# no-inference ruling are born AT the mouth - cam5 489-491: tracks born on the
# frame the back tyre crossed, 0.7 box widths past the S line's end, already
# holding a real exit. When ON: a track whose first valid crossing is an EXIT
# (exit_only) entered over the line the ray back along its first second of
# travel hits, if that hit lies within BORN_AT_MOUTH_WIDTHS box widths of its
# birth. The vehicle's own first appearance, not anyone's statistics. OFF.
BORN_AT_MOUTH = _os2.environ.get("BORN_AT_MOUTH", "0") in ("1", "true", "on")
BORN_AT_MOUTH_WIDTHS = 1.0

# THE GRAZED EXIT (2026-10-02, cam5 N_right phantom; operator: lines are
# drawn fine, solve it in software). cam5's upper NB through lane runs
# ALONG the E line and passes above the N line's top end, so through cars
# cross only the E line and the state machine took it as their exit
# (EXITED IS TERMINAL). Measured on the nc2 dumps (runs/cam5_graze/
# measure.py), from the exit crossing to the track's end: real E exits
# travel 13-31 px OUTWARD and 36-107 px along the line; the grazers
# 110-233 px ALONG the line (>= 0.9 of its length) and <= 9 px outward.
# When ON, classify_pair skips an exit after which the track rides its
# own line - along >= EXIT_GRAZE_ALONG_FRAC x the line's length AND
# along >= EXIT_GRAZE_RATIO x outward - and keeps looking for the real
# exit (else the journey is entry_only, resolved downstream).
EXIT_GRAZE_SKIP = _os2.environ.get("EXIT_GRAZE_SKIP", "0") in ("1", "true", "on")
EXIT_GRAZE_ALONG_FRAC = 0.75
EXIT_GRAZE_RATIO = 6.0

# THE LINES ARE THE MOUTHS (operator ruling 2026-09-10 on the gates
# review: "all the lines are where they are intended to be but the
# mouth should be the lines and the exit should be the lines the blue
# dots should not exist"). When ON, every leg with a drawn gate has its
# mouth POINT (legs.origin_zone) and reference_heading DERIVED from the
# line at load time — midpoint, and the direction of travel entering
# over the line — so nothing the software does depends on the dot the
# May recalibration script placed. Legs without a drawn gate keep
# their stored point. G-DEF-2 candidate; default OFF until it passes
# the fleet against 75.70.
MOUTH_FROM_GATE = _os2.environ.get("MOUTH_FROM_GATE", "0") in ("1", "true", "on")
# G-DEF-2 split (2026-09-10): the mouth POINT from the line is his
# ruling; the entry HEADING from the line's perpendicular was the
# agent's assumption and it cost cam1 18-22 points (a line drawn at an
# angle to the lane is not perpendicular to travel). With this OFF the
# heading stays the stored, track-derived value (the recalibration
# script's tail headings) while the point still comes from the line.
MOUTH_FROM_GATE_HEADING = _os2.environ.get(
    "MOUTH_FROM_GATE_HEADING", "1") in ("1", "true", "on")
# G-DEF-2 d4 (2026-09-10): each leg's entry heading measured from the
# window's OWN tracks at the moment they cross the leg's line inward —
# the circular mean of their direction of travel there. True by
# construction on every camera (the perpendicular was wrong on cam1,
# the stored May heading wrong on cam5), derived from raw video plus
# the operator's lines alone. Applied in the pass-2 replay, where the
# dump is in hand; legs with fewer than HEADING_MIN_CROSSINGS inward
# crossings keep their stored heading.
HEADING_FROM_CROSSINGS = _os2.environ.get(
    "HEADING_FROM_CROSSINGS", "0") in ("1", "true", "on")
HEADING_MIN_CROSSINGS = 20
HEADING_VELOCITY_S = 0.5      # d4: direction over +-0.5 s AROUND the crossing
# d5 (2026-09-10): d4 cost cam1 9-11 points — a turning vehicle is
# already turning AT the line, so the direction there is not the
# approach direction the classifier needs (the stored headings came
# from through-traffic tails UPSTREAM of the mouth). HEADING_APPROACH_S
# > 0 measures the direction over the approach segment ending at the
# crossing instead: from HEADING_APPROACH_S before it up to the line.
HEADING_APPROACH_S = 1.5

# THE STRAIGHT-FRAGMENT RULE (operator ruling 2026-09-07): a vehicle
# that never curved cannot be booked as a TURN on a guess. Measured:
# cam1-0700's 111 phantom driveway turns are dead straight (0.975 /
# +1.5 deg, identical to real throughs) and all came from the softmax
# destination fallback with no bank path and no gate crossing. The 5
# deg constant is the measured operating point (collateral: 2 genuine
# rights; at the classifier's 25 deg band it explodes to 65 — never
# reuse that band here). Default OFF until G-SF-1 passes.
STRAIGHT_FRAGMENT_RULE = _os2.environ.get("STRAIGHT_FRAGMENT_RULE", "1") in ("1", "true", "on")
STRAIGHT_FRAGMENT_MAX_NHC_DEG = 5.0
STRAIGHT_FRAGMENT_MIN_STRAIGHTNESS = 0.95
STRAIGHT_FRAGMENT_MIN_POINTS = 10
# Extension (operator's own words: "it doesn't matter what the path
# is"): apply the rule even when the destination came from a bank
# path-fit — cam4/cam5's phantom turns are straight fragments with a
# path alibi (cam4 33->34: 124 events, straightness 0.978, +0.4 deg).
# The 5-deg heading bound remains the genuine-turn protection.
# Default OFF (cam1's shipped basis used the narrow rule).
# DEFAULT ON since 2026-09-11 (G-DEF-4 PASS: fleet 75.86 -> 77.08, cam4
# SB_right 115/125/329 -> 48/24/117 against Mio 22/16/39; the ruled
# specimens were dropped N->S throughs sent into the driveway by a
# path fit whose bank path is a prefix of the through path).
STRAIGHT_FRAGMENT_INCLUDE_PATH_FITS = _os2.environ.get(
    "STRAIGHT_FRAGMENT_INCLUDE_PATH_FITS", "1") in ("1", "true", "on")

# G-EX-2 — THE OBSERVED EXIT BINDS THE JOURNEY (declared 2026-09-12 after
# the d18 verdict, built 2026-09-20). CLAUDE.md's hard constraint says the
# box sides ARE origin/destination gates; the code honours that for a FULL
# journey (GATE_FULL_SUPREMACY) and for an ENTRY-ONLY one (rescue_supports)
# and drops the third case on the floor. A track born past its entry gate
# whose EXIT crossing was observed is tagged exit_only, which means
# gate_origin is None by construction (entry_gates.classify_pair), so the
# rescue block's `gate_origin is not None` guard skips it: origin comes
# from the heading tier, the softmax destination is refused for tail
# motion at the vanishing point, and the whole journey drops as
# insufficient_data.
# Measured on the vl3 basis (scripts/research_exit_only.py, 2026-09-20):
# cam4 study_0700 637 exit_only tracks, 466 (73%) with NO event, 445 of
# them exiting over N; cam4 study_1600 949 / 511 / 458. Against NB_thru
# shortfalls of -360 and ~-460 on those windows. On cam5 study_1100, whose
# cells are already OVER, only 79 of 428 drop and 41 exit over N — the
# population sits where the undercount is and is near-absent where
# inflation would hurt. For contrast `full` tracks drop at 1%.
# When ON, an exit_only track with a non-gate origin binds its destination
# to the OBSERVED exit leg, movement by the cell's applied path label else
# derive_movement — the rescue_full convention verbatim. Two guards:
# never when origin == the exit leg (the exit_only path never runs the
# u-turn admission tests, and a heading-tier origin that happens to equal
# the exit leg would mint the phantom u-turns the first-exit ruling
# killed), and the event bins off start_frame, never the finalize frame
# (problem 7 is already a per-bin dispersion problem).
# Inert by construction below EVIDENCE_ACTIVATION_COVERAGE: the gate
# locals are only bound in evidence mode "on".
# SHIPPED default-ON 2026-09-24 (operator go after arm gx2: "ship it").
# Arm gx2 = this rule + BOUND_CHAIN_CONSERVE on all 12 windows: fleet
# 79.38 -> 83.50 (+4.12), clearing d18b's 80.36 honest test by 3.14; cam4
# +15.20 with every window up ~15; cam2 +1.90; cam3 +0.50; cam5 0.00; FM 51
# held out and identical to control. The G-DEF-1 letter MISSED by 0.20 on one
# clause (cam1 -1.20 against the -1.0 camera bar, no window worse than -1.3
# against the -3.0 bar), shipped on the operator's ruling that a 1.2-point
# camera mean against a 15-point gain is not the failure mode that clause was
# written to stop. Env override X=0 for experiments.
GATE_EXIT_ONLY_BINDING = _os2.environ.get(
    "GATE_EXIT_ONLY_BINDING", "1") in ("1", "true", "on")


# THE FULL-JOURNEY RESCUE (2026-09-25, arm fr1, declared in
# docs/plan_basis_2026-09-11.md before scoring). classify_trajectory reads
# a near-field-to-far-field right turn as a ~142 deg heading change under
# perspective, sends it down the U-TURN branch (>= 135), and the u-turn
# branch's 90 px net-displacement test returns insufficient_data - so
# _finalize_vehicle_data drops a track WITNESSED entering one gate and
# exiting another before gate supremacy (operator ruling 2026-08-24) can
# label it. Measured on the gx2 basis: cam5 W->S (EB right) 99/100/146 a
# window against a 335 shortfall; 1,613 full journeys fleet-wide.
# When ON (and in evidence mode "on"), such a journey with origin != exit
# continues to the gate-supremacy / rescue_full labelling instead of being
# dropped, UNLESS the track doubles back. SHIPPED default ON 2026-10-01
# (operator go after arm fr3 on the ts1 default: fleet +1.83, approach +5.8,
# labels 438 -> 444 of 512 with none worse, FM 51 identical; cam2 16:00
# -3.7 missed the window clause - its far-band W line - shipped by ruling).
FULL_JOURNEY_RESCUE = _os2.environ.get(
    "FULL_JOURNEY_RESCUE", "1") in ("1", "true", "on")
# THE ONE NEW CONSTANT of the rescue (no frozen module draws this line;
# searched 2026-09-25). Dropped full journeys are bimodal in path
# straightness: real turns ~0.41-0.51 (matching the counted journeys of the
# same gate cell, 0.44-0.56), doubling-back ID corruption 0.03-0.07 (the
# through cells, whose counted journeys run 0.98-0.99). 0.25 sits in the
# empty middle. Declared before the arm, not tuned on it.
FULL_RESCUE_MIN_STRAIGHTNESS = float(_os2.environ.get(
    "FULL_RESCUE_MIN_STRAIGHTNESS", "0.25"))

# THE JOURNEY FATE LEDGER (2026-09-20, stage 1 of the triage plan). Every
# track that ends without a counted event lands in ONE `insufficient_data`
# counter today (the fleet log's `dropped=`), which is ~18% of all tracks
# and the reason the UNDERCOUNTS are not diagnosable. vehicle_events
# explains every journey we COUNTED or REJECTED; nothing explains the ones
# that never produced a row. This writes one `track_fates` row per
# finalized track — disposition, reason, place, time — at each of the six
# silent-return sites in _finalize_vehicle_data plus the counted path. It
# is the counting analogue of the tracker's miss log and is DIAGNOSTICS
# ONLY: no vehicle_events column changes and no counter changes meaning,
# so a run with this off is byte-identical in the counts.
# Generalises scripts/cam5_sbinsuf_diag.py, which did exactly this for one
# cell on one camera by monkeypatching the finalize method.
TRACK_FATE_LEDGER = _os2.environ.get(
    "TRACK_FATE_LEDGER", "1") in ("1", "true", "on")

EMERGENCE_GUARD = _os2.environ.get("EMERGENCE_GUARD", "0") in ("1", "true", "on")
CONCEALER_ORIGIN_INHERITANCE = _os2.environ.get(
    "CONCEALER_ORIGIN_INHERITANCE", "0") in ("1", "true", "on")
CONCEALER_REACH_PX = 90.0     # concealer proximity at the newborn's birth
CONCEALER_ALIVE_SLACK_F = 15  # concealer may have died this recently
EMERGENCE_SIZE_FLOOR = 0.35   # veto bound floor as a share of own box
                              # (extent jitter on near-field boxes)

# Identity stack Pillar A (operator ruling 2026-08-24: "the mouth and
# gate infrastructure is not working properly" — queue creep across a
# drawn gate line mints journeys). When on, _gate_evidence voids
# crossings made below the frozen stationary threshold: creep entries
# stop making origins, creep exits stop making destinations. Filters
# EVIDENCE only — census/classify consumers keep calibrated volumes.
# SHIPPED default-ON 2026-08-27 with the G-CP-1 stack (measured +0.4
# solo at G-MQ-1; in the shipped arm).
MOTION_QUALIFIED_EVIDENCE = _os2.environ.get(
    "MOTION_QUALIFIED_EVIDENCE", "1") in ("1", "true", "on")

# DETECTOR HEAD (2026-09-30, docs/research_tracking_2026-09-29.md phase 4a).
# DETECT_DEDUP_HEAD: one-to-many head + class-agnostic NMS at DETECT_DEDUP_IOU
# instead of YOLO26's one-to-one head (which ignores iou= and emits car+truck
# duplicates, 2.40 pairs a frame measured). DETECT_HALF: FP16 on CUDA. Both
# default OFF; a cache built with either is a NEW basis (new variant name).
DETECT_DEDUP_HEAD = _os2.environ.get("DETECT_DEDUP_HEAD", "0") in ("1", "true", "on")
DETECT_DEDUP_IOU = 0.6
DETECT_HALF = _os2.environ.get("DETECT_HALF", "0") in ("1", "true", "on")
# ON-SCREEN ONLY (2026-09-30, docs/research_tracking_2026-09-29.md phase 3;
# operator rulings 2026-09-29 / 09-30): a vehicle's origin, destination and
# movement may come only from what the video shows for THAT vehicle, including
# its own path matched against fitted path templates (allowed), never from how
# common a movement is among other vehicles. When ON: the branch-1 origin and
# dest-tie posteriors weigh candidates by the vehicle's own path shape only
# (no supporting_count); the entry-only rescue by corpus supports is removed;
# a gate-witnessed cell's movement label is the paths' shared label, else the
# legs' geometry, never "the most-supported path". Default OFF pending an arm.
ON_SCREEN_ONLY = _os2.environ.get("ON_SCREEN_ONLY", "0") in ("1", "true", "on")
# THE MOUTH FROM MOTION + COUNT ONCE (arm mm, declared 2026-10-13,
# docs/plan_basis_2026-09-11.md; backend/services/mouth_from_motion.py).
# An unseen entry (exit) line is decided from the car's own motion against
# lane maps of the window's fully seen journeys - waited in a queue zone,
# lane fit, the backward ray, the occluder - never from movement popularity
# (operator 2026-10-13). COUNT ONCE: two counted tracks of one movement that
# reach every spot of their path together are one car. MOUTH_FROM_MOTION
# SHIPPED default ON 2026-10-15 (operator go after arm mm1, mo7 switches:
# fleet 89.06 -> 91.92, labels 445 -> 448 / held-out 271 -> 272, FM 51
# 89.4 / 93.9 -> 92.5 / 100.0; approach 83.54 -> 82.72). COUNT_ONCE stays OFF.
MOUTH_FROM_MOTION = _os2.environ.get("MOUTH_FROM_MOTION", "1") in ("1", "true", "on")
COUNT_ONCE = _os2.environ.get("COUNT_ONCE", "0") in ("1", "true", "on")
LANE_CELL_PX = 10.0          # lane-map cell (the far corner's boxes are 15-30 px)
MOTION_FIT_S = 2.0           # seconds of motion compared against the lanes
MOTION_MIN_FIT = 0.5         # a lane must explain at least half of that motion...
MOTION_MARGIN = 0.2          # ...and beat the next lane by this share
MOTION_WAIT_S = 1.0          # stood still this long at the start = waited
MIN_CLEAN_TRACKS = 5         # a movement needs this many fully seen journeys to have a lane
COUNT_ONCE_HEADWAY_PCT = 5   # percentile of a lane's own car-to-car lags = its minimum headway
COUNT_ONCE_HEADWAY_FRAC = 0.5  # one car only under HALF that: two ids on one car lag ~0 s,
                               # the closest real followers sit AT the minimum (unit test, 2026-10-13)
# THE GLOBAL TRACKLET LINKER (2026-09-30, docs/research_tracking_2026-09-29.md
# phase 2; backend/services/tracklet_linker.py). Joins the pieces a vehicle's
# track broke into BEFORE the journey logic, by one global assignment per
# level (<= 0.5 s, <= 3 s, stopped <= 60 s) with gates in seconds and box
# units, a follower test (a continuation is born where the leader WOULD BE,
# the next car where it WAS), and birth / death costs from the operator's gate
# lines. SHIPPED default-ON 2026-09-30 (operator go "Yes, continue" after arm
# lk2): fleet 80.81 -> 82.68 against the true default control, approach
# 56.83 -> 65.28, vehicle error 4,481 -> 3,995, no camera below -0.05, worst
# window -1.4, FM 51 identical. Shipped EXCLUSIVE and with the stopped level
# OFF (arm lk1 with it on broke cam3: -11.2).
TRACKLET_LINKER = _os2.environ.get("TRACKLET_LINKER", "1") in ("1", "true", "on")
LINKER_LEVEL1_GAP_S = 0.5        # first pass: short breaks only
LINKER_MOVE_GAP_MIN_S = -0.5     # a head may start up to 0.5 s before the tail ends
LINKER_MOVE_GAP_MAX_S = 3.0      # moving breaks up to 3 s (the occlusion scale)
# THE THEFT SPLIT (2026-10-01, item 5; docs/plan_basis_2026-09-11.md "ITEM 1"):
# the journey labels' identity thefts are smooth far-field hand-offs - a track
# follows a car driving away until its box is 12-20 px and nearly still, then
# carries on with a car coming the other way (cam2 t831, cam5 t386/t393,
# cam3 t471). No position jump, so per-frame guards miss them (rg2). A real
# vehicle does not slow to a stop and come back the way it went (a U-turn
# turns through a curve while moving). When ON, the linker first cuts a track
# where a sustained run of movement is followed, across only slow samples, by
# a sustained run the opposite way, at a turning point whose box is clearly
# smaller than both runs'. Sampled every THEFT_SAMPLE_S; speed in box widths
# per second (scale- and frame-rate-free). SHIPPED default ON 2026-10-01
# (operator go after arm ts1: journey labels 433 -> 438 of 512 with none
# worse, FM 51 identical, fleet +0.14; cam1's camera mean -2.10 missed the
# letter's -1.0 clause, shipped by ruling as gx2 was).
THEFT_SPLIT = _os2.environ.get("THEFT_SPLIT", "1") in ("1", "true", "on")
THEFT_SAMPLE_S = 0.5
THEFT_MOVE_WPS = 1.0          # moving = at least 1 box width per second
THEFT_RUN_S = 1.0             # each run lasts at least 1 s ...
THEFT_RUN_BOXES = 2.0         # ... and travels at least 2 box widths
THEFT_REVERSE_DEG = 135.0     # the two runs' headings differ by more than this
THEFT_TURN_SIZE_FRAC = 0.7    # turning-point box <= this x each run's median box
LINKER_OVERLAP_MAX_S = 0.5       # coexisting pieces are two vehicles beyond this
LINKER_OVERLAP_MAX_FRAC = 0.2    # ... or beyond 20% of the shorter piece
LINKER_RESID_BASE = 1.0          # box units: prediction residual gate at gap 0
LINKER_RESID_PER_S = 1.5         # box units per second of gap
LINKER_SIGMA_BASE = 0.5          # box units: residual scale in the link cost
LINKER_SIGMA_PER_S = 0.5
LINKER_FOLLOWER_RATIO = 0.5      # head nearer the leader's death point than half its
                                 # prediction residual (leader moved >= 1 box) = follower
LINKER_STOP_DIST_BOXES = 1.0     # stopped: re-born within 1 box of the same spot
LINKER_MIDBOX_COST = 6.0         # cost of a piece ending / starting mid-box
# THE NO-CROSSING SIDE DOOR (2026-09-26, arm nf1, declared in
# docs/plan_basis_2026-09-11.md before scoring). A track that crossed no
# gate and that the joint shape scorer refused is still given a destination
# by the nearest-line fallbacks (score_destination_by_polyline, then the
# softmax scorer). Traced on cam5 study_1600: 12 of 12 far-field NB stubs
# get "left" from the polyline fallback because the applied left path starts
# at x ~ 536 and the through path at x ~ 508, and the stubs live upstream of
# 508. When ON (evidence mode "on" only), such a track gets no destination
# and drops, the rescue block's own rule. NO NEW CONSTANTS.
# SHIPPED default ON 2026-09-30 (operator go after arm nf1b on the linker
# default: fleet 82.68 -> 86.87, approach +9.0, FM 51 identical; journey
# labels: phantoms 47 -> 25, real cars 434 -> 433).
NOCROSS_NO_FALLBACK = _os2.environ.get(
    "NOCROSS_NO_FALLBACK", "1") in ("1", "true", "on")
# arm nc1 tied (fleet -0.07): dropping every no_crossing count removes real
# near vehicles as often as doubles. In the audit the two differ by SIZE: the
# 14 doubles and 3 off-intersection tracks had median box widths 11-56 px
# (14 of 17 <= 30 px), the 10 correct ones 33-102 px. When ON (arm nc2), a
# no_crossing track is dropped only when its median box width is under
# NOCROSS_SMALL_FRAC of the frame width (30 px at 640). SHIPPED default ON
# 2026-10-01 (operator go after arm nc2: fleet +0.22, approach +1.5, labels
# +1/-0, FM 51 identical).
NOCROSS_DROP_SMALL = _os2.environ.get("NOCROSS_DROP_SMALL", "1") in ("1", "true", "on")
NOCROSS_SMALL_FRAC = 0.05
# C2 — coexisting-twin dedup: two simultaneous tracks on ONE vehicle
# (operator scenes 1-2; measured anatomy: overlapping spans, boxes
# riding together frame-by-frame), both minting events. Event-level
# identity test in pass-2; write-then-reject.
COEXISTING_TWIN_DEDUP = _os2.environ.get(
    "COEXISTING_TWIN_DEDUP", "1") in ("1", "true", "on")

APPLY_GATE_HEADROOM = 0.03    # incumbent must under-claim vs census by >= this
APPLY_GATE_FLOOD_MAX = 0.15   # candidate per-cell excess mass / census cap
APPLY_GATE_SATURATION = 0.25  # confusion contrast ceiling (shared w/ demotion)
# CENSUS ADEQUACY (the FM51 held-out finding, 2026-08-07). Every guard above
# reads the gate-evidence census as the window's volume ENVELOPE. That is a
# PRECONDITION, not a given: at FM51 the entry gates barely engage (blind
# evidence coverage 0.031/0.012 vs the corridor's 0.43-0.49 and the shipped
# 0.45 activation bar), so the census saw 21% of counted traffic in one
# window and NOTHING in the other. Bound measured, not tuned: the corridor's
# 12 validation windows sit at incumbent/census -11.9%..+4.7%, FM51 at +371%
# — a 20x gap either side of this bound.
APPLY_GATE_MAX_OVERCLAIM = 1.0
# When the census cannot adjudicate (degenerate or absent) AND an incumbent
# table exists the gate FAILS CLOSED: its contract is that every apply WINS its
# window, and an unmeasurable window cannot be won, so the incumbent stands and
# the operator decides (disposition 'force_once'). Fresh windows apply at rule 1.


def get_processing_mode_config(mode: str | None) -> dict:
    """Return the config dict for `mode`, falling back to default on unknown."""
    if mode and mode in PROCESSING_MODES:
        return PROCESSING_MODES[mode]
    return PROCESSING_MODES[DEFAULT_PROCESSING_MODE]

# Classification mapping (pedestrians out of scope for v2 per PRD)
# 8 = the fine-tuned head's NATIVE articulated class (plan_articulated_native
# 2026-07-17). COCO 8 is "boat", which no code path ever requests, so the id
# is free in every cache/dump this app has written; it must stay OUT of the
# stock-model class filter (detector.RELEVANT_CLASSES excludes it).
NATIVE_ARTICULATED_CLASS_ID = 8
# finetune_v2 scheme (plan_finetune_v2_retrain_2026-07-20): ft classes 2
# (long single-unit) and 3 (medium) both ride this synthetic id to
# single_unit_truck / FHWA 5 -> the Miovision Mediums bucket, bypassing the
# aspect branch (it was built for COCO-7 boxes and buries these). COCO 9 is
# traffic light — never a vehicle id, so the namespace is free.
NATIVE_SINGLE_UNIT_CLASS_ID = 9
VEHICLE_CLASSES = {2: "car", 3: "motorcycle", 5: "bus", 7: "truck",
                   NATIVE_ARTICULATED_CLASS_ID: "articulated_truck",
                   NATIVE_SINGLE_UNIT_CLASS_ID: "single_unit_truck"}

# Trajectory classification thresholds (degrees)
TRAJECTORY_THROUGH_MAX_ANGLE = 25
TRAJECTORY_TURN_MIN_ANGLE = 35
TRAJECTORY_TURN_MAX_ANGLE = 135
TRAJECTORY_UTURN_MIN_ANGLE = 135
# Env-overridable since 2026-09-11 for the G-DEF-8 step-2 sweep on the
# large basis (the floors that decide which short tracks count at all;
# the detector population sits right on them). Defaults unchanged.
TRAJECTORY_MIN_POINTS = int(_os.environ.get("TRAJECTORY_MIN_POINTS", "5"))
TRAJECTORY_MIN_DISTANCE_PX = float(_os.environ.get("TRAJECTORY_MIN_DISTANCE_PX", "50"))
TRAJECTORY_CURVATURE_THRESHOLD = 40  # cumulative curvature tiebreaker for ambiguous zone
# A real U-turn vehicle traverses the intersection and ends a meaningful distance
# from where it entered. A trajectory that classifies as a U-turn (>=135° net
# heading change) but ends very close to its start, having looped through a large
# cumulative arc, is a TRACKING ARTIFACT (ID-switch / coasting doubling back), not
# a vehicle — at the Sunnyvale cam1 these phantom U-turns were 20/30min vs ~0
# real. Gate on net (start->end) displacement, NOT path arc length.
TRAJECTORY_UTURN_MIN_NET_DISPLACEMENT_PX = 90

# Tracker tuning — ByteTrack defaults are 0.25 / 0.8 / 30 fps with
# track_buffer=30 frames. We bump track_buffer to 5s (150) so brief
# occlusions don't kill tracks, but the match/activation thresholds
# stay at defaults — match_thresh is a DISTANCE gate (1-IoU), so
# lower values are STRICTER, not looser. Setting it to 0.3 (as we
# previously did, misreading the semantics) required IoU>=0.7 every
# frame and silently dropped tracks the instant a vehicle moved any
# meaningful distance.
TRACKER_LOST_BUFFER = 150            # frames before dropping track (5s @ 30fps; ByteTrack default 30)
TRACKER_MATCH_THRESHOLD = 0.8        # ByteTrack default — IoU>=0.2 matches (loose)
TRACKER_ACTIVATION_THRESHOLD = 0.25  # ByteTrack default — confirms tracks for conf >= 0.25
# Score fusion in the first association (2026-09-12, cam4 NB census):
# supervision's ByteTrack multiplies IoU by the detection confidence before
# the match, so the effective overlap bar is 0.2 / conf — at conf 0.63 an
# overlap of 0.32, at 0.4 an overlap of 0.5. A big box receding at 10 fps
# sits at 0.25-0.4 and is refused although the detector is sure of it
# (cam4 1600: 180 of 241 mid-frame deaths of the nearest-lane NB tracks,
# scripts/probe_cam4_nb_death_point.py). The original ByteTrack has this
# fusion switchable (its MOT20 mode); boxmot's BoT-SORT, which cams 1-3
# run, does not fuse by default. TRACKER_FUSE_SCORE=0 turns the fusion
# off for the default (supervision ByteTrack) recipe. Default ON = the
# shipped behaviour until an arm passes the letter.
TRACKER_FUSE_SCORE = _os.environ.get("TRACKER_FUSE_SCORE", "1") in ("1", "true", "on")
# Position recovery, stage 2.5 of the default (supervision ByteTrack) recipe
# (2026-09-12, cam4 NB research, docs/plan_basis_2026-09-11.md "Why the
# tracker breaks"). Each near-lane vehicle's detection chain is continuous
# (24 hits) but the tracker splits it into 1-3 tracks with gaps, 562 of 636
# breaks in the far field where the box is ~29 px: consecutive real boxes
# overlap only 0.50 at 10 fps, the Kalman prediction 0.41 (the filter is
# stiff at small size), and the next real box is refused by IoU x conf
# (stage 1) or by IoU 0.5 for a weak box (stage 2). The stage takes the
# tracks still unmatched after stage 2 (tracked AND lost) and the detections
# still unmatched (high AND low, conf >= 0.10), and pairs them greedily by
# centre distance in BOX UNITS: distance / max(widths) < REACH, sizes within
# SIZE_RATIO. Births unchanged; recovered boxes never seed a new track.
# The census's linker with exactly this rule holds every vehicle as one
# chain. Default OFF until the fleet arm (d18) passes the letter.
# 2026-09-12 (operator: "improving the engineering of the tracker", not a
# switch): the stage IS the default backend's behaviour. Env X=0 is the
# experiment override, like every other rule. Production dumps are re-tracked
# only when the operator says so.
TRACKER_POSITION_RECOVERY = _os.environ.get(
    "TRACKER_POSITION_RECOVERY", "1") in ("1", "true", "on")
TRACKER_RECOVERY_REACH = 0.9        # box widths
TRACKER_RECOVERY_SIZE_RATIO = 0.3   # min(w)/max(w) below this = not the same box
# d18 (2026-09-12) MISSED: recovering boxes that no longer OVERLAP the
# prediction steals neighbours (FM51 0700: 10-11% of such recoveries were
# two-vehicle merges vs 3% of those overlapping > 0.2; cam4 1600: 19-20%
# vs 3%). The recovered box must still overlap the predicted box by at
# least this IoU — the same geometric bar stage 1 uses (match 0.8), only
# without the confidence fusion and without stage 2's 0.5 for weak boxes.
# 0 disables the gate (d18's behaviour).
TRACKER_RECOVERY_MIN_IOU = 0.2
# Confirmation by position (2026-09-12): a just-born track must be matched
# again on the very next frame by IoU x conf >= 0.3 or it is removed, and it
# is never offered a weak box. A vehicle entering over the frame edge is a
# clipped strip one frame and a full box the next (IoU ~0.2 despite the same
# width), so it is born and killed frame after frame: 70 of cam4 1600's 469
# near-lane vehicles never got a track although 86% had two or more
# consecutive confident boxes. An unconfirmed track unmatched by the library
# pass is offered the remaining boxes (any conf >= 0.10) that overlap it at
# all and keep its width within WIDTH_RATIO. 0 disables.
TRACKER_CONFIRM_BY_POSITION = _os.environ.get(
    "TRACKER_CONFIRM_BY_POSITION", "1") in ("1", "true", "on")
TRACKER_CONFIRM_WIDTH_RATIO = 0.5
# Motion-state reset (2026-09-12): supervision's Kalman filter carries aspect
# and height velocities; one violent shape change launches them and the
# predicted box balloons (2x the real width at 60% of cam4 1600's remaining
# breaks after confirmation was added). A confirmation by position always
# restarts the state from the full box; a recovery whose box width differs
# from the prediction by more than this factor does too. 0 disables.
TRACKER_REINIT_WIDTH_JUMP = 1.5
# Lost-track patience for position recovery, in SECONDS (fps-invariant):
# the census linker's 5 frames at 10 fps. Older lost ids are left to the
# library's own stage-1 re-find (IoU x conf); recovering them by position
# handed stale ids to following vehicles (FM51 0700: 246 -> 573).
TRACKER_RECOVERY_LOST_PATIENCE_S = 0.5
# The same patience in FRAMES (2026-10-09, arm pf1; 0 = off, the seconds rule
# stands). The newborn-claim census (scripts/research_recovery_guard.py) found
# that on the 25 fps camera (cam2, where 0.5 s = 12 f) about half of the wrong
# lost-track recoveries (emergence / first car ends / theft by the chains) come
# after 6-12 lost frames, against 5-6% of the same-car ones; on the 10 fps
# cameras the seconds rule already caps at 5 f. Under test, not the default.
TRACKER_RECOVERY_LOST_PATIENCE_FRAMES = int(_os.environ.get("TRACKER_RECOVERY_LOST_PATIENCE_FRAMES", "0"))
# THE SAME-CAR CHECK (2026-10-10, arm av1; docs/plan_basis_2026-09-11.md "STAGE 2"; 0 = off).
# Per frame, a track whose prediction has another box within NEAR_W box widths may
# only take a box that looks like its own car: cosine distance between the box's
# car-verifier embedding (backend/services/vehicle_verifier.py, trained label-free on
# the footage) and the mean of the track's last MEM_S of boxes <= THRESH. THRESH is
# the verifier's 1%-of-same-car point on the journey labels' side-by-side test
# (verifier_v1_all: 0.482). Needs the per-box embeddings (<variant>.ver1/ sidecar,
# scripts/build_appearance_sidecar.py --model ver1); pass 1 from cache only.
TRACKER_APPEARANCE_VETO = _os.environ.get("TRACKER_APPEARANCE_VETO", "0") == "1"
TRACKER_APPEARANCE_THRESH = float(_os.environ.get("TRACKER_APPEARANCE_THRESH", "0.482"))
TRACKER_APPEARANCE_NEAR_W = 2.0
TRACKER_APPEARANCE_MEM_S = 0.5
# RETIRE THE TWIN (2026-10-11, arm dt1; docs/plan_basis_2026-09-11.md "ARM dt1 DECLARED"; 0 = off).
# Two confirmed tracks that both took a box this frame, the smaller box at least CONTAIN inside the
# larger and IoU >= IOU, for FRAMES consecutive frames, are two ids on one car (measurement rd1: the
# "twin" behind 27-39% of cam2's wrong switches): the one holding the larger box is retired.
TRACKER_TWIN_RETIRE = _os.environ.get("TRACKER_TWIN_RETIRE", "0") == "1"
TRACKER_TWIN_CONTAIN = 0.9
TRACKER_TWIN_IOU = 0.4
TRACKER_TWIN_FRAMES = 3
# which of the two is retired: "larger" (the larger box, arm dt1) or "younger" (the later-born id, arm dt2)
TRACKER_TWIN_RETIRE_WHICH = _os.environ.get("TRACKER_TWIN_RETIRE_WHICH", "larger")
# with "younger": which nested births are deferred - "all" (any box nested in a held box, arm dt2) or
# "rebirth" (only inside a track that retired a twin within REBIRTH_S - the re-birth cycle, arm dt3)
TRACKER_TWIN_NESTED_BIRTH = _os.environ.get("TRACKER_TWIN_NESTED_BIRTH", "all")
TRACKER_TWIN_REBIRTH_S = 1.0
# Recovery guards (Phase B thefts, 2026-09-15). The theft reel ruled that every
# filmed position recovery onto a NEIGHBOUR's weak box was a theft (3 of 3)
# while every ordinary-stage match filmed was right. The census
# (scripts/research_recovery_guard.py) found no per-frame gate that separates
# thefts from good recoveries cleanly, so two candidates were built as knobs
# and judged by re-tracking cam4 1600 / cam5 1600 / FM51 0700 against the
# chain yardstick (ledger: docs/plan_basis_2026-09-11.md "Arms rg1 / rg2 / rg3").
#  HELD_IOU (DEFAULT 0.6, the tracker's behaviour): refuse a box that overlaps,
#    by at least this IoU, a box some other track already took this frame by
#    the ordinary stages - the neighbour's second box. Re-tracked: thefts
#    107 -> 83 / 221 -> 196 / 23 -> 18, one-track vehicles +53 / +118 / +16,
#    breaks -128 / -360 / -59, twin hand-offs 202 -> 121 / 557 -> 329 /
#    139 -> 97. Better on every measure on every site. 0 = off (experiment).
#  REVERSE_DEG / REVERSE_JUMP (DEFAULT OFF): refuse a box that lies >= JUMP
#    box widths from the track's last observed box in a direction more than
#    DEG degrees off the track's observed motion. At 90 deg / 0.15 it removed
#    a few more thefts but broke far more tracks (breaks +235 / +542 / +49);
#    the backward jumps it refuses are mostly a slow vehicle's own box
#    jitter. Kept as a knob for the record, not the default.
TRACKER_RECOVERY_HELD_IOU = float(_os.environ.get("TRACKER_RECOVERY_HELD_IOU", "0.6"))
# Kalman velocity process noise (2026-09-19, the miss log): supervision's filter
# lets the velocity change by std_weight_velocity x box height per frame - 1/160,
# the 30-fps pedestrian default. At 10 fps a vehicle whose pixel speed keeps
# growing (approaching the camera) is followed at a fifth to a half of its
# speed (research_breaks.py: the car moved 0.55-1.22 widths a frame where the
# filter said 0.21-0.67), and the prediction then overlaps the next box too
# little for any stage. This is that weight, a fraction of box height per
# frame; 1/160 = the library. Re-tracked and scored on the chains (ledger
# "Arms vl1-vl5"): every measure improves with the weight on all three sites,
# the knee at 1/40 on cam4 and 1/20 on cam5 / FM51; at 1/20 (DEFAULT) against
# 1/160: one-track 4241/3738/1168 -> 4422/3952/1249, breaks 2918/4057/766 ->
# 2547/3637/624, thefts 83/196/18 -> 73/149/13 (a prediction that keeps up
# with its own car overlaps the neighbour's box less). Env override for
# experiments; 1/160 reproduces the library.
# FRAME-RATE AWARENESS (2026-09-29, operator: "The software should be auto tuned
# based on the frame rate of the film"). Every per-FRAME constant in the tracker
# and pass 2 was validated on 10 fps cameras (cam1, cam3, cam4, cam5, FM 51);
# cam2 is 25 fps, and on the new-site tracker it scored 64.40 against its old
# recipe's 75.37. When ON, those constants are converted to the video's own frame
# rate: frame counts become (frames at FPS_REFERENCE) x fps / FPS_REFERENCE, and
# the Kalman velocity noise (a per-STEP quantity) is multiplied by
# (FPS_REFERENCE / fps) ** FPS_KF_POWER. At 10 fps every factor is exactly 1, so
# the validated cameras are byte-identical by construction. FPS_KF_POWER is the
# open modelling question (1 = linear in the step, 2 = quadratic), settled by
# the cam2 test, not by argument. Default OFF.
FPS_AWARE = _os.environ.get("FPS_AWARE", "0") in ("1", "true", "on")
FPS_REFERENCE = 10.0
FPS_KF_POWER = float(_os.environ.get("FPS_KF_POWER", "1"))


def fps_frames(frames_at_reference: float, fps: float) -> int:
    """A frame count validated at FPS_REFERENCE, expressed at `fps` (same real
    time). Identity when FPS_AWARE is off or fps == FPS_REFERENCE."""
    if not FPS_AWARE or not fps:
        return int(frames_at_reference)
    return int(round(float(frames_at_reference) * float(fps) / FPS_REFERENCE))


TRACKER_KF_VEL_STD = float(_os.environ.get("TRACKER_KF_VEL_STD", str(1.0 / 20)))
TRACKER_RECOVERY_REVERSE_DEG = float(_os.environ.get("TRACKER_RECOVERY_REVERSE_DEG", "0"))
TRACKER_RECOVERY_REVERSE_JUMP = float(_os.environ.get("TRACKER_RECOVERY_REVERSE_JUMP", "0.15"))
# Edge exit (2026-09-12): a track whose last observed box touches the frame
# edge while it was moving toward that edge has driven out of the picture;
# it is removed at the Tracked -> Lost transition instead of waiting 5 s as a
# lost id at the edge. FM51 0700: 133 of 200 stale-id steals were by ids last
# seen touching the right edge (the next vehicle leaving through the same
# spot inherited the id). Needs the video's frame size: pass 1 and the live
# pipeline read it from the videos row; without it the rule does nothing.
TRACKER_EDGE_EXIT = _os.environ.get("TRACKER_EDGE_EXIT", "1") in ("1", "true", "on")
# Double-box suppression at the tracker's input (2026-09-12). YOLO26 is
# NMS-free and emits stacked double boxes of either class. Measured
# (scripts/research_dup_boxes.py): pairs above 0.8 IoU are ONE vehicle 99-
# 100% of the time on cam4, cam5 and FM51 (they never separate within +-1 s);
# 0.6-0.8 is two vehicles 2-14% of the time, 0.45-0.6 up to 33%. So the input
# step removes only > 0.8 pairs, any class; 0 disables. Independent of
# PRE_TRACK_NMS_IOU (class-agnostic at the pipeline level, off).
TRACKER_DUP_BOX_IOU = 0.8
# Stacked-box guard (2026-09-12): below the 0.8 input dedup, a box stacked on
# a box a track already holds this frame (IoU > 0.6) is that vehicle's double
# box 86-98% of the time. Such a box neither confirms a newborn by position
# nor starts a new track; a genuinely occluded vehicle is born once it
# separates. 0 disables.
TRACKER_STACK_IOU = 0.6
# Weak-box births (2026-09-12, docs/plan_basis_2026-09-11.md "Sizing the
# remaining classes"): a distant or partly hidden car's boxes stay under the
# birth bar (activation + 0.1 = 0.35) for 0.5-1.5 s — cam5 1600: 12% of
# vehicles start >= 0.5 s late, FM51 0700: 27%; the hand-off reel's clip 5
# (a car hidden in a queue, conf 0.10-0.33 for 1.5 s). The recovery tracker
# keeps those weak boxes as tentative histories linked by its position rule.
# Inheritance: the track born from the car's first confident box takes the
# history as back-fill (no new tracks). Promotion (_PROMOTE): a tentative
# that held together _PERSIST_S and moved _MIN_MOVE box widths, and whose box
# does not lie inside a held vehicle (_MAX_COVER), becomes a track. Needs
# TRACKER_POSITION_RECOVERY. _GAP_S stays under the 0.5 s stop-fracture grace;
# _HISTORY_S stays far under the 90 s pass-1 resume warm-up.
TRACKER_WEAK_BIRTH = _os.environ.get("TRACKER_WEAK_BIRTH", "1") in ("1", "true", "on")
# Promotion OFF by default (2026-09-12, measured): on cam4 / FM51 / cam5 it
# trims late births by ~1 point over inheritance alone but costs one-track
# vehicles (-2 / -3 / -30) and adds breaks (+5 / +12 / +80) — a car promoted
# from weak boxes tends to lose that id when its confident box arrives. Back
# on once that continuity is fixed. Inheritance (no new tracks) stays on.
TRACKER_WEAK_BIRTH_PROMOTE = _os.environ.get(
    "TRACKER_WEAK_BIRTH_PROMOTE", "0") in ("1", "true", "on")
TRACKER_WEAK_BIRTH_PERSIST_S = 0.5
TRACKER_WEAK_BIRTH_GAP_S = 0.2
TRACKER_WEAK_BIRTH_MIN_MOVE = 0.5
# the share of a weak box lying inside a held vehicle's box above which it is
# that vehicle's double/part box. Not lower: two equal boxes at IoU 0.2 (the
# ruled clip-5 queue car beside its neighbour) already cover 0.33; the
# doubles live above IoU 0.45 (research_dup_boxes.py), i.e. cover >= ~0.6.
TRACKER_WEAK_BIRTH_MAX_COVER = 0.6
TRACKER_WEAK_BIRTH_HISTORY_S = 10.0
# ... and the same reset applies to the library's own stage-1/2 matches (a
# confident match whose box width jumps > 1.5x against the prediction), and
# the recovery gate also accepts overlap with the LAST OBSERVED box, so a
# drifted prediction cannot hide a continuation (remaining cam4 1600 breaks:
# prediction-to-next IoU 0.16 while real-to-next was 0.32).

# Origin assignment
ORIGIN_ASSIGN_MIN_FRAMES = 2   # trajectory points needed before assigning origin

# Half-length of the synthesized tripwire built from a single calibrated
# origin point (perpendicular to reference_heading, extending each way).
# 40 px was too short for legs whose origin sits near a frame edge —
# vehicles entering from those approaches are often first detected by
# YOLO at positions past the short tripwire's extent, missing it
# entirely and falling to the heading-fallback path. 120 px gives more
# lateral coverage; the line-crossing math still only matches actual
# trajectory segments, so we don't pick up spurious crossings outside
# the image.
TRIPWIRE_HALF_LENGTH_PX = 120

# Origin Tier-2 (heading fallback) leg-label blocklist. Heading-only
# attribution has a wide angular basin (<=90 deg from leg ref_heading) so
# a low-volume leg whose ref_heading sits between two main legs can
# silently absorb cross-leg traffic. At Sunnyvale this is the private
# driveway (L24) attracting 596 phantom heading-fallback events. Any leg
# whose label contains one of these keywords is excluded from heading
# fallback; polyline + tripwire tiers still attribute to it normally.
HEADING_FALLBACK_EXCLUDE_LABEL_KEYWORDS = ("Driveway",)

# Origin Tier-0 (polyline) heading-consistency gate. A polyline match is
# accepted only if the polyline's averaged first-3-segments bearing is
# within this many degrees of the track prefix's averaged first-3-segments
# bearing. Eliminates cross-leg coincidental spatial matches where a
# trajectory happens to score low against a polyline whose road points
# in a different direction.
ORIGIN_POLYLINE_HEADING_GATE_DEG = 25.0

# --- Attribution v2: joint partial-Fréchet scorer (2026-05-27) -------------
# When enabled and the camera has calibrated paths, a single joint scorer
# (score_path_joint) runs at finalization and reads origin + destination +
# movement off the best-matching path's SUB-CURVE, replacing the separate
# Tier-0 origin (entry-tangent) + Tier-0 destination polyline scorers and the
# Stage A gates above. The old scorers remain as the automatic fallback when
# the joint scorer returns no confident match, and the early _assign_origin
# tiers still gate "is this a real intersection vehicle". See
# docs/implementation_plan_accuracy_2026-05-27.md. Tunables below are starting
# values; tune on the replay harness against B0_baseline once trajectories are
# regenerated (the original 9,785 were deleted; only ~144 remain).
USE_JOINT_PARTIAL_FRECHET_SCORER = True
# Cost metric for the sub-curve match. "dtw_mean" = robust mean coupled distance
# (default); "frechet" = classic sup-norm discrete Fréchet. We use dtw_mean
# because pure Fréchet is a sup norm that a single jittery tracking point spikes:
# on the real Sunnyvale trajectories best-match Fréchet ran ~82 px median, while
# the (true-mean) dtw_mean runs ~29 px median — close to the scale the proven
# Stage A mean-perpendicular destination scorer (20 px one-way radius) used.
# Default flipped to "mdh" (Phase 2.3, 2026-06-11): fragmentation-robust
# min-directed-Hausdorff + tail-angle + exit-proximity. Corridor A/B under
# identical banks/recipes: cam1 19.4->18.4, cam2 AM 15.8->13.4 and HELD-OUT PM
# 21.6->18.9, cam4 22.5->14.7 (gross 26.0->18.8), cam5 flat; only cam3
# regressed (+1.1 net, gross flat) and is pinned to dtw_mean via its
# per-camera calib_cost_metric override. Env override for per-run sweeps.
JOINT_SCORER_COST_METRIC = _os.environ.get("JOINT_SCORER_COST_METRIC", "mdh")
# Calibrated on the surviving 144-event sample (median ~29 px, ~60% match at 35);
# RE-TUNE against B0_baseline once the full trajectory set is regenerated.
JOINT_SCORER_MAX_COST_PX = 35.0        # reject matches whose mean coupled distance exceeds this
# Deliberately LOW: a mid-turn entry (the failure mode this scorer rescues)
# covers only the path suffix (~0.40-0.55 of arc length), so a high floor would
# reject exactly those tracks. Keep this just high enough to kill tiny-fragment
# matches; lean on the soft coverage term (weight below) + max_cost for quality.
JOINT_SCORER_MIN_COVERAGE_FRAC = 0.28  # hard floor on matched sub-curve arc-length fraction
JOINT_SCORER_TAIL_WINDOW = 7           # tail points used for the exit-direction prior
JOINT_SCORER_TAIL_WEIGHT = 0.35        # blend weight of tail prior vs shape cost
JOINT_SCORER_COVERAGE_WEIGHT = 0.15    # blend weight of coverage term
# Strict gate for TURN-labelled paths only (left/right/u_turn): a turn path may
# claim a track only if the track's tail aligns with the turn's exit tangent
# (tail_prior >= floor) AND it covers enough of the turn arc. Stops straight
# through trajectories from shape-matching a turn polyline's sub-curve and being
# mislabelled as turns. See docs/turn_attribution_plan_2026-05-29.md.
JOINT_SCORER_TURN_TAIL_PRIOR_FLOOR = 0.85
JOINT_SCORER_TURN_MIN_COVERAGE = 0.40

# Origin-rewrite gate (snap-magnet defence, 2026-06-02). The joint scorer READS
# origin off the winning path, which lets a straight "turn" polyline capture a
# THROUGH track and rewrite its origin to a leg the track never entered from
# (the cam4 EB-left magnet: manual 6, attributed 214). This gate rejects a TURN
# match that would rewrite origin to a leg that is NOT the nearest origin-zone to
# the track's first point — BUT ONLY when the trajectory is itself geometrically
# straight (a through). Real turns curve, so a genuine mid-turn-FOV-entry turn
# (the joint scorer's raison d'être at cam1) stays BELOW the straightness floor
# and is spared. Self-limiting and data-driven — no per-camera flag needed.
# Validated on the snap-magnet replay (scripts/replay_snapmagnet.py): cam4
# 22.7%->7.0% net, cam1/cam2/cam3 unharmed. See memory
# project_accuracy_snap_magnet_mechanism.
ORIGIN_REWRITE_GATE_ENABLED = True
ORIGIN_REWRITE_GATE_STRAIGHTNESS = 0.97  # only gate tracks at/above this straightness

# Entry-tiebreak for shared-exit collinear path pairs (2026-07-02). Under the
# mdh cost metric two paths that MERGE to the same exit and run collinear near
# it are indistinguishable to min-directed-Hausdorff: the min-relaxation that
# makes mdh fragment-robust discards the one signal that separates them, the
# ENTRY. cam2 is the exemplar — SB-thru (27->29) and EB-right (28->29) share the
# leg-29 exit (1 px), run 11 px apart, but their entries are 171 px apart; mdh
# sees ~11 px = "same shape", so a real SB-thru track matches the EB-right path
# and its origin is rewritten SB->EB (EB +25% over / SB -11% under, a ~700-veh
# swap; a second pair does the same at the leg-26 exit). This targeted tiebreak:
# when the top match has a collinear rival that SHARES its exit AND whose entry
# is well separated, re-pick by which candidate's ENTRY is closest to the
# track's first point. It is a RELATIVE tiebreak between two already-collinear
# candidates, never an absolute entry->origin estimate (that fails here — the
# FOV clips approaches, which regressed cam2 14.4->23.5 when tried globally),
# fires only under mdh (dtw cameras like cam3 can never trigger it, so they are
# byte-identical), and overrides the mdh winner only on a decisive entry margin.
# See docs/handoff_2026-07-02_session_end.md + memory
# project_per_approach_attribution_2026_06_30.
#
# DISPROVEN 2026-07-02 (kept OFF; scaffolding retained for a non-entry retry).
# Full-chain replay REGRESSED cam2: EB 33.2->41.0, SB 12.3->15.8, 747 firings.
# Birth diagnostic (scripts/diagnose_cam2_entry.py) shows why: SB tracks are 84%
# born near the SB entry, so births DO discriminate — but the tiebreak by
# construction only fires when the entry DECISIVELY favors the rival, which
# selects exactly the misleading ~16% of genuinely-SB tracks born mid-approach
# (past the far-edge SB bank entry, drifting toward the central EB entry pixel).
# It is a biased sampler of its own worst cases: it can't move the real overcount
# (EB-attributed tracks are 87% EB-near) and corrupts the SB tracks it touches.
# The cluster detection (shared-exit + collinear) is sound and reusable; only the
# entry DISCRIMINATOR is dead here. A speed/curvature discriminator is the retry.
ENTRY_TIEBREAK_ENABLED = False
ENTRY_TIEBREAK_EXIT_PX = 15.0           # top & rival exit points within this = "shared exit"
ENTRY_TIEBREAK_COLLINEAR_PX = 15.0      # min-directed dist between the two paths below this = collinear
ENTRY_TIEBREAK_MIN_ENTRY_SEP_PX = 60.0  # only fire when the two ENTRIES are at least this far apart
ENTRY_TIEBREAK_DECISIVE_PX = 30.0       # override the mdh winner only if the rival's entry is this much closer

# Speed-tiebreak (2026-07-02) — the retry after the ENTRY tiebreak was disproven.
# Same shared-exit collinear cluster (reuses ENTRY_TIEBREAK_EXIT_PX/COLLINEAR_PX),
# but splits the pair by the track's PIXEL SPEED (median inter-point step) vs each
# candidate path's `expected_speed` signature. Speed is a per-approach signature
# mdh does NOT use and FOV-clipping does NOT corrupt (diagnostic: cam2 SB approaches
# ~5 px/step, EB ~1-2, Cohen's d~2-2.8; and it leans the RIGHT way on the exact
# tracks entry got wrong). Overrides the mdh pick only when the track's speed is
# DECISIVELY closer to a collinear rival whose signature differs enough to
# discriminate. Blind-deployable: `expected_speed` is computed from a path's
# SUPPORTING TRACKS at bank-build time (NOT Miovision) — so this is INERT until the
# bank carries it (live banks don't yet; the replay harness augments for the A/B).
# See scripts/diagnose_cam2_speed*.py + memory project_per_approach_attribution_2026_06_30.
#
# PER-CAMERA, NOT global (1/3/4/5 regression sweep 2026-07-02). Validated
# NET-POSITIVE on cam2 (EB 33.2->28.8, SB 12.3->10.8, 392 fires) and cam5 (NB
# 9.0->5.3, 2027 fires); provably INERT on cam1 (0 fires, no qualifying cluster)
# and cam3 (dtw-gated, 0 fires). BUT it REGRESSED cam4 (NB 4.9->5.8 PASS->FAIL,
# 1487 fires) — cam4's collinear speed signatures don't separate cleanly. So the
# default is OFF; enable per camera via the `calib_speed_tiebreak` knob only where
# a sweep confirms it helps (cam2, cam5). Still inert until build_bank supplies
# expected_speed on the paths.
SPEED_TIEBREAK_ENABLED = False          # OFF by default; per-camera calib_speed_tiebreak opt-in (cam2/cam5 validated)
SPEED_TIEBREAK_DECISIVE = 1.0           # px/step: override only if track speed is this much closer to the rival's signature
SPEED_TIEBREAK_MIN_SEP = 1.5            # px/step: only fire when the two paths' speed signatures differ by this

# --- Origin-evidence gate (item-8 mechanism 1, 2026-07-14) ------------------
# Phase-0 autopsy: all three attribution walls share one axis — origin gets
# CLAIMED without entry evidence (the joint scorer reads origin off the winning
# bank path; 208 NB-left->SB-right + 454 EB->SB-thru flips on cam2, 71 mid-block
# driveway grabs on cam4). When ON, a track that crossed a leg's entry gate
# inward has that origin BOUND: the joint scorer's candidates are filtered to
# paths from that leg, and the early entry-tangent origin is overridden to the
# evidenced leg. Tracks with NO entry evidence keep current behavior (counted
# via n_origin_unevidenced; the posterior half gates separately per the plan).
# OFF by default until the cam2 fit-window ablation + five-cam blind sweep
# (docs/plan_origin_evidence_gate_2026-07-14.md). Env override for dev sweeps.
ORIGIN_EVIDENCE_GATE_ENABLED = _os.environ.get(
    "ORIGIN_EVIDENCE_GATE_ENABLED", "") in ("1", "true", "on")

# --- Partial-evidence posterior (item-8 mechanism 1, posterior half) ---------
# docs/plan_posterior_half_2026-07-15.md. When the evidence cannot decide a
# single cell, build an explicit posterior over the feasible cells from corpus
# supports x shape residual, count at the posterior max, and record the
# posterior + margin so the flag queue surfaces the near-ties. Three branches:
# unevidenced-origin posterior, evidenced-truncated destination tie-break, and
# the evidenced insufficient-data rescue (the no-drop principle). Requires
# ORIGIN_EVIDENCE_GATE_ENABLED (evidence comes from the same gate pass).
# OFF by default until the stage-4 fit + stage-5 held-out + stage-6 sweep.
ORIGIN_POSTERIOR_ENABLED = _os.environ.get(
    "ORIGIN_POSTERIOR_ENABLED", "") in ("1", "true", "on")

# --- Evidence-gate ACTIVATION PRECONDITION (item-8 revival, ----------------
# plan_evidence_activation_2026-07-24 PHASE-1 VERDICT). Per-camera, GT-free:
# pass-2 first replays in PROBE mode (evidence computed + counted, ZERO
# attribution effect), reads coverage = origin_evidenced / tracks, and only
# when coverage >= the threshold re-replays with the PROVEN pair (gate +
# posterior, replay-level ONLY — the run_pass2 posterior extras
# census_expecteds/conserve_pass stay keyed on their own flags; phase 1
# never measured them). Census scale: cam2-stock 0.510 activates (4.1->2.8%
# total, NB 3.2); everything else 0.387-and-below stands down, incl. the
# held-out FM51 at 0.02. C=0.45 = the census-definition gap midpoint.
# Default ON (operator promotion 2026-07-27, after the live cam2
# verification byte-matched phase 1): every pass-2 runs the blind census;
# only coverage >= C activates. EVIDENCE_ACTIVATION_ENABLED=0 reverts.
EVIDENCE_ACTIVATION_ENABLED = _os.environ.get(
    "EVIDENCE_ACTIVATION_ENABLED", "1") in ("1", "true", "on")
# DEFAULT 0.20 since 2026-09-11 (G-BAR-1 PASS, docs/plan_blank_site_
# 2026-09-11.md). 0.45 was the corridor's census-definition midpoint;
# a blank site with its lines drawn where vehicles are tracked (the
# operating rule) reaches 0.24-0.30, and holding the channel off there
# cost FM51 4-12 movement points on three of four windows. On the
# corridor the change is neutral (77.08 -> 76.97; only cam4 1600 and
# cam5 0700 sat under 0.45). Env-overridable for experiments.
EVIDENCE_ACTIVATION_COVERAGE = float(_os.environ.get("EVIDENCE_ACTIVATION_COVERAGE", "0.20"))

# --- Posterior EXTRAS under the activation precondition (block D1, ----------
# docs/plan_v2_conserve_activation_2026-08-11.md). The conservation pass
# (at most one counted event per fragment CHAIN) and census_expecteds were
# retired as blind five-camera defaults per the two-iteration budget for ONE
# stated reason: not blind-deployable where evidence coverage is low
# (plan_conservation_pass_2026-07-15 — "the mechanism family is REAL: cam2
# 9.1 -> 3.3-3.5%... NOT blind-deployable where evidence coverage is low
# (36-60%)"). The activation precondition above is exactly the decider for
# that, and it shipped 2026-07-27 — but it governs the REPLAY only (see the
# note above: the extras "stay keyed on their own flags; phase 1 never
# measured them"), so conserve_pass has never actually run. Confirmed: no
# `conservation` key in ANY block-0 arm sidecar.
#
# ON: the extras follow the per-window ACTIVATION decision instead of the
# raw ORIGIN_POSTERIOR_ENABLED flag. OFF (default): byte-identical to today.
# NOTE the extras only bite where the pair is ON — conserve_replay_additions
# rejects only posterior-sourced events (_ADDITIVE), so on an all-direct
# replay it is a strict no-op by design.
CONSERVE_ON_ACTIVATION = _os.environ.get(
    "CONSERVE_ON_ACTIVATION", "0") in ("1", "true", "on")
# --- GATE-AG2: reattribution adjudication constants (2026-08-13) -------------
# docs/plan_gate_ag2_2026-08-13.md. FROZEN by the declared choice rule
# (tightest round values passing the P1 validation candidate with >= 1.5x
# margin; every constructed negative must still fail). P1 = ppt2_cam2_
# study_1600 vs the live incumbent + (re-frozen 2026-08-13 with the
# SECOND validated positive, ppt2-on-live study_1100, per the same rule
# over ALL positives: max moved_share 0.0273 -> 1.5x = 0.0410 -> cap
# 0.05; validated 8/8 incl. the new N6 runaway negative). Concentration
# 0.5895 -> 1.5x = 0.884 -> cap 0.90 (the adversarial one-cell shape
# reads ~1.0). NOT env-overridable (structural constants, AG1
# convention).
APPLY_GATE_REATTR_MOVED_MAX = 0.05
APPLY_GATE_REATTR_CONC_MAX = 0.90
# Concentration mass qualifier (2026-08-17, operator-ruled amendment by
# the moved_share re-freeze precedent): concentrated_movement binds only
# when moved_cell_mass EXCEEDS the PPT-3 composer cap scale (CAP_BETA =
# 40). Below it, one-cell concentration is the legitimate shape of a
# capped composer at low-cell-count geometry (cam4 T-junction P3: 28
# moves, concentration 1.0, Mio-confirmed +4.1); mass floods (N6
# runaway: hundreds into one cell) stay far above it. Re-validated
# 2026-08-17: 8/8 constructed cases + P3.
APPLY_GATE_REATTR_CONC_MASS_MIN = 40

# --- Auto-calibration sample window + concurrency (2026-08-18, operator) -----
# The operator sets a wall-clock start + duration in the calibration UI;
# the machine resolves it against the video's recording start. Default
# start targets the busy day (+7 h into a midnight-start file = 07:00);
# default DURATION re-frozen 15 min on the operator's 2026-08-19 ruling —
# collection costs ~3 GPU-min per footage-min, so the original 11 h
# default priced at ~30 GPU-hours while 15 busy minutes yield ~5k
# trajectories (the pre-2026-08-18 calibration was built from 57).
# Longer windows remain available in the UI (bounds 15 min .. 15 h).
# Concurrency: bounded pool with FIFO queue — each job carries its own
# detector instance; two keep the GPU busy without starving either run.
AUTO_CAL_MIN_SAMPLE_SEC = 15 * 60
AUTO_CAL_MAX_SAMPLE_SEC = 15 * 3600
AUTO_CAL_DEFAULT_OFFSET_SEC = 7 * 3600
AUTO_CAL_DEFAULT_DURATION_SEC = 15 * 60
AUTO_CAL_MAX_CONCURRENT = 2

# --- C-1: evidence-ranked chain arbitration (D1 iteration 2, 2026-08-12) -----
# docs/plan_v2_c1_arbitration_2026-08-12.md. Block D1 measured that "legacy
# always wins" is a SECOND, independent defect of the conservation pass: on a
# MIXED chain it rejects the posterior's correct event whenever the chain's
# legacy event is itself a misattributed flip (225/275, 173/219, 354/436 of
# the D1 rejections were the blanket rejected_vs_legacy branch, and the pass
# lost on the customer bar at its own high-coverage success camera).
# ON: a mixed chain keeps its best-evidenced event — ranked by agreement with
# the track's OWN gate crossings (a flip IS a disagreement; the match count
# subsumes tag strength: a full track can agree on both components, an
# entry-only track on one, a blind track on none), then track length — and may
# reject a LEGACY event for the first time. All-additive chains keep the
# proven _ADDITIVE_RANK path; legacy-only chains stay untouched (not ours to
# fix). OFF (default): byte-identical blanket "legacy always wins".
# Read at CALL TIME through the config module (patch backend.config, not
# two_pass — the D1 patching-trap lesson).
CHAIN_ARBITRATION_EVIDENCE = _os.environ.get(
    "CHAIN_ARBITRATION_EVIDENCE", "0") in ("1", "true", "on")
# The two fit-then-frozen constants (stage 4 fits them on cam2 study_0700
# ONLY; env overrides exist for that sweep and nothing else):
# margin floor — an origin posterior whose top-2 margin falls below this is
# flagged origin_ambiguous (Feeder-1 subtype). Unitless probability margin.
ORIGIN_POSTERIOR_MARGIN_FLOOR = float(_os.environ.get(
    "ORIGIN_POSTERIOR_MARGIN_FLOOR", "0.25"))
# tie band — candidates whose joint-scorer cost sits within this RATIO of the
# winner's cost are "tied" (their separating geometry lies past the track's
# death point); tied cells re-pick by corpus-support proportions. Unitless.
DEST_TIE_BAND = float(_os.environ.get("DEST_TIE_BAND", "0.15"))

# --- Claim-time origin veto (origin-grab phase 1, 2026-07-17) ----------------
# docs/plan_origin_veto_2026-07-17.md — mechanism ② with phase 0's measured
# signature (phase0_origin_grab_2026-07-17.md, 394 claims, two sites): a
# candidate origin leg may NOT be claimed when the track was born ON another
# leg-pair's through-road (< D_MAIN px from its bank polyline) AND beyond the
# candidate's mouth throat (> D_MOUTH px from its anchor). Applies to all
# three _assign_origin claim tiers; the fallback is the remaining candidates
# (phase 0: the grabs' births already sit nearest the true main-road origin).
# Constants are FROZEN geometry px from the phase-0 doc — D_MAIN=25 is the
# measured knee (20→30 moves genuine-capture 21%→38%), D_MOUTH=60 sits in a
# flat window (40→70 changes nothing at either site). No time constants.
# OFF by default until the FM51 ablation + frozen-constant corridor sweep
# pass (the plan's phase 2). Env override for replay harnesses only.
ORIGIN_CLAIM_VETO_ENABLED = _os.environ.get(
    "ORIGIN_CLAIM_VETO", "") in ("1", "true", "on")
ORIGIN_VETO_D_MAIN_PX = 25.0
ORIGIN_VETO_D_MOUTH_PX = 60.0

# --- Report letterhead (§3-E deliverables, 2026-07-16) -----------------------
# The operating firm's block on the PDF report (the example deliverable
# carries the operator's OWN brand). Empty name = the block is omitted —
# never render placeholder branding. Set once per install (env or here).
REPORT_LETTERHEAD = {
    "name": _os.environ.get("REPORT_FIRM_NAME", ""),
    "address_lines": [ln for ln in _os.environ.get(
        "REPORT_FIRM_ADDRESS", "").split("|") if ln],
    "contact": _os.environ.get("REPORT_FIRM_CONTACT", ""),
    "tagline": _os.environ.get("REPORT_FIRM_TAGLINE", ""),
}

# Pipeline-level grace period before considering a tracker-missing vehicle
# "lost" and finalizing it. YOLO detection can flicker (detect, miss, detect)
# on consecutive frames; without a grace window every flicker fragments a
# single vehicle into many one-point "tracks" that get dropped as
# insufficient_data. Bytetrack's own lost_buffer is TRACKER_LOST_BUFFER
# frames; this should be ≤ that so we don't outlive the tracker.
# Env-overridable for A/B replays (G-LP-1, 2026-08-25): the tracker's
# identity memory and this finalize grace are ONE mechanism — a locked-
# recipe dump carries healed occlusion gaps that a 60-frame grace would
# split back apart and double-count. Default unchanged: production
# behavior byte-identical.
TRACK_FINALIZE_GAP_FRAMES = int(_os2.environ.get(
    "TRACK_FINALIZE_GAP_FRAMES", "60"))   # 2s @ 30fps

# --- Articulated (semi-truck) classification (§3-D, 2026-07-06) -------------
# The COCO "truck" class is one bucket; distinguishing an articulated semi
# (FHWA 8-13) from a single-unit box truck (FHWA 5) needs a size signal. bbox
# ASPECT RATIO fails at approach-angle cameras (a truck viewed end-on is
# near-square: FM51 truck aspect p50 1.34 ~ car 1.38), so the old aspect>2.0 gate
# never fired -> 0 articulated vs Miovision's 102. The view-invariant signal is a
# truck's LENGTH relative to the LOCAL CAR baseline (median car length at the same
# image-distance band): a semi runs ~2x a box truck runs ~2x a car, at any
# distance. A truck whose length exceeds ARTICULATED_LEN_RATIO x the local car
# median is re-bucketed to articulated. K is BELOW the raw 3x length ratio because
# a long vehicle foreshortens MORE than a short one at an approach angle, so its
# bbox-length ratio compresses; validated offline on FM51 -> ~95 articulated ~=
# 102 at K=2.0 (a geometric threshold, SANITY-checked vs the aggregate, NOT fit to
# it -- the §0 overfit guard). The split is approximate: bbox size can't perfectly
# separate a short semi from a long box truck. See memory
# project_articulated_classification_2026_07_06.
ARTICULATED_LEN_RATIO = 2.0      # truck length > this x local-car-median -> articulated
ARTICULATED_BAND_PX = 40         # image-row band (px) for the local car-size baseline
ARTICULATED_MIN_CARS_PER_BAND = 20  # a band needs this many cars for a trustworthy median

# Native articulated votes (plan_articulated_native_2026-07-17): a track is
# articulated when >= this many of its detections carry the fine-tuned head's
# native class (NATIVE_ARTICULATED_CLASS_ID). 2 mirrors the size pass's
# _MIN_MATCHED_FRAMES=2 — by construction, not fit: one flickered frame never
# flips a class, two independent frames is the established evidence floor.
# Class-at-birth alone would systematically under-call semis (far-field births
# detect as plain vehicle before the trailer resolves), hence votes.
NATIVE_ARTICULATED_MIN_FRAMES = 2
# Same vote-floor pattern for the finetune_v2 single-unit id (classes 2/3 ->
# 9): two independent frames, one flicker never flips. Articulated takes
# precedence at finalize (a far-field semi often reads medium before the
# trailer resolves — the rarer, more specific class wins).
NATIVE_SINGLE_UNIT_MIN_FRAMES = 2

# --- Bank-gated through filter (FM51 audit #4, 2026-07-06) ------------------
# A "through" movement is only legitimate between OPPOSING legs; a through from a
# T-intersection stem (side road) is geometrically impossible. Short fragments of
# main-road through vehicles can fall to the fallback scorer, get their origin
# mis-read onto an adjacent side-road leg, and be labelled a "through" that
# DUPLICATES an already-counted main-road vehicle (FM51 side road: ours 105 vs
# Miovision 60, +75%; 33 bogus S->E throughs start at the main-road zone, avg 32-pt
# fragments). The bank is the authority on which through-movements are real (built
# from the site's own tracks) -> reject a "through" whose (origin,dest) is NOT a
# bank through-pair with real support (>= MIN_SUPPORT, so phantom 0-support paths
# don't count). Blind-deployable (no through where the site has no through-movement),
# generalizes to any T; 4-ways reject nothing (all throughs connect opposing legs).
# PER-CAMERA VALIDATED TOOL, NOT a blind default: the corridor regression (2026-07-06)
# showed cam3 has 691 LONG throughs on a bank-LEFT pair (real left-turners mislabeled,
# not duplicate fragments) — rejecting those would delete real vehicles. So run
# reject_invalid_throughs only where validated vs ground truth (FM51 cam2: 33 short
# duplicate fragments, side road 105->72). See MASTER_PLAN §2 #4 + memory
# project_per_approach_attribution_2026_06_30.
THROUGH_GATE_MIN_SUPPORT = 1     # bank turn-paths below this support are phantom (ignored)

# Ensure directories exist
DATA_DIR.mkdir(exist_ok=True)
PROJECTS_DIR.mkdir(exist_ok=True)
