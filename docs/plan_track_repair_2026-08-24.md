# Track Repair scored gate (G-TR-1) — gate doc

Declared BEFORE any scored run (house gate discipline,
MASTER_ACCURACY_ROADMAP "Gate discipline"). Mechanism: the A3 splice
cutter as a dump-level repair (operator identity law, 2026-08-24: gates
cut tracking; a vehicle cannot reverse mouth-to-gate; occlusion does not
end identity, incompatible motion does). Lineage: infrastructure e8ded5a;
blanket-cut negative fd2311b; graze amendment (rev 4) 41104c6; Stage 2
direction gate + collision fix (rev 5), glue negative + default off,
455bebc. This is a DIFFERENT mechanism than the dead conservation family
(ledgered 2026-08-12): that family was subtractive event arbitration
(rejected=1 writes against counted events); this is a dump repair — the
replay simply counts the repaired tracks; no event is arbitrated.

## What is being tested

ARM = env A3_CUT_DUMPS=1, code at commit 455bebc — run_pass2 resolves the
three cam2 study windows to the a3_ CUT dumps (rev 5: graze-amended
Type-1 + pinch cuts, segment namespace 1e6+tid*10+k; CHAIN_GLUE off, so
cut-only). Geometry unchanged (drawn gates + curated paths, the shipped
basis). Supremacy ships ON, so the arm measures cuts ON TOP of supremacy
— the correct composed basis.

CONTROL = shipped production = the gatesup scores (G-GS-1 SHIPPED
2026-08-24). Valid control per the G-GS-1 precedent: the arm is
exclusively a code/flag arm on an unchanged-geometry basis. New score
JSONs self-record this control in production/production_approach.

Offline projection already on record (corrected census, 41104c6 +
455bebc): deficit cells heal (EB_left -229 -> -41 at 1600, SB_right
erased, WB_left ~0, SB_thru partial), overcount cells inflate in the
PROXY — but the proxy has no turn_merge/volume machinery; this replay is
the honest adjudicator.

## G-TR-1 (the ship gate)

- Controls (measured 2026-08-24, score_gatesup_cam2_study_*): pooled
  movement 64.8% (214/330); per-window 67.3 (72/107) / 62.0 (67/108) /
  65.2 (75/115); approach 43.8 / 50.0 / 40.6 (pooled 44.8, 43/96).
- PASS: arm pooled movement > 64.8%, AND no window more than 2.0 below
  its control (floors 65.3 / 60.0 / 63.2). Approach recorded alongside
  (secondary; the healing indicator).
- MISS: A3_CUT_DUMPS stays default-off (already is — zero revert);
  negative ledgered here + roadmap. No restore: replays are scratch-only;
  production untouched either way until Confirm & process.

## Interactions ledgered

- Cuts change gate tags per segment -> the gate_full supremacy population
  moves; report n_gate_supremacy / posterior_source='gate_full' ctrl vs
  arm (G-GS-1 convention).
- Cutting removes production's split-on-reuse double counts (measured in
  production: 95 tids carry 195 events in study_1600 alone) — a
  volume-DOWN effect concentrated in the overcounted through cells;
  report the duplicate census in the arm DB vs production.
- Demotion census self-censuses the a3_ dump (a3_ deliberately absent
  from the base-prefix strip, e8ded5a: cuts CLEAN the census).
- Volume-gate/turn_merge coupling: report merged_away +
  census/expecteds ctrl-vs-arm diffs.
- Silent-fallback hazard: A3 resolution failure logs a warning and runs a
  control replica — armed-verification (stats sidecar variant =
  a3_study_*) is a REQUIRED step before scoring.

## Procedure

1. Arm replays study_0700/1100/1600, FRESH workdir
   _replay_scratch/trackrepair_20260824, apply=False (production
   untouched), env A3_CUT_DUMPS=1, from the repo root (kin npz lookup is
   CWD-relative). Chain: runs/v2_week1/gtr1_chain.ps1. The stale glued
   a3_ dumps fail the reuse key (glue.enabled=True vs CHAIN_GLUE off) and
   rebuild cut-only in-run — wanted.
2. Verify armed: sidecar variant a3_study_*; a3_ meta rule_rev 5 + glue
   disabled + kin fitted.
3. Copy working DBs to stems trackrepair_cam2_study_* (sqlite backup
   API); score all three with v2_score_dev in one call.
4. Verdict here + roadmap changelog, commit — PASS or MISS.

## Verdict — G-TR-1 MISS on all three windows (2026-08-24)

| window | movement ctrl -> arm | approach ctrl -> arm |
|---|---|---|
| study_0700 | 67.3 -> **50.5** (-16.8) | 43.8 -> 0.0 |
| study_1100 | 62.0 -> **34.3** (-27.7) | 50.0 -> 21.9 |
| study_1600 | 65.2 -> **28.4** (-36.8) | 40.6 -> 21.9 |
| pooled | 64.8 -> **37.4** (119/318; bar >64.8) | 44.8 -> **14.6** |

Mechanism (two coupled structural failures; neither is a cutter defect —
the cut rules themselves remain splice-validated 54/56):

