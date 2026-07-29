"""Stage 2.2 — auto-resolution ABLATION under the pre-declared hard gate
(plan_stage2_labor_levers_2026-07-29, amendment section).

Simulates the BLIND rule pipeline on the production open queue —
read-only, nothing is written to the DB:

  R5 scope  — event flags whose wall-clock time falls outside the claim
              scope (declared trims where present, else the daylight
              envelope 06:00-20:00). Time-only test.
  R-CAP     — every (approach, movement, wall-bin) cluster keeps its K
              most-severe members; the excess resolve as redundant.
              >=1 survivor per cluster => recall provably unchanged.
  R2 holes  — bank_coverage_hole flags with impact <= T0 resolve.

For each config: per-camera survivors, resolved-by-rule counts, the
card estimate (distinct surviving cluster keys + surviving broad
flags), and the recall re-join (same shared join as the recall script)
vs the baseline runs/3b_validation/rule595_queue_recall.json.

HARD GATE (pre-declared): G1 per-camera survivors <= 99; G2 overall BIG
recall >= 94.3 AND no per-camera BIG-recall drop below baseline.
Evidence -> runs/stage2_labor/ablation.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import triangulate_manual as T
from backend.services.spot_check import _rec_offset_seconds
from rule595_compliance import CORRIDOR, DAYLIGHT, score
from rule595_queue_recall import BIG, PROJECT, flag_matches_bin, load_open_flags

OUT = Path("runs/stage2_labor/ablation.json")
BASELINE = Path("runs/3b_validation/rule595_queue_recall.json")

CONFIGS = [
    {"name": "R5_only", "K": None, "T0": 0},
    {"name": "R5_cap1", "K": 1, "T0": 0},
    {"name": "R5_cap3", "K": 3, "T0": 0},
    {"name": "R5_cap1_T0_5", "K": 1, "T0": 5},
    {"name": "R5_cap1_T0_15", "K": 1, "T0": 15},
]


def claim_windows(conn, cam: int) -> list[tuple[int, int]]:
    """The camera's claim scope in wall-clock seconds: declared trims of
    its intersection, else the daylight envelope (blind rule R5)."""
    iid = conn.execute("SELECT intersection_id FROM cameras WHERE camera_id=?",
                       (cam,)).fetchone()[0]
    rows = conn.execute(
        "SELECT start_wallclock, end_wallclock FROM trims WHERE "
        "intersection_id=? ORDER BY sort_order", (iid,)).fetchall()

    def secs(hms: str) -> int:
        h, m, s = (int(x) for x in hms.split(":"))
        return h * 3600 + m * 60 + s
    if rows:
        return [(secs(a), secs(b)) for a, b in rows]
    return [(DAYLIGHT[0] * 3600, DAYLIGHT[1] * 3600)]


def apply_rules(flags: list[dict], severity: dict, windows, rec: float,
                K: int | None, T0: float):
    """The blind pipeline. Returns (survivors, resolved_by_rule) where
    resolved_by_rule maps rule name -> [flag_id, ...]."""
    resolved: dict[str, list[int]] = {"R5_scope": [], "R_cap": [], "R2_hole": []}
    survivors: list[dict] = []
    in_scope_events: list[dict] = []
    for f in flags:
        if f["event_id"] is not None and f["ev_ts"] is not None:
            wall = f["ev_ts"] + rec
            if not any(lo <= wall < hi for lo, hi in windows):
                resolved["R5_scope"].append(f["flag_id"])
                continue
            in_scope_events.append(f)
        else:
            # broad / interval flags: R2 only
            if f["subtype"] == "bank_coverage_hole" and f["impact"] <= T0:
                resolved["R2_hole"].append(f["flag_id"])
                continue
            survivors.append(f)

    if K is None:
        survivors.extend(in_scope_events)
        return survivors, resolved

    clusters: dict[tuple, list[dict]] = defaultdict(list)
    for f in in_scope_events:
        wall_bin = int((f["ev_ts"] + rec) // 900) * 900
        clusters[(f["appr"] or "?", f["mv"] or "?", wall_bin)].append(f)
    for members in clusters.values():
        members.sort(key=lambda f: (-severity.get(f["flag_id"], 0.0),
                                    f["flag_id"]))
        survivors.extend(members[:K])
        resolved["R_cap"].extend(f["flag_id"] for f in members[K:])
    return survivors, resolved


def main() -> int:
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    base = json.loads(BASELINE.read_text())
    result: dict = {"configs": {}}

    # per-camera invariants (loaded once)
    cams: dict[int, dict] = {}
    for cam, hours in CORRIDOR.items():
        ours = T.load_ours(cam)
        mio = T.load_miovision(cam)
        if hours is None:
            minutes = [m for m in sorted(mio.keys())
                       if DAYLIGHT[0] <= m.hour < DAYLIGHT[1]]
        else:
            minutes = [dtime(h, m) for lo, hi in hours
                       for h in range(lo, hi) for m in range(60)]
        fails = [r for r in score(ours, mio, minutes) if not r["ok"]]
        rec = _rec_offset_seconds(PROJECT, cam) or 0
        flags = load_open_flags(conn, cam)
        severity = {}
        for fid, ej in conn.execute(
                "SELECT flag_id, evidence_json FROM review_flags WHERE "
                "camera_id=? AND (status IS NULL OR status NOT IN "
                "('resolved','dismissed','auto_resolved'))", (cam,)):
            try:
                severity[fid] = float((json.loads(ej) or {}).get("severity", 0.0))
            except (TypeError, ValueError):
                severity[fid] = 0.0
        cams[cam] = {"fails": fails, "rec": rec, "flags": flags,
                     "severity": severity,
                     "windows": claim_windows(conn, cam)}
    conn.close()

    for cfg in CONFIGS:
        cfg_res: dict = {}
        tot_big = tot_big_caught = 0
        tot_fail = tot_caught = 0
        for cam, c in cams.items():
            survivors, resolved = apply_rules(
                c["flags"], c["severity"], c["windows"], c["rec"],
                cfg["K"], cfg["T0"])
            rows = []
            for r in c["fails"]:
                caught = any(flag_matches_bin(f, r["bin"], r["cell"], c["rec"])
                             for f in survivors)
                rows.append((abs(r["ours"] - r["ref"]), caught))
            big = [x for x in rows if x[0] >= BIG]
            n_caught = sum(1 for _d, cg in rows if cg)
            n_big_caught = sum(1 for _d, cg in big if cg)
            tot_fail += len(rows); tot_caught += n_caught
            tot_big += len(big); tot_big_caught += n_big_caught
            # card estimate: distinct surviving event-cluster keys + others
            keys = set()
            n_other = 0
            for f in survivors:
                if f["event_id"] is not None and f["ev_ts"] is not None:
                    wall_bin = int((f["ev_ts"] + c["rec"]) // 900) * 900
                    keys.add((f["appr"] or "?", f["mv"] or "?", wall_bin))
                else:
                    n_other += 1
            b = base[f"cam{cam}"]
            recall = round(100.0 * n_caught / len(rows), 1) if rows else None
            big_recall = (round(100.0 * n_big_caught / len(big), 1)
                          if big else None)
            cfg_res[f"cam{cam}"] = {
                "survivors": len(survivors),
                "resolved": {k: len(v) for k, v in resolved.items()},
                "cards_est": len(keys) + n_other,
                "recall_pct": recall, "big_recall_pct": big_recall,
                "recall_delta": (round(recall - b["recall_pct"], 1)
                                 if recall is not None else None),
                "big_recall_delta": (round(big_recall - b["big_recall_pct"], 1)
                                     if big_recall is not None else None),
                "g1_pass": len(survivors) <= 99,
            }
        overall_big = round(100.0 * tot_big_caught / tot_big, 1)
        overall = round(100.0 * tot_caught / tot_fail, 1)
        g2 = (overall_big >= 94.3 and
              all(v["big_recall_delta"] is not None and v["big_recall_delta"] >= 0
                  for v in cfg_res.values()))
        cfg_res["_overall"] = {
            "recall_pct": overall, "big_recall_pct": overall_big,
            "g2_pass": g2,
            "g1_pass_cams": sorted(k for k, v in cfg_res.items()
                                   if not k.startswith("_") and v["g1_pass"]),
        }
        result["configs"][cfg["name"]] = cfg_res
        print(f"[AB] {cfg['name']}: overall recall {overall}% big {overall_big}% "
              f"G2 {'PASS' if g2 else 'FAIL'}", flush=True)
        for cam in sorted(cams):
            v = cfg_res[f"cam{cam}"]
            print(f"[AB]   cam{cam}: {len(cams[cam]['flags'])} -> "
                  f"{v['survivors']} (cards~{v['cards_est']}) "
                  f"resolved {v['resolved']} recall_d {v['recall_delta']} "
                  f"big_d {v['big_recall_delta']} "
                  f"G1 {'PASS' if v['g1_pass'] else 'FAIL'}", flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("ABLATION DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
