# Plan — the claim-time origin veto (origin-grab phase 1, 2026-07-17)

Mechanism ② with its motivating data (`phase0_origin_grab_2026-07-17.md`):
a side-leg ORIGIN CLAIM is a mid-block grab when the track is born ON a
crossing through-road and away from the claimed mouth's throat. Phase 0
measured the boundary on 394 claims across two sites; this plan wires it
as a veto at CLAIM time and gates it. Full discipline: flag OFF by
default, constants FROZEN from phase 0, ablation on FM51 replays, then
the frozen-constant blind corridor sweep before any default flips.

## The rule (frozen — nothing here is tunable during ablation)

For candidate origin leg L and track birth b (= trajectory[0], the same
point phase 0 measured):

    VETO(L, b)  iff  d_mouth(L, b) > 60 px
                AND  min over through-paths p with L ∉ {p.origin, p.dest}
                     of dist(b, polyline(p)) < 25 px

- `d_mouth` = birth → L's mouth anchor (origin_zone[0]; midpoint for
  legacy 2-pt zones).
- The "other road" set is THROUGH paths only (movement_label='through',
  both legs ≠ L) — EXACTLY the polyline set phase 0 measured d_main
  against (FM51: the 1↔2 mains; cam4: the 33↔35 arterial). A site with no
  such pair for any L simply never vetoes — conservative by construction.
- Both constants are GEOMETRY px from the phase-0 doc (D_MAIN=25 at the
  measured knee, M=60 in the flat window). No time constants.

## Where it applies

`_assign_origin` only — all three claim tiers:

1. **Tier 0 polyline**: vetoed legs' paths are removed from the candidate
   set before scoring (phase 0: the grabs RIDE this tier — far-field entry
   segments hug the crossing road). The natural fallback is the remaining
   main-road path match, which phase 0 showed lands the true origin.
2. **Tripwire tier**: vetoed legs are skipped (a stem tripwire's span
   crosses the main road in far-field compression; crossing it from a
   mid-box birth is not entry evidence).
3. **Heading fallback**: vetoed legs are skipped.

The veto set is computed ONCE per track from its birth (geometry is
birth-fixed) and cached on the vehicle dict; O(legs×paths) once, no
per-frame cost (the incremental-scan invariant is untouched — the veto
only shrinks the LEG set, constant per track).

A track vetoed from every matching candidate falls through the tiers and
lands origin-less (insufficient_data / the conservation feeders' pool) —
counted, never silently reassigned. New counter `n_origin_vetoed` (tracks
with a non-empty veto set) rides the replay stats like the evidence-gate
counters.

Out of scope (deliberately): the finalize-time origin machinery (joint
scorer rewrites, entry/speed tiebreaks, posterior branches) — each has its
own guards; phase 0's populations were claim-tier grabs.

## Flag + constants

`ORIGIN_CLAIM_VETO_ENABLED` (default **False**; env override
`ORIGIN_CLAIM_VETO=1` for replay harnesses — no .py edits mid-job),
`ORIGIN_VETO_D_MAIN_PX = 25.0`, `ORIGIN_VETO_D_MOUTH_PX = 60.0`.

## Ablation (FM51 ftv1 replays, dev scorer display only)

Veto ON vs the existing OFF baselines (`fullchain_ftv1_*.db`), through-gate
applied to both sides (the established scoring basis). Pass shape:

- side-leg (origin 3) accepted → ~60–72 (from 133);
- through-gate kills → near zero (the killed 3→2 throughs should now claim
  leg 1 and survive as real SB throughs — the restoration path);
- SB/NB approach totals move toward Miovision (SB was −6.5%);
- window totals stay ≤ ~±2%, interval MAE ≤ ~2.5% class.

## Phase 2 — the frozen-constant blind corridor sweep (the ship gate)

Replay cams 1–5's study windows veto-ON vs veto-OFF (replays are ~50 s
post-398c913), per-cell diff tables:

- cam4 (34→33) sheds toward its genuine cluster (~30–45 of 166 replay
  claims) with NO loss on the arterial through cells;
- cam2 / cam3 / cam5 touched cells: no regression (cam3 3.2 and cam2's
  two-pass table are the tripwires; cells the veto never touches must be
  IDENTICAL — the veto only ever removes a claim path);
