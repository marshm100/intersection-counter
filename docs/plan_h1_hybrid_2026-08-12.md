# Block H1 — per-regime tracker hybrid (base throughs + OC-SORT turns), GT-FREE
# (2026-08-12)

Tier-1 block 4 of the options-inventory campaign (category H — "in-repo,
pre-V2, never re-tested under V2").

## Premise (in-repo evidence, pre-V2)

`scripts/hybrid_prototype.py:1-17` and
`docs/ocbot_hybrid_results_2026-06-01.md`: ByteTrack/BoT-SORT gets THROUGHS
right (SB-thru 425 ≈ manual 424) but fragments TURNS; OC-SORT recovers
TURNS (~2×; NB-left 97 ≈ 96) but over-counts throughs via ID switches (631
vs 424). cam2/4/5 once shipped their best numbers on the hybrid recipe.
Block 0 located today's damage in TURN cells — cam2 EB_left [Mio, ours]:
229/215, 326/247, 496/335; NB_left 411/348, 450/328, 420/373; cam4 NB_left
20/1, 17/1, 23/8; cam5 NB_right 21/5, 26/4, 35/0.

**The GT dependency this block drops:** the shipped combiner's turn gate
consumed Miovision volumes (`scripts/apply_hybrid.py:35-65`,
`_bot_turn_keep_ids` ← `manual_per_minute`). Under V2, pass 2 already
provides the GT-free equivalents: its own corpus bank
(`two_pass.py:991-995`) and the scale-1 turn merge
(`pass2_replay.py:100-104`). Measurement stays Miovision-scored (dev
yardstick); the MECHANISM is blind-deployable.

Enabling facts (verified 2026-08-12): `ocsort` is a first-class backend
(`backend/services/tracker.py:309-317`; boxmot 18.0.0 imports clean);
OC-SORT never decodes frames → pass-1 from the detection cache is pure
CPU. NO V2-era ocsort tracks exist; the old `%TEMP%` study DBs are purged.
Fresh pass-1s are required; detection is already paid.

## Design

- **Variant P (primary, pre-declared):** global movement partition — base
  DB supplies `through` + `u_turn` (u-turns are 8 events/2 h at cam2;
  moving them is a variable with no measurable upside); oc DB supplies
  `left` + `right`.
- **Variant F (fallback = the only iteration 2):** left-only swap — oc
  supplies `left`; `right` stays base. Both named deficits are lefts, and
  cam2 EB_right is a +142 gate-geometry OVER-count: importing oc rights is
  the risky half of the swap. One variable separates P and F.
- **NO cross-backend dedup** (measured harmful 2026-06-01: 154
  false-deleted throughs; "Use --no-dedup"). The per-bin gate is the
  conservation arbiter. REPORTED instead: per-movement insert/drop
  counts; co-temporal overlap diagnostic (inserted oc turn events with a
  kept base event on the same origin leg within ±3 s — an UPPER BOUND on
  double-counts); v2_phantom_diag damage split vs control.
  (`v2_chain_dup_probe` is only valid within one backend's arms — base
  chain maps don't cover foreign oc track ids; noted limitation.)
- **`scripts/v2_hybrid_merge.py` (NEW):** `--camera --window --base-db
  --oc-db --out [--take left,right] [--overlap-window-s 3.0]`. WAL-safe
  base copy via sqlite3 `conn.backup()` (several scratch DBs carry live
  -wal sidecars); ATTACH oc read-only; column list from `PRAGMA
  table_info(vehicle_events)` minus `event_id` (schema-drift-safe, the
  hybrid_prototype pattern); DELETE base kept rows with `movement IN
  (take)`; INSERT oc kept rows with `vehicle_track_id + 1,000,000`
  (uniqueness + provenance); oc rejected rows never imported; base
  rejected rows left in place; writes `h1merge_cam<C>_<W>.json`
  diagnostic beside the out DB.

## GATES — declared before any run; numbers final

Controls: committed `score_d1ctrl_cam2_study_*` = 53.4/42.9/44.0;
`score_ga3ctrl_cam4_study_*` = 75.4/69.4/75.8; `score_ga3ctrl_cam5_
study_*` = 66.4/71.7/63.1.

**G-H1p (basis parity, precondition):** re-run base arms (`h1base`) score
CELL-FOR-CELL equal to the committed d1ctrl JSONs on all 3 cam2 windows.
Mismatch = basis drift since Block 1 → STOP, re-baseline; nothing else is
interpretable (and B1's use of committed controls must be re-checked if
close in time). This is why bases are re-run (~25 min total) instead of
reusing the extant `d1_conserve/ctrl` DBs: re-running PROVES today's
calibration still reproduces the committed controls.

**G-H1k (kill gate — read from score JSONs BEFORE any merge code is
built):** on cam2, deficit cells {EB_left, NB_left}, per-cell
err = |v2 − mio| from the totals tables: `h1oc` must cut the summed err
(2 cells × 3 windows; control mass ≈ 486 events) by **≥ 10%** vs
`h1base`, AND be lower on ≥ 2 of 3 windows. FAIL → the hybrid premise is
dead under the V2 chain; block STOPS with zero merge code and no cam4/5
runs (iteration 1 spent). (10% is the minimum "premise alive" signal
against the historical 2× claim.)

**G-H1a (primary, variant P):**
- 5/95: `h1` ≥ d1ctrl on all 3 cam2 windows AND ≥ +1.0 on one;
- target cells: EB_left err strictly reduced vs control on ALL 3 windows;
  NB_left err reduced on ≥ 2 of 3;
- phantom guard: non-compliant phantom slots ADDED ≤ RECOVERED (the merge
  inserts events; denominator growth is the known trap — gated, not
  narrated);
- watch cell (reported, not gated): EB_right — any worsening is called
  out in the verdict.

**G-H1b (extension, cam4+cam5, ONLY if G-H1a passes):** hybrid arms ≥
their ga3ctrl controls on all 6 windows (strict non-regression, 0.0
tolerance). Per-camera kill-read first on {NB_left, EB_right} (cam4) /
{NB_right, EB_right} (cam5). Merge base source: ga3ctrl DBs allowed IFF
each sidecar's stored `calib_fingerprint` equals today's for that camera
(free basis-hygiene proof); else re-run those bases too.

**Activation guard (standing rule):** record
`result.evidence_activation` per arm. cam2 controls ACTIVATED
0.564/0.487/0.485 (the last two only +0.037 above the 0.45 bar); cam4/5
study_1100 NOT activated at 0.442/0.441 (−0.008/−0.009 — the likeliest
flips). An ocsort dump changes track composition → coverage moves. State
flip vs control → that window's flag-on comparison VOID; supplementary
`EVIDENCE_ACTIVATION_ENABLED=0` arm + control pair (fresh workdirs, stems
`h1ocx`/`h1basex`), gate on the flag-off pair.

**Iteration budget: 2, from zero.** Iteration 2 = variant F, ONLY if P
fails G-H1a while G-H1k passed (re-merge only, no new pass-1/pass-2;
stems `h1f_*`). Otherwise ledger: "the regime hybrid does not survive the
V2 chain / per-bin bar", with the 2026-06 result recorded as
non-transferring.

## Run protocol (sequential; disk check before cam4/5: ≥ 8 GB free)

Phase 0: build merge script + phantom-diag extension; copy detection
caches to the new variant names (the re-detect trap):
`<hash>/study_<W>.parquet → oc_study_<W>.parquet` + same for
`.meta.json` (cam2 ×3).
Phase 1: 3 cam2 ocsort pass-1s, DETACHED (Start-Process + log + Monitor;
budget 10-45 min each): `py -X utf8 scripts/dump_raw_tracks.py --project
97a7849a --camera 2 --variant oc_study_<W> --start-hms <07:00:00 |
11:00:00 | 16:00:00> --minutes 120 --backend ocsort`. Fresh variants —
NEVER a bare re-run on an existing variant (silent overwrite; the
mode="w+" memmap at two_pass.py:726-728).
Phase 2: 6 pass-2s (h1base + h1oc per window), own workdirs under
`_replay_scratch/h1_hybrid/`; WAL-safe copies to `h1base_cam2_<W>.db` /
`h1oc_cam2_<W>.db`; score; delete twopass_ originals. KEEP the h1base/
h1oc DBs until merges are done.
Phase 3: G-H1p, then G-H1k from the six score JSONs. Stop on fail.
Phase 4: merges (variant P) + scores (stems `h1_cam2_<W>`), overlap +
phantom diagnostics, G-H1a. Delete arm DBs after.
Phase 5 (conditional): cam4/5 extension per G-H1b.

---

## RESULTS (2026-08-12)

**G-H1p PASS — exact cell-for-cell match at all three windows** (h1base
53.4 55/103, 42.9 45/105, 44.0 48/109 == committed d1ctrl). Doubles as
the end-to-end OFF-parity proof for the C-1 backend change on real data.

**Activation guard FIRED at study_1100/1600**: the ocsort dumps drop
origin-evidence coverage below the 0.45 bar (0.472 / 0.397 / 0.388 vs
base 0.564 / 0.487 / 0.485) — the THIRD instance of the coupling measured
today (extension raises it, ft2 sinks it, ocsort sinks it): **the
tracker choice controls pair activation.** Default-flag comparisons at
those two windows are VOID; supplementary flag-off OC arms run
(`h1ocx`, EVIDENCE_ACTIVATION_ENABLED=0), paired against today's
committed flag-off base controls (`e4ctrlx`, identical env, replay
determinism proven by G-H1p's exact reproduction).

**G-H1k FINAL — flag-state-matched pairs:**

  window                        base err   oc err   verdict
  study_0700 (act-ON pair)         77        39     oc LOWER (-49%)
  study_1100 (flag-off pair)      520       438     oc LOWER (-16%)
  study_1600 (flag-off pair)      384       469     oc NOT lower (+22%)
  SUMMED                          981       946     cut +3.6%

Windows condition: 2/3 PASS. Magnitude condition: +3.6% < +10% **FAIL**.
Cell detail at the failure: at 1600 OC's EB_left collapses to 207 (mio
496; base 368) — in the densest window OC under-counts the very turn
cells it recovers elsewhere. The premise ("OC recovers turns ~2x") is
WINDOW-DEPENDENT under the V2 chain, not uniform: halves the deficit at
0700, inverts at 1600.

## VERDICT — G-H1k FAILED; block STOPS before any merge ran

LEDGER: **the per-regime tracker hybrid does not survive the V2 chain /
per-bin bar at cam2.** The 2026-06 event-level result (cam1, old chain,
GT-fed turn gate) is recorded as non-transferring. Iteration 2 (variant
F) is NOT triggered — its precondition was G-H1k passing. No cam4/5 runs.
Two independent disqualifiers:
1. the deficit-error cut (+3.6%) is far under the pre-declared minimum
   premise-alive signal (+10%) and inverts at the heaviest window;
2. the ocsort dumps stand the evidence pair down at 2 of 3 windows under
   the shipped config — the hybrid would surrender the pair's measured
   +4.0/+3.3 there before the turn swap even starts.

No window-scoped revival is named: selecting mechanisms per window by GT
performance is the overfit the prime directive forbids, and the blind
selector family for exactly this was disqualified by G-P1.

Note on order: `scripts/v2_hybrid_merge.py` was pre-built during a
compute wait BEFORE the kill-gate read and NEVER RAN. It is committed as
the revival kit per the retirement convention (code remains
revival-ready); the kill gate still did its job — zero merge runs, no
cam4/5 compute, ~2 h saved.

The sweep's literature note stands for the checkpoint: per-movement
SOURCE selection is validated in the literature and per-regime
PARAMETERS (speed-conditioned Kalman covariances) are the cheaper
validated fallback family — either would be a NEW mechanism with its own
plan+budget, not this block's iteration 2.
