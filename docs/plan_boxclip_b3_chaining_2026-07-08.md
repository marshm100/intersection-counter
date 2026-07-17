# Plan — box-clip B3: global fragment CHAINING (2026-07-08)

Stage B (efd88c0) reached net −11.8% / MAE 15.9% with three located deficits:
SB-thru −399 + SB-right −308 (truncation mass in 4,504 no-crossing stubs + 848
attribution rejects), EB-thru −118 ↔ EB-right +156 (template bias: EB-thru has ~3
full journeys so no discovered channel), WB 8.7% (attribution added to a clean
approach). All three share one root: fragments of ONE vehicle are handled as
independent tracks by separate heuristics (stitch, same-cell pairing) that each
cover only a slice of the break modes.

## The redesign: one mechanism instead of three

**Chain globally, then classify chains.** Build a directed graph over ALL track
records (full, entry-only, exit-only, no-crossing; too-short excluded):

- Edge A→B iff B plausibly continues A — the PROVEN stitch rules, now applied
  to every pair, not just entry×exit:
  - moving break: gap ∈ (−0.5 s, 3 s], birth-death distance ≤ 70 px
  - stationary break (stop-bar red): A ends <0.4 px/frame → gap ≤ 50 s, ≤ 35 px
- Greedy resolution on (dist + 0.5·gap): each track ≤1 predecessor, ≤1
  successor; time-ordered, so no cycles. Candidate search via birth-frame
  searchsorted window (12,815 tracks — no all-pairs).
- Merge each chain into ONE virtual track (concatenate points in time order)
  and re-run classify() on it. A far-field SB stub + mid-box piece + exit piece
  becomes ONE track that crosses both gates → a full journey, counted once,
  GEOMETRICALLY — no statistical pairing needed.

This subsumes: B1 stitching (a 2-chain), the same-cell attr pairing (an n-chain
resolved before attribution), and the attributed-stub-vs-counted-full double
count (the stub chains into the counted journey and is consumed).

## Order of operations (the reorder matters)

1. classify raw tracks (unchanged) → records
2. **chain → merged virtual tracks → re-classify chains**
3. **re-discover channels from post-chain full journeys** — chaining should
   mint full EB-thru journeys, giving the cell a data template where it had ~3
   (the EB-right +156 / EB-thru −118 mirror is a discovery-coverage artifact)
4. attribute still-truncated chains (entry/exit-only) — unchanged scoring:
   discovered-first channels, direction penalty, ≤30 px + 0.7 margin
5. no-crossing chains: attribute ONLY if arc length ≥ 80 px (bank builder's
   min-path) and the fit clears the same bar — these are vehicles nothing else
   counted; anything chainable was consumed in (2)
6. all guards stay: u-turn dwell/excursion/lane-shift/opposite-lane-cluster,
   jitter collapse

## Anti-double-count: structural + measured
Chains consume fragments before anything is counted, so the failure mode
narrows to breaks EXCEEDING the chain rules (moving gap >3 s). Diagnostic
(reported, not assumed): count attributed no-crossing chains whose time window
and channel span plausibly overlap a counted same-cell journey (±5 s) —
"suspicious" metric; if SB-thru overshoots mio with high suspicious counts,
the chain gap needs widening, not the attribution gate loosening.

## Ablation matrix (full trim + 30-min cut, same scorer)
1. --no-chain --no-attribute = stage A (regression check: must reproduce)
2. chains only (--no-attribute): how much the geometry alone recovers
3. chains + attribution, no no-crossing (step 5 off): main configuration
4. + no-crossing attribution: the SB recovery test — watch the suspicious metric

Success: beat the live baseline (net −4.5%, per-approach MAE 9.8%) or minimum
SB < 15% with NB still PASS, WB back ≤ 5%, u-turns ≤ 5 total. Then the gate
call + freeze all constants for the cam3–5 blind generalization run.

## Non-goals
Unchanged: no GT in the pipeline; no per-camera tuning (all constants stay
geometric and camera-agnostic); no app wiring yet.
