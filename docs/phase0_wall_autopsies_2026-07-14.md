# Item-8 phase 0 — wall autopsies (2026-07-14)

Loss ledgers from the full-day pass-1 dumps + applied events, box-clip as
the §3-B diagnostic, Miovision as dev scorer only. The join is validated:
it reproduces the published signatures exactly (NB-left 0.31, EB split
0.24/1.46). Scripts: scratchpad `phase0_cam2.py` / `phase0_cam4.py`
(session artifacts; method documented here).

## Wall A — cam2 NB-left (29→28), 6 h: Miovision 1281, events 394 (0.31)

| bucket | n | share | class |
|---|---|---|---|
| never a complete box journey | 585 | 46% | tracking/fragmentation floor |
| box-complete, NO event emitted | 288 | 22% | attribution-side DROP (recoverable) |
| box-complete, STOLEN | 243 | 19% | attribution (recoverable) |
| box-complete, merged away | 86 | 7% | turn-merge collateral |
| attributed correctly | 79 | 6% | — |

Thief cells for the 243 stolen: **208 → SB-right (27→28)** — an N↔S ORIGIN
FLIP with the same exit leg — plus 31 → NB-thru. Two consequences: (1) the
celebrated SB-right 1.07 "fix" is partially FED by stolen NB-lefts (its
overshoot above 1.0 is consistent with this); (2) the attribution-reachable
pool is 617 vehicles (48%) — a perfect matcher on existing journeys caps
NB-left recall at ~0.54. **The "attribution wall" label was half right:
half the loss is capability-class (never journeyed), and that half routes
to the §3-D/tracking track, not to any matcher.**

## Wall B — cam2 EB (origin 28), 6 h: Mio thru 749 / right 1217

- Box-clip completes only **20 EB-thru journeys ALL DAY** (and 228 right);
  **1510 origin-28 tracks die inside the box** — split almost exactly
  50/50: 745 before the thru/right divergence (arc ~85 px in; sep >40 px),
  765 past it. **Shape matching on full journeys is DEAD for EB-thru —
  ceiling ~3% of Miovision.** Any honest mechanism must classify
  TRUNCATED tracks.
- Where the events actually come from: truncated origin-28 tracks are
  attributed as **SB-thru 27→29 (454!)**, no-event (386), SB-left 27→26
  (166), SB-right 27→28 (163), EB-right 28→29 (128)… — the same N↔S
  origin flip as Wall A, at scale. The applied bank has **no 28→26 path
  at all** (the S4 bank-hole flag's mechanism), so EB-thru exists only as
  fallback events (179 day total).
- The winnable pools: (i) 765 past-divergence deaths — discriminable by
  death position relative to the divergence; (ii) the 745 pre-divergence
  deaths are shape-undecidable BY CONSTRUCTION — only an explicit
  posterior (corpus-window supports, scale-1) can allocate them; (iii)
  killing the origin flips removes the SB-thru/SB-left contamination.

## Wall C — cam4 EB-left (34→33): ours 90 vs Mio 64 over covered hours

Birth census: **71/90 (79%) born mid-block on the arterial** (closer to
the 33/35 axis than the driveway mouth; birth distance from the mouth p50
204 px), 9 at the mouth, 10 elsewhere; 76% share one first-segment bearing
bin — a single coherent class, exactly the §2d artifact-review story. The
mid-block-birth origin gate has a well-defined target.

## THE CROSS-CUTTING FINDING (the decision checkpoint's headline)

All three walls share one failure axis: **origin is CLAIMED without entry
evidence.** Tracks that never crossed an entry gate (late births, mid-box
births, mid-block births) still get an origin from anchor/shape proximity
— producing the N↔S flips (208 NB-left→SB-right, 454 EB→SB-thru), the
driveway grabs (71 on cam4), and cross-cell contamination that corrupts
even "fixed" cells. This is one mechanism family, not three.

## Decision — phase-1 order (revising the plan's candidate list)

1. **Origin-evidence gating + explicit posterior (unifies candidates 1+2).**
   A track whose birth lies inside/past the box (no entry-gate crossing)
   may not take a hard origin from proximity; it gets (a) the box-crossing
   origin when one exists, else (b) a posterior over origins from corpus
   supports + death/exit geometry, else (c) origin-uncertain → flag queue.
   Targets: Wall A steals (243), Wall B's SB contamination (454+166+163),
   Wall C's class (71). The (s,d) machinery serves this (s-span coverage,
   death-position features) rather than being a standalone matcher.
2. **The unclaimed-288 diagnosis** (Wall A's biggest single attribution
   pool): why does replay emit NO event for box-complete NB-left journeys
   (insufficient-data? quality gate? scorer rejection?) — one session,
   pure diagnosis, likely cheap recall.
3. **EB-thru allocation** (pre-divergence posterior) — only after 1, since
   killing the origin flips changes the EB pool's composition.
4. Wall A's never-journeyed 585 → routed to the capability track
   (fragmentation/ReID-class work), NOT matcher work. CHARACTERIZED.

Gate discipline unchanged: each mechanism prototypes on cam2's 07:00
window, holds out 11:00/16:00, freezes constants, then the five-camera
blind sweep vs current baselines (cam3 3.2 / cam4 live 4.6 tripwires).

## Cautions recorded

- SB-right (1.07) and SB-thru (0.85) will MOVE when the flips are fixed —
  score whole-camera cells, never one cell in isolation.
- The dump→event join keys on vehicle_track_id per window; finalize-gap
  ID splits make it approximate (single-digit noise, not material to the
  buckets above).
- The 86 merge-eaten NB-lefts say the volume gate's corpus expecteds are
  low for that cell — recheck AFTER the flips are fixed (the corpus bank
  discovers from the same flipped tracks).
