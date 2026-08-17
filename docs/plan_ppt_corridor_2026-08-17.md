# PPT corridor round — cam1/4/5 counting blocks
# (2026-08-17, operator "ok go"; instruments already green at all 8
# windows: precision 0.952-0.991, coverage 0.78-0.95)

Eight windows: cam1 study_0700/1600 (no 1100 base dump), cam4 x3,
cam5 x3. Never-applied cameras: the live tables should equal their
base-dump replay controls. Bars from the committed live scores:
cam1 60.5/54.5; cam4 75.4/69.4/75.8; cam5 66.4/71.7/63.1.

## PRE-REGISTERED PROCEDURE (the freeze-selection rule is declared,
## data-driven, and runs BEFORE any candidate exists — the cam2
## precedent formalized)

Per window, in order:
  (c0) tid-alignment: live window (tid,cell,movement) multiset == the
       ga3ctrl control DB's — else STOP that window (basis drift).
  (c1) UNFROZEN DIAGNOSTIC compose (scratch only, never a candidate):
       reveals per-cell err deltas and the movement matrix.
  (c2) FREEZE RULE (declared): any ORIGIN owning a cell whose |err|
       grows > 5 in the diagnostic joins that window's freeze set —
       per CAMERA, the freeze set is the UNION over its windows
       (a camera's geometry is one thing; per-window freezes would be
       overfitting). cam2's origin-28 freeze is this rule's precedent.
  (c3) CANDIDATE compose with the camera's freeze set; gates:
       (g1) zero-mass (asserted);
       (g2) frozen-origin cells byte-equal to live (asserted at score);
       (g3) 5/95 >= live + 1.0 for the window;
       (g4) no cell's |err| grows > 5 — misses confined to
            already-non-compliant cells go to a batched operator
            ruling (the PPT-2 precedent); any healthy-cell regression
            auto-fails;
       (g5) instrument floors re-checked in the compose calibration
            (>= 0.90 / >= 0.60, standing).
  (c4) AG2 candidacy vs live (record=False) — gate_pass_reattr
       required.
  (c5) apply per the audited scripts/v2_apply_reattr.py (fresh
       recorded adjudication, quiesced server incl. the orphan-worker
       kill, backup, swap, exact post-verify of ALL other windows of
       that camera + the applied one), each apply reported
       individually. Authorized by the operator's "ok go" on this
       named round; any (g4) operator-ruling items are batched into
       ONE question BEFORE their applies.

## Deliverables

Diagnostic + candidate JSONs and scores per window (stems
`pptd_cam<N>_<win>` diagnostics, `pptc_cam<N>_<win>` candidates);
per-camera freeze sets recorded here; apply records appended to the
standing apply doc; verdicts here. Committed either way.


---

## VERDICT (2026-08-17) — the round closes with ZERO applies; PPT is a
## cam2 mechanism as built

(c0) PASSED all 8 windows (live == replay controls, multiset-exact).
(c1) diagnostics: the unfrozen mechanism DAMAGES these cameras —
cam4's scorer moved ~290 events into EB_thru, a cell where Miovision
counts ZERO (cam4 is a T-JUNCTION; the movement is physically
impossible — a phantom prototype built from >= 10 misclassified fulls
cleared the 10-full floor that was safe at cam2's 3,000-full density);
cam5 overshoots its starved right-turn cells (NB_right 5->90 vs Mio
21) — the same attractor ft2 found, over-corrected; cam1 floods
EB_left/EB_right. (c2) freeze rule, applied faithfully: cam5 freezes
ALL FOUR origins, cam4 all three (T-junction), cam1 three of four.
(c3) cam1's WB-only candidates re-attribute ZERO events (every move
reads or writes a frozen origin, or dies at floors) -> g3 fails
trivially. cam4/cam5 stand down by rule.

**LEDGER: PPT re-attribution does not transfer to cam1/4/5 as-is.**
The cam2 successes (+5.5, +4.6 shipped) were carried by prototype
MASS — 3,000+ fulls per window at 25 fps. G-PPT-i is now measured
NECESSARY BUT INSUFFICIENT: it validates the scorer on complete
held-out journeys and cannot see fragment-population cell-composition
effects (phantom prototype cells, saturation overshoot). Two named
future iterations, each needing its own gate: (i) per-cell
prototype-quality floors (minimum full-SHARE, not a flat 10-full
count — would have deleted cam4's impossible EB_thru prototype);
(ii) saturation-aware per-cell net-gain caps (would have tempered
cam5's right-turn overshoot and cam2-0700's NB_left double-
correction). PROCESS NOTE, recorded: the first cam1 candidate run
silently applied NO freeze (a string-typed flag made the old int
comparison always-false; the patch script printed success without
verifying) — caught because the census was byte-identical to the
unfrozen diagnostic; fixed with verified edits and re-run. The prior
cam2 applies are unaffected (int-typed flag era, freezes verified
byte-equal at the time).

Production standing after the round (unchanged today):
cam1 60.5/54.5 · cam2 55.8/55.0/49.5 · cam4 75.4/69.4/75.8 ·
cam5 66.4/71.7/63.1 · cam3 72.6.
