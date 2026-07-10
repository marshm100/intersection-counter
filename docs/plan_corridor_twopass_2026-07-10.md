# Plan — corridor completion on two-pass + MASTER_PLAN refresh (2026-07-10)

Extends the two-camera result (cam2 full-day, cam1 07:00 — both beat their
live baselines) to cams 5/4/3, then brings MASTER_PLAN current. The loop per
camera is the established measure-then-apply discipline; Miovision scores,
never feeds.

## Per-camera gates (pre-declared — no post-hoc goalposts)

| cam | dump | recipe check | apply gate (per-approach MAE, same window) | expected friction |
|---|---|---|---|---|
| 5 | study_0700 ✓ | bytetrack = calib default ✓ | ≤ live 8.7% (A4a already measured 7.1%) | none — formality via the endpoint path |
| 4 | study_0700 ✓ | bytetrack ✓ | ≤ live 4.6% | **likely FAIL** — A4a run 2 was 5.1%, cause = the leg-34 calibration defect. If it fails: NO apply; cam4 stays live until the operator leg-34 review, and the corridor ships PARTIALLY migrated — an honest state, recorded. |
| 3 | study_0000 (full day) ✓ | bytetrack ✓ | 07:00–09:00 ≤ live 3.2% (the corridor's best camera — regression is a hard stop), 11:00/16:00 reported | full-day bank build + replay is the biggest pass-2 yet (1.07M points, 47k tracks) — minutes-scale still expected; full-day apply replaces cam3's whole table |

Each apply is window-scoped with a backup; the queue rebuilds itself via the
apply path (S4/S5 rows included). Run through the `/two-pass/process`
endpoint path (`TWO_PASS_ENABLED=1` env for the session) — every corridor
apply from here on doubles as stage-3.4 dry-run evidence.

## Riders (small, alongside the waits)

1. **cam3 scoped tier-1 parity** — `pass2_parity.py` grows a `--window` so the
   reference retrack covers 07:00–09:00 instead of the dump's full day (a
   24 h reference retrack is pointless compute). Same |Δ| ≤ 2/cell bar.
2. **apply-reuse fix** — `run_pass2(apply=True)` reuses the existing working
   DB when the dump meta + corpus bank are unchanged (halves apply wall time;
   today it recomputes).
3. **cam1 stale `balanced_960_skip1.meta.json`** — the one-line correction,
   finally.

## MASTER_PLAN refresh (after the applies land)

- **New §2d** — the two-pass shipping arc: A2 parity (3 cams |Δ|=0), A4a merge
  (scale-1 corpus expecteds; extrapolation retired), B-VAL→B4 (queue validated;
  T2+T4 caught at rank 1; T1 dissolved because its mechanism got FIXED), cam
  results table, and the now-standing rules: drawn channels never enter a
  fitted bank's attribution set (measured 4×); two-counter QA needs the second
  counter within ~2× accuracy (S3 blocked).
- **§4 re-sequenced** to what actually remains: stage 3.4 (trim→window + card
  UI + detection-at-ingest + operator dry-run → flag flip), C-worklist polish,
  the attribution research walls (cam2 NB-left / EB split — the §2b coverage-
  aware matcher direction inherits them), §3-D labeling, D-low-light, F2/F3,
  S1 sensitivity.
- Retirements ledger updated (dedup, bank-D, box-clip counter, ReID rollout,
  scaled expecteds) — one place to see what NOT to retry.

## Deliverables

Applies (or documented holds) for cams 5/4/3 + a corridor scoreboard table
(live vs two-pass per camera, one honest cut each), the refreshed MASTER_PLAN,
and a session-close commit. Negative outcomes (a cam4 hold) are deliverables.
