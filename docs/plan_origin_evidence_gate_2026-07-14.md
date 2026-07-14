# Plan — item-8 phase 1, mechanism ①: the origin-evidence gate (2026-07-14)

**STATUS (same day): stages 1–2 SHIPPED (59d021d, e0fa2c0, flag default
OFF); stage-3 fit-window ablation RUN — filter half = qualified PASS with
one induced regression, traced.**

cam2 study_0700, Mio / flag-off control / gated (counters: 4691 evidenced
= 80%, 1140 unevidenced, **348 corrected flips**; events 5347 vs 5440 ctrl,
insufficient +93 — no drop ballooning):

| cell | mio | ctrl | gate | read |
|---|---|---|---|---|
| NB-left | 411 | 146 | **209** | recall 0.36→0.51 — the flip fix works |
| SB-thru | 1384 | 1082 | **1137** | +55, contamination shed |
| SB-right | 379 | 361 | 314 | down past Mio (0.83) — shed its stolen NB-lefts |
| EB-right | 167 | 494 | **394** | overcount −100 |
| EB-thru | 119 | 23 | 34 | still the bank hole |
| **EB-left** | 229 | 157 | **304** | **INDUCED regression 0.69→1.33** |
| NB-thru / WB-right | — | — | — | stable (tripwires hold) |

Watch-cell |err| sum 1124→946 (−16%). **The EB-left regression is the bank
hole made visible:** evidenced origin-28 tracks are now correctly bound to
28→* candidates, but the applied bank has NO 28→26 (EB-thru) path — so
real EB-thrus are forced into 28→27 (left) and 28→29 (right). Before the
gate they escaped into other origins' cells (wrong, but spread out). This
is the predicted ①→③ coupling, arriving early.

**Decision (next ablation before any freeze):** fill the 28→26 hole with
the CORPUS-FITTED path (discovered from the site's own tracks — standing
rule 1 bans DRAWN paths in fitted banks; a corpus-fitted path is
bank-family-consistent) and re-run the arm. If EB-left returns to ~ctrl
and EB-thru rises, the filter+fill pair goes to held-out 11:00/16:00 and
then the five-cam sweep. The posterior half remains separate.

**FILL ARM (pinned gates, same day):** first run was CONFOUNDED — gate
geometry was derived from the candidate set, so the injected path rotated
the leg-26/28 gates (evidenced 4691→2628). Fixed by pinning gates to
`_gate_paths` (900e9df — also a product hazard: an operator path edit
would have rotated evidence gates silently). Pinned rerun, gate vs fill:
NB-left/SB-right/NB-thru/WB-right byte-identical (pin verified, 348
corrections stable); **EB-thru 34→76** (the fill reaches its cell);
EB-right 394→381; watch |err| 946→**902** (ctrl 1124, −20% total).
**BUT EB-left 304→303 — the bank-hole hypothesis for the EB-left
regression is FALSIFIED**: the 147 extra EB-lefts are not starved
EB-thrus (they didn't drain into the new thru path; EB-thru's +42 came
from the fallback pool). The regression has an unidentified mechanism.

**Next (before freeze): the EB-left autopsy** — box-clip cells for the
fill-DB's (28→27) events on study_0700 (the phase-0 join machinery on the
working DB): who are the +147 — truncated EB-thrus whose shape curves
left? mis-evidenced non-EB tracks? full-journey 27-exits? The freeze
decision waits on this; everything else in the arm supports shipping the
filter+fill pair.

Phase-0 verdict (`phase0_wall_autopsies_2026-07-14.md`): all three walls
share one axis — origin is CLAIMED without entry evidence (208 NB-left→
SB-right flips, 454 EB→SB-thru flips, 71 mid-block driveway grabs). The
§2c order of authority already SAYS "box-side crossings decide origin for
every track" — but the implementation never did it: the joint scorer reads
origin off the winning bank path (`score_path_joint`), which IS the flip
mechanism (the ORIGIN_REWRITE_GATE covers only straight tracks). This
mechanism implements the stated design for origin.

## The mechanism

At finalization, compute the track's ENTRY-GATE crossings (the operator-leg
box perimeter — the same gates box-clip builds from legs + bank paths):

