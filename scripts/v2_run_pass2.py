"""Pipeline-V2 — run the PRODUCTION pass-2 on a dump variant, in scratch.

Calls backend.services.two_pass.run_pass2 with apply=False: corpus bank +
replay-classify + merge land in a working DB under _replay_scratch —
production tables untouched. This is how V2 assembly is measured on the
REAL attribution chain (control: the original variant; treatment: the
v2a_ re-ID'd variant).

Usage:
  py -X utf8 scripts/v2_run_pass2.py --camera 2 --variant v2a_study_0700
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.two_pass import run_pass2        # noqa: E402

def default_workdir(project: str) -> str:
    """Per-project scratch (the corridor's path is unchanged by this: it
    resolves to the same data/projects/97a7849a/_replay_scratch/v2_week1)."""
    return f"data/projects/{project}/_replay_scratch/v2_week1"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--workdir", default=None,
                    help="override the per-project scratch dir")
    args = ap.parse_args()
    workdir = args.workdir or default_workdir(args.project)
    t0 = time.time()
    res = run_pass2(args.project, args.camera, variant=args.variant,
                    workdir=workdir, apply=False)
    rep = res.get("replay", {})
    mrg = res.get("merge", {})
    print(f"[pass2] cam{args.camera} {args.variant}: tracks={rep.get('tracks')} "
          f"events={rep.get('events')} insufficient={rep.get('insufficient_data')} "
          f"merge_kept={mrg.get('kept')} merged_away={mrg.get('merged_away')} "
          f"out={res.get('out_db')} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
