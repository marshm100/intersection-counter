# QD — discharge-event counting (plan + pre-declared gates)
# (2026-08-18, night; the block E4R's measured verdict points at.
#  Research basis: MASTER_ACCURACY_ROADMAP §7b #1. Status: PLANNED —
#  gates declared BEFORE any build; build starts after the running
#  auto-cal frees the repo.)

## The measured problem (all numbers cam2 study_1600, committed in
## runs/v2_week1/e4r_miss_audit_2026-08-18.json + this doc)

Conversion funnel of all 10,196 dump tracks in the window:
  counted 6,727 · eventless:no_crossing 2,033 · eventless:entry_only
  563 · eventless:full 359 · eventless:exit_only 206 · too_short 308.

The QD-recoverable class = eventless tracks that CROSS AN EXIT MOUTH
MOVING (median crossing speed 4.2 px/fr): **565**, splitting into:
  - **280 with NO event row at all** (median 8.7 s, p25 5.6 s tracks
    — pure pipeline drops; the clean recovery target);
  - 285 with REJECTED rows (deliberate dedup/quality verdicts — a
    SEPARATE reviewed pool; naive recovery risks double-counting).
Window net deficits: EB −287 · SB −164 · (WB +51 over). The clean
280 ≈ half the window's net volume gap. The 2,033 no-crossing
fragments are UNREACHABLE by any counting policy → Q1
reconciliation's territory, not this block's.

## The mechanism (production-precedented: GRIDSMART count-on-exit,
## NCHRP WOD 436 stop-bar volume zones)

For tracks that cross an exit mouth OUTBOUND and MOVING and produce
no kept event: emit a recovered event. Origin resolution order:
(1) the track's own backward trace reaching an entry mouth (the 359
eventless-fulls class — origin self-evident); (2) channel/lane
membership of the trace; (3) unresolved-origin bucket (reported,
never guessed into a movement).

## Pre-declared gates

- **G-QD-1 (same-vehicle guard / double-count kill gate):** a
  recovered event is admitted ONLY if no kept event exists at the
  same exit mouth within ±T_dwell of the crossing whose track
  overlaps spatially (the queue-slot test). T_dwell frozen by blind
  sweep on non-GT windows BEFORE any scored run (gate-discipline
  workflow). On the three GT windows, recovered-event double-count
  rate (recovered event whose vehicle already counted) must be
  ≤ 2% of recoveries, measured by manual spot-review of a random 50.
- **G-QD-2 (score gates, replay, both bars):** per window,
  approach-bar ≥ live + 3.0; movement-bar ≥ live − 0.0 (no
  regression); no HEALTHY movement cell |err| grows > 5 (the g4
  pattern; non-compliant-cell regressions batch to operator ruling).
- **G-QD-3 (apply path):** QD candidates ADD events → zero-mass does
  NOT hold → they go through the ORIGINAL recall-mode apply gate
  (event_flood / headroom guards), NOT the AG2 reattribution mode.
  No apply outside the gate, ever.
- **G-QD-4 (rejected-pool separation):** iteration 1 touches ONLY
  the no-row class. The 285 rejected-row tracks are a SECOND
  iteration with their own gate (re-adjudicating dedup verdicts
  against the embedding evidence — E1's machinery).
- Two-iteration budget, standing.

## Order of work

1. Origin-recoverability audit on the 280 (trace/channel resolution
   rates) — read-only, feeds G-QD-1 constants. Extend to cam1/4/5
   windows + the other cam2 windows.
2. Build the recovery pass as a replay-side candidate composer
   (scratch DBs, like the PPT composer — no backend changes until
   gates pass).
3. Blind-freeze T_dwell + guards; GT-window scores; candidacy;
   operator-ruled applies per window.

## Interaction with the running calibration wave

QD counts exit-mouth crossings — mouth geometry comes from the
calibration. If the auto-cal wave ships new mouths at any camera, QD
constants for that camera re-derive (activation-coupling law). Run
QD's scored iteration AFTER the wave's verdict at each camera, or
pin to current geometry and re-run.
