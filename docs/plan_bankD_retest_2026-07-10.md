# Plan — bank-D retest under the two-pass recipe (2026-07-10)

**VERDICT (same day): FAIL — D is retired for good, and the failure mode is
bigger than D.** On 07:00–09:00 (the gate's required window) the D arm scores
18.4% per-approach MAE vs the two-pass baseline's 16.6%, with a BROAD
attribution scramble far beyond the added cell: EB-right +316 (483 vs 167 —
baseline hour-2 EB-right was within ±2), SB-thru −317, NB-left −265. The
override bank was verified byte-identical to the applied bank plus exactly
the one drawn path, so the scramble is REAL: **a verbatim drawn centerline
added to a fitted bank acts as a partial-match magnet for truncated tracks
across the whole intersection** — the §2b coverage-blind-matcher hazard,
now measured a FOURTH time (cam2 §2c −18.5%, cam5 audit arm B 38.9%, cam5
arm C phantoms, this). Standing rule hardened: **drawn channels may feed
bank BUILDS (claiming/expecteds/QA) but must never enter the applied
attribution path-set of a fitted bank.** No fitted (28,26) alternative
exists — drawn-channel claiming excludes those tracks from the auto-fit; a
refit-mode variant would be a NEW mechanism needing its own plan. The
EB-thru cell stays covered by its rank-1 S4 queue card (operator review),
which is the designed outcome. The gate below was pre-declared; 07:00
failing ends the test (1100/1600 arms stopped mid-run).

Re-opens the HELD decision from docs/bank_coverage_audit_2026-07-09.md: add the
operator's drawn EB-thru (28→26) path to cam2's applied bank. The July-9 hold
was the metric tension (per-cell better, per-approach worse via cancellation
against EB-right's overcount). Conditions have changed, measured:
- the A4a merge is live (the dedup precondition that failed is superseded);
- the day-long two-pass state shows EB-thru starving (0.24) INTO EB-right
  (1.50) — the exact misattribution arm D pulled back (+13 thru, −5 right);
- the queue's rank-1 card (S4 bank hole, impact 179) is this cell.

## Arms (per study window, 07/11/16)

- **BASELINE** = the applied two-pass state (project.db as of cf88e03) —
  already measured: 16.6 / 13.7 / 12.2% per-approach MAE (120-min windows).
- **D** = identical pass-2 (same dumps, same corpus expecteds from the
  twopass workdir bank QA, same frozen merge) with ONE change: attribution
  paths = applied bank + the drawn EB-thru path
  (`evaluations/cam2_live_plus_ebthru.json`, unchanged since July 9 — the
  applied bank it extends is byte-identical today).

## Gate (pre-declared)

Per window: (a) per-cell abs total improves; (b) EB-thru ratio moves toward 1
without EB-right worsening past its current +; (c) per-approach MAE ≤ the
baseline's. Pass on 07:00 + at least one other window → APPLY: insert the
EB-thru path into `intersection_paths` (sample_window_seconds 1800 — its
support is a 30-min claim), re-run the three pass-2 applies, queue rebuilds
(the S4 hole flag should dissolve itself — the hole no longer exists).
FAIL → D goes back on hold with the new numbers recorded.

Miovision = scorer only; no constants change anywhere; harness in scratchpad
(an A/B of bank CONTENT through the existing pass-2, not a new mechanism).
