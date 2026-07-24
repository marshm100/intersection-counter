# Plan — evidence-gate ACTIVATION PRECONDITION (the item-8 revival, 2026-07-24)

Item 8's mechanism ① (origin-evidence gate + partial-evidence posterior,
flags OFF, code+tests revival-ready) is PROVEN at cam2 — 9.1 → 3.3%
per-approach total (EB 24.3→17.0, NB 13.9→3.2; stage-5 verdict,
`plan_posterior_half_2026-07-15.md`) — and PROVEN HARMFUL at low-evidence
cameras (cam1 EB 14.4→199.4%). It was retired as a blind default because
nothing decided per-camera whether to trust it. This plan adds that
decider: a GT-free activation precondition, and measures the gate on BOTH
detection bases at cam2 — where the ft2 re-baseline
(`ft2_corridor_rebaseline_2026-07-24.md`) left the corridor's only ft2
wins (NB 8.9 / SB 8.6) trapped behind an EB split-flood (38.3).

**The compound hypothesis (new, from the re-baseline):** an occlusion-split
fragment born mid-intersection crosses NO entry gate — so the evidence
gate + posterior should suppress cam2's EB flood (unevidenced fragments
can't hard-claim EB) while KEEPING ft2's genuine NB/SB recall (real
entries carry evidence). If that holds, ft2+gate is the first
configuration with a credible shot at all-approaches ≤5% on the
corridor's hardest camera.

## The rule (frozen before any sweep)

    ACTIVATE(cam) iff coverage(cam) >= C,  C = 0.70
    coverage = n_origin_evidenced / n_tracks, measured on the camera's OWN
    gate-ON replay — operator geometry + applied bank only, NO ground truth.

C = 0.70 is the midpoint of the measured gap between the proven-good site
(cam2 ≈ 0.80) and every proven-bad one (cam1/4/5 0.36–0.60, FM51 0.02–0.06),
declared as exactly that — the validation below tests the DECISIONS it
makes, not the value itself. No other constants; the gate + posterior run
at their stage-4 frozen constants unchanged.

## Phase 1 — measurements (replay-only, both bases exist on disk; flags via
the existing env overrides, NO code edits)

1. **Coverage census**: gate-ON replay per (cam, basis) over the study
   dumps — stock cams 1/2/4/5 + ft2 cams 1/2/4/5 + FM51 (ftv1/ftv2n) —
   recording coverage + per-approach error. One replay serves both numbers.
2. **cam2 stock + gate**: must reproduce the 3.3-class result on today's
   chain (regression check — the veto phase-3 edits are flag-gated inert,
   prove it holds).
3. **cam2 ft2 + gate**: the compound question. Watch cells: EB 38.3 → must
   crush toward ≤17 (the stock+gate level) or below; NB/SB must HOLD their
   8.9/8.6 wins (the fragments-carry-no-evidence hypothesis predicts both).
4. **Stand-down confirmation**: FM51 + cam1/4/5 coverages must land below C
   on both bases (expected from item-8's censuses; cam1's 199.4% harm is
   already on the record — cite, don't re-burn iGPU).

## Acceptance (the ship gate for wiring)

- The rule's DECISIONS are all correct: ON exactly at cam2 (both bases),
  OFF everywhere else including the held-out FM51 — decided blindly from
  each camera's own replay.
- cam2 stock+gate reproduces ≤3.5% total with no approach above ~17.
- cam2 ft2+gate: every approach ≤ stock+gate's, EB materially below 38.3;
  the aspiration is all-approaches ≤5% — not required to ship the
  precondition, required to CLAIM the bar.
- No touched-cell regression anywhere the rule activates.

PASS → wire the precondition into pass-2 (per-camera auto-activation from
its own replay coverage; measure-then-apply; own commit + operator ✓).
FAIL → verdict section + the rule joins the retirement ledger with its
numbers; the corridor stays stock-basis production.

## Costs

Replays only (~1–4 min/window post-398c913): ~9 corridor windows × 2 bases
+ FM51's 4 window-DBs, scored with the established per-approach scorer.
No detection, no training, no product wiring in this phase.

---

## PHASE-1 VERDICT (2026-07-24 — census + gate-ON scoring complete;
evidence runs/finetune_v2/evgate_phase1.json)

**The stock-basis revival PASSES — cam2's best numbers ever recorded. The
ft2 compound FAILS. The activation rule makes every correct decision, with
one honest recalibration.**

**Coverage census** (n_origin_evidenced/n_tracks_total, gate-ON replay —
the census's own pinned definition):

| camera×basis | coverage | decision | correct? |
|---|---|---|---|
| cam2 stock | **0.510** | **ON** | ✓ 4.1→**2.8%** total (NB 13.9→**3.2**, SB→7.3, WB 9.9, EB 23.5) |
| cam2 ft2 | 0.344 | OFF | ✓ gate-ON measured **17.3%** — see below |
| cam5 stock | 0.387 | OFF | ✓ (item-8 harm class) |
| cam4 stock | 0.341 | OFF | ✓ |
| cam4 ft2 | 0.332 | OFF | ✓ |
| cam5 ft2 | 0.329 | OFF | ✓ |
| cam1 stock | 0.265 | OFF | ✓ (the EB-199% site) |
| cam1 ft2 | 0.183 | OFF | ✓ |
| FM51 ft1 / ftv2 | 0.023 / 0.020 | OFF | ✓ held-out control stands down ×20 clear |

**C recalibrated 0.70 → 0.45** — a DEFINITION change, not a knob turn: the
plan froze 0.70 against item-8's census scale; this census's pinned
denominator (all born tracks) reads the same signal lower (cam2-stock's
numerator 4691 at 0700 is IDENTICAL to item-8's — only the denominator
differs). On this scale the gap is [0.387, 0.510], midpoint 0.45, and the
DECISION SET is exactly what 0.70 produced on the old scale: activate
cam2-stock alone. Margin note: the gap is 12 pts wide; a future site
landing in it is a gray zone — the conservation feeders remain the
backstop, and activation only ever moves a camera TO the proven-better
configuration.

**The compound hypothesis is DEAD as configured** (gate+posterior on ft2):
pooled 17.3% total (EB 61.4, NB 13.8) vs no-gate ft2's 4.9. Mechanism: on
ft2 the unevidenced population IS the fragment flood (8,551/13,907 tracks
at AM), and the posterior half hard-counts unevidenced tracks by corpus
proportions — "counting by popularity," the item-8 plan's named risk,
realized at scale (+750 events AM). The filter half behaved; the posterior
fed on the flood. **The census statistic itself detects this blindly**
(cam2 coverage 0.510→0.344 under ft2) — the rule refuses ft2 for the same
reason the scoring condemns it. Named-but-not-chased follow-up: a
posterior-OFF ablation on ft2 (one env flag) — bounded, unproven, parked.

**Ship recommendation:** wire the activation precondition into pass-2 —
per-camera auto-activation when the camera's own gate-ON replay coverage
≥ 0.45 (this census's definition, computed blind at any site) — which
today activates exactly cam2-stock: total 2.8%, three of four approaches
at/near the bar (NB 3.2 / SB 7.3 / WB 9.9), EB 23.5 the remaining wall
(the occlusion-split class; a distinct mechanism). Measure-then-apply,
operator ✓, own commit.
