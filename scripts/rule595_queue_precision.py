"""Stage 2.1 — queue PRECISION vs the 5/95 cell-bins (the recall join
inverted; plan_stage2_labor_levers_2026-07-29).

For every OPEN flag: its match FOOTPRINT over the scored (bin, cell)
pairs, through the SAME shared join as the recall script. Classified:
  TP    — footprint contains >=1 FAILING bin (BIG-TP if any |delta|>=20)
  NOISE — footprint non-empty, every matched bin COMPLIANT
  OOS   — footprint empty (outside scored windows / no scored cell)

Also emits the rule-feeding cuts 2.2's thresholds come from:
  - (cell,bin) cluster-size x compliance for event flags (R1 grid)
  - det-conf / margin band precision (R4 grid)
  - out-of-scope mass per camera (R5)
  - per caught BIG failure: what catches it, and whether ONLY a small
    event-flag cluster does (the R1 recall-risk set)
  - duplicate audit (R3 — expected zero)

Basis: production project.db 97a7849a open queue as-is vs Miovision GT
over the dev scoring windows (cam3 daylight cut) — the same basis as
runs/3b_validation/rule595_queue_recall.json. DEV measurement; the
derived rules themselves must stay blind-computable.
Evidence -> runs/stage2_labor/precision.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import triangulate_manual as T
from backend.services.spot_check import _rec_offset_seconds
from rule595_compliance import CORRIDOR, DAYLIGHT, score
from rule595_queue_recall import BIG, PROJECT, flag_matches_bin, load_open_flags

OUT = Path("runs/stage2_labor/precision.json")

DET_BANDS = [(0.30, 0.35), (0.25, 0.30), (0.0, 0.25)]
MARGIN_BANDS = [(0.15, 0.20), (0.10, 0.15), (0.0, 0.10)]


def main() -> int:
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    result: dict = {}
    for cam, hours in CORRIDOR.items():
        ours = T.load_ours(cam)
        mio = T.load_miovision(cam)
        if hours is None:
            minutes = [m for m in sorted(mio.keys())
                       if DAYLIGHT[0] <= m.hour < DAYLIGHT[1]]
        else:
            minutes = [dtime(h, m) for lo, hi in hours
                       for h in range(lo, hi) for m in range(60)]
        rows = score(ours, mio, minutes)
        scored = {(r["bin"], r["cell"]): r for r in rows}
        rec = _rec_offset_seconds(PROJECT, cam) or 0
        flags = load_open_flags(conn, cam)
        evidence = {fid: json.loads(ej) if ej else {} for fid, ej in conn.execute(
            "SELECT flag_id, evidence_json FROM review_flags WHERE camera_id=? "
            "AND (status IS NULL OR status NOT IN "
            "('resolved','dismissed','auto_resolved'))", (cam,))}

        # footprints
        foot: dict[int, list] = {}
        for f in flags:
            foot[f["flag_id"]] = [k for k in scored
                                  if flag_matches_bin(f, k[0], k[1], rec)]

        # (cell,bin) clusters of EVENT flags (footprint is 0 or 1 pair)
        cluster: dict[tuple, list] = defaultdict(list)
        for f in flags:
            if f["event_id"] is not None and len(foot[f["flag_id"]]) == 1:
                cluster[foot[f["flag_id"]][0]].append(f["flag_id"])

        # per-subtype classification
        per_sub: dict = {}
        for f in flags:
            fp = foot[f["flag_id"]]
            sub = f["subtype"]
            d = per_sub.setdefault(sub, {
                "n": 0, "tp": 0, "tp_big": 0, "noise": 0, "oos": 0,
                "cell_scoped": 0})
            d["n"] += 1
            if f["event_id"] is None and f["i0"] is None:
                d["cell_scoped"] += 1
            if not fp:
                d["oos"] += 1
                continue
            fails = [k for k in fp if not scored[k]["ok"]]
            if fails:
                d["tp"] += 1
                if any(abs(scored[k]["ours"] - scored[k]["ref"]) >= BIG
                       for k in fails):
                    d["tp_big"] += 1
            else:
                d["noise"] += 1
        for d in per_sub.values():
            denom = d["tp"] + d["noise"]
            d["precision_pct"] = round(100.0 * d["tp"] / denom, 1) if denom else None

        # cluster-size x compliance (R1): flags in clusters <=T
        cluster_cut = {}
        for tmax in range(1, 9):
            on_ok = on_fail = on_big = 0
            for k, members in cluster.items():
                if len(members) <= tmax:
                    if scored[k]["ok"]:
                        on_ok += len(members)
                    else:
                        on_fail += len(members)
                        if abs(scored[k]["ours"] - scored[k]["ref"]) >= BIG:
                            on_big += len(members)
            cluster_cut[f"T<={tmax}"] = {
                "flags_on_compliant": on_ok, "flags_on_failing": on_fail,
                "of_which_on_big": on_big}

        # confidence-band precision (R4)
        def band_table(sub: str, key: str, bands):
            out = {}
            for lo, hi in bands:
                n = tp = noise = oos = 0
                for f in flags:
                    if f["subtype"] != sub:
                        continue
                    v = evidence.get(f["flag_id"], {}).get(key)
                    if v is None or not (lo <= v < hi):
                        continue
                    n += 1
                    fp = foot[f["flag_id"]]
                    if not fp:
                        oos += 1
                    elif any(not scored[k]["ok"] for k in fp):
                        tp += 1
                    else:
                        noise += 1
                denom = tp + noise
                out[f"[{lo:.2f},{hi:.2f})"] = {
                    "n": n, "tp": tp, "noise": noise, "oos": oos,
                    "precision_pct": round(100.0 * tp / denom, 1) if denom else None}
            return out

        # caught BIG failures: what catches each (R1 recall-risk view)
        big_bins = []
        for k, r in scored.items():
            if r["ok"] or abs(r["ours"] - r["ref"]) < BIG:
                continue
            matches = [f for f in flags if flag_matches_bin(f, k[0], k[1], rec)]
            ev_cluster = [f for f in matches if f["event_id"] is not None]
            broad = [f for f in matches if f["event_id"] is None]
            big_bins.append({
                "bin": k[0], "cell": k[1], "ours": r["ours"], "ref": r["ref"],
                "n_event_flags": len(ev_cluster),
                "broad_subtypes": sorted({f["subtype"] for f in broad}),
                "only_small_cluster": (not broad and 0 < len(ev_cluster) <= 5),
                "uncaught": not matches})
        risk = [b for b in big_bins if b["only_small_cluster"]]

        # R3 duplicate audit
        dup_events = conn.execute(
            "SELECT COUNT(*) FROM (SELECT event_id, COUNT(*) c FROM review_flags "
            "WHERE camera_id=? AND event_id IS NOT NULL AND (status IS NULL OR "
            "status NOT IN ('resolved','dismissed')) GROUP BY event_id "
            "HAVING c > 1)", (cam,)).fetchone()[0]
        on_worked_events = conn.execute(
            "SELECT COUNT(*) FROM review_flags f JOIN vehicle_events e "
            "ON e.event_id = f.event_id WHERE f.camera_id=? AND f.status='open' "
            "AND (COALESCE(e.rejected,0)=1 OR COALESCE(e.manually_edited,0)=1)",
            (cam,)).fetchone()[0]

        n_flags = len(flags)
        n_oos = sum(1 for f in flags if not foot[f["flag_id"]])
        n_tp = sum(1 for f in flags if any(not scored[k]["ok"]
                                           for k in foot[f["flag_id"]]))
        n_noise = n_flags - n_oos - n_tp
        result[f"cam{cam}"] = {
            "open_flags": n_flags, "tp": n_tp, "noise": n_noise, "oos": n_oos,
            "precision_pct": round(100.0 * n_tp / (n_tp + n_noise), 1)
            if (n_tp + n_noise) else None,
            "by_subtype": per_sub,
            "cluster_cut": cluster_cut,
            "cluster_sizes": dict(Counter(
                len(m) for m in cluster.values())),
            "det_bands_low_det_conf": band_table(
                "low_det_conf", "detection_confidence", DET_BANDS),
            "margin_bands_ambiguous_dest": band_table(
                "ambiguous_dest", "destination_margin", MARGIN_BANDS),
            "big_bins_caught_only_by_small_cluster": risk,
            "dup_events": dup_events, "flags_on_worked_events": on_worked_events,
        }
        r = result[f"cam{cam}"]
        print(f"[PR] cam{cam}: {n_flags} open -> TP {n_tp} / NOISE {n_noise} "
              f"/ OOS {n_oos}  precision {r['precision_pct']}%", flush=True)
        for sub, d in sorted(per_sub.items(), key=lambda kv: -kv[1]["n"]):
            print(f"[PR]   {sub:<18} n={d['n']:<5} tp={d['tp']:<5} "
                  f"noise={d['noise']:<5} oos={d['oos']:<4} "
                  f"prec={d['precision_pct']}%", flush=True)
        if risk:
            print(f"[PR]   BIG bins caught ONLY by <=5-event cluster: "
                  f"{[(b['bin'], b['cell']) for b in risk]}", flush=True)
    conn.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("QUEUE PRECISION DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
