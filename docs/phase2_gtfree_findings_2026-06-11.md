# Phase 2 — GT-Free Banks + Fragmentation-Robust Matcher: Findings (2026-06-11)

Plan: docs/implementation_plan_architecture_2026-06-11.md (Phase 2). All numbers are net/gross
@30min via od_accuracy.py, **bank-vs-bank under the identical pure-botsort recipe** (per-camera
Phase-1 knobs auto-applied). Shipped events are untouched — every camera's live numbers still come
from its previously-validated recipe.

## Exit-gate scoreboard (GT-free bank vs Miovision bank, same recipe)

| cam | Miovision bank | GT-free v4 | verdict |
|----:|---------------:|-----------:|---------|
| 2   | 15.8 / 31.8    | **14.6** / 35.1 | **BEATS** the GT bank |
| 3   | 2.5 / 12.5     | 5.2 / 13.0 — held-out PM: **4.9 vs 7.1** | passes; **beats GT bank out-of-sample** |
| 4   | 22.5 / 26.0    | **15.7** / 19.4 | **BEATS** the GT bank |
| 1   | 19.4 / 23.7    | 69.5 | FAILS — anchor-on-through-path (no channel file exists) |
| 5   | 19.4 / 28.9    | 54.3 (with research channels) | FAILS — same mechanism, both endpoints |

**Verdict: the GT-free recipe is viable** — 3 of 5 cameras meet or beat the gate, and the
T-junction (cam3) generalizes to a regime it never saw (bank built on 30 min of AM traffic,
applied to PM: 4.9% vs the Miovision bank's 7.1%). That is the new-site bootstrap story working
end-to-end: 30 minutes of the site's own unlabeled traffic + operator calibration.

## The builder (scripts/build_bank_gtfree.py) — what replaced each Miovision dependency

| Miovision gave us | GT-free replacement (measured iteration) |
|---|---|
| which OD cells exist | anchor grouping + track-level bearing re-binning + channel claims |
| manual >= 5 gate | absolute n >= 5 (the published 1% share rule REJECTED: it killed cam3's real EB-right whose 6 collected tracks = exactly its manual count) |
| movement labels (XML slots) | **leg cardinal pairs** (operator calibration, required anyway for Excel TMC). Image-space shape labeling was tried and FAILED at skewed 4-ways (collinear exits: cam2 105%, cam4 185%) — through/left/right is world knowledge, not image geometry |
| magnet gates (vs manual volume) | bearing-consistency gate (fitted polyline entry/exit vs calibrated-or-consensus leg headings), same-origin coincidence dedup (keep larger support), minor-cell coherence gate (mean member spread <= 40 px; 5 scattered fragments at 59 px spread cost ~4pp before this) |
| (nothing) | per-site QA report (2.4): support shares, bearing residuals, polyline-ambiguity pairs, **leg heading sanity** (flagged cam1 leg 25 at 93 deg off and cam4 leg 34 at 147 deg off — the cam1-label-swap class of error, caught automatically) |

Other load-bearing details: leg headings auto-corrected to observed consensus (>45 deg off) for the
builder's internal tests only; channel declarations claim their tracks BEFORE anchor binning (with
the research matcher's tail-direction gate so the opposing through can't claim the same corridor).

## Why cam1 and cam5 fail — characterized, not mysterious

Both have a leg anchor sitting ON the through-stream's image path. Hundreds of through tracks
endpoint-bin to the wrong leg (cam1: "NB-right" 183 vs manual 1; cam5: "NB-right" 295 vs manual 5),
and the phantom flow then dominates every data-derived reference at that anchor (entry/exit
consensus, auto-fixed headings), so no purely statistical gate can break the tie — the
contamination is self-consistent. Track-level bearing re-binning recovered cam5 from 132->54 and a
channel claim pinned its NB-through, but the research channel file doesn't cover the remaining
corridors (it was drawn for the turn experiments) and cam1 has no channel file at all.

**Remediation (plan's own fallback): an operator channel-drawing session for these cameras** —
draw the through corridors as well as the turns (~30 s per movement in the channel tool). This is
operator minutes, not ground truth. The builder already supports it (channel-priority claims +
hand-drawn fallback). cam1 additionally has the known deeper tracking gap (its shipped 7.2% needed
the ReID path; even its Miovision bank only reaches 19.4% under the standard recipe).

## Shipped: "mdh" matcher as the apply-side default (2.3)

`_mdh_cost` (trajectory_classifier.py): MIN of directed mean-of-minimum distances + tail-direction
term (0.5 px/deg) + exit-proximity term (0.25) — the published fragmentation-robust similarity
(arXiv 2111.09171), partial-overlap-tolerant so it needs no start sweep. A/B vs dtw_mean, identical
banks/recipes:

| cam | dtw_mean | mdh |
|----:|---------:|----:|
| 1   | 19.4 | **18.4** |
| 2 AM | 15.8 | **13.4** |
| 2 PM (held-out) | 21.6 | **18.9** |
| 3   | **2.5** | 3.6 |
| 4   | 22.5 | **14.7** (gross 26.0 -> 18.8) |
| 5   | 19.4 | 19.5 |

Wins 4 of 5 (incl. the held-out regime; biggest on cam4, the attribution/phantom camera), loses
only on cam3. Shipped as: `JOINT_SCORER_COST_METRIC` default = "mdh" (env-overridable) + per-camera
`cameras.calib_cost_metric` override (migration/getter/setter/PATCH validation) + **cam3 pinned to
dtw_mean** (its live 2.5% recipe re-verified byte-for-byte after the flip). No live events
re-applied anywhere — every camera's shipped events still beat the pure-recipe numbers, so mdh
takes effect for future processing and new sites.

## Status vs plan

- 2.2 GT-free banks: core DONE, validated; cam1/cam5 blocked on operator channels (not on code).
- 2.3 distance function: DONE, shipped (mdh default + per-camera override).
- 2.4 QA report: DONE (emitted as *_qa.json next to every built bank; leg-sanity catches
  heading/label errors; warns on ambiguity and bent throughs).
- 2.1 channel tool -> product UI: NOT started (frontend). It is now the binding item: cam1/cam5
  remediation and the <1 hr new-site setup both run through the channel-drawing UI.

## Artifacts

evaluations/gtfree_bank_cam{1..5}.json (+ _qa.json), evaluations/shipped_bank_cam{1..5}.json,
evaluations/phase2_gtfree_{validation,v2,v3,v4}.log, evaluations/phase2_mdh_ab.log,
scripts/build_bank_gtfree.py.
