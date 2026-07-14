# Plan — §4 item 8: the attribution walls (research) (2026-07-14)

The corridor is applied on two-pass (4/5, all at-or-better than live) and the
operator surface is done (items 6–7). What remains between the honest
numbers and the ≤5% per-approach bar is CONCENTRATED in three measured
walls. This is research, not product work: full gate discipline (plan doc →
ablations → frozen-constant blind sweep before wiring; negatives are
deliverables; time-based constants; Miovision/manual = DEV scorer only,
never a pipeline input — §0 litmus on everything).

## The walls (exact signatures, from the committed findings)

- **Wall A — cam2 NB-left recall 0.32** (old recipe ~0.36; two-pass didn't
  move it; −127 in hour 2 alone). "The known attribution wall" — but the
  detection-vs-tracking-vs-attribution decomposition has never been run on
  the FULL-DAY corpus; the label is inherited, not re-proven.
- **Wall B — cam2 EB thru/right collinear split.** Two-pass fixed the
  APPROACH: EB total +37 vs the old +696. But internally EB-thru 0.24 /
  EB-right 1.50 — thru starves into right. The day's S4 bank-hole flag
  (impact 179, queue rank 1) carries the fallback EB-thru events. A pure
  REALLOCATION problem inside a conserving approach — any fix must
  preserve the approach total (a clean ablation invariant).
- **Wall C — cam4 EB-left +31, mid-block-birth origin assignment.**
  Arterial tracks born mid-road get their origin mis-binned to the
  driveway anchor (birth bearings ~81° even on live origin-34 events); the
  anchor-move fix A/B-measured WORSE (5.5% vs 5.1%) and was reverted.
  cam4's live table passes the product bar — this wall is about closing
  the last hold honestly, not saving a failing camera.

## What may NOT be retried (the retirements ledger binds this plan)

Box-clip as counter (Gate B); drawn-path fill of a fitted bank's
attribution set (measured 4×: §2c, cam5 audit ×2, bank-D retest under
two-pass — FAIL, retired); blanket ReID rollout; BEV/IPM; the entry
tiebreak; ×-scaled merge expecteds; per-camera detection profiles; the
cam4 anchor move. Standing rules §2d 1–3 hold. Box-clip's legitimate role
is DIAGNOSTIC/QA (§3-B) — phase 0 uses it exactly there.

## New assets the old diagnoses lacked

Full-day pass-1 raw-track dumps on all five cameras + pass-2 replay in
minutes. Every hypothesis below is testable against the corpus without
re-detection, and every candidate mechanism ablates at replay speed.

## Phase 0 — wall autopsies (diagnosis before mechanism; ~1 session)

Produce a LOSS LEDGER per wall from the dumps + per-interval Miovision
(scorer only):

- **A:** do the missing NB-left vehicles exist as raw tracks? Box-clip
  DIAGNOSTIC over the dump (its demoted §3-B role): tracks entering the NB
  mouth and exiting the left-exit mouth, per interval, vs Miovision's
  NB-left. Split the 0.68 loss into: never-tracked (→ capability track,
  not attribution) / tracked-but-unclaimed (fallback or dropped) /
  tracked-and-STOLEN (attributed elsewhere — name the thief cells).
- **B:** truncation-ceiling analysis. For EB tracks: death position vs the
  thru/right divergence point; s-coverage histogram. Fraction dying before
  divergence = unattributable-by-shape BY CONSTRUCTION = the ceiling of ANY
  shape matcher. The remainder is the winnable pool. Also ledger where
  Miovision's EB-thru went (right-steal vs fallback vs missing).
- **C:** birth census of cam4 origin-34 events (extends the 07-13 review):
  birth position along the arterial vs the mouth; how many of the +31 are
  mid-block-birth class members; where their box-crossings actually lie.
- **Decision checkpoint (deliverable even if all answers are "no"):** which
  walls does a matcher change actually reach? If B's ceiling says most of
  the split error is pre-divergence truncation, shape matching is dead
  there and the honest lever is posterior reallocation (below) or a
  capability-track item — written down, with numbers.

## Phase 1 — one mechanism at a time (evidence-ordered candidates)

1. **The (s,d) curvilinear matcher (§2b direction) — Wall B first, A if
   the autopsy says attribution.** Road-aligned coordinates per approach
   (geometry from the applied bank's own paths — operator/site data, no
   GT): s = arc position, d = lateral offset; coverage = s-span, which
   fixes the exact coverage-blindness `_mdh_cost` hard-wires (§2b).
   Ambiguity becomes EXPLICIT: a track ending before the divergence gets a
   posterior over the sharing cells from corpus-window supports (scale-1 —
   the standing-rule-2 pattern) instead of a hard mdh snap to whichever
   collinear path sits closer. Blind-deployable by construction.
   Invariants asserted in every ablation: EB approach total stays ~+37;
   no touched cell regresses on the OTHER cams.
2. **Mid-block-birth origin gate — Wall C.** A track born beyond the mouth
   (s past the box edge + a margin, time-based-free geometry) may not claim
   a side-leg origin from anchor proximity; it defers to its box-crossing
   or lands origin-uncertain in the flag queue (S-feeder, conservative
   counts). Structurally different from the retired anchor move: it gates
   CLAIMS, not anchor positions.
3. **If A's autopsy says never-tracked:** Wall A leaves attribution and
   joins the §3-D capability track (low-light/far-field recall) — that is
   a finding, not a failure.

Protocol per mechanism: prototype on cam2's dump with HELD-OUT hours (fit
any constants on the 07:00 window, validate untouched on 11:00/16:00),
freeze constants, then phase 2. One mechanism lands (or retires) before
the next starts.

## Phase 2 — the gate (unchanged discipline)

Frozen-constant blind sweep on ALL FIVE cameras via pass-2 replay, scored
vs the CURRENT baselines (cam1 7.6 / cam2 8.1 / cam3 3.2 / cam4 live 4.6 /
cam5 7.1 per-approach MAE, plus the per-cell table): target cells must
improve, passing cams must hold (cam3's 3.2 and cam4's live table are
regression tripwires). PASS → apply through the product flow
(measure-then-apply, backups). FAIL → retirement entry + findings doc.

## Parallel track — §3-D detector fine-tune (independent lane)

Articulated first (beat the ~70% bbox-size heuristic), low-light second;
scoped in `detector_derisk_spike_2026-07-08.md`; its own gate is HELD-OUT
SITE generalization, never corridor-fit. Starts when label/GPU time is
allocated; gets its own plan doc then. Nothing in phases 0–2 blocks on it.

## Success criteria for item 8 (honest closure allowed)

Each wall ends in exactly one of: **MOVED** (measured at the gate, applied)
or **CHARACTERIZED** (ceiling/mechanism documented with numbers, routed to
the right track — capability, QA feeder, or accepted residual). Item 8
closes when all three walls have a verdict; it does NOT require all three
to be wins. Corridor-level goal: the failing cams' honest per-approach MAE
moves toward ≤5% with zero regression on the passing ones.

## Ops rails

Long ablation sets run detached with logs + resume; no `.py` edits while a
server-hosted job runs; scorer scripts (`measure_cam2_reid_spike`,
`interval_metric`) stay the only place GT is read.
