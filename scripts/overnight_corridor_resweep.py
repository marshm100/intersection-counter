"""Overnight corridor re-sweep — NON-DESTRUCTIVE. For cam1/cam3/cam4/cam5,
re-derive the bank with CURRENT code (staleness check) and sweep the per-camera
NMS/match knobs, scoring every candidate with od_accuracy --camera N. Writes a
morning brief: shipped net vs the best candidate per camera + the apply command
for any candidate that beats shipped. NEVER writes project.db — the morning
review + engineer visual gate decides what ships (per cam2 2026-06-08, a fresh
rebuild alone moved 16.4->10.0, so staleness is real; but net-better can still
hide compensating per-minute errors, hence the gate).

cam2 is intentionally skipped (already done: nms0.85 + match0.90 -> 8.8%).
cam1's incumbent is BoT+ReID (7.2%); ReID is NOT re-run here (too costly
overnight) — cam1's non-ReID candidates only ship if they beat 7.2%.

Usage:  py scripts/overnight_corridor_resweep.py --minutes 30
        py scripts/overnight_corridor_resweep.py --minutes 2 --cameras 4   # smoke
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import overnight_accuracy as oa
from overnight_accuracy import PY, PROJ_DB, SCR, log, run, measure

# (nms, match) knob grid. nms 'off'/'0.85'; match None = mode default (~0.8),
# 0.90 = the stricter association that fixed cam2's through-duplication.
KNOB_GRID = [("off", None), ("off", 0.90), ("0.85", None), ("0.85", 0.90)]


def resweep_camera(cam: int, minutes: float) -> dict:
    mins = str(minutes)
    tag = f"cam{cam}"
    shipped = measure(cam, PROJ_DB, minutes)[0]
    log(f"=== {tag}: shipped baseline net={shipped}% ===")

    bank = str(Path(SCR) / f"resweep_{tag}_bank.json")
    rc, _ = run([PY, "scripts/build_bank.py", "--camera", str(cam), "--minutes", mins,
                 "--out", bank], f"{tag} build_bank")
    if rc != 0:
        return {"cam": cam, "shipped": shipped, "error": "build_bank failed"}

    candidates = []  # (net, recipe_label, db_path)

    # Candidate A: bank-only BoT-retrack (cam3's shipped recipe; also the turns
    # source for the hybrid arms).
    botdb = str(Path(SCR) / f"resweep_{tag}_bot.db")
    rc, _ = run([PY, "scripts/apply_bank.py", "--camera", str(cam), "--backend", "botsort",
                 "--minutes", mins, "--bank", bank, "--out-db", botdb], f"{tag} botsort bank")
    if rc == 0:
        net = measure(cam, botdb, minutes)[0]
        if net is not None:
            candidates.append((net, "bank/botsort", botdb))
            log(f"   {tag} [bank/botsort]: net={net}%")

    # Candidates B: bytetrack-hybrid over the knob grid (throughs from bytetrack
    # with the swept knobs, turns merged from the shared botsort bank).
    if rc == 0:  # need botdb for the hybrid turns
        for nms, match in KNOB_GRID:
            mlabel = "m0.8" if match is None else f"m{match}"
            label = f"hybrid/nms{nms}/{mlabel}"
            btdb = str(Path(SCR) / f"resweep_{tag}_bt_{nms}_{mlabel}.db")
            cmd = [PY, "scripts/apply_bank.py", "--camera", str(cam), "--backend", "bytetrack",
                   "--minutes", mins, "--bank", bank, "--out-db", btdb, "--nms-iou", nms]
            if match is not None:
                cmd += ["--match-thresh", str(match)]
            rc2, _ = run(cmd, f"{tag} throughs [{label}]")
            if rc2 != 0:
                continue
            hydb = str(Path(SCR) / f"resweep_{tag}_hy_{nms}_{mlabel}.db")
            # --throughs-db is the bytetrack throughs (btdb); turns merged from botdb.
            rc3, _ = run([PY, "scripts/apply_hybrid.py", "--camera", str(cam), "--minutes", mins,
                          "--bank", bank, "--bot-db", botdb, "--throughs-db", btdb,
                          "--out-db", hydb], f"{tag} hybrid [{label}]")
            if rc3 != 0:
                continue
            net = measure(cam, hydb, minutes)[0]
            if net is not None:
                candidates.append((net, label, hydb))
                log(f"   {tag} [{label}]: net={net}%")

    if not candidates:
        return {"cam": cam, "shipped": shipped, "error": "no candidates measured"}
    best = min(candidates, key=lambda c: c[0])
    log(f"   {tag} BEST candidate: {best[1]} net={best[0]}% (shipped {shipped}%) "
        f"delta={best[0] - shipped:+.1f}pp")
    return {"cam": cam, "shipped": shipped, "best_net": best[0],
            "best_recipe": best[1], "best_db": best[2], "bank": bank, "botdb": botdb,
            "all": [(round(n, 1), lbl) for n, lbl, _ in sorted(candidates)]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--cameras", type=int, nargs="*", default=[1, 3, 4, 5])
    args = ap.parse_args()
    oa.LOG_PATH = f"evaluations/corridor_resweep_{time.strftime('%Y%m%d')}.log"
    log(f"###### CORRIDOR RE-SWEEP  cameras={args.cameras}  window={args.minutes}min ######")

    results = []
    for cam in args.cameras:
        try:
            results.append(resweep_camera(cam, args.minutes))
        except Exception as e:  # one camera's failure never aborts the night
            log(f"!! cam{cam} EXCEPTION: {e!r}")
            results.append({"cam": cam, "error": repr(e)})

    log("\n###### MORNING BRIEF ######")
    log(f"{'cam':<5}{'shipped':>9}{'best':>8}{'delta':>8}  recipe")
    for r in results:
        if "best_net" in r:
            d = r["best_net"] - r["shipped"]
            flag = "  <-- APPLY" if d < -0.2 else ""
            log(f"cam{r['cam']:<2}{r['shipped']:>8.1f}%{r['best_net']:>7.1f}%{d:>+7.1f}pp  {r['best_recipe']}{flag}")
        else:
            log(f"cam{r['cam']:<2}  ERROR: {r.get('error')}")
    log("\nApply commands for winners (review + visual-gate FIRST, then run):")
    for r in results:
        if r.get("best_net") is not None and r["best_net"] < r["shipped"] - 0.2:
            if r["best_recipe"] == "bank/botsort":
                log(f"  py scripts/apply_bank.py --camera {r['cam']} --minutes {args.minutes:g} "
                    f"--bank {r['bank']} --apply  # net {r['best_net']}%")
            else:
                # hybrid recipe label: hybrid/nms<x>/m<y>
                btdb = r["best_db"].replace("_hy_", "_bt_")
                log(f"  py scripts/apply_hybrid.py --camera {r['cam']} --minutes {args.minutes:g} "
                    f"--bank {r['bank']} --bot-db {r['botdb']} --throughs-db {btdb} --apply  "
                    f"# {r['best_recipe']} net {r['best_net']}%")
    log("\n(measure-only run complete — nothing applied to project.db)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
