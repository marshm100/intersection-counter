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
