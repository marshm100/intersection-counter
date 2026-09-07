# CAM1 MORNING RE-DETECT (2026-09-07) — G-C1-1 declared

Disease (from the anti-theft cell table): cam1-0700 misses ~450 NB
through + ~180 SB, a steady 15-21% per-bin shortfall. Cause
candidate (dump meta): the morning basis is yolo26s@960 while the
same camera's evening basis (86.2) is yolo26l@1280.

## D0 (pre-GPU decision point)

Screenline census on the CURRENT morning dump (atr_counts, the
G-ATR-1-validated counter): S-leg inbound vs Mio NB total (~2,530);
N-leg outbound vs Mio NB_thru (~2,141). Low entry = detection;
entry fine + exit low = far-field death (still detection); both
fine = PIVOT to attribution forensics, no GPU spent.

## G-C1-1 (declared before any scoring; two iterations)

Basis arm: l1_study_0700 = detect-at-ingest under counted_path
(yolo26l@1280 conf 0.10 skip 1), camera's own tracker recipe —
ONE variable. PASS = ALL of: movement pct rises materially;
NB_thru + SB_thru deficits shrink; NO phantom minting (sub-10-Mio
cells passing on +-5 slack are not wins; NB_right-style growth is a
fail); approach reported, never decisive. Worst-cells table
mandatory. Ship (B3) only on PASS + operator go, via the cam1-1600
per-window promotion flow with backups + pre_l1_* rename-aside.

## D0 result (recorded 2026-09-07): GO

Screenline census, current yolo26s@960 basis, 07:00-09:00:
S-leg in 1,354 vs Mio NB ~2,530 (54%); N-leg out 868 vs Mio
NB_thru 2,141 (41%); N-leg in 727 vs Mio SB ~1,859 (39%, far
field); S-leg out 1,472 vs 1,859 (79%, near field). Tracks are
born late and die early — the far half of the frame is
under-detected. Counted NB events (2,197) EXCEED entry crossings
(1,354): the rescue machinery papers over entry loss, but through
completion caps at what survives to the far gate. Same geometry
scores 86.2 on the big-detector evening basis. GPU spend justified.

## Verdict

(to be recorded)

## Iteration 2 (threshold law) result — recorded 2026-09-07

Operator ruling implemented (ground-contact crossing anchor,
GATE_GROUND_ANCHOR): WB_right phantoms 68 -> 1 (Mio 1, PERFECT);
NB_right 147 -> 111; NB_thru recovered further 1846 -> 1920 (deficit
449 -> 221); movement 61.0 -> 61.8, approach 59.4 -> 64.5.

Two remaining mechanisms, both measured:
1. RESIDUAL NB_right (111 vs Mio 3): the drawn driveway line lies ON
   the far road surface, so far-lane vehicles' ground contacts
   genuinely cross it at ground level. The anchor cannot fix a line
   that overhangs the roadway — the line must move to the driveway's
   actual mouth (operator calibration surface).
2. ACTIVATION KNIFE-EDGE (the mapped hazard, live): probe coverage
   fell 0.439 vs the 0.45 bar -> evidence channel flipped OFF for
   the window, costing SB_thru 1741 -> 1551. A 1.1% miss on a fixed
   bar, not a defect of the anchor.

G-C1-1's two iterations are spent. Both remaining moves are operator
calls: the gate redraw (his surface) + one post-redraw re-run.

## THE STRAIGHT-FRAGMENT RULE — G-SF-1 declared (2026-09-07)

Operator ruling: a vehicle that never curved cannot be booked as a
turn on a guess. Measured: all 111 surviving phantom driveway turns
are dead straight (0.975 / +1.5 deg) and every one came from the
softmax destination fallback (no bank path into leg 25 exists, no
gate crossed). Rule: guessed-dest turns (softmax writer, no
posterior source, no gate-dest agreement) with straightness >= 0.95,
|net heading change| <= 5 deg, >= 10 points reroute to the
straight-continuation leg (bank through path, else opposite
cardinal; validated through + not a bank turn pair) or drop.
Evidence-when-available deviation recorded in the plan: the window
runs evidence-off (coverage 0.439), so the rule fires on geometry
alone there; real driveway entries are Mio-scale ~3/window.

G-SF-1 PASS = movement pct rises materially vs 64.2; NB_right
collapses toward Mio 3; NB_thru rises; genuine turn cells move only
by the measured collateral (~2); no phantom-slack cells; approach
never decisive. Ship = the whole cam1-0700 package on operator go.

## G-SF-1 verdict

(to be recorded)
