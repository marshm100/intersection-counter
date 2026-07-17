"""THE acceptance metric: AVG |err| <= 5% per 15-min interval vs ground truth.

Net counts hide per-interval error — a run can net ~0% while individual 15-min
bins swing far past 5% (cam1: AVG |err| ~7% vs manual while Miovision holds
~2.8%). So per-interval mean-ABSOLUTE error, not net, is the bar.

This is a DEVELOPMENT-VALIDATION metric: it needs ground truth (manual or
Miovision), which we do NOT have at a real site. At deployment the blind proxy
is the acceptance gate (backend/services/spot_check.acceptance — spot-count
error + the flag queue), which we validate to track this metric. See
docs/MASTER_PLAN.md.

Timing floor: at fine granularity a vehicle our clock bins at 15:14:59 and
Miovision bins at 15:15:01 lands in different bins, so even a perfect counter
shows a few % per interval. That floor (Miovision sits ~2.8% vs manual on cam1)
is why the realistic bar is <=5%, not <=1% — see [[project_accuracy_target_metric]].

Pure functions (summarize_bins / per_interval) have no heavy deps so they are
unit-tested directly; the CLI lazy-imports the per-minute loaders.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import time

TARGET_PCT = 5.0
REF_FLOOR = 20          # ignore bins whose reference total is below this (noise)
MIN_BIN_MINUTES = 10    # a bin needs this many counted minutes (partial-sheet guard)


def summarize_bins(pairs, ref_floor: float = REF_FLOOR, target: float = TARGET_PCT) -> dict:
    """pairs: iterable of (label, ours_total, ref_total). Returns the AVG |err|
    summary over bins whose reference total >= ref_floor."""
    rows = []
    for label, o, r in pairs:
        if r is None or r < ref_floor:
            continue
        rows.append((label, o, r, 100.0 * abs(o - r) / r))
    if not rows:
        return {"avg_abs_err_pct": None, "max_abs_err_pct": None,
                "worst_interval": None, "n_bins": 0, "n_over_target": 0,
                "target_pct": target, "verdict": "n/a", "per_interval": []}
    errs = [e for *_, e in rows]
    avg = sum(errs) / len(errs)
    worst = max(rows, key=lambda x: x[3])
    return {
        "avg_abs_err_pct": round(avg, 1),
        "max_abs_err_pct": round(worst[3], 1),
        "worst_interval": worst[0],
        "n_bins": len(rows),
        "n_over_target": sum(1 for e in errs if e > target),
        # Bins where the app counted ZERO while the reference had volume: a
        # COVERAGE gap (our processing window not covering that interval), not a
        # counting error — these dominate e.g. a 24h camera's pre-dawn bins and
        # would otherwise masquerade as a huge AVG |err|.
        "n_no_coverage": sum(1 for _l, o, _r, _e in rows if o == 0),
        "target_pct": target,
        "verdict": "PASS" if avg <= target else "FAIL",
        "per_interval": [{"bin": l, "ours": o, "ref": r, "abs_err_pct": round(e, 1)}
                         for l, o, r, e in rows],
    }


def _bin_label(t: time, bin_min: int) -> str:
    return f"{t.hour:02d}:{(t.minute // bin_min) * bin_min:02d}"


def _bin_total(src: dict, minutes: list, direction: str | None = None) -> int:
    s = 0
    for t in minutes:
        for (d, _mv), n in src.get(t, {}).items():
            if direction is None or d == direction:
                s += n
    return s


def per_interval(ours: dict, ref: dict, minutes: list | None = None,
                 bin_min: int = 15, min_minutes: int = MIN_BIN_MINUTES,
                 ref_floor: float = REF_FLOOR, target: float = TARGET_PCT,
                 by_approach: bool = False) -> dict:
    """AVG |err| per interval between two per-minute sources keyed
    {time: {(direction, movement): count}}.

    minutes: which minutes to include (default = every minute the reference
    covers). A bin needs >= min_minutes counted minutes to be scored — this is
    what keeps a partial manual sheet's edge bins from polluting the average."""
    if minutes is None:
        minutes = sorted(ref.keys())
    binmins: dict[str, list] = defaultdict(list)
    for t in minutes:
        binmins[_bin_label(t, bin_min)].append(t)
    full = {b: mins for b, mins in binmins.items() if len(mins) >= min_minutes}

    pairs = [(b, _bin_total(ours, full[b]), _bin_total(ref, full[b]))
             for b in sorted(full)]
    res = summarize_bins(pairs, ref_floor, target)

    if by_approach:
        dirs = sorted({d for src in (ours, ref) for cell in src.values()
                       for (d, _mv) in cell})
        res["per_approach"] = {}
        for d in dirs:
            dpairs = [(b, _bin_total(ours, full[b], d), _bin_total(ref, full[b], d))
                      for b in sorted(full)]
            res["per_approach"][d] = summarize_bins(dpairs, ref_floor, target)
    return res


