"""G-BR-1 Arm C driver (docs/plan_bank_refresh_2026-09-06.md).

--arm ctrl:    stock priors — run_pass2 resolves production normally.
--arm refresh: refreshed priors — patches backend.database.get_db_path
  to resolve the refreshed snapshot. THE TRAP this dodges:
  pass2_replay.replay_camera:141-143 clobbers its working DB with a
  fresh copy of whatever get_db_path resolves, so pre-seeding a
  refreshed DB as the replay target is a silent no-op; the bank=
  injection arg is equally wrong (collapses per-row
  sample_window_seconds and bypasses run_pass2's census chain).
  Patching the resolver is the one path that carries the refreshed
  priors through the full production chain. apply=False guarantees
  the production writers never run; detection dumps resolve via the
  literal data/projects path, so pass-1 is shared by both arms.

Usage:  py -X utf8 scripts/bankref_validate.py --arm ctrl|refresh
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/bankref_20260906")
SNAPSHOT = BASE / "refreshed_project.db"
WINDOWS = [(1, "study_0700"), (1, "study_1600"),
           (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
           (3, "study_0600"),
           (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", choices=["ctrl", "refresh"], required=True)
    args = ap.parse_args()

    import backend.database as DB
    import backend.services.two_pass as TP

    if args.arm == "refresh":
        assert SNAPSHOT.exists(), "refreshed snapshot missing"
        _orig = DB.get_db_path
        DB.get_db_path = (lambda pid: SNAPSHOT if pid == PROJECT
                          else _orig(pid))
        TP.get_db_path = DB.get_db_path

    workdir = BASE / args.arm
    workdir.mkdir(parents=True, exist_ok=True)
    for cam, variant in WINDOWS:
        t0 = time.time()
        try:
            res = TP.run_pass2(PROJECT, cam, variant=variant,
                               workdir=workdir, apply=False)
            n = (res.get("replay") or {}).get("events", "?")
            print(f"[{args.arm}] cam{cam} {variant}: events={n} "
                  f"({time.time()-t0:.0f}s)", flush=True)
        except Exception as e:
            print(f"[{args.arm}] cam{cam} {variant}: FAILED {e}", flush=True)

        if args.arm == "refresh":
            # post-replay assertion: refreshed priors survived the copy
            import sqlite3
            wdb = workdir / f"twopass_cam{cam}_{variant}.db"
            if wdb.exists():
                a = sqlite3.connect(f"file:{SNAPSHOT}?mode=ro", uri=True)
                b = sqlite3.connect(f"file:{wdb}?mode=ro", uri=True)
                q = ("SELECT path_id, supporting_count, sample_window_seconds"
                     " FROM intersection_paths WHERE camera_id = ?"
                     " ORDER BY path_id")
                assert (list(a.execute(q, (cam,)))
                        == list(b.execute(q, (cam,)))), \
                    f"priors did not survive replay for cam{cam}!"
                a.close(); b.close()
    print(f"[{args.arm}] ARM COMPLETE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
