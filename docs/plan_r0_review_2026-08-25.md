# R0 — the measured review pass (2026-08-24/25) — REPORT

The Tier-0 experiment, finally run: one operator works one window's
queue on the v2 review instrument; both accuracy bars scored before and
after; every action recorded. Window: cam2 16:00-18:00 (the largest
scoped queue). Basis: shipped production (gate supremacy, 64.8 pooled).
Snapshots: project_20260824T215544_pre_r0.db ->
project_20260825T175315_post_r0.db (both integrity-verified).

## The instrument became half the experiment

The operator opened the original worklist and ruled it unusable ("an
open question... a blank canvas with no structure"). FIFTEEN operator
rulings were built into the instrument during the session: machine-
proposed line items for gap cards; editable movements; the T (bad
track) verb; full-path looping replays; unmissable vehicle highlighting
(which had been silently broken since the page was built — the API
never sent the event's track id); leg labels + gate lines on the video;
per-item notes; per-item undo; confirmed-before-marked saves; durable
movement choices; session restore on reload; no-cache asset serving;
row format for event cards; the same-leg thief verb; item scrollboxes.
The result is the certification instrument the product needs — REVIEW-UI
v2, hardened by live operator use.

## What the operator found (the findings ARE the result)

- Gap cards (2 worked by hand, 34 machine-proposed candidates):
  **33 of 34 were tracker debris** — thieves and tracks lingering on
  idle queue-waiters. 1 real missed vehicle. The remaining 12 gap cards
  were closed administratively citing the two-card finding (operator
  decision).
- Event cards: mostly accepts; T rulings continued. **36 operator-
  labeled splices total** now in review_log — the largest labeled
  identity-error set in the project.
- TWO NEW FAILURE SUBCLASSES named by the operator:
  1. SAME-LEG mid-motion handoff: lock hops from vehicle A (turning
     right) to vehicle B (going straight) on the same leg — distinct
     from opposite-direction theft.
  2. PARKED-ROW theft zone: a permanently parked row on the passing
     vehicle's right seeds thefts — a stationary occluder, distinct
     from the oncoming queue.
- INFRASTRUCTURE FINDING (operator): "the mouth and gate infrastructure
  is not working properly" — queue creep across drawn gate lines mints
  full journeys (the u-turn debris class). The enumerator now motion-
  qualifies crossings; the PRODUCTION counting rule (motion-qualified
  evidence) is chartered as the next declared gate.

## The measurement

| | before | after |
|---|---|---|
| movement bar (study_1600) | 65.2 (75/115) | **65.2 (75/115)** |
| approach bar (study_1600) | 40.6 (13/32) | **40.6 (13/32)** |
| production events in window | 32,119 | 32,120 (**+1**) |

Active review time (from log burst analysis): **~15-20 logged minutes**
(event-card accepts are not logged; true active review ~20-30 min,
interleaved with instrument iteration — a clean uninterrupted
review-hours number needs the next session, on the finished
instrument).

## R0 VERDICT

**Review at this basis cannot move the score, and the reason is now
measured, not argued:**
- The VOLUME deficit is detection-dark — no track exists for review to
  bless. (Confirms G-LP-1's structural finding from the other side.)
- The ATTRIBUTION deficit is identity-level — review can LABEL a thief
  in seconds but repairing the count requires knowing which real
  vehicle's journey was stolen, which the reviewer often cannot know
  from one clip.
- What review DOES produce, cheaply: labeled identity errors (36 in
  ~20 min), taxonomy discoveries (2 new subclasses), and certification-
  grade audit trails. Review is the CERTIFICATION and DATA layer, not
  a score-recovery layer.
- The portfolio scenario "ML + review reaches ~70-85" is DEAD at this
  basis. All score recovery funnels through the identity stack:
  tracker consistency (the reserved G-LP-2, now armed with 36 labels +
  2 subclasses), motion-qualified gate evidence (declared gate,
  chartered), and detector recall (Stage 5).

Operator's own formulation, mid-session: "thieves and tracking
consistency is the biggest lever here we need to fix." The ledger
agrees, three measurements deep.
