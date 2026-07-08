# Plan — box-clip pass-2 STAGE B: stitch + attribute truncated tracks (2026-07-08)

Stage A (committed 218711e) counts only tracks that cross two gates: net −37% on the
full 7–9 AM cam2 trim, but WB already at 5.4% AVG|err| — the counting mechanics are
proven; the missing mass sits in 2,206 entry-only + 964 exit-only + 4,504 no-crossing
tracks. Stage B recovers the single-gate population. GT-free throughout: geometry +
the operator's drawn channels only.

## Order of operations (each step measured before the next is trusted)

### B1 — in-box stitching (BEFORE any attribution — the anti-double-count step)
A vehicle whose track breaks inside the box yields an entry-only piece A and an
exit-only piece B; attributing both separately counts it twice (the old EB +769
mechanism). So stitch first, attribute leftovers:
- **Moving break** (occlusion mid-box): B born within 70 px of A's death, time gap
  in (−0.5 s, 3 s]. Direction not enforced (turns bend in-box).
- **Stationary break** (track lost at the stop bar through a red): A ends
  near-stationary (<0.4 px/frame) → allow gap up to 50 s but distance ≤ 35 px (a
  stopped car resumes where it stopped). Known residual risk: a follower creeping
  into the leader's spot — accepted for the prototype, measured by phantom checks.
- Greedy match on (distance + 0.5·gap) score, each piece used once. Stitched pair
  = ONE event: origin = A's gate, dest = B's gate, timestamp = A's origin crossing.

### B2 — channel-shape attribution of the remaining singles (§2c order of authority)
The known gate pins one endpoint; the drawn channels disambiguate the other:
- exit-only (dest gate known): score the track's EARLY 60% of points (the
  discriminating part — channels converge at the shared exit) against each drawn
  channel INTO that gate; mean point-to-polyline distance.
- entry-only (origin known): symmetric, LATE 60% against channels OUT of the origin.
- Accept only if best ≤ 30 px (§2b: cars sit 12–25 px on drawn curves) AND best <
  0.7 × second-best. Otherwise leave uncounted and REPORT the reject count —
  honesty over guessing.
- Timestamps: entry-only keeps its origin crossing; exit-only uses its birth frame
  (late by the pre-birth transit — small vs 15-min bins; noted, not hidden).

### B3 — no-crossing stubs: DECISION POINT, not automatic
Only if SB/EB remain materially short after B1+B2. Upstream approach stubs can chain
to already-counted tracks (same vehicle) — any use of them needs full chain-stitching
with a counts-once rule. Defer until the B1+B2 numbers say whether it's needed.

## Measurement matrix (scripts/measure_cam2_reid_spike.py, full trim + 30-min cut)
1. stage A (have): net −37.1%, MAE 36.2%
2. B1 only (--no-attribute): isolates stitching's recovery + phantom pressure
3. B1+B2 (default): the stage-B number vs the live baseline (net −4.5%, MAE 9.8%)

Watch cells for regressions: WB stays ~5%, u-turns stay ~0 (guards from stage A),
NB-right stays ≤ a few. Success = SB/EB recover materially with no phantom inflation;
target remains ≤5% per approach blind.

## Explicit non-goals
- No GT anywhere in the pipeline (scorer only).
- No per-camera parameter tuning against Miovision; all thresholds are geometric
  (pixel/frame scales) and stated in code as constants.
- No app wiring yet — prototype on the cam2 trim; wiring is MASTER_PLAN §4 item 5.
