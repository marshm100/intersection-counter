# ATR site operating flow (the tube-count replacement)

Product ack: 2026-09-06 (demo workbook ATR_demo_TownEast_2026-05-12).
Validation: G-ATR-1 PASS in docs/plan_atr_2026-08-28.md — NB screenline
8/8 fifteen-minute bins within the 5%/5 Miovision bar.

## Direction semantics (operator ruling, 2026-09-06)

A screenline on a cardinal leg carries BOTH directions of travel, and
the bound direction is always the opposite of the cardinal: on the
North leg, Southbound = moving from the north toward the south,
Northbound = coming from the south heading north. The workbook columns
are named by direction of travel, never in/out.

## Placement law

Screenlines go in the NEAR or MIDDLE of the frame only. The far band
is where tracks have not been born yet (the Town East SB gate captured
43% for exactly this reason). A purpose-aimed midblock camera does
this naturally.

## New-site steps (all existing surfaces)

1. Ingest the video (videos tab; the filename parser stamps the
   recording start time).
2. Save labels — this creates the intersection + camera. Set
   leg_count = 2 (the road's two directions).
3. Calibrate: two legs with correct CARDINAL directions (they drive
   the column names), and draw the screenline gate on each leg you
   want counted. Near/mid frame only (placement law).
4. Add trims (or accept the proposals) — trims define the study
   windows the export resolves.
5. Run PASS-1 ONLY via the per-camera two-pass endpoint (counted_path
   mode; chunked and resumable).
6. Download: GET /projects/{pid}/intersections/{iid}/export/atr.xlsx

## NEVER

- NEVER run Confirm & process on a midblock project. Pass-2 routes
  through derive_movement's degenerate 2-leg branch and writes junk
  left/right events. ATR is pass-1 + the standalone counter only.

## Workbook contents

Per study window: a Volumes sheet (15-min directional rows including
zero bins, bold hourly subtotals, window totals, per-direction peak
hour + PHF, rolling hourly totals at every 15-min step) and a Classes
sheet (car/truck/bus/motorcycle per direction per 15-min interval).
Disclosure printed on the cover: video classifies by visual length
class, not axle count.

## MVP limits (disclosed)

- First video per camera only (long single files fine).
- Multi-day = one intersection card per day (existing convention).
- Speed percentiles and axle classes: chartered, not built
  (docs/product_gap_tmc_atr_2026-08-23.md).
