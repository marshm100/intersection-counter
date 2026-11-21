# Removal-trial inventory — boolean flags in backend/config.py (2026-11-20)

Plan: docs/plan_removal_trials_2026-11-20.md. Built from config.py defaults, the comment above each flag, code
references outside config/tests, and doc mentions. about 56 boolean flags matched by a text scan; 6 more env settings
(3 ORIGIN_* enables, 3 tuning strings) were not classified. **Not measured:** no fleet was run. "Evidence" below
means a result written down in config.py or CLAUDE.md. A flag marked "none found" may still have been measured
in a handoff or the DB; that makes it a trial candidate, not proven dead.

## A. Ship ruling on file, default ON (keep; 15 rules in CLAUDE.md)
GATE_GROUND_ANCHOR, STRAIGHT_FRAGMENT_RULE, GATE_EVIDENCE_EITHER_CORNER, JOURNEY_STATE_MACHINE,
STRAIGHT_FRAGMENT_INCLUDE_PATH_FITS, GATE_EXIT_ONLY_BINDING, TRACKLET_LINKER, NOCROSS_NO_FALLBACK, THEFT_SPLIT,
FULL_JOURNEY_RESCUE, NOCROSS_DROP_SMALL, MOUTH_FROM_MOTION. Each has a dated operator go and a score in CLAUDE.md.
Not trial candidates. (Tracker defaults — TRACKER_POSITION_RECOVERY, TRACKER_CONFIRM_BY_POSITION, TRACKER_EDGE_EXIT,
TRACKER_WEAK_BIRTH, TRACKER_FUSE_SCORE — are judged on the tracking chains per the tracker ruling, not here.)

## B. Default ON with NO ship ruling or measurement found — first removal-trial candidates
| Flag | What it does | Why it is a candidate |
|---|---|---|
| FLOW_ORIGIN_INFERENCE | entry-less track gets an origin from its own birth point + own first-8-point bearing matched to fitted path templates; a unique claim only, never popularity (pipeline.py:1158) | CORRECTED same day after reading the code: this fits the on-screen-only ruling's allowance ("its own path matched against fitted path templates"), so no ruling is needed on principle. Still a trial candidate: shipped 2026-08-27 on the old basis, never re-measured since the linker, and fires 3-1755 times per window in the 10-15 health sidecars (cam3 0600: 1755). See plan_flow_origin_trial_2026-11-20.md. |
| STOP_FRACTURE_COLLAPSE | post-pass merges red-light twin births (two_pass.py:1343) | A post-hoc count patch for fractures; the linker is now the only fragment rule (Step 9.124). Fix-tracking-not-count-patches memory applies. |
| COEXISTING_TWIN_DEDUP (TRIAL 2026-11-21: KEEP, fleet -1.71 off) | event-level dedup of simultaneous twin tracks (two_pass.py:1999) | Same: a post-hoc patch. Tracker twin handling (TRACKER_TWIN_RETIRE, held-box guard) covers the cause. |
| GATE_FULL_SUPREMACY, APPLY_GATE_ENABLED, MOTION_QUALIFIED_EVIDENCE, EVIDENCE_ACTIVATION_ENABLED, MOUTH_FROM_GATE_HEADING | gate/evidence plumbing | Used widely (docs 4-9 mentions); EVIDENCE_ACTIVATION is part of the 0.20-coverage rule in CLAUDE.md. Likely keep; confirm owner. Lower priority. |
| TWO_PASS_ENABLED, TRACK_FATE_LEDGER | infrastructure / diagnostics | Keep. TRACK_FATE_LEDGER is diagnostics only and byte-identical on the counts. |

## C. Default OFF, a negative or "never ship" result is written down (delete candidates)
| Flag | Recorded result |
|---|---|
| V2_TIMELOCAL | "LEDGERED-DEAD 2026-08-06 ... never enable without a debiasing design". |
| A3_CUT_DUMPS | DEFAULT OFF after the Demo-1 negative 2026-08-24 (SB_thru projected -479 -> -1126 at 1600). |
| CHAIN_GLUE | DEFAULT OFF after the Demo-2 negative 2026-08-24 (EB_right error +246 -> +429); only consulted when A3_CUT_DUMPS is on, so it dies with it. |
| LINKER_STOPPED_LEVEL | lk1: 5,052 stopped links on cam3, SB/NB through -930/-590. CLAUDE.md says it broke cam3. |
| TRACKER_WEAK_BIRTH_PROMOTE | measured 2026-09-12: one-track -2/-3/-30, breaks +5/+12/+80. |
| NOCROSS_DROP_ALL | arm nc1, superseded by NOCROSS_DROP_SMALL (nc2). |
| NOCROSS_EXTENT_FALLBACK | arm nf2, superseded by NOCROSS_NO_FALLBACK (nf1b). |
| APPLY_GATE_FAIL_OPEN | the "old behavior" kept as a switch; fail-closed is the contract. |

## D. Default OFF, built for an arm that has no recorded verdict (trial or delete)
JOURNEY_FIRST_EXIT (operator ruling 2026-09-08, but superseded by JOURNEY_STATE_MACHINE ON?) · MOUTH_FROM_GATE,
HEADING_FROM_CROSSINGS (G-DEF-2, docs mention only plan_default) · BORN_INSIDE_NEAREST_LINE (G-DEF-7, "MISSED" per the
BORN_AT_MOUTH comment) · BORN_AT_MOUTH · EXIT_GRAZE_SKIP (cam5 N_right) · ON_SCREEN_ONLY · COUNT_ONCE ("stays OFF")
· TRACKER_APPEARANCE_VETO (arm av1) · TRACKER_TWIN_RETIRE (arm dt1) · FPS_AWARE (cam2 25 fps test open) ·
DETECT_DEDUP_HEAD, DETECT_HALF (new cache basis) · CONSERVE_ON_ACTIVATION, CHAIN_ARBITRATION_EVIDENCE (conservation
pass family; "never actually run") · EMERGENCE_GUARD, CONCEALER_ORIGIN_INHERITANCE (anti-theft campaign, no config
comment) · V2_DEMOTION_ENABLED, V2_GATE_AXIS (v2 campaign, "until G-OR1..4 pass"), V2_MERGE_RESCUE (open since 9.124;
the only remaining caller path of merge rejections is unproven).
Several of these have a live shipped successor (state machine, mm1, linker). The first thing each trial must answer is
whether the successor already does its job.

## Proposed order of the follow-up arms (each its own plan + gate)
1. **Trial FLOW_ORIGIN_INFERENCE** (no ruling needed after the code read): control vs flag-off on the fleet.
2. **Delete group C** (8 flags, all with a written negative): code removal, tests, one fleet run to confirm default
   unchanged (they are OFF, so by construction identical; the fleet run proves it). Template step 2 says delete in the
   same arm as something that makes it unnecessary; group C is itself that arm.
3. **Trial STOP_FRACTURE_COLLAPSE and COEXISTING_TWIN_DEDUP** switched off together on the fleet + journey labels.
4. Group D one family at a time, newest first.

## Unproven
- Group C "negative" results come from config comments; the arm records they cite were not re-read.
- The doc-mention counts were by name only. A flag renamed in an old doc would show zero.


## Update 2026-11-21
- FLOW_ORIGIN_INFERENCE: deleted (Step 9.129, fleet-confirmed).
- Group C: 7 of 8 deleted in docs/plan_delete_negative_flags_2026-11-21.md (fleet confirm pending). TRACKER_WEAK_BIRTH_PROMOTE deferred: recipe key is in the pass-1 reuse fingerprint; needs a tracker-evidence arm.
