# Production apply record — PPT-2 re-attribution, cam2 study_1600
# (2026-08-13)

Operator-approved ("ok go for it"). THE FIRST PRODUCTION ACCURACY
CHANGE SINCE 2026-08-10, and the largest single-window production
improvement of the campaign. Applied through the audited path with a
fresh record=True adjudication under the newly validated GATE-AG2
reattribution mode (docs/plan_gate_ag2_2026-08-13.md, G-AG2-v 6/6).

## Applied (1 window), measured vs Miovision

  window            before   after    delta   gate
  cam2 study_1600    44.0     49.5    +5.5    gate_pass_reattr

Mechanism: PPT-2 position-based path-over-time re-attribution
(plan_t3_ppt_reattr_2026-08-13; the operator's design principle — the
movement is the path of the car over time, channels are layout
guidelines only). 143 of 6,835 kept events re-decided (2.1%), ZERO
events added or removed, every EB (origin-28) cell byte-identical (the
image-space-unresolvable pair frozen by design), every moved event's
proven gate endpoint verified untouched BY THE GATE ITSELF
(endpoint_integrity, gate-side recomputation from the window's own
dump). Held-out instrument precision 0.967 at 92% coverage
(split-half, the window's own full journeys — GT-free end to end).

## Process (the standing checks, all run)

- Server stopped first (2026-08-10 precedent); no pending -wal.
- Pre-checks: schema 32==32 cols; window kept-mass 6835==6835.
- Fresh adjudication AT APPLY TIME, record=True → apply_adjudications
  trail: apply [gate_pass_reattr].
- Pre-apply backup: backups/20260813_151203_pre_twopass_cam2.db
  (+ rotation, keep 12).
- Swap via _apply_window_events (the shipped primitive; window-scoped
  by crossing timestamp).
- Post-verify: study_0700 5815 OK, study_1100 4426 OK; study_1600
  kept 6835 with (tid, origin, dest, movement) MULTISET exactly equal
  to the candidate; live-table score 49.5 (54/109) confirmed.
- Candidate: p1_live_cam2_study_1600.db — composed ON the live table
  (event-id aligned; track-id parity live-vs-control verified
  multiset-exact beforehand).

## Deferred, recorded

- FLAG QUEUE not rebuilt: rebuild_flags consumes pass-2 borderline
  rows that a re-attribution candidate does not carry. The window's
  existing flags reflect pre-apply movements for the 143 moved events.
  Rebuild rides the next full pass-2 apply of this window, or a
  dedicated flags-refresh block if the operator wants it sooner.
- The bundle-coherence caveat from 2026-08-10 applies unchanged: this
  is an operator-run artifact apply; "Confirm & process" would meet
  the gate as a fresh candidate against the improved incumbent and
  stand down (the protection working).

## Named next candidates (in order)

1. Compose-on-live PPT-2 for cam2 study_0700 and study_1100 —
   re-attribute the APPLIED tables (their events came from v2c-based
   artifacts; the v2c dumps exist for track lookup + prototypes).
   Expected shape per the on-base measurements: +5 to +8 per window.
2. PPT instruments at cam1/4/5 (the mechanism is camera-agnostic;
   G-PPT-i per camera decides).
3. cam3 (its 0600 window already sits at 72.6; instrument first).


---

## ADDENDUM 2026-08-14 — second apply: cam2 study_1100 (50.4 -> 55.0)

Operator-approved with explicit confirmation (the moved-share cap had
been re-frozen 0.025 -> 0.05 after this candidate first missed it — by
the declared choice rule over both validated positives, re-validated
8/8 incl. the new N6 runaway negative; plan_gate_ag2 records the full
trail). Same audited path via the generalized
scripts/v2_apply_reattr.py: server quiesced (NOTE: killing the uvicorn
parent orphans the reload WORKER holding the socket — netstat showed a
stale dead-parent PID while python 23056 held the inherited handle;
kill the worker too), fresh record=True adjudication
[gate_pass_reattr], backup 20260814_085707_pre_twopass_cam2.db, swap,
post-verify exact (0700 5815 OK, 1600 6835 OK, 1100 kept 4426
multiset-MATCH), live-table score 55.0 (60/109) confirmed.

  window            before   after    delta   gate
  cam2 study_1100    50.4     55.0    +4.6    gate_pass_reattr

cam2 production now: 55.8 / 55.0 / 49.5 (was 55.8 / 50.4 / 44.0 two
days ago). study_0700's compose-on-live candidate FAILED (e2) on
NB_left double-correction (413->498 vs Mio 411 — PPT re-attribution
overlaps the 2026-08-10 pair lift on that basis) and is LEDGERED; a
saturation-aware iteration is future work with its own gate.

## Corridor-wide instrument sweep (2026-08-14): G-PPT-i PASSES
## EVERYWHERE

  cam1 study_0700  0.9775 @ 0.948     cam1 study_1600  0.9642 @ 0.814
  cam4 study_0700  0.9709 @ 0.879     cam4 study_1100  0.9912 @ 0.860
  cam4 study_1600  0.9831 @ 0.919     cam5 study_0700  0.9520 @ 0.779
  cam5 study_1100  0.9830 @ 0.935     cam5 study_1600  0.9564 @ 0.870

Counting blocks at cam1/4/5 are the named next round — each with its
own declared gates (per-camera freeze analysis first: does any camera
carry a cam2-EB-like unresolvable pair?), then candidacy through the
validated AG2 mode.
