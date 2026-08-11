# Block D1 — the posterior EXTRAS under the ACTIVATION precondition
# (2026-08-11)

Tier-1 block 1 of the options-inventory campaign
(`docs/options_inventory_2026-08-11.md`, category D — "the retirement reason
has since been fixed and nobody re-tested").

## The claim this block tests

`census_expecteds` + `conserve_pass` were retired as blind five-camera
defaults per the two-iteration budget
(`plan_conservation_pass_2026-07-15.md:85`). The stated reason was ONE thing:

> "It is NOT blind-deployable where evidence coverage is low (36-60%)"

The **activation precondition** decides exactly that question. It was built,
validated, promoted 2026-07-27, and is DEFAULT ON — but `config.py:427-429`
records that it governs the REPLAY only: the extras "stay keyed on their own
flags; phase 1 never measured them". So the fix for the retirement reason
shipped and was never pointed at the retired mechanism.

Verified before building: `result.replay.conservation` is absent from every
Block-0 arm sidecar — `conserve_pass` has never run in this campaign.
(Method note: that key is nested under `result.replay`, not at the top level
of `result`; a top-level check reports absent for both cases and cannot tell
"never ran" from "ran and reported". Check the nested path.)

## Change

- `config.CONSERVE_ON_ACTIVATION` (env, **default OFF**).
- `two_pass.posterior_extras_enabled(activation)` — one pure function, the
  whole decision. OFF: reduces exactly to `ORIGIN_POSTERIOR_ENABLED`, so the
  shipped path is byte-identical.
- The `expected` computation MOVED to after the replay (it now depends on the
  activation decision). Verified nothing between the old and new position
  consumes it — the only readers are the demotion block and
  `merge_replay_turns`, both downstream.
- `backend/tests/test_conserve_activation.py` — 9 tests.

Encoded in the tests because both would cost a wasted run: the two knobs are
patched DIFFERENTLY (`ORIGIN_POSTERIOR_ENABLED` is a module-global imported
at `two_pass.py:43`, so patching `backend.config` does nothing;
`CONSERVE_ON_ACTIVATION` is read through the config module at call time), and
`conserve_replay_additions` rejects only `_ADDITIVE` sources so it is a
strict no-op on an all-direct replay.

## Basis

BASE dumps, all V2 mechanism flags OFF — the shipped configuration. The
extension line is closed, so measuring D1 on v2c dumps would price it against
a retired mechanism. On base dumps **cam2 is the entire surface**: the only
camera clearing 0.45 (coverage 0.564 / 0.487 / 0.485), and the camera where
the posterior half was originally proven. Only `CONSERVE_ON_ACTIVATION`
differs between arms.

## VERDICT — G-D1b FAILED

  window            CTRL            CONS         5/95 delta  rejected  vs-legacy
  cam2 study_0700  53.4  55/103   47.6  49/103     **-5.8**     275       225
  cam2 study_1100  42.9  45/105   40.0  42/105     **-2.9**     219       173
  cam2 study_1600  44.0  48/109   43.1  47/109     **-0.9**     436       354

G-D1a **PASS** — inert when off; 929 + 9 tests green.
G-D1c **PASS** — the conservation block is reported at every window.
G-D1b **FAIL** — negative at all three; the gate required non-regression
with >=+1.0 on one window.

Note the scored-cell counts are IDENTICAL between arms (103/103, 105/105,
109/109). The pass adds and removes no cells — it rejects events INSIDE
existing cells, turning 6 / 3 / 1 compliant cell-bins non-compliant.

**It is not the aggregate-vs-per-bin trap.** I checked, because the original
proof was on per-approach totals while today's bar is per-cell-per-bin, and
this project has been burned by exactly that substitution before (LEC2:
"aggregate MAE wins that BREAK BINS"). A consistently-computed aggregate
error over the same DBs moves the SAME way at all three windows —
14.57 -> 15.47, 20.57 -> 21.45, 15.23 -> 19.25. The conservation pass is
worse on both metrics at cam2.
(That figure is my own `sum|ours-mio|/sum(mio)` over all scored cells, valid
for the CTRL-vs-CONS comparison and NOT comparable to the doc's 9.1/3.5
per-approach numbers.)

## WHY it fails — the original doc predicted this, verbatim

`plan_conservation_pass_2026-07-15.md:77-82`:

> "**chain arbitration is a single dial with failure modes on opposite ends.**
> 'Legacy always beats additive' fixed cam5 (+10.0 -> +1.1; 1,319 duplicate
> rejections, 96% against legacy chains) and most of cam4 — but **on cam2 it
> rejects the posterior's CORRECT event whenever the chain's legacy event is
> itself a misattributed flip**, giving back most of the -5.8 win."

That is exactly what the rejection split shows: **225 of 275** (and 173 of
219) rejections come from `rejected_vs_legacy` — the aggressive branch at
`two_pass.py:325-329` that rejects EVERY additive event on any chain
containing a legacy one.

**This corrects the retirement's own stated reason.** The record says the
mechanism was retired for not being blind-deployable at LOW coverage. But
cam2 has HIGH coverage (0.487-0.564) and is the doc's own success case —
"where evidence coverage is high (80%), the posterior is decisively correct"
— and the pass still loses there on the customer bar. So coverage was not
the only defect. **"Legacy always wins" is a second, independent defect, and
the activation precondition does not touch it.** Fixing the coverage half
was necessary and insufficient.

## Iteration 2 (budget: 1 of 2 spent, counting from zero per the 2026-08-11
## operator decision)

The named successor already exists on the record and is the same object as
options-inventory item **C-1**: *"evidence-ranked chain arbitration
(iteration 4, own plan+budget)"* (`MASTER_PLAN.md:738`). The measurement
above converts it from a suggestion into a specified one: on a MIXED chain,
do not assume the legacy event is correct — rank by evidence and keep the
best-evidenced, the way the all-additive branch already does via
`_ADDITIVE_RANK`.

That is a distinct mechanism, not a knob turn, so it gets its own
pre-declared gate rather than riding this block's. Pre-declare before
building: on the same three cam2 windows, mixed-chain arbitration must be
>= CTRL on all three and >= +1.0 on one; and the rejection split must shift
away from `rejected_vs_legacy` (the quantity the diagnosis implicates).

**If iteration 2 also fails, LEDGER the conservation pass as dead on the
customer bar** and record that its original per-approach proof does not
transfer to per-bin scoring — which is a result worth having either way,
because it is currently cited as a proven mechanism.

`CONSERVE_ON_ACTIVATION` stays **default OFF** regardless.
