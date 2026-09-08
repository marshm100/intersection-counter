# CAM2 DOUBLED RIGHT TURNS (2026-09-08) — diagnosis

cam2's EB_right is the corridor's biggest single wrong cell:
  Miovision 1,217 across the day | production 1,722 | +505 OVER
And the biggest under is SB_thru: Mio 4,695, production 4,032 (-663).

## Hypotheses tested

1. MISATTRIBUTED ORIGIN (the cam5 invented-origin class — SB throughs
   booked as EB rights, which would explain both the over and the
   under at once). TESTED AND REJECTED: of 1,009 EB_right events in
   the evening window, the ground-anchored gate evidence witnesses
   880 entering over the W gate and only THREE over N. They really do
   come from the west arm. The two errors are separate problems.

2. SHAPE: these "right turns" average a net heading change of +9.5
   deg with straightness 0.855 — nearly straight, and nearly
   identical to the same approach's THROUGH (-10.8 deg, 0.923). For
   contrast the same camera's other rights bend +24.3 and +36.5 deg,
   and its EB LEFT bends -103.3 deg with straightness 0.446 (a proper
   turn shape). So the label does not match the motion. Note the
   shipped straight-fragment rule cannot reach them: their
   destination comes from a bank path fit, not a guess.

3. DUPLICATES. The loose test (coexist in time, end within 120 px)
   flags 711 of 1,009 — but that is the QUEUE TRAP the operator
   identified on cam5, where queued vehicles naturally coexist and
   end near each other. The tight test — median centre distance
   <= STITCH_STAT_DIST (35 px) across the whole shared life — flags
   155 pairs, the tightest 3-6 px apart for 166-428 frames. Queued
   vehicles sit a car length apart, so those are candidates for one
   vehicle counted twice. 155 would account for half the +310 excess
   in that window.

Note COEXISTING_TWIN_DEDUP is shipped and default ON, so these pairs
are passing it — worth checking which of its three criteria
(overlap fraction, median distance, median IoU) they slip through.

Filmed pair 4613+4616 (3 px apart for 17 s) for operator ruling:
one vehicle counted twice, or two vehicles that close?
