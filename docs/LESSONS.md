# LESSONS

What past mistakes taught. Read before writing any arm plan (docs/ARM_TEMPLATE.md).

Rules for this file:
- One lesson, one line: date, source, what to do, and WHY. A lesson without its why is deleted.
- Add a lesson only from a measured failure or an operator ruling, never a hunch.
- A lesson seen three times is proposed as a rule or a check. A new check is admitted only if it tests the
  PRODUCT against ground truth, and it must survive a removal trial.
- Every lesson carries a review date three months out; one that has not mattered by then is deleted.
- Never longer than one page. To add past that, delete first.

## Lessons

- 2026-10-15, fm51_arm: print the mtime of the working DB a scorer reads. WHY: it scored a stale DB (last written 2026-09-20) for weeks and every "FM 51 identical" after the linker was void. Review by 2027-02-20.
- 2026-09-10, fleet_flags: never run two fleet_flags.py fleets at once. WHY: they share the arm/ working dir and corrupt each other. Review by 2027-02-20.
- 2026-09-30, arm d2: judge an arm per vehicle (journey labels) as well as on the fleet. WHY: 5/95 totals let errors cancel; d2 failed the fleet yet won cam1 per vehicle. Review by 2027-02-20.
- 2026-09-29, one-default ruling: a camera the default fails is a default problem, never a per-site recipe. WHY: cams 1-3 on one-off BoT-SORT recipes made the 83.50 fleet number dishonest (honest control 80.81). Review by 2027-02-20.
- 2026-09-24, gx2: a letter-of-the-gate miss shipped by ruling is not precedent for arguing a letter down. WHY: the camera clause exists to stop a default that RUINS a window; only the operator rules an exception. Review by 2027-02-20.
- 2026-09-11, blank-site calibration: draw gate lines where vehicles are reliably TRACKED, not at the far mouth. WHY: lines at the mouths sit at coverage ~0.1, below the 0.20 evidence activation, so every counting default is inert (FM 51: 87.5/67.8 vs 91.9/79.3). Review by 2027-02-20.
- 2026-08-22, environment: re-score one archived control on any new machine before trusting a ctrl/arm comparison. WHY: the environment (torch/ultralytics versions) is not part of the measurement basis and cannot be reconstructed. Review by 2027-02-20.
- 2026-11-21, fleet_flags stems: name FLEET_STEM with no underscore (foctl, not fo_ctl). WHY: v2_score_dev reads the camera number from stem.split("_")[1]; fleet_flags swallows the scorer's stderr, so a bad stem printed live->None / delta ? for all windows with no error. Review by 2027-02-20.
- 2026-11-21, COEXISTING_TWIN_DEDUP off: fleet 91.88 -> 90.17 (-1.71), cam4 0700 -4.6, cam4 1600 -3.8, cam5 0700 +1.9. WHY: the linker and tracker twin handling do not cover simultaneous twin tracks; a rule called a post-hoc patch still earned its keep, so score before deleting. Fleet event counts do not show the effect (write-then-reject). Review by 2027-02-21.
- 2026-11-23, STOP_FRACTURE_COLLAPSE off: fleet 91.88 identical, labels identical on 419 vehicles; deleted. WHY: a pass-1 flag cannot be trialled by a pass-2 fleet over existing dumps (they already carry its effect); it needs a re-track (cached detections, ~2 h, deterministic on cam4 1100) and the linked dump must be swapped with it. Review by 2027-02-23.
- 2026-11-28, cam2 EB-right "over-count": hand count 08:31-08:33 = 8 (7 on red), ours 8, Miovision 1. WHY: Miovision drops EB right-on-red after 08:00 (red-minute EB-right 57 -> 7 at the hour, ours 61 -> 64); a reference can be the failing side, so check a disputed cell by hand before an arm. Review by 2027-02-28.
