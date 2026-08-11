"""Why did the 5/95 denominator grow? — the Block-0 side finding.

docs/plan_v2_confound_split_2026-08-11.md

rule595.score_cells scores the UNION of (bin, cell) slots present in either
source and skips only slots where BOTH are zero. So a candidate that counts
where Miovision reports nothing ENLARGES ITS OWN DENOMINATOR: the new slot
is scored, our count must fit +/-5 against a reference of 0, and it usually
does not.

Measured at cam1 study_1600: arm A 48/88 compliant -> arm C 54/118. Six MORE
correct slots, thirty more scored, percentage down 54.5 -> 45.8. The headline
"regression" is mostly slots that did not exist before.

This script classifies every slot that a candidate ADDS relative to the
control:
    PHANTOM   Miovision reports 0 in that (bin, cell) — we invented it
    MISS      Miovision reports > 0 and we were previously silent there;
              compliant => a RECOVERY, non-compliant => a real but wrong count

The distinction decides the remedy. Phantoms are a suppression problem and
are fixable without touching the mechanism that produced the recall gains.
Misses that land non-compliant are a calibration problem. Treating the two
as one number is what makes "the bundle regressed" unactionable.

Usage:
  py -X utf8 scripts/v2_phantom_diag.py --camera 1 --variant study_1600
  py -X utf8 scripts/v2_phantom_diag.py --camera 1 --variant study_1600 --arm B
"""
from __future__ import annotations

import argparse
import sys
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.rule595 import score_cells                  # noqa: E402
from v2_score_dev import (CORRIDOR, SITES, events_from_db,        # noqa: E402
                          leg_dir_for, load_miovision,
                          per_min_from_events)

SCRATCH = Path("data/projects/97a7849a/_replay_scratch")


def rows_for(db: Path, cam: int, variant: str, project: str) -> dict:
    site = SITES[project]
    leg_dir = leg_dir_for(project, cam, site)
    mio = load_miovision(cam, site)
    lo, hi = site["windows"][variant]
    minutes = [dtime(h, m) for h in range(lo, hi) for m in range(60)]
    mio_minutes = [m for m in minutes if m in mio]
    ours = per_min_from_events(events_from_db(str(db), cam, site), leg_dir)
    rows = score_cells(ours, mio, mio_minutes)
    return {(r["bin"], r["cell"]): r for r in rows}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=CORRIDOR)
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True, help="base variant, e.g. study_1600")
    ap.add_argument("--arm", default="C", choices=["B", "C"],
                    help="candidate arm to compare against control arm A")
    args = ap.parse_args()
    cam, var = args.camera, args.variant

    ctrl_db = SCRATCH / "v2_week1" / f"ga3ctrl_cam{cam}_{var}.db"
    if args.arm == "C":
        cand_db = SCRATCH / "v2_confound" / "armC" / f"armC_cam{cam}_v2c_{var}.db"
        if not cand_db.exists():
            cand_db = SCRATCH / "v2_confound" / "armC2" / f"armC_cam{cam}_v2c_{var}.db"
    else:
        cand_db = SCRATCH / "v2_week1" / f"twopass_cam{cam}_v2c_{var}.db"
    for p in (ctrl_db, cand_db):
        if not p.exists():
            print(f"missing: {p}")
            return 1

    a = rows_for(ctrl_db, cam, var, args.project)
    c = rows_for(cand_db, cam, var, args.project)

    added = sorted(set(c) - set(a))
    dropped = sorted(set(a) - set(c))
    shared = sorted(set(a) & set(c))

    phantom = [k for k in added if c[k]["ref"] == 0]
    miss_ok = [k for k in added if c[k]["ref"] > 0 and c[k]["ok"]]
    miss_bad = [k for k in added if c[k]["ref"] > 0 and not c[k]["ok"]]
    flipped_bad = [k for k in shared if a[k]["ok"] and not c[k]["ok"]]
    flipped_ok = [k for k in shared if not a[k]["ok"] and c[k]["ok"]]

    ka = sum(1 for k in a if a[k]["ok"])
    kc = sum(1 for k in c if c[k]["ok"])
    added_fail = [k for k in added if not c[k]["ok"]]
    ut_fail = [k for k in added_fail if "uturn" in str(k[1])]
    print(f"=== cam{cam} {var}: arm A (control) vs arm {args.arm} ===")
    print(f"  A {ka:>3d}/{len(a):<3d} = {100*ka/max(len(a),1):.1f}%"
          f"   ->   {args.arm} {kc:>3d}/{len(c):<3d} = {100*kc/max(len(c),1):.1f}%")
    print()
    print(f"  slots ADDED by arm {args.arm}: {len(added)}")
    print(f"    PHANTOM  (Mio reports 0)          {len(phantom):>4d}")
    print(f"    MISS ok  (Mio > 0, we now fit)    {len(miss_ok):>4d}"
          f"   <- genuine RECOVERY")
    print(f"    MISS bad (Mio > 0, count wrong)   {len(miss_bad):>4d}")
    print(f"  slots DROPPED: {len(dropped)}")
    print(f"  shared slots RIGHT->WRONG: {len(flipped_bad)}"
          f"   WRONG->RIGHT: {len(flipped_ok)}")
    print()
    # THE NUMBER THAT DECIDES THE REMEDY. Added slots are mostly harmless:
    # tolerance(0) = 5.0 per bin, so a phantom slot under ~5 vehicles PASSES.
    # Counting phantom MASS overstates the damage — measured 2026-08-11, it
    # sent the first read of this block at a u-turn guard that buys nothing.
    print(f"  DAMAGE SPLIT  (non-compliant {len(a)-ka} -> {len(c)-kc})")
    print(f"    added slots that FAIL      {len(added_fail):>4d}"
          f"   (u-turns among them: {len(ut_fail)})")
    print(f"    shared net right->wrong    {len(flipped_bad)-len(flipped_ok):>+4d}")
    dom = ("SHARED-CELL INFLATION" if (len(flipped_bad) - len(flipped_ok))
           > len(added_fail) else "ADDED SLOTS")
    print(f"    dominant: {dom}")
    if flipped_bad:
        by = {}
        for k in flipped_bad:
            by[k[1]] = by.get(k[1], 0) + 1
        print("    right->wrong by cell: "
              + " · ".join(f"{k} {v}" for k, v in
                           sorted(by.items(), key=lambda x: -x[1])))
    print()
    if phantom:
        tot = sum(c[k]["ours"] for k in phantom)
        print(f"  phantom mass: {tot} counted vehicles across {len(phantom)} slots")
        by_cell: dict = {}
        for k in phantom:
            by_cell.setdefault(k[1], []).append(c[k]["ours"])
        print(f"  {'cell':>16s} {'slots':>6s} {'counts':>7s}")
        for cell, v in sorted(by_cell.items(), key=lambda x: -sum(x[1])):
            print(f"  {str(cell):>16s} {len(v):>6d} {sum(v):>7d}")
    if flipped_bad:
        print()
        print(f"  {'bin':>6s} {'cell':>16s} {'ref':>5s} {'A':>5s} {args.arm:>5s}")
        for k in flipped_bad[:15]:
            print(f"  {str(k[0]):>6s} {str(k[1]):>16s} {c[k]['ref']:>5.0f} "
                  f"{a[k]['ours']:>5.0f} {c[k]['ours']:>5.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
