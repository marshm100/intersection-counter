# Handoff — V2 campaign state after blocks 1+2 (2026-08-07)

Everything committed on `claude/accuracy-impl-2026-05-27` through
`affb74c` (NOT pushed). 896 tests green. Production tables untouched by
the whole campaign; all V2 flags DEFAULT OFF.

## Where the campaign stands (one paragraph)

The operator's bar: reach/exceed Miovision under an independent manual
referee, on 640x480, no footage upgrade (MASTER_PLAN §2e). Blocks 1+2
built the V2 harness (replay-parity proven), shipped three measured-safe
mechanisms behind flags (endpoint extension, census-dosed claim demotion
+ contrast guard + base census, merge rescue), ledgered eight dead
channels, and closed with the G-A3 corridor sweep: blanket application
FAILS (cam1/4/5 regress) but cam2 (+2.4/+6.7/+3.5) and cam3 daylight
(+8.5 on 479 bins — the campaign's largest win, over the SHIPPED table,
blind) prove the bundle where journeys are missing. THE APPLICABILITY
LAW (11 windows): wins where journeys are MISSING, losses where
completion MANUFACTURES journeys; every loss carries the +25-37%
event-flood signature the blind conservation guards already flag.

## THE NEXT BLOCK (start here): the Phase-1 APPLY GATE

Per-window candidate-vs-incumbent adjudication under the BLIND guards
(conservation/event-flood/reverse-balance/star-census — all existing
machinery), as PRODUCT architecture wired into run_pass2/apply:
- Validation set ready-made: 11 adjudication ground truths in
  `_replay_scratch/v2_week1/` (ga3ctrl_cam{1,3,4,5}_*.db vs
  twopass_cam{C}_v2c_*.db + the cam2 trio) — the gate must pick
  correctly at all 11 BLIND (no Mio in the gate itself; Mio only
  validates the gate's verdicts).
- Then: bundle rides the gate (cam2+cam3 apply, cam1/4/5 stand down);
  FM51 held-out adjudication joins validation; the same gate closes the
  blind-product-test wound (product can no longer overwrite curated
  judgment: every apply must win its window).
- Also pending in that architecture: dispositions-as-product-state and
  the schema-drift bug fix (pass2:'current' must fingerprint schema —
  int2's Error card from 07-31 is still the live evidence).

## Operator decisions open

1. Push the branch (6 commits local-only).
2. V2 flag posture: recommendation stays default-OFF until the apply
   gate exists.
3. Blind-run rollback (2026-08-01 tables still in production;
   per-camera backups in data/projects/97a7849a/backups/) — note cam3's
   V2 result (72.6) now EXCEEDS both the blind-run table (64.1) and the
   pre-blind daylight state; the apply-gate block will supersede this
   decision naturally.
4. FM51 held-out sweep scheduling.

## Mechanics for the next session

- Docs chain: MASTER_PLAN §2e (authoritative) -> plan_v2_week1_verdict
  (block 1) -> plan_v2_block2_2026-08-06 (block 2 + verdict) -> this.
- Scripts: scripts/v2_*.py (18); scratch: _replay_scratch/v2_week1;
  dumps: v2c_* variants alongside originals in detections/.
- Flags: V2_DEMOTION / V2_MERGE_RESCUE / V2_TIMELOCAL (dead) — env, all
  default off; TWO_PASS_ENABLED default on (product).
- Run pattern for long jobs: Start-Process detached + log file + Monitor
  (backgrounded tool tasks get reaped; detached survives).
- ortools is DEV-ONLY (numpy must stay 1.26.4 — the 2.5 incident).
- The app server may still be running on port 5000 (PIDs from 07-31);
  kill by command-line match before serving fresh.
- Dev scoring: scripts/v2_score_dev.py <working.db> (the only Mio
  reader); py -X utf8 always (cp1252 console).
