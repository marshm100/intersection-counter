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

---

## AMENDMENTS + FREEZE RECORD (2026-08-18, before any scored run)

- **Sweep-basis amendment (declared before the sweep ran):** no
  non-GT-hour dumps exist, so T_dwell freezes by LEAVE-ONE-CAMERA-OUT
  median knee across the other cameras' windows, with procedural
  GT-blindness (the sweep path imports nothing Miovision).
- **G-QD-0 verdict: PASS with a documented refinement** — the
  composer buckets rejected-row tracks FIRST, so its recoverable
  class (280 at cam2-1600) equals the committed no-row class exactly;
  counted 6,727 and too_short 308 byte-match. The 565 union of the
  original audit = 280 no-row + 285 rejected (203 fulls + 82
  exit-only), reconciled.
- **Phase-A result:** every admitted candidate resolves via its OWN
  TRACE (the channel rung fired zero times — moving exit-onlys are
  rare and channel-claims never matched) → iteration 1 is exactly
  the eventless-fulls recovery, origin gate-proven on every
  candidate. Pools: cam1 36/133 · cam2 161/69/152 · cam4 83/79/88 ·
  cam5 253/319/436 · FM51 31/0.
- **T_dwell FREEZE: 3.0 s for all four corridor cameras** (LOCO
  medians identical). ANOMALY LEDGERED: all knees (3.0-4.0 s) sit
  above the pre-declared [1.0, 2.0] s band — echo exit-time offsets
  run multi-second at these sites; error direction is
  over-suppression; spot review is the acceptance backstop.
  Record: runs/v2_week1/qd_freeze.json (geom hashes pinned).

## PHASE C VERDICT (2026-08-18, late night) — two windows PASS G-QD-2

Composed at frozen T_dwell 3.0 s, scored both bars, all 11 corridor
windows + FM51-am. AMENDMENT 2 (declared on the g4 catch): recovered
u_turns are DEFERRED to iteration 2 — the _reverses 120-degree test
cannot separate a genuine u-turn from an ID-SWITCH SPLICE (the g4
check caught SB_uturn 4->10 vs Mio 2 at cam2-1100 with all six
passing _reverses); appearance evidence (E1) is the discriminator.

  window       ins   movement          approach          G-QD-2
  cam2-1100     17   55.0 -> 55.0 (=)  46.9 -> 50.0 (+3.1)  PASS (g4 clean)
  cam4-1100     31   73.5 -> 77.6      41.7 -> 50.0 (+8.3)  PASS (g4 clean)
  cam1-0700     14   +0.5              -3.1               FAIL (approach)
  cam1-1600     20   -2.2              =                  FAIL (movement)
  cam2-0700     28   =                 =                  FAIL (no gain)
  cam2-1600    152c  gate-blocked window (headroom+flood; scored-only)
  cam4-0700     27   +2.4              -4.2               FAIL (approach)
  cam4-1600     26   -1.2              +8.3               FAIL (movement)
  cam5 x3    64/63/65 movement -3.8/-6.6/-4.8 (mis-gated labels
             inherited from cam5's broken geometry — the wave
             interlock case; RETRY POST-WAVE)              FAIL
  FM51-am/pm  31c/0   not composed (apply story separate)

Recall-gate preflight, cam2-1100 final 17-event candidate:
gate_pass (recorded below). cam4-1100 passes G-QD-2 but its apply
gate fails on INCUMBENT headroom — LEDGERED gate-blocked pending
census growth from the calibration wave; re-preflight after each
wave apply.

REMAINING before the cam2-1100 apply: G-QD-1 acceptance (operator
50-sample spot review — runs/v2_week1/qd_review_cam2_study_1100.json)
+ operator apply approval + composer landing into scripts/ with the
12-test suite (waits for the auto-cal job to free the repo).
