# Phase 3 — Conservation QA Layer: Findings (2026-06-12)

Plan: docs/implementation_plan_architecture_2026-06-11.md (Phase 3). Zero-ground-truth validation
for new sites, per standard agency practice (Maryland SHA et al., from the architecture research).

## What shipped

- **backend/services/conservation_qa.py** — two checks:
  - `reverse_balance(project, intersection)` (3.1): each movement vs its geometric reverse
    (reverse of cardinal pair (a,b) is (b,a): NB-thru<->SB-thru, SB-left<->WB-right). Relative
    imbalance with a 20-vehicle floor; verdicts ok/warn/fail at 25%/50%. **Window-aware:** under
    6h of footage every pair reports `info` — peak-period directional imbalance is real traffic
    (cam1 AM: NB 543 vs SB 431 is the commute, not an error).
  - `corridor_consistency(project, ordered_ids, axis)` (3.2): for adjacent intersections A,B —
    A's vehicles exiting toward B vs B's vehicles entering from A's direction, both directions.
    Counts the SAME stream twice minutes apart, so it is valid at ANY window length — the primary
    new-site check. Turning traffic is handled naturally (a turn onto the corridor feeds the
    directional OUT total via its destination leg's cardinal). Verdicts at 15%/30% gap with a
    30-vehicle floor.
- **backend/routers/qa.py** — GET `/projects/{p}/intersections/{i}/qa/conservation` and
  GET `/projects/{p}/qa/corridor?order=ids&axis=NS|EW` (order defaults to intersections
  sort_order; first id = southernmost/westernmost).
- **UI (3.3)** — new **QA sub-tab** on the intersection detail (Settings / Cameras / Clip trim /
  QA): both tables with OK/WARN/FAIL/INFO badges, this intersection's links bolded, wording that
  frames flags as "review these cells", pointing at the Review screen.
  Screenshot: screenshots/qa_tab_intersection2.png.
- 7 service tests (verdict tiers, window gating, volume floors, turn-fed directional IO).

## Exit-gate validation on the live corridor (07:00–07:30)

**Corridor consistency rank-correlates with known error** — interior links conserve at 1–6%
(2->3 Nbound 1%, 3->4 2%, 4->5 5%), and the three warns land exactly on the known-weak spots:

| link | gap | known cause |
|---|---:|---|
| 1->2 Nbound | 18% | cam1 = weakest tracker (old ReID-path events) |
| 2->1 Sbound | 19% | same link, both directions |
| 3->2 Sbound | 22% (vs 1% Nbound!) | cam2's SB-side undercount (the −41 SB-right residual) — asymmetry isolates the direction |

Incidentally this confirms intersection sort_order 1..5 IS the geographic order (the conserving
links could not conserve otherwise).

**Reverse balance catches 2 of the 3 worst residual-map cells** even at 30 min: cam4 EB-left 46
vs SB-right 13 (the +38 overcount) and cam5 NB-left 77 vs EB-right 16 (the −23 EB-right
undercount). Its two structural blind spots, confirmed live, justify the secondary/info framing:
- correlated errors cancel (cam2 SB-right −41 doesn't flag because its reverse pair, EB-left,
  undercounts in tandem: 41 vs 39);
- genuine asymmetric demand false-positives (cam3 EB-left 30 vs SB-right 5 — manual says 16 vs 3,
  the imbalance is REAL). Maryland's own framing applies: imbalance triggers investigation, not
  rejection.

## Notes / future

- Both checks read counted vehicle_events (all cameras on the intersection, rejected=0). After
  cross-camera dedup ships per-event flags, the query should respect them.
- Mid-block access annotation (per-link tolerance widening) deferred until a corridor needs it —
  the Belt Line links sit comfortably inside the bands.
- Per-15-min binning deferred: the per-window totals already isolate direction and the Review
  screen covers drill-down. Add bins when full-day runs land (Phase 4 spot-count work).
