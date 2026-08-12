# Block B1 — the structural twin channel, ISOLATED
# (2026-08-12)

Tier-1 block 3 of the options-inventory campaign (category B — "built but
never measured against a gate"). The week-1 verdict named this **item 1**:
"co-temporal tracklets COMPETING FOR THE SAME CONTINUATION = one vehicle.
No thresholds, pure structure. Cheap to implement; instrument first."

## What is already known (and why it proves nothing yet)

`twin_pairs_structural` (`scripts/v2_common.py:348-406`) ran end-to-end
ONCE: the cam2 `v2a_study_0700` dump on disk IS the structural channel
(meta: engine "premerge+ratio_greedy", premerge_groups 124,
premerged_tracklets 259 — matches a fresh recomputation exactly: 135 pairs
→ 124 union-find groups over 259 tracklets). It scored **53.4 vs control
53.4** — net zero — with target cell EB_right 309→290 (Miovision 167).
That result is attributable to NOTHING because the twin merge was bundled
with the sequential ratio-greedy stitch, whose assembly line FAILED G-A1;
the v2a "held-outs" (study_1100/1600) are a different engine entirely
("greedy_frozen", no premerge). Never written up until now.

Also on record: the cam2 EB_right flood is **mostly gate geometry (false
EB origins), not twins** — pair-geometry found 2/92 tight co-temporal
pairs in that cell (week-1 verdict day-5 addendum). So the target-cell
condition below is DIRECTIONAL, not "close the flood".

## Build (phase 0 — before any gated run)

1. **`scripts/v2_twin_instrument.py` (NEW)** — the twin instrument that
   does not exist (`v2_frag_instrument.py` measures SEQUENTIAL stitch
   purity; wrong phenomenon). Synthetic injection on a real tracklet
   table, seeded (SEED 42), donors = full journeys ≥ 12 s passing the
   frag-instrument quality gates, MAX 150, split into disjoint twin-host
   and decoy-host halves.
   - TWIN clone (detector double-box model): co-life log-uniform
     1-10 s inside the donor span; constant offset, uniform direction,
     magnitude U(0.05, 0.35) × donor mean bbox diagonal, clipped so
     same-size-box IoU ≥ 0.30; per-frame jitter N(0, max(1 px,
     0.03 × diag)); bbox w,h × U(0.9, 1.1) + per-frame N(0, 0.02 × size);
     conf × U(0.55, 0.9); 10% frame drop with ≥ 3 surviving common
     frames.
   - DECOY negatives (the documented killers of the four dead channels):
     queued-follower (same path, time-lag U(0.8, 2.0) s) and
     lane-neighbor (perpendicular offset U(2.5, 4.0) × zv_radius,
     same motion).
   - Pipeline: rebuild table with clones (`table_from_pieces`), re-run
     `fit_motion_residual` on the augmented table (mirrors the
     v2_reid_dump order), run `twin_pairs_structural`, score.
   - METRICS: twin recovery recall (aggregate + per co-life bin
     {1-2, 2-5, 5-10 s}); decoy false-flag rate (aggregate + per class);
     clean-window flagged-pair count (context: measured 135/249/264 at
     cam2, 149/483 at cam1); `seq_overlap_frac` = fraction of admitted
     pairs that are also confident stitch_greedy links — DIAGNOSTIC ONLY
     (both verdicts assert "same vehicle"; high overlap predicts
     re-derived G-A1, it cannot falsify a pair).
   - Artifact: `runs/v2_week1/twin_<table-stem>.json`.
2. **`scripts/v2_reid_dump.py`** — `--engine {greedy,off}` (off skips
   stage 3b entirely: `links, chains = [], []`, no second
   fit_motion_residual) and `--out-prefix` (default `v2a`; the
   v2_extend_dump precedent). Meta telemetry: record `twin_mode`, and
   `engine` becomes `"premerge_only"` / `"passthrough"` under
   `--engine off`. Defaults byte-preserve today's behavior.
3. **`scripts/v2_common.py`** — `dist_mult` honest-signature fix:
   default 1.5, actually used at `:386`, docstring corrected. Behavior-
   preserving (sole caller passes no override). A parameter that silently
   ignores caller input is the confound class this campaign kills. NOT
   swept in this block.
4. **`scripts/v2_phantom_diag.py`** — `--ctrl-db` / `--cand-db` overrides
   (hardcoded paths cover only ga3ctrl/armC layouts). Shared with H1.

## GATES — declared before any run; numbers final

**G-B1i (instrument kill gate, runs FIRST) — on tracklets_cam2_study_0700
AND tracklets_cam1_study_1600 (the two-camera density-transfer
precedent):**
- injected-twin recovery recall ≥ 0.80 aggregate AND ≥ 0.60 in every
  co-life bin;
- decoy false-flag rate ≤ 0.02 aggregate; either decoy class > 0.05 =
  FAIL.
Anchors: the dead co-life-IoU channel caught ~1/4 of twin mass; 0.80 is
"decisively better than the dead channel"; 0.02 mirrors the frag
instrument's 0.98 purity tripwire. FAIL → block STOPS, ledger
"structural signature does not recover the double-box class"
(iteration 1 spent).

**G-B1p (harness parity, precondition — not a research result):**
- `b1p` (twin off + engine off) dump row-MULTISET equals the base dump
  on all 5 windows (lexsort both by (frame, track_id, cx),
  np.array_equal — byte order legitimately differs: the writer re-sorts
  frame-major);
- pass-2 of b1p on cam2 study_0700 scores CELL-FOR-CELL equal to
  committed `score_d1ctrl_cam2_study_0700.json` (53.4, 55/103).
Any mismatch → STOP, debug harness; no arm result is interpretable.
Passing makes the committed controls (d1ctrl cam2, ga3ctrl cam1) valid
comparators for the twin arms with one-variable discipline intact.

**G-B1a (counting gate; controls: d1ctrl cam2 53.4/42.9/44.0, ga3ctrl
cam1 60.5/54.5):**
- 5/95 per-cell per-bin: `b1t` ≥ control on ALL 5 windows AND ≥ +1.0 on
  at least one;
- target cell, DIRECTIONAL: cam2 EB_right total moves strictly toward
  Miovision 167 on all 3 cam2 windows, by ≥ 10 events at study_0700
  (control is +142 over);
- phantom guard: v2_phantom_diag (b1t vs control) reports ZERO new
  non-compliant phantom slots per window (twin-merge only removes
  events; a growing denominator means the harness moved something else).

**Activation guard (standing rule):** record
`result.evidence_activation` from every arm sidecar. Control states:
cam2 ACTIVATED 0.564/0.487/0.485; cam1 NOT 0.265/0.438. State flip vs
control → that window's flag-on comparison VOID; run arm + fresh base
control with `EVIDENCE_ACTIVATION_ENABLED=0` (fresh workdirs, stems
`b1tx`/`b1cx`), gate on the flag-off pair.

**Iteration budget: 2, from zero.** Iteration 2 (ONLY if G-B1a fails AND
the instrument diagnostics implicate admissions): require BOTH join and
fork collision for a pair (structural tightening, not a threshold turn);
same gates. Otherwise ledger the twin class closed at event level (the
fifth channel, and the first with a clean isolation).

## Run protocol (sequential)

Phase 1 instrument ×4 tables (gate reads cam2_0700 + cam1_1600;
cam2_1100/1600 context) → Phase 2 arm dumps `b1t`/`b1p` × 5 windows
(seconds each; writes only new-variant .tracks dirs, no parquet needed —
verified: v2a dumps have none) → Phase 3 parity checks + one b1p pass-2 →
Phase 4 five b1t pass-2s (cam2×3, cam1 0700+1600; own workdirs under
`_replay_scratch/b1_twin/`; WAL-safe copies to `b1t_cam<C>_<W>.db`;
score; delete DBs) → Phase 5 activation check + phantom diag + EB_right
totals. Runs ≈ 1.5 h; build 3-5 h.
