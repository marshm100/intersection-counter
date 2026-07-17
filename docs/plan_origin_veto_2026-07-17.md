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
