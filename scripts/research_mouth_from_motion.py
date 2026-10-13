"""STEP 3 of arm mm (2026-10-13, declared in docs/plan_basis_2026-09-11.md): the
offline check BEFORE wiring. Copies each window's control working DB (STEM, the
same-day default) to mo1 (MOUTH_FROM_MOTION) and mo2 (+ COUNT_ONCE) (+ mo3-5 below), applies the
post-passes to the COPIES only, then scores them (v2_score_dev -> score_mo*_...json).
Prints per window: decisions by evidence, entry lines changed (old cell -> new
cell), ties, count-once merges, and the movements each arm moves (Miovision /
control / arm). Afterwards run:
  eval_journeys.py STEM mo1      eval_journeys.py STEM mo2      (dev only)
Step 3b (after the verdict) adds the redesigned moving-car evidence:
  mo3 = THE GRAZE (the ray skips a line it meets along, ray_leg)
  mo4 = mo3 + the ray's direction from the mean early motion
  mo5 = mo4 + lanes fitted over the whole visible moving track
  mo6 = mo4 + the lane tier votes from exclusive cells over the whole track
  mo7 = mo6 + a U-turn only when the visible track itself reverses
ARMS (env MM_ARMS, comma list, default all) picks which to build.
Nothing in production or the held-out set is touched.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_mouth_from_motion.py [STEM]
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services.mouth_from_motion import count_once_pass, mouth_from_motion_pass  # noqa: E402
from backend.services.two_pass import _pinned_gates  # noqa: E402
from eval_journeys import BASE, PROJ, locate  # noqa: E402
from v2_score_dev import CORRIDOR, NORM, SITES, leg_dir_for  # noqa: E402

VARIANTS = {"mo1": {}, "mo2": {}, "mo3": {"graze": True},
            "mo4": {"graze": True, "mean_ray": True},
            "mo5": {"graze": True, "mean_ray": True, "whole": True},
            "mo6": {"graze": True, "mean_ray": True, "exclusive": True},
            "mo7": {"graze": True, "mean_ray": True, "exclusive": True, "uturn_seen": True}}
ARMS = [a for a in os.environ.get("MM_ARMS", ",".join(VARIANTS)).split(",") if a]

WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
           (3, "study_0600"), (4, "study_0700"), (4, "study_1100"), (4, "study_1600"), (5, "study_0700"),
           (5, "study_1100"), (5, "study_1600")]


def score(db: Path) -> tuple[float, float]:
    subprocess.run([sys.executable, "-X", "utf8", "scripts/v2_score_dev.py", str(db)], capture_output=True)
    d = json.loads(Path(f"runs/v2_week1/score_{db.stem}.json").read_text())
    return d["v2"]["pct"], d["v2_approach"]["pct"]


def totals(db: Path) -> dict:
    """movement -> (Miovision, ours) over the window, from the score file."""
    d = json.loads(Path(f"runs/v2_week1/score_{db.stem}.json").read_text())
    return {k: (v[0], v[1]) for k, v in d["totals"].items()}


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "dt2c"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    out = []
    for cam, w in WINDOWS:
        v = con.execute("SELECT content_hash, fps, width, height FROM videos WHERE camera_id=?",
                        (cam,)).fetchone()
        fps = float(v["fps"])
        legs = [dict(r) for r in con.execute("SELECT * FROM legs WHERE camera_id=?", (cam,))]
        ld = leg_dir_for(CORRIDOR, cam, SITES[CORRIDOR])
        src, rows = locate(stem, {}, cam, w, v["content_hash"])
        gates, skip = _pinned_gates(PROJ, cam, rows)
        if gates is None:
            print(f"cam{cam} {w}: no gates {skip}")
            continue
        base = score(src)
        tot0 = totals(src)
        res = {"cam": cam, "w": w, "base": base}
        for arm in ARMS:
            db = BASE / f"{arm}_cam{cam}_{w}.db"
            shutil.copy2(src, db)
            st = mouth_from_motion_pass(db, cam, rows, fps, gates, legs=legs,
                                        frame_size=(v["width"], v["height"]), **VARIANTS[arm])
            if arm != "mo2":
                dec = st.pop("decisions")
                ev = Counter(f"{d['tag']}:{d['evidence']}" for d in dec)
                moves = Counter(
                    f"{ld.get(d['o'])} {NORM.get(d['mv'], d['mv'])} -> {ld.get(d['new_o'])} "
                    f"{NORM.get(d['new_mv'], d['new_mv'])}" for d in dec if d["changed"])
                res[arm + "_info"] = dict(n=len(dec), changed=sum(d["changed"] for d in dec),
                                          ev=dict(ev), moves=moves.most_common(6))
            else:
                co = count_once_pass(db, cam, rows, fps)
                res[arm + "_info"] = dict(count_once=co["count_once_rejected"], headway=co["headway_s"])
            res[arm] = score(db)
            tot = totals(db)
            res[arm + "_cells"] = sorted(
                ((k, tot0[k][0], tot0[k][1], tot[k][1]) for k in tot if tot[k][1] != tot0[k][1]),
                key=lambda r: -abs(r[3] - r[2]))[:5]
        out.append(res)
        print(f"\n== cam{cam} {w}: movement {base[0]} -> "
              + "  ".join(f"{a} {res[a][0]}" for a in ARMS)
              + f"   (approach {base[1]} -> " + "  ".join(f"{a} {res[a][1]}" for a in ARMS) + ")")
        for a in ARMS:
            print(f"   {a}: {res[a + '_info']}")
            print(f"       cells moved (mio, ctrl, arm): {res[a + '_cells']}")
    if out:
        n = len(out)
        for k in ("base", *ARMS):
            print(f"FLEET {k}: movement {sum(r[k][0] for r in out) / n:.2f}  "
                  f"approach {sum(r[k][1] for r in out) / n:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
