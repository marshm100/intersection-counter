"""§3-B phase 0 — the spot-layer confusion matrix (plan_3b_validation_2026-07-28).

Simulates the blind spot-count gate with a PERFECT operator on the corridor:
for each camera, `propose_windows` (stratified) picks the windows; the
simulated manual count for a window is GROUND TRUTH (Miovision per-minute)
over the window's wall-clock minutes; `compare_spot_count` (the production
service, unmodified) produces the verdict. Camera spot-layer verdict =
pass iff EVERY processed segment's window passes (the acceptance rule).

Protocol choices (declared): 30-min windows (the service's own CI math —
NEEDED_TOTAL_FOR_CI ≈ 850 vehicles — documents 10 min as structurally too
short to certify); N seeds per camera so verdict stability under window
placement is itself measured (an unstable verdict = phase-1 evidence for
the in-segment hardest-interval bias candidate).

Also recorded per window: per-approach GT-vs-system errors (the
per-approach blindness probe — the spot TOTAL can pass while an approach
fails; reported, not gated — phase-1 candidate (c)).

Basis: PRODUCTION project.db events (the shipping config) vs Miovision.
Evidence -> runs/3b_validation/phase0_matrix.json
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.services.spot_check import (
    _processed_segments, _rec_offset_seconds, compare_spot_count,
    propose_windows)
import triangulate_manual as T

PROJECT = "97a7849a"
CAMS = [1, 2, 3, 4, 5]
MINUTES = 30.0
SEEDS = [97, 198, 299, 400, 501]
OUT = Path("runs/3b_validation/phase0_matrix.json")

# GT verdicts on file (dev yardstick; bases as recorded):
# totals — cam1 4.0 / cam2 4.8 (production interval-scorer) / cam3 3.2 /
# cam4 4.7 / cam5 7.2; per-approach fails per MASTER_PLAN/handoff.
GT_VERDICT = {
    1: {"total": 4.0, "total_pass": True,  "approach_fails": ["EB 21.0"]},
    2: {"total": 4.8, "total_pass": True,  "approach_fails": ["EB 17.2", "WB 9.9", "SB 10.2"]},
    3: {"total": 3.2, "total_pass": True,  "approach_fails": []},
    4: {"total": 4.7, "total_pass": True,  "approach_fails": ["SB 9.1"]},
    5: {"total": 7.2, "total_pass": False, "approach_fails": ["EB 16.1", "NB 17.3", "SB 5.1"]},
}

_DIR = {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}
_MV = {"thru": "through", "uturn": "u_turn", "left": "left", "right": "right"}


def gt_manual_counts(mio, rec_offset, start, duration):
    """GT counts over the window's wall-clock minutes, keyed like
    _system_counts ('N through' style)."""
    t0 = rec_offset + start
    out = defaultdict(int)
    base = datetime(2000, 1, 1)
    m0 = base + timedelta(seconds=t0 - (t0 % 60))
    m = m0
    end = base + timedelta(seconds=t0 + duration)
    while m < end:
        cell = mio.get(m.time().replace(second=0, microsecond=0))
        if cell:
            for (d, mv), n in cell.items():
                dd, mm = _DIR.get(d), _MV.get(mv, mv)
                if dd:
                    out[f"{dd} {mm}"] += n
        m += timedelta(minutes=1)
    return dict(out)


def approach_errors(report):
    """Per-approach (bound letter) GT-vs-system relative error from the
    report's cells — the per-approach blindness probe."""
    agg = defaultdict(lambda: [0, 0])
    for c in report["cells"]:
        d = c["cell"].split()[0]
        agg[d][0] += c["manual"]
        agg[d][1] += c["system"]
    return {d: {"manual": m, "system": s,
                "rel_err": round((s - m) / m, 3) if m else None}
            for d, (m, s) in sorted(agg.items())}


def main() -> int:
    result = {"minutes": MINUTES, "seeds": SEEDS, "gt_verdicts": GT_VERDICT}
    matrix = {}
    for cam in CAMS:
        mio = T.load_miovision(cam)
        rec = _rec_offset_seconds(PROJECT, cam)
        segs = _processed_segments(PROJECT, cam)
        cam_rows = []
        for seed in SEEDS:
            pw = propose_windows(PROJECT, cam, minutes=MINUTES, seed=seed)
            win_verdicts = []
            worst_app = None
            for wdx, w in enumerate(pw.get("windows", [])):
                manual = gt_manual_counts(mio, rec, w["start_seconds"],
                                          w["duration_seconds"])
                rep = compare_spot_count(PROJECT, cam, w["start_seconds"],
                                         w["duration_seconds"], manual)
                apps = approach_errors(rep)
                for d, a in apps.items():
                    if a["rel_err"] is not None and a["manual"] >= 50:
                        if worst_app is None or abs(a["rel_err"]) > abs(worst_app[1]):
                            worst_app = (f"seg{wdx}:{d}", a["rel_err"])
                win_verdicts.append({
                    "segment": w["segment_index"],
                    "start": w["start_seconds"], "dur": w["duration_seconds"],
                    "verdict": rep["verdict"],
                    "total_rel_err": rep["total"]["rel_err"],
                    "ci95": rep["total"]["ci95"],
                    "manual_total": rep["total"]["manual"],
                    "approach_errors": apps,
                })
            vs = [w["verdict"] for w in win_verdicts]
            cam_verdict = ("pass" if vs and all(v == "pass" for v in vs)
                           else "fail" if "fail" in vs else "review")
            cam_rows.append({"seed": seed, "camera_verdict": cam_verdict,
                             "window_verdicts": vs,
                             "worst_approach": worst_app,
                             "windows": win_verdicts})
            print(f"[M] cam{cam} seed={seed}: {cam_verdict} "
                  f"(windows {vs}) worst_app={worst_app}", flush=True)
        verdict_dist = defaultdict(int)
        for r in cam_rows:
            verdict_dist[r["camera_verdict"]] += 1
        gt = GT_VERDICT[cam]
        blind_pass_frac = verdict_dist.get("pass", 0) / len(SEEDS)
        false_pass = (not gt["total_pass"]) and verdict_dist.get("pass", 0) > 0
        matrix[cam] = {
            "n_segments": len(segs),
            "verdict_distribution": dict(verdict_dist),
            "blind_pass_frac": blind_pass_frac,
            "gt": gt, "FALSE_PASS": false_pass,
            "rows": cam_rows,
        }
        print(f"[M] cam{cam}: segments={len(segs)} dist={dict(verdict_dist)} "
              f"GT_pass={gt['total_pass']} FALSE_PASS={false_pass}", flush=True)

    result["matrix"] = {str(k): v for k, v in matrix.items()}
    result["false_passes"] = [c for c, m in matrix.items() if m["FALSE_PASS"]]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"[M] FALSE-PASS cameras: {result['false_passes']}", flush=True)
    print(f"wrote {OUT}", flush=True)
    print("MATRIX DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
