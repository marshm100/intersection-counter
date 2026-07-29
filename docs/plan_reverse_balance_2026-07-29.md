# PLAN — REVERSE-BALANCE PEAK-AWARE APPLICABILITY (2026-07-29)

The named fix from the acceptance-composition sim
(plan_3b_validation_2026-07-28, closing finding): reverse_balance is
red on ALL FIVE corridor intersections over peak-window claims — real
directional peaking, exactly its docstring's warning — so it adds no
discrimination and solely determines several gate compositions. It is
also the noise line on every Stage-4 traffic light ("Directional
balance looks off" everywhere).

## The defect, precisely

`applicable` keys on the event WINDOW SPAN (≥ 6 h). A study of three
peak trims spans 07:00–18:00 = 11 h → applicable — but the COVERED
footage is peak windows, where AM-in/PM-out asymmetry is expected
traffic. Span is the wrong question; coverage SHAPE is the right one.

## The frozen rule (pre-declared)

reverse_balance is APPLICABLE only when the claim scope is genuinely
continuous-day-shaped, i.e. ALL of:
1. NO declared trims (declared trims = an explicit peak-window claim →
   informational, with a note saying so);
2. the processed coverage forms a SINGLE continuous block (15-min
   occupancy buckets; a >20-min hole splits blocks — the same gap
   convention as spot segmentation). Multiple disjoint blocks =
   peak-shaped coverage → informational;
3. the window ≥ 6 h (the existing floor, kept).
cam3-class full-day runs stay fully applicable — a day-long imbalance
is a genuine review prompt and remains one.

## GATE (pre-declared)

(a) unit tests: trims → info; disjoint blocks → info; single long
block → applicable; short window → info (existing).
(b) production before/after (read-only): per intersection, the
reverse_balance item verdict and the composed overall — reverse_balance
must stop being the SOLE determinant anywhere; NO other item's verdict
may change; intersections whose overall was solely rb-determined move
to what their remaining items say. Evidence table in this doc.
(c) full suite green.

## VERDICT (2026-07-29 — GATE MET; 892 tests, +3; evidence
runs/stage5_phantom/reverse_balance_ab.json)

**One measured revision on the record**: the first cut split coverage
blocks at the 20-min spot-gap convention — and shredded int3 (the one
full-day camera, which the pre-declared design says STAYS applicable)
into 8 phantom blocks on overnight ZERO-TRAFFIC lulls. Measured gap
structure: int3's largest lull = 53 min; the true processing gaps at
int4/int5 = 120/180 min. BALANCE_GAP_SPLIT_SEC frozen at 90 min — in
the measured gap with margin both ways.

**Production before → after (the applicability rule isolated by patch,
same basis):**

| int | rb before | rb after | why | overall after |
|---|---|---|---|---|
| 1 | fail | info | declared trims | **review** (rb was its sole fail) |
| 2 | fail | info | declared trims | fail (other items) |
| 3 | fail | **fail** | APPLICABLE — full-day scope kept | fail |
| 4 | fail | info | 3 disjoint peak blocks | fail (other items) |
| 5 | fail | info | 3 disjoint peak blocks | **review** (rb was its sole fail) |

The check now discriminates: red only where a full-day claim makes
imbalance a genuine review prompt (int3), silent where peaking is
declared or structural. No other gate item changed (independent
computations; verified in the evidence). The Stage-4 traffic lights
lose their universal "directional balance" noise line; the export
compositions at int1/int5 move to what their remaining items honestly
say.
