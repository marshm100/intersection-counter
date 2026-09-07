# ANTI-THEFT CAMPAIGN (2026-09-06) — G-LT-1 declared

Diagnosis: the vanish-zone census (27,516 moving mid-scene deaths,
12 windows) + the operator's six filmed-scene rulings: ~71%+ are
thefts (occluded vehicle emerges, the moving track is handed over,
then dies). Light is the accomplice, not the killer. Operator design
rule: emergence spawns a NEW track, never a hand-over; mid-scene
births inherit origin from the concealer.

Build: EMERGENCE_GUARD (pass-1 tracker veto, default off) +
CONCEALER_ORIGIN_INHERITANCE (pass-2 origin tier, default off).

## G-LT-1 (declared before any scoring; two-iteration budget)

Arms: (a) baseline = shipped basis standings; (b) eg_ dumps + stock
pass-2 (isolates the guard); (c) eg_ dumps + concealer inheritance.
All scored by v2_score_dev on scratch stems.

PASS: corridor movement pct RISES in arm (c) vs baseline; no window
drops > 1.0 pt; changed worst-cells trace to theft-class cells;
emergence_vetoes and n_origin_concealer_inherited nonzero and sane;
gate_breaks (post-hoc severs) DROP. Watch stop-fracture and twin
dedup interactions with the new births. Approach bar never decides.

Ship only on PASS + operator go (before/after reel of the filmed
theft scenes included in the review).

## Verdict

(to be recorded after the runs)

## G-LT-1 verdict — iteration 1: MISS (recorded 2026-09-06)

Corridor movement 77.1% (baseline) -> 53.8% (guard) / 53.7%
(guard+concealer). Every window but cam1-0700 (+0.7) fell; cam1-1600
86.2 -> 42.0, cam3 83.7 -> 47.3. The concealer tier is ~neutral on
top (its +events showed it firing, but it cannot rescue what the
guard breaks).

MECHANISM (measured): the veto over-fires by orders of magnitude at
production noise — 764,573 veto events on cam2-1600 (2h) and 1.44M
on cam3 vs ~1.5-5k plausible real thefts per window. Honest
detections routinely violate the motion bound (occlusion-truncated
boxes shift centers; queue compression; near-field extent jitter
beyond the 0.35 floor). Fragmentation followed: cam3 46,388 ->
56,070 tracks; cam1 20,238 vs 7,493 base with rows HALVED (cam1 also
carries a possible config confound - its promoted basis is fl-era).
The counting pipeline's rescue equilibrium is tuned to the current
fragmentation regime; the guard shattered that regime. Echoes the
G-ID-1 identity-stack MISS.

Flags remain default OFF (nothing shipped). Iteration 2 (if taken,
the declared budget's last): a COMPETITIVE veto — fire only when the
disputed detection has a strictly better-fitting alternative owner
(another track's projection or a fresh-birth case), never on an
uncontested claim; drop the graced-lost extension to first pass
only. Unit scenarios all still hold.

## G-LT-1 verdict — iteration 2: MISS (recorded 2026-09-07; budget exhausted)

Corridor movement 77.1 -> 70.6 (guard) / 70.1 (+concealer). The
discipline fixed the fragmentation catastrophe (iter-1 53.8), and
the per-window split is the real finding:
  WINS:  cam1-0700 64.2 -> 70.5 (+6.3!), cam2-1100 70.4 -> 72.1
  NEAR:  cam3 83.7 -> 82.9
  LOSSES: cam1-1600 86.2 -> 47.9 (the best window collapsed; the
  botsort+reid recipe), cam2-0700 -11.9, cam2-1600 -9.2

Gate letter: corridor must rise, no window may drop > 1.0 — MISS.
Flags remain OFF; nothing shipped; eg_ dumps retained as scratch.

BANKED LEARNINGS (third identity campaign, same lesson): (1) the
theft diagnosis is real and PAYS where theft density is highest
(cam1 mornings +6.3 proves the mechanism); (2) blanket tracker-level
identity enforcement fights the downstream rescue equilibrium and
loses its winnings in the best-tuned windows; (3) any future revival
should be PER-WINDOW (calibration knob, ship only where it wins) or
appearance-informed (the light-accomplice finding: position alone
cannot separate a thief from noise at sub-box distances).

## Per-window ship candidate REFUSED (2026-09-07, worst-cells law)

cam1-0700's +6.3 does not survive the cell table. The pct gain is
substantially scoring slack: the guard MINTS small phantom movements
(SB_uturn 20 vs Mio 0; SB_left 11 vs 1; NB_right grows 72->86 vs
Mio 3) whose 2-3/bin volumes pass the +-5 rule slack as "compliant"
cells (scored cells 81 -> 95). Meanwhile the REAL deficits worsened:
NB_thru 1692 -> 1674 vs Mio 2141, SB_thru 1636 -> 1575 vs 1756.
Only EB_left/NB_left truly improved. The movement bar was gamed the
same way the approach bar was in the cam5 phantom lesson — one level
down. NO SHIP. The campaign closes as a clean negative.

The real cam1-0700 disease the table exposes: ~450 missing NB
through vehicles (21% deficit) and ~180 SB — consistent across every
bin, i.e., systematic coverage loss, not thefts. That is the
detection/birth-wall class, not an identity class.