# --- CLI (lazy-imports the per-minute loaders) ------------------------------

def _fmt(res: dict, indent: str = "  ") -> str:
    if res["verdict"] == "n/a":
        return f"{indent}(no bins above the reference floor)"
    gap = (f"   [!] {res['n_no_coverage']} bins had NO app coverage (window gap, not error)"
           if res.get("n_no_coverage") else "")
    return (f"{indent}AVG |err|: {res['avg_abs_err_pct']:.1f}%  [{res['verdict']}]"
            f"   max {res['max_abs_err_pct']:.1f}% @ {res['worst_interval']}"
            f"   bins>{res['target_pct']:.0f}%: {res['n_over_target']}/{res['n_bins']}{gap}")


def report_camera(cam: int) -> None:
    import triangulate_manual as T  # lazy: pulls openpyxl + the DB loaders
    ours = T.load_ours(cam)
    mio = T.load_miovision(cam)
    res = per_interval(ours, mio, by_approach=True)
    name = (T.MANUAL_BY_CAM.get(cam).stem if cam in T.MANUAL_BY_CAM else f"cam{cam}")
    print(f"\n########## cam{cam}  AVG |err| per 15-min interval ##########")
    print(f"reference: MIOVISION (full window)   target: AVG |err| <= {TARGET_PCT:.0f}%")
    print(_fmt(res))
    print("  per approach:")
    for d, r in res["per_approach"].items():
        if r["n_bins"]:
            print(f"    {d:<3} AVG |err| {r['avg_abs_err_pct']:.1f}%  [{r['verdict']}]"
                  f"  max {r['max_abs_err_pct']:.1f}% @{r['worst_interval']}  (n={r['n_bins']})")

    # Gold check vs the human hand count where we have rich coverage (cam1).
    if cam in T.MANUAL_BY_CAM:
        manual = T.parse_manual(T.MANUAL_BY_CAM[cam])
        mins = sorted(manual.keys())
        if len(mins) >= 4 * 15:   # only meaningful with several full bins (cam1)
            ours_g = per_interval(ours, manual, minutes=mins)
            mio_g = per_interval(mio, manual, minutes=mins)
            print(f"  GOLD CHECK vs MANUAL ({len(mins)} counted minutes):")
            print(f"    OURS  AVG |err| {ours_g['avg_abs_err_pct']:.1f}%  [{ours_g['verdict']}]"
                  f"   (Miovision benchmark {mio_g['avg_abs_err_pct']:.1f}%  [{mio_g['verdict']}])")
        else:
            print(f"  (manual sheet too thin for a per-interval gold check: "
                  f"{len(mins)} minutes)")


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=None,
                    help="camera id; omit to run all 5 Sunnyvale cameras")
    args = ap.parse_args()
    cams = [args.camera] if args.camera else [1, 2, 3, 4, 5]
    for cam in cams:
        try:
            report_camera(cam)
        except Exception as e:
            print(f"\ncam{cam}: ERROR {e}")
    return 0


if __name__ == "__main__":
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    raise SystemExit(main())
