# Plan — mechanism ① iteration 3: the conservation pass (2026-07-15)

Parent: `plan_posterior_half_2026-07-15.md` (sweep run 2 = FAIL, structural:
the posterior half's additions are UNCONSERVED — proven where recall is
broken (cam2 9.1→3.5), double-counting where live is already at truth (cam4
+3.0 tripwire, cam5 +10.0)). User-approved iteration (option A).

## The design principle

Conservation must be VEHICLE-level, not budget-level. The sweep showed the
census cannot provide honest per-cell budgets (over-expects turn cells on
fat-unevidenced cameras, under-expects truncation-dominated cells). But the
double-count mechanism is concrete: a physical vehicle fragments into k
tracks; legacy counts one fragment; the posterior's branch-1/rescue counts
another. The blind, budget-free fix: **at most one counted event per
fragment CHAIN, and additive events always lose to legacy events.**

- Fragment chains come from `boxclip_pass2.chain_tracks` — the B3 machinery,
  proven at Gate B, with the dedup-ceiling lesson already baked in (only
  journey-INCOMPLETE tracks chain; a box-full journey never chains, so a
  1–2 s-headway follower cannot be merged into its leader). Its STITCH_*
  constants are frozen since 2026-07-08. **Zero new constants.**
- cam2's genuinely-missed vehicles are chains in which NOTHING else was
  counted → their additive event survives. cam4/cam5's fragments belong to
  chains whose other member already produced a legacy event → the additive
  event is rejected. The discriminator is exactly the thing that differed
  between the cameras.

## Build

1. **`backend/services/track_chains.py`** — port `chain_tracks` + `_end_speed`
   + STITCH_* verbatim from `scripts/boxclip_pass2.py` (script re-imports;
   the entry_gates port pattern). `build_chain_map(tracks, gates, fps) →
   {track_id: chain_id}` classifies each dump track (tags gate the chaining)
   and chains the fragments.
2. **`posterior_source` marker column** on vehicle_events (migration,
   nullable): 'branch1' / 'rescue_full' / 'rescue_supports' / 'dest_tie',
   written by the pipeline branches. Closes the run-2 instrumentation gap
   (rescues were unattributable) AND is the conservation join key.
3. **`conserve_replay_additions(db, camera_id, chain_map)`** (service):
   post-replay, pre-merge pass in the write-then-reject pattern the merge
   already uses. Per chain over kept events: if the chain has a NON-additive
   (posterior_source NULL) event, reject every additive one; else keep the
   single best additive (rescue_full > branch1 > rescue_supports, then
   longest track) and reject the rest. Singleton chains unaffected.
4. **Wiring:** `run_pass2` + the ablation harness run replay → CONSERVE →
   merge (the merge then polices turns over cleaner counts), gated on
   ORIGIN_POSTERIOR_ENABLED like the census.
5. Tests: chain-service fidelity (fragments chain, fulls don't, followers
   don't), conserve semantics (legacy beats additive; best-of-additives;
   singletons kept), posterior_source per branch.

## The gate (unchanged discipline, run 3)

Stage-4 fit (bars: ctrl 1166/1124, filter+fill 902; run-2 posterior 609/650
is the reference, some give-back acceptable) → stage-5 held-out (MUST beat
ctrl 1054/1284 on both) → stage-6 five-camera sweep INCLUDING cam3 this
time. Pass condition: cam2 keeps its class win; cam1/cam4/cam5 hold their
baselines (the run-2 failures are the cells to watch: cam4 35→33 ≈ 6693,
cam5 turn cells ≈ live); cam3 3.2 tripwire. FAIL → the posterior half
retires for real (two structural iterations is the budget).

## Risks

- Chaining at replay scale (all dump tracks) is O(n log n) with small
  windows — runtime fine; correctness rests on the B3 tag-gating.
- cam2 give-back: if a material share of cam2's recovery was
  fragment-continuations of counted vehicles, stage-4/5 will show it —
  that's the honest number, not a failure of the pass.
- The rescue_full case (box-full journey dropped by the chain) can't chain
  by construction (full journeys are chain-inert) — it is conserved by
  definition; only its duplicates via OTHER members' legacy events are
  caught, which is the desired asymmetry.
