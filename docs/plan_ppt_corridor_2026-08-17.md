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
