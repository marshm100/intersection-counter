"""G-BLANK-1 arm — the default on FM 51, pass-2 over a dump, scored.

Runs run_pass2(0acb12c0, cam 2, variant, apply=False) under whatever
the process's config defaults are (no env flags = the default),
copies the working DB to a stem, scores it with v2_score_dev
--project 0acb12c0, and prints movement / approach / coverage.

Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/fm51_arm.py STEM VARIANT [VARIANT...]
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.two_pass import run_pass2  # noqa: E402

PROJ, CAM = __import__("os").environ.get("FM51_PROJ", "0acb12c0"), 2
BASE = Path("data/projects/0acb12c0/_replay_scratch/blank_20260911")


def main() -> int:
    stem, variants = sys.argv[1], sys.argv[2:]
    wd = BASE / "arm"
    wd.mkdir(parents=True, exist_ok=True)
    for variant in variants:
        t = time.time()
        res = run_pass2(PROJ, CAM, variant=variant, workdir=wd, apply=False)
        rep = res.get("replay") or {}
        act = res.get("evidence_activation") or {}
        src = wd / f"twopass_cam{CAM}_{variant}.db"
        dst = BASE / f"{stem}_cam{CAM}_{variant}.db"
        shutil.copy2(src, dst)
        out = subprocess.run([sys.executable, "-X", "utf8", "scripts/v2_score_dev.py",
                              "--project", "0acb12c0", str(dst)], capture_output=True, text=True)
        sc = Path(f"runs/v2_week1/score_{dst.stem}.json")
        mv = ap = None
        if sc.exists():
            d = json.loads(sc.read_text())
            mv, ap = d["v2"]["pct"], d["v2_approach"]["pct"]
        else:
            print(out.stdout[-2000:], out.stderr[-2000:])
        print(f"FM51 {stem} {variant}: movement {mv}  approach {ap}  cov {act.get('coverage')} "
              f"{'ON' if act.get('activated') else 'OFF'}  events={rep.get('events')} "
              f"dropped={rep.get('insufficient_data')}  ({time.time() - t:.0f}s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
