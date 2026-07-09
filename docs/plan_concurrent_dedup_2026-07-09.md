# Plan — concurrent-duplicate event dedup (2026-07-09)

**VERDICT (same day): NEGATIVE at the DEV gate — mechanism retired.** The full
ablation grid (sep 15–30 × overlap 0.5/0.7 × through/all, cam2 live events,
07:00–07:30) worsens the per-cell abs total at EVERY point (243 → 247–300).
Target cells barely move (EB-right +31→+29 best case); the pass instead merges
REAL distinct vehicles in the dense NB-thru stream (626 dead-on → −2 to −35) and
worsens SB-thru (−43 → up to −65). Root cause of the mismatch with the July-6
diagnosis: the 305 validated concurrent duplicates were counted on the RAW
6-hour track dump; the LIVE event stream (post-NMS `project_cam2_nms_applied`,
post-hybrid merge) no longer carries them. The residual EB-right/SB-right
overcounts are collinear-ATTRIBUTION shaped (§2c territory), not ID-split
shaped. Consequence: the held cam2 bank-D apply stays HELD (its precondition —
shrink EB-right via dedup — failed). No blind sweep run. The grid + plan below
are retained as the record.

The diagnosed cheap lever from `docs/cam2_perapproach_diagnosis_2026-07-06.md`
mechanism 2: SB-thru occlusion splits EB tracks into concurrent duplicate IDs
(305/3789 EB tracks validated as tight <20px concurrent duplicates). Today's
bank-coverage session (docs/bank_coverage_audit_2026-07-09.md) makes it load-
bearing twice: cam2 EB-right sits +26 over (81 vs 50 — the ID-split cell), and
the held bank-D apply (EB-thru fill) only becomes a clean win on both metrics if
this overcount shrinks.

## Mechanism (post-tracking, event-level, GT-free)

Prior art: `scripts/replay_dedup.py` (through-only), `dedup_ceiling.py` (the
same-place-at-same-FRAME definition — whole-curve similarity is wrong, all
throughs share the lane). Two events of the SAME camera and SAME (origin, dest,
movement) cell are one vehicle when their frame ranges overlap ≥ overlap_frac of
the shorter AND their interpolated positions stay within sep px (mean over the
overlap). Union-find; the longest-duration member survives. CONCURRENT only —
no sequential stitching (dedup_ceiling showed stitching is the risky half; the
ID-SPLIT signature is simultaneity, which two distinct vehicles cannot fake at
<20px for half a track).

Constants are fps-safe by construction: overlap_frac is dimensionless, sep is
image px. No frame counts (cams run 10–25 fps).

## Ablation (DEV, cam2 07:00–07:30, Miovision = scorer only)

Grid: sep ∈ {15, 20, 25, 30} × overlap_frac ∈ {0.5, 0.7} × scope ∈ {throughs,
all movements}. Watch cells: EB-right +26, SB-right +31 (also over), EB-left
+11; guard cells: NB-thru 626 (dead-on today — any undercount = over-merge),
SB-thru −43 (must not worsen). Pick the sweet spot on per-cell abs total; note
the per-approach MAE cut too.

## Gate (frozen constants, blind)

Freeze the chosen (sep, overlap_frac, scope). Run cams 1/3/4/5, 07:00–07:30,
live project.db events. PASS = per-cell abs improves or holds on every camera;
HARD FAIL = any passing camera (3/4) regresses. Negative result = deliverable.

## If passed

Re-test cam2 bank D + dedup jointly (dedup applied to the bank-D retrack DB) —
the joint result must beat live on BOTH the per-cell cut and the per-approach
MAE for the held apply decision to re-open.

## Explicitly out of scope

Sequential (gap) stitching; tracker changes; per-camera constants. One frozen
recipe or nothing.
