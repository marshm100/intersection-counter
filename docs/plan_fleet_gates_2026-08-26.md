# Fleet gate drawing — cams 3/4/5 measured (2026-08-26/27)

Operator drew gates on cams 3/4/5 (cam1 pending — no saved gates in
the DB at measurement time). C0 (skewed-T stem label fix, f3e4165)
landed first per the charter. Postgates snapshot:
backups/project_20260827T040144_postgates_fleet.db (the restore point
that PRESERVES drawn gates). Scratch arm: fresh workdir
fleetgates_20260826, 7 replays, stems fg_cam*_study_*.db, scores
runs/v2_week1/score_fg_*.json. Production untouched.

## Verdict table (movement bar / approach bar, arm vs shipped)

  window            arm              shipped         activation
  cam5 0700         66.4 / 50.0      66.4 / 50.0     0.342 OFF (was 0.330)
  cam5 1100         71.7 / 40.6      71.7 / 40.6     0.420 OFF (was 0.441)
  cam5 1600         63.1 / 21.9      63.1 / 21.9     0.413 OFF (was 0.402)
  cam4 0700         51.9 / 37.5      75.4 / 37.5     0.458 ON
  cam4 1100         59.6 / 66.7      73.5 / 41.7     0.540 ON
  cam4 1600         72.9 / 66.7      75.8 / 66.7     0.433 OFF
  cam3 0600 (14h)   62.5 / 14.9      72.6 / 28.0     0.547 ON

## Reading

- cam5: drawn gates did NOT lift evidence coverage over the 0.45 bar
  (the plan's "within 0.01-0.05 of the bar" hope measured false at
  0700; 1100 even dipped). Channel stayed off -> scores byte-identical
  to production. Inert: no ship, no harm.
- cam4/cam3: gates DID flip the channel on (0700/1100 at cam4; the
  cam3 14h window) — and the movement bar got WORSE exactly where it
  flipped (-23.5, -13.9, -10.1). One bright spot: cam4 1100 approach
  +25.0 (41.7 -> 66.7). cam4 1600 (channel off) moved -2.9 on the
  C0-relabel + gate-geometry effects alone.
- [inference] The cam2 gates win does not transfer bare: cam2's
  activation flip landed on months of curated paths/banks; cams 3/4/5
  have none of that supporting calibration, and cam4 is a driveway T
  whose stub geometry may not suit exits[-1] supremacy semantics.
  Same shape as the identity-stack lesson: each camera's shipped
  basis is its own compensating equilibrium; flipping one honest
  channel on redistributes attribution without fixing what it leans
  on.

## Disposition

- NOT shipped (movement floor fails at cam4/cam3; cam5 inert).
  Negative ledgered here + roadmap changelog.
- Drawn gates STAY saved in the project DB (operator work product,
  preserved by the snapshot). DORMANCY CAVEAT: any future
  Confirm & process on cams 3/4/5 will inherit these gates and the
  activation flips — do not run a production apply on these cameras
  without deciding this ledger's question first.
- cam1: no saved gates (legs still "Leg 1-4"); save outcome unknown —
  operator question open. The cam1 orphan-1100-events ruling (add
  trim vs retire the row) also remains open.
- C0 stands on its own merits (label truth; the Mio-zero phantom
  cell dies) independent of the gates decision.