1. **Entry evidence exists** (crossed a leg's gate inward): origin is that
   leg, hard. The joint scorer's candidate paths are FILTERED to
   `origin_leg == evidenced leg` before matching — the winner can no longer
   rewrite origin across the intersection. (This alone kills the Wall-A
   208-flip and the Wall-B 454 SB-thru contamination: those tracks HAVE
   entry evidence at leg 29/28; only their matched path lied.)
2. **No entry evidence** (born mid-box / mid-block): NO hard origin from
   anchor or shape proximity. The track gets a POSTERIOR over origins:
   exit-gate evidence (if any) fixes the destination; corpus-window
   supports (scale-1, standing-rule-2 pattern) weight the feasible
   (origin→dest) cells; shape residual against each candidate's sub-curve
   breaks ties. Above the confidence floor → counted at the posterior max
   WITH an `uncertain_event` flag (origin_ambiguous subtype, S-feeder);
   below → counted origin-uncertain and queued. Nothing is silently
   dropped (the §3-A no-drop principle) and nothing hard-claims a mouth it
   never crossed (Wall C's 71).
3. U-turn/jitter semantics port verbatim from box-clip (JITTER_S burst
   collapse; same-leg re-cross ≠ u-turn without dwell + lane shift).

Blind-deployable throughout: gates are operator geometry, supports are the
site's own corpus, no GT anywhere. New constants: ONE posterior confidence
floor (fit on the 07:00 window, frozen thereafter); gate geometry reuses
box-clip's proven constants unchanged.

## Build stages

1. **`backend/services/entry_gates.py`** — verbatim port of
   `build_gates`/`_seg_cross`/crossing-collapse from `scripts/
   boxclip_pass2.py` (script re-imports from the service; one source of
   truth — the turn_merge port pattern). Unit tests: gate fidelity vs the
   script on a cam2 dump sample (identical crossings on N=500 tracks).
2. **Pipeline wiring, behind `ORIGIN_EVIDENCE_GATE_ENABLED` (default
   OFF).** At `_finalize_vehicle_data`: compute crossings once; evidence →
   candidate filter into the joint scorer; no-evidence → the posterior
   path + flag emission. Legacy behavior bit-identical when OFF
   (test-gated, the TWO_PASS_ENABLED pattern). Instrument counters:
   n_evidenced / n_posterior / n_uncertain / n_fallback.
3. **Ablation on cam2 study_0700 (the FIT window)** via pass-2 replay
   (~minutes/run): flag off vs on; posterior-floor sweep; report per-cell
   recall/precision + whole-camera MAE. Success shape: NB-left recall
   0.31→≥0.45, SB-right back toward 1.0 (it will DROP — that is the fix
   working, score whole-camera only), SB-thru up, EB SB-contamination
   gone, approach totals conserved. Also watch: fallback/insufficient
   counts must not balloon (the filter removes candidates — the unclaimed-
   288 pool must not grow; if it does, that diagnosis pulls forward).
4. **Freeze constants → held-out 11:00/16:00.** No re-tuning after this
   line — held-out movement must match the fit-window story.
5. **Five-camera blind sweep** (frozen constants, replay, current
   baselines: cam1 7.6 / cam2 8.1 / cam3 3.2 / cam4 live 4.6 / cam5 7.1):
   improve the target cells, hold the tripwires (cam3, cam4-live; cam4's
   (34→33) should shed most of its 71-event mid-block class). PASS →
   apply through the product flow, per-window backups; flip the flag
   default in its own commit. FAIL → retirement entry + findings; the
   posterior piece and the filter piece gate SEPARATELY (the filter may
   pass while the posterior retires — they are independently revertible).

## Explicitly out of scope (phase-1 items ② and ③ wait)

The unclaimed-288 drop diagnosis (next, informed by stage-3's counters);
EB-thru pre-divergence allocation (after the flips die — the pool changes);
the never-journeyed 585 (capability track); any turn-merge expectation
recheck (the corpus bank re-discovers from de-flipped tracks first).

## Risks named

- Restricting candidates can starve matches → more fallback events, not
  fewer errors. The stage-3 counters + the no-balloon check catch it.
- cam1 (botsort+reid recipe) has different birth behavior — the sweep, not
  cam2 intuition, decides whether the gate helps or hurts there.
- Gates derive from operator leg anchors; a badly-placed anchor makes a
  gate miss real entries. The n_evidenced counter per leg vs corpus
  supports is the QA cross-check (feeds §3-B if it fires).

## Ops

Ablations run detached with logs + resume; no repo `.py` edits while a
server job runs; scorers (`measure_cam2_reid_spike`, `triangulate_manual`,
`interval_metric`) remain the only GT readers.
