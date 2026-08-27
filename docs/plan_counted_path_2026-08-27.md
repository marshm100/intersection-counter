# COUNTED-PATH CAMPAIGN — gate doc (declared 2026-08-27, before any scored run)

Diagnosis lineage: docs/diag_waste_reel_2026-08-27.md (the operator's
two review reels + measurements). Detection solid; paths exist; only
60-71% of tracked vehicles become counts in the worst windows. Three
mechanisms, operator-validated, built flag-gated (all default off):

- A QUEUE_AWARE_MERGE (636bd9f): the turn-merge pair predicate
  additionally requires near-disjoint spans (MERGE_MAX_OVERLAP_FRAMES
  12). Meter at 0700: merged_away 306 -> 48; EB_left 129 -> 0;
  SB_right 177 -> 41; the operator's scene-4 left-turner survives.
- B FLOW_ORIGIN_INFERENCE (167829d): entry-less births claim the
  single leg whose dominant-flow path passes the birth with agreeing
  bearing (frozen constants: ORIGIN_VETO_D_MAIN_PX, CHAIN_DIR_TOL_DEG);
  pertinence guard (drawn-gate side test) refuses periphery births;
  distinct counter n_origin_flow_inferred.
- C STOP_FRACTURE_COLLAPSE: dump transform; twin pinned to the rest
  position at BOTH ends, strictly inside the dwell gap, collapses
  into the victim (frozen STITCH_STAT_*; one-end proximity = the
  forbidden caterpillar predicate; gate-chord refusal). Collapsed
  29/43/76 pairs on the three cp_ dumps — the SEQUENTIAL class.
- C2 COEXISTING_TWIN_DEDUP (amendment, measured before declaration):
  the operator's scenes 1-3 measured as COEXISTING twins (overlapping
  spans, births 12-123 px apart, boxes riding one vehicle), which the
  dump transform's gap signature cannot see and the queue-aware merge
  now rightly protects. Event-level identity test in pass-2, BEFORE
  the volume-gated merge: spans overlap >= TWIN_OVERLAP_FRAC (0.6) of
  the shorter life, median common-frame center distance <=
  STITCH_STAT_DIST, median common-frame box IoU >= TWIN_IOU_MIN (0.2
  — boxes on ONE vehicle overlap; queue neighbors' IoU is ~0 at any
  distance). Shorter track's event rejected (write-then-reject).
  Meter at 0700: 123 twin pairs; all three operator scenes resolve to
  exactly one count.

## G-CP-1 (decisive)

- ARM: cp_ dumps (idc detections = yolo26l@1280 floor 0.10, stock
  tracker, STOP_FRACTURE_COLLAPSE=1 at pass-1) -> pass-2 with
  QUEUE_AWARE_MERGE=1 + FLOW_ORIGIN_INFERENCE=1 +
  COEXISTING_TWIN_DEDUP=1 + MOTION_QUALIFIED_EVIDENCE=1. Fresh scratch workdir
  gcp1_20260827; copy-to-stem gcp1_cam2_study_*; one v2_score_dev
  call.
- CONTROLS: shipped 64.8 pooled (67.3/62.0/65.2) — the decisive bar;
  solo-C 64.3 (62.4/66.7/64.0) — the same detections with no
  mechanisms, the attribution control.
- PASS: pooled movement > 64.8 AND no window more than 2.0 below its
  shipped control (floors 65.3/60.0/63.2). Approach bar recorded
  (secondary).
