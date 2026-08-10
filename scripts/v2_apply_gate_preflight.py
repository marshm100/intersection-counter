"""PRE-FLIGHT (read-only): what would the apply gate decide against the
LIVE production tables?

The 11/11 validation compared each candidate against its SCRATCH CONTROL.
In production the incumbent is project.db's applied table — different
rows, therefore possibly different verdicts. Nothing is written here:
record=False, and project.db is opened read-only by the gate's counters.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from backend.database import get_connection, get_db_path        # noqa: E402
from backend.services.apply_gate import adjudicate_apply        # noqa: E402
from backend.services.two_pass import gate_census_inputs        # noqa: E402

PROJECT = "97a7849a"
S = Path("data/projects/97a7849a/_replay_scratch/v2_week1")
RUNS = Path("runs/v2_week1")

CANDIDATES = [
    "twopass_cam1_v2c_study_0700", "twopass_cam1_v2c_study_1600",
    "twopass_cam2_v2c_study_0700", "twopass_cam2_v2c_study_1100",
    "twopass_cam2_v2c_study_1600",
    "twopass_cam3_v2c_study_0600",
    "twopass_cam4_v2c_study_0700", "twopass_cam4_v2c_study_1100",
    "twopass_cam4_v2c_study_1600",
    "twopass_cam5_v2c_study_0700", "twopass_cam5_v2c_study_1100",
    "twopass_cam5_v2c_study_1600",
]


def chash_for(cam):
    conn = get_connection(PROJECT)
    try:
        return conn.execute(
            "SELECT content_hash FROM videos WHERE camera_id=? "
            "ORDER BY sort_order LIMIT 1", (cam,)).fetchone()[0]
    finally:
        conn.close()


print(f"{'window':22} {'decision':11} {'reasons':38} "
      f"{'inc(prod)':>10} {'cand':>7} {'R_inc':>8} {'fs_cand':>8}")
out = []
for stem in CANDIDATES:
    d = json.loads((S / f"{stem}.stats.json").read_text())
    r = d["result"]
    f_lo, f_hi = d["dump_meta"]["frames"]
    fps = (f_hi - f_lo) / r["window_seconds"]
    cam, variant = r["camera_id"], r["variant"]
    census, confusion = gate_census_inputs(PROJECT, cam, chash_for(cam),
                                           variant, fps)
    v = adjudicate_apply(PROJECT, cam, variant,
                         incumbent_db=get_db_path(PROJECT),
                         candidate_db=S / f"{stem}.db",
                         t_lo=f_lo / fps, t_hi=f_hi / fps,
                         census=census, confusion=confusion, record=False)
    m = v["metrics"]
    print(f"cam{cam} {variant:16} {v['decision']:11} "
          f"{','.join(v['reasons'])[:38]:38} {m.get('inc_total', 0):10d} "
          f"{m.get('cand_total', 0):7d} "
          f"{m.get('R_inc', float('nan')):8.1%} "
          f"{m.get('flood_share_cand', float('nan')):8.1%}")
    out.append({"camera": cam, "variant": variant, **v})

(RUNS / "preflight_production_incumbents.json").write_text(
    json.dumps(out, indent=1))
n_apply = sum(1 for o in out if o["decision"] == "apply")
print(f"\nwould APPLY at {n_apply} of {len(out)} windows; "
      f"wrote {RUNS / 'preflight_production_incumbents.json'}")
