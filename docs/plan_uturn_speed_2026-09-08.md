# U-TURN SPEED SWEEP (2026-09-08) — NEGATIVE RESULT

Measurement only (scripts/uturn_speed_sweep.py). No code changed, no
flag added, nothing shipped.

## Statistic B (thirds) is DISQUALIFIED — it inverts the truth

On the operator's three ruled tracks:
              statistic A (halves)   statistic B (thirds)
  REAL u-turn        1.2                   11.6   <-- most suspicious
  THEFT fast         6.4                    8.7
  THEFT creep        2.6                    6.0
B ranks the REAL u-turn as the WORST offender. Ruled out. Only
statistic A preserves the operator's ordering, and a cut anywhere in
2.0-3.0 puts all three of his rulings on the correct side.

## But no threshold separates at fleet scale

Across cam1 x2, cam2 x3, cam3 (Miovision u-turn counts as truth):

  group          Mio   ours   T=1.5  T=2.0  T=2.5  T=3.0  T=4.0
  Mio says ZERO    0     27       3      5     10     10     19
  Mio says N>0    41     22      10     13     14     17     19

At T=2.5 the rule kills 17 of 27 phantoms — and 8 of 22 REAL u-turns
with them. There is no cut where the zero-cells collapse while the
positive cells hold.

## Two findings that matter more than the threshold

1. COVERAGE: only 49 of 144 u-turn events have a resolvable journey
   span, so a speed test could never act on two thirds of the class
   however it is tuned.
2. THE CLASS IS TWO-SIDED. We do not merely over-count u-turns; on
   the approaches where they are REAL we badly UNDER-count:
     cam1 1600 EB: Miovision 13, ours 1
     cam2 1600 SB: Miovision 12, ours 6
     cam3      NB: Miovision  8, ours 8 (the only matched cell)
   A speed VETO only attacks the over-count and makes the
   under-count worse. Any real fix has to explain both sides.

## Recommendation

BANK the class. The operator's speed intuition is correct and
ordering-valid on every case he ruled, but it cannot be turned into a
fleet threshold on this evidence, and a veto would deepen the
under-count on the approaches where u-turns are genuine. Reopening
needs the under-count understood first — why cam1-1600 finds 1 of 13
real u-turns — because that is the same evidence problem from the
other direction.
