# Plan — Phase-1 APPLY GATE: per-window candidate-vs-incumbent adjudication (2026-08-07)

Successor to plan_v2_block2_2026-08-06.md (block verdict: G-A3 blanket FAIL,
the applicability law, "build the apply gate" named as the next block).
Closes the blind-product-test wounds from MASTER_PLAN §2e: (1) uniform
two-pass apply overrode per-camera dispositions; (3) cached pass-2 re-apply
broke across schema migration (int2's Error card — still live evidence).
Same discipline: plan with pre-declared gates first; scratch-only until the
gates pass; production tables and V2 flags untouched throughout the block.

## The mechanism (the applicability law made mechanical)

THE LAW (block-2 verdict, 11 blind windows): the bundle wins where journeys
are MISSING, loses where completion MANUFACTURES journeys; every loss carries
the event-flood signature the blind guards already flag. The gate turns that
law into per-window adjudication executed at APPLY time: a candidate working
table may replace the incumbent applied table only if it wins its window
under the blind guard battery. No Miovision anywhere in the gate.

Blind quantities, all from existing machinery, computed on the BASE dump
(extension-proof — the base-census principle the demotion selector shipped):

- census C_cell = census_expecteds(base rows) — gate-evidence traffic per
  cell; T = sum(C). The window's own evidence envelope.
- I_cell / K_cell = incumbent / candidate counted events (camera- and
  window-scoped, rejected=0, destination NOT NULL). Incumbent = project.db's
  applied table for the window; candidate = the pass-2 working DB.
- R_inc = sum(I)/T - 1 — how far the incumbent under/over-claims vs
  evidence. Negative = journeys missing = recovery headroom.
- flood_share(X) = sum_cell max(0, X_cell - C_cell) / T — per-cell mass
  claimed BEYOND gate evidence (the event-flood signature, per-cell so
  starved cells cannot cancel flooded ones).
- covered(X) = sum(X) - sum_cell excess(X); d_cov = covered(K) - covered(I)
  — evidence-backed recovery the candidate actually adds.
- saturation = lower-median per-origin confusion from strict_full_census —
  the shipped contrast-guard measure (cam1 transfer verdict: oblique
  geometry saturates the confusion channel; census attribution is then
  untrustworthy and adjudication must not pretend otherwise).

DECISION (evaluate all guards, record every failure; apply only if none):

0. Operator disposition rules first (see dispositions below): 'hold' ->
   stand down (operator_hold); 'force_once' -> apply (operator_force),
   consumed after one use.
1. sum(I) == 0 -> APPLY (fresh_window): an empty incumbent has nothing to
   defend; first processing keeps its legacy behavior. Metrics recorded.
2. T == 0 (no drawn gates/paths -> no census) -> APPLY (not_adjudicable):
   the gate abstains rather than freezing re-processing on cameras without
   geometry; curated-judgment protection there is the operator disposition.
3. saturation >= APPLY_GATE_SATURATION (0.25, the shipped contrast-guard
   constant, hoisted to config and shared) -> STAND DOWN
   (saturated_geometry).
4. R_inc > -APPLY_GATE_HEADROOM -> STAND DOWN (no_headroom): the incumbent
   already claims to within h of its evidence; there are no missing
   journeys to recover, which is the only regime the bundle wins in.
5. flood_share(K) > APPLY_GATE_FLOOD_MAX -> STAND DOWN (event_flood): the
   candidate manufactures events beyond the evidence envelope.
6. d_cov <= 0 -> STAND DOWN (no_recovery): principled — an apply must add
   evidence-covered mass, not just excess.
7. Otherwise APPLY (gate_pass).

Constants (pre-declared here, frozen before implementation):
APPLY_GATE_HEADROOM = 0.03, APPLY_GATE_FLOOD_MAX = 0.15,
APPLY_GATE_SATURATION = 0.25 (existing). Directional sanity: the rule is
asymmetric by design — swapping candidate and incumbent at a window the
gate applied must yield stand-down (headroom vanishes), so the gate cannot
be walked back to a starved table by re-running it.

Guard-family mapping (the verdict's four names -> machinery): conservation
= conserve_pass/merge, already in-chain upstream of the counts the gate
reads; event-flood = flood_share vs census (rules 4/5); star-census =
census_expecteds/strict_full_census (the census + confusion channel);
reverse-balance stays at the post-apply flag layer (rebuild_flags) — its
peak-aware applicability makes it info-only on peak windows, and adapting
it to working DBs would be NEW machinery, not "existing guards"; recorded
as out of gate-v1 scope on the record.

## Validation evidence (measured during recon, quoted for the record)

12 on-disk pairs in _replay_scratch/v2_week1 (9 ga3ctrl_* controls vs
*_v2c_* candidates + the cam2 trio, whose on-disk incumbents are the
demotion-standalone tables — sidecars record non-null doses; ground truth
below = sign of the committed score deltas on these exact artifacts, which
is why cam2's deltas here differ from the block-verdict narrative that
compared against block-1's clean controls). The "11 windows" of the
verdict = these minus cam2 study_0700, the dev window.

window            truth   mio_d   R_inc   R_cand  fs_cand  d_cov    sat
cam1 study_0700   STAND   -15.7   +3.3%   +17.3%   29.4%    +170  0.728
cam1 study_1600   STAND   -10.9  -11.9%    +0.4%   24.7%    +190  0.777
cam2 study_0700   APPLY    +1.4   -5.9%    -0.4%   12.4%     +58  0.079
cam2 study_1100   APPLY    +4.7   -9.2%    -4.4%   10.2%     +80  0.119
cam2 study_1600   STAND    -1.0   -0.9%    +5.5%   28.8%    +173  0.066
cam3 study_0600   APPLY    +8.5   -9.4%    +6.4%    6.8%   +7290  0.000
cam4 study_0700   STAND   -15.1   +2.7%   +31.7%   33.0%     +88  0.037
cam4 study_1100   STAND    -5.0   +1.2%   +22.9%   23.1%     +75  0.051
cam4 study_1600   STAND   -23.7   +4.7%   +32.2%   32.9%    +138  0.063
cam5 study_0700   STAND   -11.2   -5.7%   +17.1%   58.5%    +368  0.059
cam5 study_1100   STAND    -8.7  -11.0%   +11.1%   48.1%    +291  0.112
cam5 study_1600   STAND   -11.5   -9.7%    +9.1%   52.5%    +392  0.100

The rule adjudicates 12/12. Margins: flood_share — binding winners' max
10.2% vs losers' min 23.1% (F=15 sits mid-gap; the dev window's 12.4%
leaves 2.6 pts); headroom — winners' max -5.9% vs stand-side max -0.9%
(h=3 has >=2.1 pts each way); saturation — 0.73/0.78 vs everyone else
<=0.12 (6x). Redundancy: cam2-1600 fails TWO guards independently
(headroom -0.9%, flood 28.8%); cam1-1600 fails two (flood 24.7%,
saturation 0.777); cam4 windows fail two (headroom AND flood). The
losers' fs_cand of 23-58% is the verdict's "+25-37% event-flood
signature" measured per-cell; winners sit at 6.8-12.4%.

HONESTY: h and F are placed inside gaps measured on this same 12-window
set. The rule FORM is the applicability law (not fitted), saturation is an
inherited shipped constant, and d_cov>0 never binds here — but h and F are
still validated in-sample. The out-of-sample test is pre-committed: FM51
(held-out site, project 0acb12c0) adjudication joins this validation set
before any flag-posture change, per the handoff.

## Dispositions as product state (wound #1)

New project.db table `dispositions` (idempotent CREATE, the migration
pattern in database.py):

  camera_id INTEGER, variant TEXT, disposition TEXT
  CHECK (disposition IN ('auto','hold','force_once')),
  note TEXT, updated_at TEXT, PRIMARY KEY (camera_id, variant)

Default (no row) = 'auto' (gate adjudicates). 'hold' = operator judgment:
never auto-apply this window (the cam4-HOLD / cam1-PM-live-table lesson —
the campaign's judgment moves from docs into the product). 'force_once' =
operator-approved apply: bypasses the gate once, reverts to 'auto', the
consumption recorded. Every adjudication (either direction) appends to
`apply_adjudications` (camera_id, variant, decision, reasons, metrics
JSON, created_at) — the audit trail that makes the gate's behavior
reviewable from the product, no docs required.

Enforcement points: run_pass2(apply=True) — both the fresh-compute AND the
sidecar-reuse path route through the gate; the process endpoint's S5-union
filters to APPLIED results only (a stood-down window must not inject its
working DB's S5 rows over the incumbent's flags).

## Schema-drift fix (wound #3)

calib_fingerprint digests operator state only; the reuse sidecar therefore
survives schema migrations and _apply_window_events then INSERT-SELECTs
project.db's column list against a pre-migration working DB — "no such
column origin_posterior_json", int2's Error card. Fix: the sidecar gains
`schema_fingerprint` = sha256 of vehicle_events' ordered PRAGMA
table_info column names from the DB the working table was built against;
reuse and plan_intersection's pass2:'current' both require it to match the
CURRENT project.db schema. Legacy sidecars lack the key -> recompute once
and carry it (the existing legacy-sidecar precedent). plan_intersection
reports 'stale' on mismatch instead of feeding a doomed apply.

## Pre-declared gates (all must pass; nothing ships otherwise)

- GATE-AG1 (the block's exit gate): the PRODUCT adjudicator (the shipped
  backend function, not a reimplementation) run offline over the 12
  on-disk pairs picks the score-winning side at ALL 11 blind windows —
  zero Miovision inside the gate; the committed score JSONs only verify
  verdicts afterward. The dev window (cam2 study_0700) is reported
  alongside; expected APPLY.
- GATE-AG2: full pytest suite green; the legacy flow is behavior-identical
  wherever the gate abstains (fresh windows, no-geometry cameras) — the
  896-test base must not need semantic edits outside tests that assert the
  new machinery itself.
- GATE-AG3: schema-drift regression test — a sidecar fingerprinted under a
  different schema must be treated as stale (recompute path) and
  plan_intersection must report 'stale', red-before/green-after against
  the unfixed code path.
- Scope guard: no production apply, no flag-default change, no rollback
  decision inside this block; the gate ships dark (wired but exercised
  only by tests + the offline validation) until the operator reviews the
  evidence.

## Sequencing

1. This plan doc (commit 1).
2. Schema fingerprint fix + regression test (commit 2 — small,
   independent, closes the live Error card's cause).
3. Dispositions + adjudications tables + enforcement + tests (commit 3).
4. apply_gate service + run_pass2/reuse wiring + S5-union filter + unit
   tests (commit 4).
5. scripts/v2_apply_gate_validate.py -> runs/v2_week1/
   apply_gate_validation.json + score cross-check; verdict section
   appended here; handoff refreshed (commit 5).


## BLOCK VERDICT (2026-08-07, same session — all three gates PASS)

**GATE-AG1 PASS: 11/11 binding blind windows (12/12 including the cam2
dev window), through the SHIPPED adjudicator** (adjudicate_apply fed by
gate_census_inputs — the exact product path, record=False), zero
Miovision inside the gate; the committed score JSONs checked verdicts
only afterward. Evidence: runs/v2_week1/apply_gate_validation.json.
Every stand-down's recorded reasons land in the law's failure families:
cam1 saturated_geometry (+ event_flood; 0700 also no_headroom), cam2
study_1600 no_headroom + event_flood (caught twice at the knife-edge),
cam4 no_headroom + event_flood, cam5 event_flood. Every apply is a pure
gate_pass. The three shipped wins the gate authorizes: cam2 0700/1100
and cam3 daylight (+8.5, the campaign's largest).

**GATE-AG2 PASS**: full suite green on the final tree (919 tests; the
one legitimate breakage — test_create_database's table inventory — was
the two new tables, assertion extended). Legacy behavior preserved where
the gate abstains: fresh windows apply ungated (rule 1), no-geometry
cameras apply ungated (rule 2), APPLY_GATE=0 reverts to unconditional
apply.

**GATE-AG3 PASS**: schema_fingerprint + sidecar_reusable shipped; the
drifted-sidecar case reports 'stale' end-to-end (red before the fix by
the old predicate's construction — dump_meta+calib only). int2's Error
card cause is closed: the next process run recomputes instead of dying.

Scope guard held: no production applies ran; the only production-DB
change is the additive empty dispositions/apply_adjudications tables via
the idempotent schema (what any connection performs). V2 mechanism flags
remain default-OFF; APPLY_GATE defaults ON as product architecture.

**What the product now enforces**: uniform two-pass apply can no longer
overwrite curated judgment — an operator 'hold' blocks, and an 'auto'
window must WIN its window under the blind guards, with every
adjudication in the audit trail. The blind-product-test wounds 1 and 3
are closed at the architecture level; wound 2 (detect-basis vs
disposition) is naturally absorbed: a re-derived table that regresses now
stands down instead of shipping.

**NEXT (in order)**:
1. FM51 held-out adjudication (project 0acb12c0) joins the validation set
   — the pre-committed out-of-sample test of h/F before any flag-posture
   change.
2. The bundle rides the gate: enabling the V2 flags for a corridor
   re-process becomes safe-by-construction (cam2+cam3 apply, cam1/4/5
   stand down) — OPERATOR decision, now enforceable in product.
3. G1-closure: re-run the 07-31 blind product test verbatim; the gate +
   dispositions must reproduce >= curated scores with zero hand-holding.
4. Operator decisions still open: push the branch; blind-run rollback
   (partially superseded — cam3's V2 path now exceeds both prior states
   and the gate adjudicates any future candidate).
