"""G-LT-1 stage 2 — pass-2 + scoring over the eg_ dumps.

--arm b: guard dumps + stock pass-2 (isolates the emergence guard).
--arm c: guard dumps + CONCEALER_ORIGIN_INHERITANCE=1 (adds the
         origin tier). The env flag is set before backend.config
         imports.

Baseline for comparison: the bankref treatment scores (brt_*) — the
exact production configuration of today (refreshed priors, stock
tracker). Working DBs land in _replay_scratch/ltg_20260906/arm{b,c};
scoring stems eg{b,c}_cam{N}_{variant} (single-token prefix, the
v2_score_dev parsing contract).

Usage:  py -X utf8 scripts/ltg_validate.py --arm b|c
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("--arm", choices=["b", "c"], required=True)
ARGS = ap.parse_args()

if ARGS.arm == "c":
    os.environ["CONCEALER_ORIGIN_INHERITANCE"] = "1"   # before config
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/ltg_20260906")
WINDOWS = [(1, "study_0700"), (1, "study_1600"),
           (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
           (3, "study_0600")]


def main() -> int:
    from backend.services.two_pass import run_pass2
    workdir = BASE / f"arm{ARGS.arm}"
    workdir.mkdir(parents=True, exist_ok=True)
    for cam, variant in WINDOWS:
        t = time.time()
        try:
            res = run_pass2(PROJ, cam, variant=f"eg_{variant}",
                            workdir=workdir, apply=False)
            rep = res.get("replay") or {}
            print(f"[arm{ARGS.arm}] cam{cam} {variant}: "
                  f"events={rep.get('events')} "
                  f"concealer={rep.get('origin_concealer_inherited', 0)} "
                  f"({time.time()-t:.0f}s)", flush=True)
        except Exception as e:
            print(f"[arm{ARGS.arm}] cam{cam} {variant}: FAILED {e}",
                  flush=True)
            continue
        wdb = workdir / f"twopass_cam{cam}_eg_{variant}.db"
        stem = BASE / f"eg{ARGS.arm}_cam{cam}_{variant}.db"
        if wdb.exists():
            shutil.copy2(wdb, stem)
    # score every stem for this arm
    for cam, variant in WINDOWS:
        stem = BASE / f"eg{ARGS.arm}_cam{cam}_{variant}.db"
        if stem.exists():
            subprocess.run([sys.executable, "-X", "utf8",
                            "scripts/v2_score_dev.py", str(stem)],
                           capture_output=True)
    print(f"[arm{ARGS.arm}] ARM COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
