# Handoff — 2026-08-11, the options-inventory campaign

Branch `claude/accuracy-impl-2026-05-27`, **pushed and in sync with origin**
(HEAD `8073b55`). 929 + 9 tests green. Every mechanism flag default OFF.
Production `vehicle_events` untouched all session — verified, not asserted
(cam2 `study_1600` reads 6835 over frames 1439950-1619950 under the
`window_cell_counts` predicate; `project.db` mtime still 2026-08-10).

## Where the campaign stands, in one paragraph

The V2 campaign's central negative result turned out to be CONFOUNDED, its
largest shipped win turned out to be mis-attributed, and the mechanism it
was built on is now closed on evidence. An audit
(`docs/options_inventory_2026-08-11.md`) found roughly half the research
architecture unbuilt plus a large body of work retired by the standing
TWO-ITERATION BUDGET — a policy stop, not an exhaustion proof. The operator
approved implementing all of it in tiers. **Tier 1 is 1 of 4 blocks done**;
that block failed its gate and, in failing, corrected the retirement reason
on record for the mechanism it tested.

## What this session established (each is committed with evidence)

1. **The G-A3 "applicability law" was measured on a confounded experiment**
   (`3c6830b`, `docs/plan_v2_confound_split_2026-08-11.md`). The chain
   compared "base dump + flags OFF" vs "v2c dump + flags ON" and moved FOUR
   variables; the undeclared fourth is the evidence-activation flip, because
   extension lifts blind coverage past the 0.45 bar at every camera that was
   standing down. All 12 windows re-run with the pair forced off.
   **cam3's +8.5 — applied to production, recorded as "extension, the
   largest contributor" — is extension −3.0 and evidence pair +11.5.**
   Extension's value there was as a COVERAGE LEVER, not recall. cam2's
   applied gains ARE genuinely extension (its pair state never varied).
   Nothing needed rolling back; the explanation changed.
2. **The extension line is CLOSED** (`089d1d7`). Three variants measured:
   both-directions, `--skip-full` (LEDGERED — correct by design, ineffective
   in fact), forward-only (the best: cam1 study_1600 flips to +0.9, cam4
   study_1100 halves). Deciding number: **at 2 of 3 windows no extension at
   all still beats forward-only.**
3. **A previously undocumented mechanism**: extension REWRITES the
   origin/destination attribution of 5-7% of tracks that were ALREADY
   counted, at every camera. Orthogonal to the recall gain it was built for.
4. **G-P1 FAILED** (`2ef62de`): corridor link agreement cannot select where
   the evidence pair helps — 7/12 sign agreement (chance is 6/12), Spearman
   −0.210, and it misses on the three biggest windows. The failure is
   systematic, not noisy: the pair binds origins to gate-evidenced legs and
   links compare exactly that cardinal balance, so the signal measures how
   much the origin distribution MOVED, not whether it moved the right way.
   **That disqualifies the whole cardinal-in/out-balance family.**
5. **Block D1 FAILED** (`8073b55`, `docs/plan_v2_conserve_activation_2026-08-11.md`)
   — see below. It corrects the retirement's own stated reason.

## The plan and our position in it

Approved plan (tiers, with a checkpoint after Tier 1). Operator decisions
2026-08-11: bar is **raw pipeline 5/95** with no human-queue credit;
near-zero human labor on a new site; corridor-only; **two-iteration budget
still binds but COUNTS FROM ZERO** on each revival; research sweep runs
BEFORE the tubelet build; execute in tiers with a checkpoint.

  TIER 1 (cheap, high-evidence)
    Block 1  D1  conservation pass under activation      DONE — G-D1b FAILED
    Block 2  E4  ft2 re-test (G-A4)                      <-- NEXT, zero detect hours
    Block 3  B1  structural twin test                    pending
    Block 4  H1  tracker hybrid, re-measured GT-free     pending
  TIER 2
    Block 5  G   second research sweep (queued-vehicle)  before Tier 3
  TIER 3
    Block 6  A1+B2 tubelet stabilization + zero-velocity
    Block 7  A2  motion-fused detection
  TIER 4  opportunistic: C-revival candidates, A3 split, A4 scale-matched 1280

Full detail: the approved plan file, plus
`docs/options_inventory_2026-08-11.md` for the complete option list with
categories A–H.

## Block D1's result, because it shapes Block 3/4 too

`census_expecteds` + `conserve_pass` were retired for ONE stated reason —
not blind-deployable at low evidence coverage. The activation precondition
decides exactly that, shipped 2026-07-27, is default ON, and governs the
REPLAY only, so `conserve_pass` had never run. This block pointed it at
them. Built behind `CONSERVE_ON_ACTIVATION` (default OFF), measured on BASE
dumps with all V2 flags off (the shipped configuration); cam2 is the whole
surface since it is the only camera clearing 0.45.

  window            CTRL           CONS        delta  rejected  vs-legacy
  cam2 study_0700  53.4 55/103   47.6 49/103   -5.8     275       225
  cam2 study_1100  42.9 45/105   40.0 42/105   -2.9     219       173
  cam2 study_1600  44.0 48/109   43.1 47/109   -0.9     436       354

