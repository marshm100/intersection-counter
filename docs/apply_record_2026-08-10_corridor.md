# Production apply record — corridor, under the Phase-1 gate (2026-08-10)

> **AMENDMENT 2026-08-11 — the CAUSE recorded below is wrong for cam3; the
> OUTCOMES all stand.** This record says "Endpoint extension — the largest
> contributor". Measured by the confound split
> (`plan_v2_confound_split_2026-08-11.md`), cam3 study_0600's +8.5 is
> extension **-3.0** and evidence pair **+11.5** — extension hurt there and
> earned the win only by lifting blind coverage 0.431 -> 0.525 past the
> activation bar, buying cam3 admission to the gate+posterior pair. cam2's
> two applied windows ARE genuinely extension (+7.5 at study_1100, +2.4 at
> study_0700); cam2's activation state never varied, so those are clean.
> Nothing here needs rolling back — all three windows measured better and
> still do. What changes is the explanation, and therefore what to build
> next: the prize at cam3 is the PAIR, not extension.

Operator-approved. THE FIRST V2 ACCURACY GAINS TO REACH PRODUCTION.
Every window went through `adjudicate_apply` (audit trail in
`apply_adjudications`); each apply took its own automatic pre-apply
backup of project.db.

## Pre-flight (read-only, runs/v2_week1/preflight_production_incumbents.json)

The 11/11 validation had compared candidates against SCRATCH CONTROLS.
Re-run against the LIVE tables — the real incumbents — the verdicts are
identical: apply at 3 of 12 windows, stand down at 9. Production
incumbents match the scratch controls row-for-row, which is the proven
replay parity holding, so the validation transfers rather than being
re-earned. Script kept: `scripts/v2_apply_gate_preflight.py`.

## Applied (3 windows), measured vs Miovision

  window              before   after    delta   gate
  cam3 study_0600      64.1     72.6    +8.5    gate_pass
  cam2 study_0700      54.4     55.8    +1.4    gate_pass
  cam2 study_1100      45.7     50.4    +4.7    gate_pass

cam3's +8.5 on 464 scored bins is the campaign's largest single win, and
it SUPERSEDES the disputed 2026-08-01 blind-run table (64.1) — the
standing rollback decision for cam3 is resolved by being overtaken.

## Stood down (9 windows) — and production is provably untouched there

cam1 x2 (saturated_geometry + event_flood), cam2 study_1600
(no_headroom + event_flood), cam4 x3 (no_headroom + event_flood),
cam5 x3 (event_flood). Verified after the fact: cam2's 16:00 window still
holds 6835 events, NOT the candidate's 7279, and cam1/4/5 totals are
unchanged. The gate refused to ship the very regressions the G-A3 sweep
measured (cam4 -23.7, cam1 -15.7, cam5 -11.5).

## Pre-apply checks run on every window

- calibration fingerprint of the artifact == current camera calibration
  (no drift since the 2026-08-06 validation);
- artifact's `vehicle_events` schema == production's (32 cols) — the
  check `schema_fingerprint` encodes, done explicitly because these
  sidecars predate that field;
- a stale 07-31 server holding port 5000 was stopped first (no -wal
  pending), per the standing mechanic.

## What is NOT shipped, and the coherence caveat

THE BUNDLE IS NOT A FLAG FLIP. Endpoint extension — the largest
contributor — is a DUMP TRANSFORMATION produced by a dev script
(`scripts/v2_extend_dump.py`), never wired into the product path.
V2_DEMOTION / V2_MERGE_RESCUE remain DEFAULT OFF, and turning them on
alone would run pass-2 against BASE dumps and would not reproduce these
gains. What happened here is an operator-run application of three
prepared, validated artifacts.

Consequence: the product's own bookkeeping tracks base variants and
cannot regenerate these three tables from the UI. If someone re-runs
"Confirm & process", the base-dump result meets the gate as a candidate
against the now-improved incumbent, fails `no_headroom`, and stands down
— the applied work is protected, which is exactly the wound the gate was
built to close. Wiring extension into the product is its own block.
