"""G-BR-1 Arm H — the health truth table with refreshed priors.

Live windows: baseline = production DB (stale priors), refreshed =
the bankref snapshot (same shipped events, refreshed priors) — the
exact ship preview. Known-bad arms: their stem DBs get a copy with
ONLY the prior columns transplanted to the refreshed values, so the
question "would health still catch this broken run under the new
priors?" is answered honestly.

PASS: cam1-1600's stale-prior RED clears; known-bad arms still
fire; no live verdict degrades without a real cause.

Usage:  py -X utf8 scripts/bankref_health_check.py
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.study_health import window_health  # noqa: E402

P = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/bankref_20260906")
SNAP = BASE / "refreshed_project.db"
SCR = "data/projects/97a7849a/_replay_scratch"

LIVE = [(1, "study_0700"), (1, "study_1600"),
        (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
        (3, "study_0600"),
        (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
        (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]

BAD_ARMS = [
    ("cam5-1100 fl ARM (NB_left flood)", 5, "fl_study_1100",
     f"{SCR}/gfp2_20260828/gfp2_cam5_study_1100.db", f"{SCR}/gfp2_20260828"),
    ("cam4-0700 fl ARM (collapse)", 4, "fl_study_0700",
     f"{SCR}/gfp2_20260828/gfp2_cam4_study_0700.db", f"{SCR}/gfp2_20260828"),
    ("cam4-1100 fl ARM", 4, "fl_study_1100",
     f"{SCR}/gfp2_20260828/gfp2_cam4_study_1100.db", f"{SCR}/gfp2_20260828"),
    ("cam1-0700 fl ARM (morning break)", 1, "fl_study_0700",
     f"{SCR}/gfp2_20260828/gfp2_cam1_study_0700.db", f"{SCR}/gfp2_20260828"),
]


def transplant_priors(src_db: str, camera_id: int) -> Path:
    """Copy an arm stem and overwrite ONLY the two prior columns with
    the refreshed values (matched per (origin, destination) cell)."""
    dst = BASE / f"hp_{Path(src_db).name}"
    shutil.copy2(src_db, dst)
    diff = json.loads((BASE / "bank_diff.json").read_text())
    c = sqlite3.connect(dst)
    with c:
        for r in diff:
            if r["camera_id"] != camera_id:
                continue
            o, d = r["cell"].split("->")
            c.execute("UPDATE intersection_paths SET supporting_count=?, "
                      "sample_window_seconds=? WHERE camera_id=? AND "
                      "origin_leg_id=? AND destination_leg_id=?",
                      (r["new"][0], r["new"][1], camera_id, int(o), int(d)))
    c.close()
    return dst


def fire_summary(h) -> str:
    if h is None:
        return "NO DATA"
    firing = "; ".join(x.split(" - ")[0][:40] for x in h["reasons"])
    return f"{h['verdict']:8} {firing}"


def main() -> int:
    print("=== LIVE windows: baseline (stale) vs refreshed priors ===")
    for cam, variant in LIVE:
        base = window_health(P, cam, variant, write=False)
        refr = window_health(P, cam, variant, db_path=str(SNAP), write=False)
        b = base["verdict"] if base else "NO DATA"
        r = refr["verdict"] if refr else "NO DATA"
        mark = "" if b == r else "  <-- CHANGED"
        print(f"cam{cam} {variant:11} {b:8} -> {r:8}{mark}")
        if b != r or (refr and refr["verdict"] != "GREEN"):
            print(f"    refreshed: {fire_summary(refr)}")
    print("\n=== KNOWN-BAD arms: must STILL fire under refreshed priors ===")
    for label, cam, variant, dbp, wd in BAD_ARMS:
        hp = transplant_priors(dbp, cam)
        try:
            h = window_health(P, cam, variant, db_path=str(hp),
                              workdir=Path(wd), write=False)
        except Exception as e:
            h = None
            print(f"{label:38} ERROR {str(e)[:50]}")
            continue
        print(f"{label:38} {fire_summary(h)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
