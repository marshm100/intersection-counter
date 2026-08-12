# Block C-1 — evidence-ranked chain arbitration (D1 iteration 2 of 2)
# (2026-08-12)

The named successor from `MASTER_PLAN.md:738` ("evidence-ranked chain
arbitration — iteration 4, own plan+budget") and
`plan_conservation_pass_2026-07-15.md:94-99`, specified by Block D1's
measurement (`plan_v2_conserve_activation_2026-08-11.md`): "legacy always
wins" is a second, independent defect of the conservation pass — 225/275,
173/219, 354/436 rejections at the three cam2 windows came from the blanket
`rejected_vs_legacy` branch, and the pass loses on the customer bar at the
doc's own high-coverage success camera. Iteration budget: this is 2 of 2
for the conservation family, counting from zero per the 2026-08-11 operator
decision. If it fails, the family is LEDGERED dead on the customer bar.

## Mechanism

On a MIXED chain (legacy + additive events), stop assuming the legacy event
is correct. Rank ALL events on the chain by gate evidence and keep the
best-evidenced one, the way the all-additive branch already keeps its best
via `_ADDITIVE_RANK`. The D1 diagnosis says the posterior's correct event
is rejected exactly when the chain's legacy event is a misattributed flip —
and a flip is, by definition, a disagreement between the event's recorded
(origin, destination) and the track's own gate crossings.

## Implementation (verified surfaces)

1. `backend/services/track_chains.py` — `build_chain_map` computes each
   track's gate `(_o, _d, tag)` via `classify()` at `:100` and DISCARDS
   them. Return them: map value becomes `(chain_id, origin, dest, tag)`
   (or a parallel dict), additive change; sole consumer updated in the
   same commit.
2. `backend/services/two_pass.py:317-336` — `conserve_replay_additions`:
   the mixed-chain branch at `:325` (`if len(additive) < len(evs)`:
   blanket-reject all additive) is replaced, behind the flag, by:
   - Build per-event evidence key from the event row + its track's gate
     record: (a) GATE-AGREEMENT — does `(origin_leg_id,
     destination_leg_id)` match the track's classify `(o, d)` where the
     track has them; (b) TAG STRENGTH — full > entry_only/exit_only >
     no_crossing/unmapped; (c) tie-break `-classifier_num_points`, then
     `event_id` (determinism). The SELECT gains `origin_leg_id,
     destination_leg_id` — no schema change, no new frozen constants.
   - Keep the single best-keyed event on the chain (legacy OR additive),
     reject the rest. New counters: `rejected_vs_legacy` keeps its
     meaning (additive rejected in favor of a legacy event);
     `legacy_rejected` counts the NEW capability (legacy rejected in
     favor of a better-evidenced event). Both reported in
     `result.replay.conservation`.
   - `dest_tie` and `demoted` sources remain non-additive (legacy-side)
     for grouping, and are rankable like any legacy event.
3. `backend/config.py` — `CHAIN_ARBITRATION_EVIDENCE` (env, default OFF),
   read AT CALL TIME via `getattr(_cfg, ...)` in two_pass — NEVER the
   module-global import at `two_pass.py:40-44` (the D1 patching trap).
   OFF ⇒ the `:325` branch byte-identical.
4. Tests (`backend/tests/test_conserve_activation.py` pattern — patch
   `TP.ORIGIN_POSTERIOR_ENABLED` module-global, `config.*` call-time):
   - OFF-parity: flag off ⇒ mixed-chain behavior identical (blanket
     reject), existing suite green unchanged.
   - Mixed chain, legacy is a flip (disagrees with its track's gates),
     additive rescue_full agrees ⇒ legacy rejected, additive kept,
     `legacy_rejected` == 1.
   - Mixed chain, legacy agrees with gates ⇒ additive rejected (old
     behavior emerges from ranking, not from the blanket).
   - `dest_tie` counts as legacy for grouping (existing pin at
     test_conservation.py:127 stays green); NEW explicit pin: `demoted`
     counts as legacy for grouping.
   - Re-pin DELIBERATELY: `test_every_ranked_source_is_additive` asserts
     `set(_ADDITIVE_RANK) <= set(_ADDITIVE)` — still true (the legacy
     ranking is by gate evidence, not by extending _ADDITIVE_RANK), so
     the pin SURVIVES; assert that explicitly in the block commit.
   - Unmapped/short tracks (< 5 points, no chain_id): untouched, pinned.
5. Interaction stated: V2_MERGE_RESCUE examines `rejected=1` rows and
   could un-reject a C-1-rejected legacy full. OFF on this measurement
   basis (all V2 flags off) and OFF in production; recorded here so the
   pair is never enabled together without a new plan.

## Measurement

BASE dumps, cam2 study_0700/1100/1600 (the D1 surface — the only camera
clearing the activation bar). Env: `CONSERVE_ON_ACTIVATION=1` +
`CHAIN_ARBITRATION_EVIDENCE=1`; everything else default. ONE variable vs
the D1 CONS arm (which had conserve on, arbitration legacy-always-wins);
d1ctrl remains the do-nothing comparator. Workdirs
`_replay_scratch/c1_arb/<win>/`, stems `c1arb_cam2_<win>`, WAL-safe
copies, DBs deleted after scoring.

## GATE — pre-declared in the D1 block doc (2026-08-11), restated verbatim

On the same three cam2 windows, mixed-chain arbitration must be
**>= CTRL on all three** (53.4 / 42.9 / 44.0) and **>= +1.0 on one**; and
the rejection split must **shift away from `rejected_vs_legacy`** (the
quantity the diagnosis implicates).

Comparators on record: CONS (iteration 1) scored 47.6 / 40.0 / 43.1 with
rejected 275/219/436, vs-legacy 225/173/354.

**If FAIL: ledger the conservation pass DEAD on the customer bar**, and
record that its original per-approach proof (cam2 9.1→3.3-3.5%) does not
transfer to per-cell-per-bin scoring — a citable result either way,
because the mechanism is currently cited as proven.
`CONSERVE_ON_ACTIVATION` and `CHAIN_ARBITRATION_EVIDENCE` stay default
OFF regardless of outcome.