- FM51 numbers hold as above.

PASS → flag default ON + ship in the promoted config (measure-then-apply).
FAIL → retirement entry + findings; the flag stays OFF and the queue keeps
surveilling the class.

## PHASE-2 VERDICT (2026-07-17, sweep + scoring complete — evidence in
runs/origin_veto/: fm51_ablation.json, corridor_sweep.json, corridor_scored.json)

**NOT SHIPPABLE AS-IS — flag stays OFF. The mechanism's redirect half is
proven; its rescue half is missing.** Established scorer (per_interval,
identical replay basis both sides), windows with dumps (cam1 0700-only):

| cam | AVG\|err\| OFF → ON | read |
|---|---|---|
| FM51 (ablation) | SB −6.5→+1.0, kills 95→6, S-left 54→5, misplacement 266→127 | the targeted WIN, bookkeeping exact |
| cam1 | 4.0 → 4.0 | wash ✓ |
| cam2 | **4.1 → 6.7** | REGRESSION — tripwire hit (SB 12.2→8.8 and EB better, but −467 events LOST) |
| cam3 | 34.8 → 34.9 | unchanged ✓ (the 34.8 level is a replay-basis artifact vs the live 3.2 — OFF≈ON is the valid read) |
| cam4 | 4.7 → 4.7 | unchanged ✓; watch cell (34→33) 166→111 with arterial +58, approaches flat |
| cam5 | 7.2 → 4.5 | total better but approaches worse — redistribution via −416 events lost |

**The mechanism in one sentence:** where an alternative candidate MATCHES,
the veto redirects correctly (FM51's 89-kill restoration; cam4's shed);
where none matches — dense far-field mid-box births whose prefixes fit no
other path's ENTRY segment and cross no tripwire — vetoed tracks DROP, and
cam2/cam5 lose ~470/~420 events, which is exactly the "never silent drop"
failure the plan's conservative principle forbade. The through-gate
comparison is instructive: the veto out-performs it where geometry offers a
fallback and reproduces its volume-loss pathology where it doesn't.

**Next stage (the rescue half, one bounded refinement — no new constants):**
a vetoed track that reaches finalize origin-less should claim the leg of
the OTHER-pair through road its birth sits ON (the same d_main<25
identification that vetoed it — the road is right there by construction),
direction picked by the birth motion's sign along the local road tangent;
only if THAT is ambiguous does it land origin-uncertain in the queue. Then
re-run this exact ablation + sweep. The FM51 numbers should hold (its
redirect already worked); cam2's −467 and cam5's −416 should return as
main-road counts or flagged uncertainty, not losses.

