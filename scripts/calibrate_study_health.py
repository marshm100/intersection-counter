"""Study-health S2 calibration — the corridor truth table.

Runs the reference-free battery over every camera-window whose TRUE
accuracy is measured (the ledger), including the known-bad experiment
arms, and prints (measured score, verdict, firing signals) sorted by
measured accuracy. The battery never sees the scores; separation is
the acceptance (gate doc G-SD-1).

Usage:  py -X utf8 scripts/calibrate_study_health.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.study_health import window_health  # noqa: E402

P = "97a7849a"
SCR = "data/projects/97a7849a/_replay_scratch"

# (label, cam, variant, db_path, workdir, measured_mov, measured_app)
ROWS = [
    # ---- live production basis (db/workdir = production defaults) ----
    ("cam1-0700 live",  1, "study_0700", None, None, 60.5, 62.5),
    ("cam1-1600 live",  1, "study_1600", None, None, 86.2, 78.1),
    ("cam2-0700 live",  2, "study_0700", None, None, 70.4, 28.1),
    ("cam2-1100 live",  2, "study_1100", None, None, 71.3, 59.4),
    ("cam2-1600 live",  2, "study_1600", None, None, 70.3, 28.1),
    ("cam3-0600 live",  3, "study_0600", None, None, 83.7, 61.9),
    ("cam4-0700 live",  4, "study_0700", None, None, 75.4, 37.5),
    ("cam4-1100 live",  4, "study_1100", None, None, 73.5, 41.7),
    ("cam4-1600 live",  4, "study_1600", None, None, 75.8, 66.7),
    ("cam5-0700 live",  5, "study_0700", None, None, 66.4, 50.0),
    ("cam5-1100 live",  5, "study_1100", None, None, 71.7, 40.6),
    ("cam5-1600 live",  5, "study_1600", None, None, 63.1, 21.9),
    # ---- known-bad / experiment arms (stem DB + scratch workdir) -----
    ("cam5-1100 fl ARM (NB_left flood)", 5, "fl_study_1100",
     f"{SCR}/gfp2_20260828/gfp2_cam5_study_1100.db",
     f"{SCR}/gfp2_20260828", 78.3, 34.4),
    ("cam4-0700 fl ARM (collapse)", 4, "fl_study_0700",
     f"{SCR}/gfp2_20260828/gfp2_cam4_study_0700.db",
     f"{SCR}/gfp2_20260828", 53.8, 41.7),
    ("cam4-1100 fl ARM", 4, "fl_study_1100",
     f"{SCR}/gfp2_20260828/gfp2_cam4_study_1100.db",
     f"{SCR}/gfp2_20260828", 57.7, 70.8),
    ("cam1-0700 fl ARM (morning break)", 1, "fl_study_0700",
     f"{SCR}/gfp2_20260828/gfp2_cam1_study_0700.db",
     f"{SCR}/gfp2_20260828", 63.0, 31.2),
    ("cam5-1100 ne ARM (b145 winner)", 5, "ne_study_1100",
     f"{SCR}/cam5_na_20260828/ne_cam5_study_1100.db",
     f"{SCR}/cam5_na_20260828", 70.8, 81.2),
]


def main() -> int:
    print(f"{'window':38}{'mov':>6}{'app':>6}  {'verdict':8} firing")
    rows = []
    for label, cam, variant, dbp, wd, mov, app in ROWS:
        try:
            h = window_health(P, cam, variant, db_path=dbp,
                              workdir=Path(wd) if wd else None,
                              write=False)
        except Exception as e:
            h = None
            err = str(e)[:60]
        if h is None:
            print(f"{label:38}{mov:>6}{app:>6}  {'NO DATA':8}")
            continue
        firing = "; ".join(r.split(" - ")[0][:44] for r in h["reasons"])
        rows.append((label, mov, app, h))
        print(f"{label:38}{mov:>6}{app:>6}  {h['verdict']:8} {firing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
