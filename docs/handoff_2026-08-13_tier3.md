# Handoff — 2026-08-13, Tier-3 execution + the geometry inversion

Branch `claude/accuracy-impl-2026-05-27`, pushed and in sync (HEAD
`2b5d2cb`). 947 tests green. All mechanism flags default OFF. Production
verified untouched at every block boundary (cam2 study_1600 = 6835
events; project.db mtime 2026-08-10 13:45).

## What closed today (each committed with evidence, gates pre-declared)

1. **F2M pilot + v2 — family CLOSED (2 iterations).** Real recovery
   (+2.9/+1.9 5/95 with ZERO phantom slots; 0.957 held-out precision)
   but EB_left over-counts both times. v2's origin-distrust fired
   correctly (leg-28 confusion 0.981, 101 constraints relaxed) and
   changed nothing — the prototypes carry the contamination.
2. **A1+B2 rescore-only — DEAD on direct evidence.** Flicker instrument
   failed on decoys twice (0.61 → 0.53 vs 0.05); the operator-approved
   staged falsifier then showed the boost CONVERTS into wrong counts
   (+747 surplus events, 5/95 53.4→51.9, five phantom cells). Third
   confirmation of the birth wall from a third level (ft2 volume, H1
   tracker, A1 confidence): the failing step is SELECTIVITY, not mass.
   Survivors: the tubelet linker (0.70-0.74 anchorless recovery), the
   per-camera birth-floor map (botsort 0.30 / bytetrack 0.35 / cam3
   0.18), the instrument-soundness finding (observational negatives
   cannot bound false births at detection level).
3. **cam5-ft2 — candidacy REFUSED by the blind apply gate**
   (event_flood 0.36/0.40 vs 0.15 at both windows) after the damage
   split localized study_0700's regression to morning-bin inflation
   (EB_thru 8-29/bin vs ref 0-2, fading by 08:00). The +6.8/+3.6 dev
   nets are substantially cancellation; the gate correctly refused to
   ship them. Right-turn resurrection stays real, needs selectivity.

## THE FINDING THAT CHANGES THE NEXT SESSION — the geometry inversion

`diag_cam2_leg28_2026-08-13.md`: leg-28 confusion 0.981 does NOT mean
false origin crossings. The birth-position probe (channel-free): 96% of
"confused" fulls are born EAST of the gate, upstream, exiting
EB-consistently — they ARE the genuine EB entries; the drawn (28,·)
CHANNEL POLYLINES sit off the actually-driven lanes. This explains
EB_thru 34 vs Mio 119 alongside EB_right +142 (throughs snapped into
the right channel) — the "flood" is largely misclassified throughs.
F2M's overshoot is re-explained as DWELL-BLIND double-counting
(fragments of counted queued vehicles outside the ±2 s guard).

**SUPERSEDED SAME-DAY — read diag_cam2_leg28_2026-08-13.md OUTCOME.**
The in-UI session + dry-run + gated write/restore corrected this twice
more: the operator's channels are FINE; the stored EB right path is
CORRECT; the left path has a real 36 px entry offset (faithful 670-full
replacement derived + committed, re-appliable under a replay-only
gate); the through path is missing because through journeys don't
complete as fulls (fragmentation — the selectivity wall); and the
confusion METRIC is structurally unsound as a leg-health signal (0.981
→ withdrawn; third gate-evidence-family signal to fall after G-P1 and
C-1). EB_right's +142 flood remains OPEN with geometry eliminated.

## Standing state

- Ledgered dead/closed: conservation family, twin class (5 channels),
  regime hybrid, extension line, ft2 basis (all cameras + cam5-scoped),
  A1 rescore-only, F2M (2 iterations), cardinal-balance selectors.
- Alive: the EB channel redraw (operator); A2 dual-rate motion mask and
  A4 scale-matched 1280 (Tier-3/4, un-run; re-prioritize AFTER the
  redraw since it may re-open cheaper paths); F2M revival conditions
  named (redraw + dwell-aware guard).
- Laws: activation-coupling (4 data points; standing memory),
  scoring-basis discipline, WAL-safe copies, stem-overwrite trap (bit
  an instrument this session — iteration-tag instrument stems).
- Instruments added: v2_twin_instrument, v2_flicker_instrument,
  v2_tubelet_stabilize (linker reusable), v2_f2m_pilot
  (--origin-distrust), v2_leg28_diag (generic --leg), v2_hybrid_merge
  (unused revival kit), phantom_diag --ctrl-db/--cand-db.
- Costs today: ~3 h wall, 1 tracking run, ~15 replays, zero detect
  hours, zero production changes.
