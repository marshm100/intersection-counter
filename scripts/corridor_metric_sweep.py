"""mdh vs dtw_mean per-approach + net sweep across corridor cameras, via the
full-chain replay (no retrack). One process (imports load once), streaming per
(cam, metric). Decide the default cost metric with the user from the output.
Usage: py -u metric_sweep.py [cam1 cam2 ...]   (default: all but cam2, already done)
ASCII prints."""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve())); sys.path.insert(0, str(Path(".").resolve()))
import replay_fullchain as R

PROJECT = "97a7849a"
cams = [int(a) for a in sys.argv[1:]] or [1, 3, 4, 5]

for cam in cams:
    for metric in ("mdh", "dtw_mean"):
        print(f"\n########## cam{cam}  cost_metric={metric} ##########", flush=True)
        try:
            pm, nw, ntot = R.replay(PROJECT, cam, cost_metric=metric)
            print(f"(replay wrote {nw}/{ntot})", flush=True)
            R.report(cam, pm, metric)
        except Exception as e:
            print(f"cam{cam} {metric}: ERROR {e}", flush=True)
        sys.stdout.flush()