- Readouts: both bars; per-cell deltas in SB_right / EB_left /
  WB_right / NB_thru (the named engines' cells); merged_away census;
  n_origin_flow_inferred per window; stop_fracture_collapsed per
  dump meta; dup-pair census (the scene-1 signature); u-turn canary;
  evidence activation (witnessed-crossing coverage — flow-inferred
  origins deliberately EXCLUDED from the coverage metric); QD law
  (added deficit-cell volume -> operator sample sheet).
- SEQUENCE: arm replays (mechanical) -> mechanism demos -> OPERATOR
  ACK -> only then v2_score_dev. MISS: ledgered, flags stay off,
  production untouched. PASS: ship ladder (PROCESSING_MODES entry for
  the l1280 recipe + the three flags + MQE, Confirm & process +
  force_once, operator go).

## Interactions ledgered

- A un-rejects volume in cells the volume gate polices — expecteds
  unchanged; the borderline S5 signal untouched.
- B adds origin mass without witnessed crossings; MQE (on in the arm)
  governs witnessed crossings only — disjoint surfaces by
  construction; the coverage metric excludes inferred origins.
- C removes dup volume in the same cells A un-rejects — directions
  oppose; the gate adjudicates the net.
- The exit_only origin_frame quirk (entry_gates.py:361) is known and
  untouched this campaign.

## VERDICT (2026-08-27): G-CP-1 **PASS** — the campaign's first

Operator ack on all six demo scenes preceded the run (card
ack_reel_gcp1; scene-6 clarification verified: the queued vehicle's
discharge counts via its successor track).

  window       ARM     shipped   solo-C
  0700         70.4     67.3      62.4
  1100         71.3     62.0      66.7
  1600         70.3     65.2      64.0
  pooled       70.6     64.8      64.3     (+5.8 over shipped;
                                            every window over its
                                            own control; floors moot)

Best cam2 basis ever recorded (previous best window 67.3; now every
window 70.3-71.3). Approach bar: 28.1/59.4/28.1 vs 43.8/50.0/40.6 —
mixed (secondary, recorded; 1100 +9.4, 0700/1600 down; anatomy below).

NAMED-CELL HEALING at 0700 [Mio / arm / production]:
  SB_right 379 / 378 / 219  — the 160-vehicle deficit healed to ONE
  EB_left  229 / 236 / 174  — healed to +7
  NB_thru 2198 / 2225 / 2226 — held
  SB_thru 1384 / 1216 / 1170 — +46 recovered, -168 residual (the
    far-band/occlusion through class; next lever)
  WB_right 293 / 355 / 323  — regressed +32 (residual overcount;
    ledgered)
  EB_right stuck ~39/bin vs 11 (known fisheye-corner class, pre-
    existing; untouched by this campaign)
U-turn canary: EB 11 vs Mio 2 (elevated, small numbers; prod was 8).

Mechanism activity per window (armed-verification recorded): twin
pairs 137/?/?; merged_away 48/47/84 (was 306 at 0700); flow-inferred
origins 122/128/144; stop-fracture collapses 29/43/76; activation
0.569/0.485/0.489 (witnessed-crossing coverage, inferred origins
excluded).

SHIP: awaiting operator go. Ship ladder = PROCESSING_MODES entry
(yolo26l@1280 recipe), the four flags + MQE default-on for cam2,
production dump rebuilds, pre-ship VACUUM backup, Confirm & process +
force_once, post-apply re-score.

## SHIPPED (2026-08-27)

The full ladder, every step verified:
1. Config commit b055d8d: PROCESSING_MODES "counted_path"
   (yolo26l@1280 c0.10); five mechanism flags default-ON; the two
   legacy pins re-pinned flag-off explicitly; project processing_mode
   = counted_path; suite 1,126 green.
2. Promotion: study_0700/1100/1600 caches + dumps renamed aside as
   pre_cp_* and replaced by the cp_ artifacts with corrected truthful
   sidecars (model/imgsz/conf/content_hash); armed-verification
   passed (frames exact, complete true, stop_fracture_collapsed
   29/43/76, backend botsort). The 1600 rename required the server
   kill (the known Windows memmap handle).
3. Server relaunched fresh; flags frozen ON (first replay's sidecar
   confirms twin_dedup + origin_flow_inferred active).
4. Pre-ship backup backups/project_20260827T220538_pre_ship_cp.db
   (VACUUM INTO, integrity ok, 96,422 events).
5. Confirm & process, empty body: applied TRUE x3, apply-gate
   decision "apply" (gate_pass) in all three windows — NO force_once
   needed (the incumbent under-claimed the new census; headroom
   existed as predicted).
6. Post-apply re-score: PRODUCTION = ARM exactly —
   70.4 / 71.3 / 70.3 movement (approach 28.1 / 59.4 / 28.1).
   Live spot-check: SB_right 0700 = 378 vs Miovision 379.

Production basis is now 70.6 pooled movement. Standing caveats
unchanged: no applies on cams 1/3/4/5 (dormant drawn gates + the new
default-on flags would both land there); scratch variants
(cp_/idc_/id_/s4_/pre_cp_) retained as experiment artifacts.
