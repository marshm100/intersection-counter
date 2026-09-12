"""G-FLEET-1 — offer the shipped flag set to the remaining windows.

Runs pass-2 over each window's EXISTING production dump with
GATE_GROUND_ANCHOR + STRAIGHT_FRAGMENT_RULE + GATE_EVIDENCE_EITHER_CORNER,
scores it against Miovision, and reports coverage/activation/score.
apply=False throughout — nothing touches production.

Usage:  GATE_GROUND_ANCHOR=1 STRAIGHT_FRAGMENT_RULE=1 \
        GATE_EVIDENCE_EITHER_CORNER=1 py -X utf8 scripts/fleet_flags.py
Env:    FLEET_ARMS=1:study_0700,3:study_0600  (window selector)
        FLEET_STEM=sm2                        (arm name for DBs / scores)
        FLEET_WORKERS=6                       (parallel windows; 1 = serial)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.config as _cfg  # noqa: E402

# G-DEF-1 (2026-09-10): the arm runs under WHATEVER flags the environment
# sets - including none, the blank-site baseline - and prints them, so
# a run's basis is never a guess. (The old assert required the fleet
# set; the reuse fingerprint already forces a recompute on any change.)
_ARMED = sorted(n for n in dir(_cfg)
                if n.isupper() and isinstance(getattr(_cfg, n), bool)
                and getattr(_cfg, n))
print(f"flags ON: {', '.join(_ARMED) or 'none (baseline)'}", flush=True)

from backend.services.two_pass import run_pass2  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
import os
_ARMS = os.environ.get("FLEET_ARMS", "")
# FLEET_STEM names the arm's scratch DBs and score JSONs (default "ff",
# the G-FLEET-1 arm). G-SM-1 (2026-09-09) runs as "sm" so the fleet arm
# stays on disk as the comparison basis.
_STEM = os.environ.get("FLEET_STEM", "ff")
# live standings: cam1 1600 shipped at 95.3 on 2026-09-08; cam1 0700 /
# cam2 0700 / cam2 1100 / cam3 0600 shipped 2026-09-09 (G-SM-1 iter 3)
_ALL = {(1, "study_0700"): 85.1, (1, "study_1600"): 95.3, (2, "study_0700"): 75.2, (2, "study_1100"): 76.7, (2, "study_1600"): 68.5, (3, "study_0600"): 88.5, (4, "study_0700"): 73.3, (4, "study_1100"): 78.7, (4, "study_1600"): 70.2, (5, "study_0700"): 79.0, (5, "study_1100"): 73.3, (5, "study_1600"): 71.8}   # THE DEFAULT's standings, 2026-09-12 (fleet 77.97 after the fracture rule)   # 2026-09-11 (fleet 76.97 after G-BAR-1): 84.0 95.3 75.2 75.7 71.3 87.6 71.1 74.5 75.4 73.3 71.4 68.9   # THE DEFAULT's standings, 2026-09-10 (fleet 75.86; cam3 87.6 on the 09-11 ruled headings)
if _ARMS:
    want = [tuple(a.split(":")) for a in _ARMS.split(",")]
    # a basis-tagged variant (l1_study_0700) scores against the plain
    # window's live standing; an unknown window scores against 0
    LIVE = {(int(c), v): _ALL.get((int(c), v), _ALL.get((int(c), v.split("study_")[-1] and "study_" + v.split("study_")[-1]), 0.0))
            for c, v in want}
else:
    LIVE = {k: v for k, v in _ALL.items() if k != (1, "study_0700")}


# FLEET_WORKERS (2026-09-09, operator go): windows run in PARALLEL
# processes, one per window, up to this many at once. Each window
# writes its own working DB / bank / score JSON under distinct names
# and only READS the pass-1 dumps and project DB, so they do not
# collide. The arm's wall time becomes its longest window (cam3 ~15
# min) instead of the sum (~28 min). FLEET_WORKERS=1 is the old
# sequential run.
_WORKERS = int(os.environ.get("FLEET_WORKERS", "6"))


def _run_window(cam: int, variant: str, live: float, wd: Path):
    """One window end to end: pass-2 over the existing dump, copy the
    working DB to the arm stem, score it. Returns the summary tuple
    (or None on failure). Safe to run in a child process."""
    t = time.time()
    try:
        res = run_pass2(PROJ, cam, variant=variant, workdir=wd,
                        apply=False)
    except Exception as e:
        print(f"cam{cam} {variant}: FAILED {e}", flush=True)
        return None
    rep = res.get("replay") or {}
    act = res.get("evidence_activation") or {}
    stem = BASE / f"{_STEM}_cam{cam}_{variant}.db"
    src = wd / f"twopass_cam{cam}_{variant}.db"
    if src.exists():
        shutil.copy2(src, stem)
        subprocess.run([sys.executable, "-X", "utf8",
                        "scripts/v2_score_dev.py", str(stem)],
                       capture_output=True)
    sc = Path(f"runs/v2_week1/score_{_STEM}_cam{cam}_{variant}.json")
    mv = ap = None
    if sc.exists():
        d = json.loads(sc.read_text())
        mv, ap = d["v2"]["pct"], d["v2_approach"]["pct"]
    print(f"cam{cam} {variant}: live {live} -> {mv}  "
          f"(app {ap})  cov {act.get('coverage')} "
          f"{'ON' if act.get('activated') else 'OFF'}  "
          f"events={rep.get('events')} dropped="
          f"{rep.get('insufficient_data')}  ({time.time()-t:.0f}s)",
          flush=True)
    return (cam, variant, live, mv, ap, act, rep)


def main() -> int:
    wd = BASE / "arm"
    wd.mkdir(parents=True, exist_ok=True)
    # longest window first so it never waits behind the short ones
    order = sorted(LIVE.items(), key=lambda kv: (kv[0][0] != 3, kv[0]))
    out = []
    if _WORKERS <= 1 or len(order) == 1:
        for (cam, variant), live in order:
            r = _run_window(cam, variant, live, wd)
            if r:
                out.append(r)
    else:
        from concurrent.futures import ProcessPoolExecutor
        with ProcessPoolExecutor(max_workers=min(_WORKERS, len(order))) as ex:
            futs = [ex.submit(_run_window, cam, variant, live, wd)
                    for (cam, variant), live in order]
            for f in futs:
                r = f.result()
                if r:
                    out.append(r)
    out.sort(key=lambda r: (r[0], r[1]))
    scored = [r for r in out if r[3] is not None]
    if scored:
        fleet = sum(r[3] for r in scored) / len(scored)
        live_m = sum(r[2] for r in scored) / len(scored)
        print(f"\nFLEET mean over {len(scored)} windows: live {live_m:.2f} "
              f"-> arm {fleet:.2f} ({fleet - live_m:+.2f})", flush=True)
        for cam in sorted({r[0] for r in scored}):
            rs = [r for r in scored if r[0] == cam]
            print(f"  cam{cam} mean: live {sum(r[2] for r in rs) / len(rs):.2f} "
                  f"-> {sum(r[3] for r in rs) / len(rs):.2f}", flush=True)
    print(f"\n{'window':16}{'live':>7}{'new':>7}{'delta':>8}"
          f"{'cov':>7}{'chan':>6}")
    for cam, variant, live, mv, ap, act, rep in out:
        d = f"{mv - live:+.1f}" if (mv is not None and live) else "?"
        print(f"cam{cam} {variant:11}{live:>7}{mv if mv else 0:>7}{d:>8}"
              f"{act.get('coverage', 0):>7}"
              f"{'ON' if act.get('activated') else 'OFF':>6}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