NOT the aggregate-vs-per-bin trap — checked deliberately; a consistently
computed aggregate error moves the same way at all three windows. The
original doc predicted the failure verbatim ("on cam2 it rejects the
posterior's CORRECT event whenever the chain's legacy event is itself a
misattributed flip"), and the rejection split confirms it.

**It corrects the retirement's stated reason.** cam2 has HIGH coverage and
is the doc's own success case, and the pass still loses there on the
customer bar. Coverage was not the only defect; "legacy always wins" is a
second, independent one the activation precondition does not touch.

**Iteration 2 (1 of 2 spent)** is the already-named revival candidate C-1,
"evidence-ranked chain arbitration" (`MASTER_PLAN:738`), now specified by
measurement: on a MIXED chain rank by evidence instead of assuming legacy is
correct. Gate pre-declared in the block doc.

## NEXT ACTION — Block 2, the ft2 re-test (zero detection hours)

Why it is free: cam2's `ft2_study_0700/1100/1600` caches already exist on
disk, and cam3's `study_0600` was ALREADY detected on ft2 (it is the
promoted `balanced` default). No re-detect needed.

    py -X utf8 scripts/v2_run_pass2.py --camera 2 --variant ft2_study_0700 \
        --workdir data\projects\97a7849a\_replay_scratch\e4_ft2
    py -X utf8 scripts/v2_score_dev.py <that>/twopass_cam2_ft2_study_0700.db

Compare against the stock-basis control (`d1ctrl_cam2_*` from Block 1 — base
dumps, flags off, same environment). G-E4a: does ft2 still amplify each
camera's defect under today's chain (the 2026-07-24 finding)? Scope to cam2;
cam3 has no STOCK counterfactual and building one costs ~19 h.

**Traps for this block specifically:** `study_HHMM` variant names encode NO
detection basis — cam3 `study_0000` is stock@960 while `study_0600` is
ft2@640, same scheme, and nothing validates it. Read the `.meta.json`
sidecar (`model` / `imgsz` / `confidence`), never the name. Also add `ft2_`
to the prefix tuple in `scripts/v2_score_dev.py:172` if the scorer cannot
resolve the window (it currently strips `v2a_..v2f_` only).

## TRAPS — each of these has already cost, or nearly cost, a wasted run

1. **`sidecar_reusable` does NOT encode env flags.** A second arm sharing a
   workdir silently returns the FIRST arm's result. Give every arm its own
   `--workdir`.
2. **`v2_score_dev.py` writes `runs/v2_week1/score_<db_stem>.json`.** Reusing
   a stem OVERWRITES committed evidence. Use a distinct stem per arm
   (`d1ctrl_cam2_...`, `armC_cam1_v2c_...`); the scorer parses
   `stem.split("_")[1]` for the camera and `split("_",2)[2]` for the variant.
3. **`result.replay.conservation` is nested under `replay`**, not at the top
   level of `result`. A top-level check cannot distinguish "never ran" from
   "ran and reported".
4. **`two_pass.ORIGIN_POSTERIOR_ENABLED` is a module-global imported at
   `two_pass.py:43`.** Patch `backend.services.two_pass`, not
   `backend.config`. `CONSERVE_ON_ACTIVATION` is read through the config
   module at call time, so the two knobs are patched differently.
5. **`conserve_replay_additions` rejects only `_ADDITIVE` sources** — a
   strict no-op on an all-direct replay whatever the flag says.
6. **Background Bash tasks are REAPED at turn boundaries** in this harness
   (measured). Long jobs: `Start-Process` detached + log file + `Monitor`.
   Do not use `ps -W | grep <script>` as a liveness check — Git Bash `ps`
   does not expose Windows command lines and it will report a healthy chain
   as dead.
7. **`run_pass1(resume=False)` SILENTLY OVERWRITES an existing dump slot**
   (`two_pass.py:688-703`); the recipe-drift hard error at `:591-599` fires
   only in resume mode. Relevant to Block 4.
8. **A new variant name without a copied parquet triggers a full re-detect**
   (`cache_exists` checks file + sidecar only) — ~2.8 h per cam2 window.
   Copy `<base>.parquet` AND `<base>.meta.json` first.
9. **Memory: ~7.8 GB total, ~700 MB free under normal load.** Run
   measurements sequentially; cam3's 14 h window peaks around 600 MB.
10. **`v2_extend_dump.py` writes a single mutable slot per variant.** A
    heading-lock run already clobbered a stack run there once. `--skip-full`
    now refuses to write `v2c_`; pass `--out-prefix`.

## Instruments built this session (all committed, all reusable)

- `scripts/v2_confound_table.py` — basis-aware A/C/B decomposition. The
  basis differs per camera and the script encodes it: at cam1/3/4/5 the pair
  is OFF in arm A so extension = C−A; at cam2 it is already ON so
  extension = B−A. Reading cam2's C−A as "extension" inverts the answer.
- `scripts/v2_phantom_diag.py` — classifies slots a candidate ADDS
  (phantom / recovery / miss) and reports the DAMAGE SPLIT. Built because
  phantom MASS is not phantom DAMAGE: `tolerance(0)` is 5/bin, so most
  invented slots pass.
- `scripts/v2_chain_dup_probe.py` — chain destruction + duplicate population
  per arm.
- `scripts/v2_pair_selector_probe.py` — the G-P1 selector test.
- `scripts/v2_extend_dump.py --skip-full / --out-prefix` (default OFF, path
  byte-identical).

## Standing mechanics

- Dev scoring: `scripts/v2_score_dev.py` is the ONLY module that reads
  Miovision. `py -X utf8` always (cp1252 console).
- All measurement: `run_pass2(apply=False)` into
  `data/projects/97a7849a/_replay_scratch/<block>/`.
- Apply gate validation: `py -X utf8 scripts/v2_apply_gate_validate.py
  --project 97a7849a` (corridor 11/11 binding; FM51 exits 1 BY DESIGN).
- Tests: `python -m pytest backend/tests/ -v` (baseline 929, +9 from D1).
- Logs are NOT committed (matching the existing `runs/**/*_run.log`
  precedent); chain scripts and score JSONs ARE.
