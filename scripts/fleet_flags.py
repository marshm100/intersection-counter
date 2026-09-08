"""G-FLEET-1 — offer the shipped flag set to the remaining windows.

Runs pass-2 over each window's EXISTING production dump with
GATE_GROUND_ANCHOR + STRAIGHT_FRAGMENT_RULE + GATE_EVIDENCE_EITHER_CORNER,
scores it against Miovision, and reports coverage/activation/score.
apply=False throughout — nothing touches production.

Usage:  GATE_GROUND_ANCHOR=1 STRAIGHT_FRAGMENT_RULE=1 \
        GATE_EVIDENCE_EITHER_CORNER=1 py -X utf8 scripts/fleet_flags.py
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import (GATE_EVIDENCE_EITHER_CORNER,  # noqa: E402
                            GATE_GROUND_ANCHOR, STRAIGHT_FRAGMENT_RULE)

assert (GATE_GROUND_ANCHOR and STRAIGHT_FRAGMENT_RULE
        and GATE_EVIDENCE_EITHER_CORNER), "flags not armed"

from backend.services.two_pass import run_pass2  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
LIVE = {(1, "study_1600"): 86.2,
        (2, "study_0700"): 70.4, (2, "study_1100"): 71.3,
        (2, "study_1600"): 70.3,
        (3, "study_0600"): 83.7,
        (4, "study_0700"): 75.4, (4, "study_1100"): 73.5,
        (4, "study_1600"): 75.8,
        (5, "study_0700"): 66.4, (5, "study_1100"): 71.7,
        (5, "study_1600"): 63.1}


def main() -> int:
    wd = BASE / "arm"
    wd.mkdir(parents=True, exist_ok=True)
    out = []
    for (cam, variant), live in LIVE.items():
        t = time.time()
        try:
            res = run_pass2(PROJ, cam, variant=variant, workdir=wd,
                            apply=False)
        except Exception as e:
            print(f"cam{cam} {variant}: FAILED {e}", flush=True)
            continue
        rep = res.get("replay") or {}
        act = res.get("evidence_activation") or {}
        stem = BASE / f"ff_cam{cam}_{variant}.db"
        src = wd / f"twopass_cam{cam}_{variant}.db"
        if src.exists():
            shutil.copy2(src, stem)
            subprocess.run([sys.executable, "-X", "utf8",
                            "scripts/v2_score_dev.py", str(stem)],
                           capture_output=True)
        sc = Path(f"runs/v2_week1/score_ff_cam{cam}_{variant}.json")
        mv = ap = None
        if sc.exists():
            d = json.loads(sc.read_text())
            mv, ap = d["v2"]["pct"], d["v2_approach"]["pct"]
        out.append((cam, variant, live, mv, ap, act, rep))
        print(f"cam{cam} {variant}: live {live} -> {mv}  "
              f"(app {ap})  cov {act.get('coverage')} "
              f"{'ON' if act.get('activated') else 'OFF'}  "
              f"events={rep.get('events')} dropped="
              f"{rep.get('insufficient_data')}  ({time.time()-t:.0f}s)",
              flush=True)
    print(f"\n{'window':16}{'live':>7}{'new':>7}{'delta':>8}"
          f"{'cov':>7}{'chan':>6}")
    for cam, variant, live, mv, ap, act, rep in out:
        d = f"{mv - live:+.1f}" if mv is not None else "?"
        print(f"cam{cam} {variant:11}{live:>7}{mv if mv else 0:>7}{d:>8}"
              f"{act.get('coverage', 0):>7}"
              f"{'ON' if act.get('activated') else 'OFF':>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