**Also recorded:** the finalize-time origin-rewrite leak (FM51 S-right
76→84: ~8 vetoed tracks re-stolen by the joint scorer's rewrite, outside
this mechanism's scope) — a candidate for the same next stage: the rewrite
gate should respect the birth veto set.

---

## PHASE 3 — the rescue half + the rewrite-veto (code-level design, 2026-07-20)

The verdict's "bounded next stage," specified against the real finalize
path so it can be built without re-reading it. Two edits, both under the
EXISTING flag `ORIGIN_CLAIM_VETO_ENABLED`, **no new constants** (reuse
`ORIGIN_VETO_D_MAIN_PX = 25`, `ORIGIN_VETO_D_MOUTH_PX = 60`). Flag-OFF stays
byte-identical (every new branch is reached only through a non-empty veto
set, which is empty when the flag is off — `_compute_origin_veto` already
returns `frozenset()` at `pipeline.py:812`).

### Where the drop happens (the target)

`_finalize_vehicle_data` (`pipeline.py:1027`): when a track reaches finalize
with `vehicle["origin_leg_id"] is None` it is counted as `insufficient_data`
and **returned/dropped** at `pipeline.py:1033-1041`. A track the claim-time
veto stripped of every candidate lands here — this is the cam2 −467 / cam5
−416 pathology. The rescue intercepts BEFORE that return; the rewrite-veto
protects a correctly-claimed origin from being re-stolen downstream.

### Confirmed conventions (checked, do not re-derive)

- **Polyline orientation is origin→destination.** `_entry_segment` is "the
  first half of the polyline — the off-frame-entry-to-intersection-center
  portion" (`origin_detector.py:239`). So the unit tangent `T` returned by
  `entry_gates._closest_on_polyline(poly, pt)` (index i→i+1) points FROM the
  path's `origin_leg` TOWARD its `destination_leg`. Direction-sign rule
  below depends on this — assert it in a test.
- `_closest_on_polyline` returns `(closest_point, unit_tangent, distance)`.
- The claim-time veto never vetoes a through-road's OWN two legs
  (`pipeline.py:838-840` skips `lid in (o, d)`) — so the road the birth sits
  ON always has both its legs available to claim.

### Part 1 — the rescue (an origin-less vetoed track claims the road it sits on)

New helper `_origin_rescue(birth, prefix) -> int | None`:

1. Gated: `if not ORIGIN_CLAIM_VETO_ENABLED: return None`.
2. Through-road set = the SAME set `_compute_origin_veto` uses (extract the
   `throughs` comprehension at `pipeline.py:815-821` into a shared
   `_through_paths()` so the rescue road set is identical to the veto road
   set by construction).
3. Find the through-path(s) `p` with `_closest_on_polyline(p.polyline,
   birth)[2] < ORIGIN_VETO_D_MAIN_PX`. **If 0 or ≥2 match → return None**
   (no road, or birth on a crossing of two roads = ambiguous). This is the
   same `d_main<25` identification that fired the veto — "the road is right
   there by construction."
4. Direction: `T` = tangent at `birth`'s closest point on `p`;
   `M` = `prefix[-1] − prefix[0]` (`prefix = traj[:min(8, len)]`, the same
   window claim-time and phase 0 used). **Degeneracy guard (constant-free,
   NOT a tuning knob):** if `|M| < 1px` (sub-pixel = not a real through) or
   `dot(M, T) == 0` (perpendicular) → return None.
5. `origin = p.origin_leg_id if dot(M, T) > 0 else p.destination_leg_id`
   (motion along +T = travelling origin→dest → origin is the origin leg;
   anti-parallel = the reverse-direction through on the same road →
   origin is the destination leg).

Wire at `pipeline.py:1033`, inside the `origin_leg_id is None` branch,
before the drop:

```python
if vehicle["origin_leg_id"] is None:
    rescued = self._origin_rescue(trajectory[0], trajectory[:8]) \
        if trajectory else None          # trajectory read up from below
    if rescued is not None:
        leg = next((l for l in self.legs if l["leg_id"] == rescued), None)
        if leg is not None:
            vehicle["origin_leg_id"] = rescued
            vehicle["reference_heading"] = leg["reference_heading"]
            vehicle["origin_frame"] = frame_number   # or start_frame proxy
            vehicle["origin_veto"] = vehicle.get("origin_veto") \
                or self._compute_origin_veto(trajectory[0])   # for Part 2
            self.n_origin_rescued += 1
            # fall through — do NOT return; the normal chain now runs
    if vehicle["origin_leg_id"] is None:
        # existing insufficient_data drop == "origin-uncertain → the queue"
        ... (unchanged 1034-1041)
```

The **ambiguous/no-road case keeps the existing `insufficient_data` drop** —
that IS "origin-uncertain → the conservation feeders' pool/queue" (already
counted at `n_insufficient_data`; the §3-B coverage feeder surveils these,
per the phase-1 plan's "counted, never silently reassigned"). No new queue
plumbing.

A rescued track then flows through the ENTIRE normal chain (classify →
joint scorer → destination → through_gate → turn-merge), so its main-road
through is still subject to `through_gate.reject_invalid_throughs` and the
volume gate — the rescue recovers a MISSED far-field through, it does not
bypass the dedup that the FM51 redirect (kills 95→6) depends on.

### Part 2 — the rewrite-veto (the joint scorer may not re-steal to a vetoed leg)

At `pipeline.py:1091`, `candidate_paths = self._paths` feeds the joint
scorer (`score_path_joint`, 1131), which READS ORIGIN OFF the winning path
and rewrites `origin_leg_id` at 1289-1292. Nothing there consults the veto
— the leak (FM51 S-right 76→84). Fix: filter the candidate set by the veto
before scoring:

```python
veto = vehicle.get("origin_veto") or frozenset()
candidate_paths = ([p for p in self._paths
                    if p.get("origin_leg_id") not in veto]
                   if veto else self._paths)
```

Compose with the (currently-OFF) evidence-gate narrowing at 1111 — apply the
same `not in veto` filter to that branch's list too, so the two are order-
independent. Effect: the joint scorer cannot SELECT a veto-origin path, so
the 1289 rewrite can't move origin to a vetoed leg. If the filter empties the
set, `score_path_joint` finds no match → `polyline_dest` stays None → the
softmax `score_destination_by_polyline` / `score_destination_leg` fallback
runs on the ALREADY-CLAIMED (or rescued) origin — **origin is preserved, no
drop.** Counter `n_origin_rewrite_vetoed` increments when the filter shrinks
the set.

### Counters + stats

Add `self.n_origin_rescued = 0` and `self.n_origin_rewrite_vetoed = 0`
beside `n_origin_vetoed` (`pipeline.py:247`), and surface both in
`pass2_replay.py:224` next to `origin_vetoed`. They ride the replay stats
exactly like the phase-1 counter (the sweep reads them for bookkeeping-exact
accounting: rescued + redirected + still-dropped must reconcile the event
delta, the "bookkeeping exact" bar the FM51 ablation already met).

### Tests (extend test_pipeline.py's veto block, 227-273)

1. **Rescue, both directions.** Reproduce a far-field mid-block birth on a
   through-road with every side-leg claim vetoed; motion +T → claims
   `origin_leg`; reversed motion → claims `destination_leg`. `n_origin_rescued
   == 1`, an event is emitted (was a drop).
2. **Rescue ambiguity → drop.** Perpendicular / sub-pixel birth motion, or
   birth within 25px of two through-roads → stays `insufficient_data`,
   `n_origin_rescued == 0`.
3. **Rewrite-veto.** A vetoed-origin path that would otherwise win the joint
   scorer is excluded; origin stays the claimed main-road leg;
   `n_origin_rewrite_vetoed == 1` (the S-right 76→84 shape).
4. **Flag-OFF byte-identical.** With the flag off, `n_origin_rescued ==
   n_origin_rewrite_vetoed == 0` and event rows are unchanged vs pre-phase-3
   (guards the no-regression basis the whole gate rests on).

### The re-gate (SAME harness, unchanged — the ship gate)

Env override `ORIGIN_CLAIM_VETO=1`, replays only (dumps exist post-398c913),
scored with `interval_metric.per_interval` on the identical replay basis both
sides. Reproduce `runs/origin_veto/*.json`:

- **FM51 ablation** (`scripts/fm51_fullchain_ab.py` + through-gate both
  sides → `fm51_ablation.json`): the redirect must HOLD (SB ≈ +1.0, kills
  ≈6, misplacement ≤127) AND the S-right leak close (76→84 back toward 76).
- **Blind corridor sweep** (`scripts/corridor_metric_sweep.py` →
  `corridor_sweep.json` / `corridor_scored.json`, the per-cam total + per-
  approach `AVG|err|` OFF vs ON table). **ACCEPTANCE:** cam2 recovers from
  6.7 toward ≤4.1 (the −467 returns as real counts or flagged uncertainty,
  NOT losses); cam5 approaches recover from the −416 redistribution;
  cam1/cam3/cam4 stay flat (the veto-untouched cells must remain identical).
- PASS → flag default ON + ship in the promoted config (measure-then-apply).
  FAIL → retirement entry + findings; flag stays OFF, queue keeps surveilling.

**Harness cost (real):** the FM51/corridor DRIVER scripts the Fable-5 session
ran were in the ephemeral session scratchpad, not committed. The committed
primitives to rebuild them from: `scripts/replay_origin.py`,
`scripts/replay_fullchain.py`, `scripts/fm51_fullchain_ab.py`,
`scripts/corridor_metric_sweep.py`, `scripts/interval_metric.py`, and the
target JSON shapes in `runs/origin_veto/`. Budget a rebuild step before the
gate can run. Detached replays follow [[server-process-lifecycle]] /
[[replay-quadratic-stationary-tracks]] (Start-Process + Monitor).

### Open checks to close during the build

- Assert polyline orientation (origin→dest) in a test rather than trust it.
- The rescued origin's `classifier_*` audit columns will be relative to the
  claimed heading — same acceptable-for-v1 staleness already noted at
  `pipeline.py:1299-1304` (reported movement comes from the path label, so
  counts are unaffected); document, don't fix.
- Watch for rescue OVER-recovery: if cam2 swings past +467 into an OVER-count
  (a rescued through duplicating an already-counted main-road fragment), the
  per-approach `AVG|err|` catches it — that would route to a fragment-dedup
  guard, not more rescue.

---

## PHASE-3 VERDICT (2026-07-20 — ablation + blind sweep complete; evidence in
runs/origin_veto/: fm51_ablation_phase3.json, corridor_sweep_phase3.json,
corridor_scored_phase3.json)

**FAIL — RETIRED as a default per the two-iteration budget. Flag stays OFF.**
Both phase-3 halves built and unit-proven (811 green, flag-off byte-identical
— re-confirmed at scale: every corridor OFF replay reproduced its committed
total exactly, cam1 4668 / cam2 16648 / cam3 30384). FM51 improves further;
the corridor does not recover, and the tripwires hit HARDER than phase 1.

**FM51 (the lone win, again):** redirect held and strengthened (S 133→79 vs
phase-1's 91; W 1627→1778 vs 1758; S-left 54→4) and the rewrite leak CLOSED
(S-right 76→67; phase 1 had 76→84). Rescue returned 810 drops (W-through
1572→1729 ≈ Mio's 1735). Cost: overshoot up slightly (total +4.0% vs
phase-1's +3.7%, intMAE 4.19 vs 3.84).

**Corridor (established per-approach scorer, replayed-minutes basis both
sides; OFF column reproduces committed corridor_scored.json exactly):**

| cam | AVG\|err\| OFF → ON3 (phase-1 ON) | events Δ ON3 (ph-1) | read |
|---|---|---|---|
| 1 | 4.0 → 4.1 (4.0) | +19 (−1) | wash ✓ |
| 2 | **4.1 → 7.2 (6.7)** | **−538 (−467)** | REGRESSION — worse than phase 1; tripwire |
| 3 | 5.9 → 6.0 on the replayed-window cut (the committed 34.8 was the whole-day artifact basis) | +119 (+15) | wash ✓ |
| 4 | 4.7 → 5.0 (4.7) | +50 (+3) | wash (marginal) |
| 5 | 7.2 → 4.6 (4.5) total = cancellation; **EB 16.1 → 26.1 (21.0)** | −412 (−416) | approach REGRESSION — worse than phase 1 |

**The mechanism in one sentence:** at corridor far-field compression the
frozen `d_main<25` signature stops discriminating — the veto fires on the
broad birth population, not the mid-block-grab class (cam2: 21,142 vetoed
tracks vs 16,648 emitted events; rewrite-veto gutted 14,002 finalize
candidate sets) — so the rescue redistributes at scale instead of recovering
(cam2 28>29 −858 / 27>29 +524), and the NEW rewrite-veto half (the FM51
leak-closer) nets MORE loss than phase 1 had without it. Both halves inherit
the veto set's precision; where the set is pervasive, every consumer
amplifies the error. Same cross-camera non-generalization class that retired
the item-8 evidence gate.

**Disposition:** flag default stays OFF (env override kept for harnesses);
code + tests revival-ready; the origin-grab class returns to flag-queue
conservation surveillance. The FM51 residual (side +73 / SB −6.5% at
promotion) remains a KNOWN shipped residual, not silently fixed.

**Named revival candidates (each needs its own plan + held-out-site gate):**
1. **Site-activation precondition** — the veto-rate itself is a blind health
   check: FM51-shaped stem sites show a moderate, redirect-balanced rate;
   corridor compression shows a pervasive one → stand down. Same shape as the
   evidence gate's named coverage-precondition candidate.
2. **Compression-relative constants** — 25 px is not the same road at
   different focal lengths; a road-width-normalized d_main needs a fresh
   phase-0 measurement pass, not a knob sweep.