1. **COVERAGE DILUTION — the repair de-activated the gates it serves.**
   Evidence activation coverage: ctrl 0.566 -> arm 0.474 / 0.410 / 0.397
   against threshold 0.45. Windows 1100+1600 replayed with the entire
   evidence-gate machinery OFF (gate_full events 0 vs ctrl 579/605);
   0700 barely activated (gate_full 291 vs ctrl 502). Cause: cutting
   mints thousands of no-crossing debris segments (10,720/9,413/14,327
   segments from 2,810/2,474/3,859 cut tracks) and the activation
   denominator counts every track.

2. **DEBRIS COUNTING — non-full segments stay countable.** Cut segments
   carry 54-61% of arm events (3,891/3,186/5,500 of 7,154/5,429/9,022):
   fragments with no or partial gate evidence are still classified via
   the posterior/bank path machinery — whose corpus bank is itself built
   from cut fragments. SB_thru balloons to 3,346 vs Mio 2,247 at 1600
   while EB_thru/WB_left/NB_right collapse. The offline census could not
   see this class: it only credited gate-full verdicts. Under the
   operator's law (vehicles counted only when entering through a gate),
   cut DEBRIS must not be independently countable — the pipeline's
   eligibility thresholds were calibrated for whole tracks and were left
   unchanged.

Confirmed predictions retained for the record: split-on-reuse duplicate
tids collapse under cutting (production 95 -> arm 39 at study_1600);
armed-verification worked (all three sidecars a3_study_*, rev 5, glue
off, kin fitted); arm wall-clock 185/137/156 s per window.

MISS handling per the declaration: A3_CUT_DUMPS stays default-off
(already was — zero revert); this negative ledgered here + roadmap.

Open next (operator ruling): (a) a SEGMENT-ELIGIBILITY amendment — cut
debris excluded from the evidence-coverage denominator and from non-gate
counting (segments count only via gates), the smallest change that
re-tests the same mechanism; or (b) shelve pass-2 repair and open Stage 4
(pass-1 lock persistence: fix the tracker so tracks never need cutting) —
the operator's original diagnosis.

## SHIPPED — no. G-TR-1 MISS; production untouched (scratch-only replays).

## G-TR-2 — the debris-eligibility re-test (declared 2026-08-24, before
## any scored run; operator ruling: option (a))

ARM = A3_CUT_DUMPS=1 at the rev-6 amendment commit: cut segments survive
only with a PHYSICAL gate crossing (temporally adjacent bracketing points
at physical speed — a crossing synthesized across a latch teleport is a
theft artifact, not evidence); all-debris cut tracks pass through uncut.
Both G-TR-1 mechanisms addressed at the dump layer: debris can neither be
counted nor vote on evidence activation. CONTROL, PASS thresholds, MISS
handling: IDENTICAL to G-TR-1 (pooled movement > 64.8; floors 65.3 /
60.0 / 63.2; approach secondary). Fresh workdir trackrepair2_20260824;
armed-verification now also checks rule_rev 6 + debris stats present.

## G-TR-2 Verdict — MISS (2026-08-24); mechanism family CLOSED at budget

| window | movement ctrl -> arm | approach ctrl -> arm |
|---|---|---|
| study_0700 | 67.3 -> **61.0** (-6.3; floor 65.3 breached) | 43.8 -> 34.4 |
| study_1100 | 62.0 -> **61.9** (-0.1; floor 60.0 held) | 50.0 -> 40.6 |
| study_1600 | 65.2 -> **60.9** (-4.3; floor 63.2 breached) | 40.6 -> 34.4 |
| pooled | 64.8 -> **61.3** (193/315; bar >64.8) | 44.8 -> **36.5** |

The amendment did what it declared: debris dropped (2,655/2,394/3,675
segments; 101/54/144 all-debris tracks passed through uncut), evidence
coverage restored ABOVE control at 0700 (0.619/0.538/0.522 vs ctrl 0.566;
activated x3), supremacy back (gate_full 276/321/500). The repair still
scores below shipped production: gate_full is ~half of control's
502/579/605 (production's whole spliced tracks classify full — sometimes
via theft-synthesized crossings that happen to be right — while honest
cut segments classify partial), and 2,881/2,443/3,992 events still come
from partial-evidence cut segments through the path machinery, whose
every threshold was calibrated on the broken-track world. The
activation-coupling law called this: a repaired track basis moves
everything downstream, and re-tuning the downstream for it is a larger
project than the repair itself.

VERDICT: two scored MISSes (G-TR-1 37.4, G-TR-2 61.3) = the
two-iteration budget for the pass-2 cut-dump repair family is SPENT.
Family CLOSED (reopen only on new evidence). A3_CUT_DUMPS stays
default-off permanently; the cutter library, the direction gate, the
split-on-reuse quantification, and the physical-crossing evidence rule
remain in the codebase as validated components for Stage 4.

Open next: Stage 4 — pass-1 lock persistence (fix the tracker so tracks
never need cutting): lost-buffer pass-through + meta recording (hygiene),
then motion-gated re-association per the operator's bus law, its own
plan + scored gate. This was the operator's original diagnosis.
