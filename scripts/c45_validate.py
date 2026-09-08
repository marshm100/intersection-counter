"""G-C45-1 B2 — pass-2 + scoring for cam4/cam5's l1_ dumps under the
shipped cam1 environment (both operator laws on).

Usage:  GATE_GROUND_ANCHOR=1 STRAIGHT_FRAGMENT_RULE=1 py -X utf8 scripts/c45_validate.py
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import (GATE_GROUND_ANCHOR,  # noqa: E402
                            STRAIGHT_FRAGMENT_RULE)

assert GATE_GROUND_ANCHOR and STRAIGHT_FRAGMENT_RULE, "flags not armed"

from backend.services.two_pass import run_pass2  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/c45_20260907")
WINDOWS = [(4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]


def main() -> int:
    wd = BASE / "arm"
    wd.mkdir(parents=True, exist_ok=True)
    for cam, variant in WINDOWS:
        t = time.time()
        try:
            res = run_pass2(PROJ, cam, variant=f"l1_{variant}",
                            workdir=wd, apply=False)
            rep = res.get("replay") or {}
            print(f"cam{cam} {variant}: events={rep.get('events')} "
                  f"rerouted={rep.get('straight_rerouted')} "
                  f"dropped={rep.get('straight_dropped')} "
                  f"({time.time()-t:.0f}s)", flush=True)
        except Exception as e:
            print(f"cam{cam} {variant}: FAILED {e}", flush=True)
            continue
        src = wd / f"twopass_cam{cam}_l1_{variant}.db"
        stem = BASE / f"cx_cam{cam}_{variant}.db"
        if src.exists():
            shutil.copy2(src, stem)
            subprocess.run([sys.executable, "-X", "utf8",
                            "scripts/v2_score_dev.py", str(stem)],
                           capture_output=True)
    print("ARM COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
