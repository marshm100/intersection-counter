"""Stage 2.2/2.3 — apply the frozen auto-resolution + bin re-key to the
PRODUCTION corridor queue, with full backup and the post-sweep re-join
(plan_stage2_labor_levers_2026-07-29).

In-place sweep only (queue_autoresolve.sweep) — NEVER a rebuild, so the
pass-2-only S5 merge_borderline flags survive and the baseline recall
comparison stays apples-to-apples.

  python scripts/rule595_queue_sweep.py            apply + re-join
  python scripts/rule595_queue_sweep.py --revert   restore from backup

Backup: every review_flags row (all columns) ->
runs/stage2_labor/review_flags_backup_2026-07-29.json (written once;
refuses to overwrite a different existing backup).
Evidence -> runs/stage2_labor/post_sweep_recall.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import time as dtime
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import triangulate_manual as T
from backend.services import queue_autoresolve as qa
from backend.services.spot_check import _rec_offset_seconds
from rule595_compliance import CORRIDOR, DAYLIGHT, score
from rule595_queue_recall import BIG, PROJECT, flag_matches_bin, load_open_flags

DB = Path(f"data/projects/{PROJECT}/project.db")
BACKUP = Path("runs/stage2_labor/review_flags_backup_2026-07-29.json")
OUT = Path("runs/stage2_labor/post_sweep_recall.json")
BASELINE = Path("runs/3b_validation/rule595_queue_recall.json")


def backup() -> int:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM review_flags")]
    conn.close()
    if BACKUP.exists():
        old = json.loads(BACKUP.read_text())
        if {r["flag_id"] for r in old} != {r["flag_id"] for r in rows}:
            raise SystemExit(f"{BACKUP} exists with different flag_ids — "
                             f"refusing to overwrite")
        print(f"[SW] backup already present ({len(old)} rows) — kept")
        return len(old)
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    BACKUP.write_text(json.dumps(rows, indent=0))
    print(f"[SW] backed up {len(rows)} review_flags rows -> {BACKUP}")
    return len(rows)


def revert() -> int:
    rows = json.loads(BACKUP.read_text())
    conn = sqlite3.connect(DB)
    with conn:
        for r in rows:
            conn.execute(
                "UPDATE review_flags SET status=?, resolved_at=?, batch_key=?, "
                "impact=?, evidence_json=? WHERE flag_id=?",
                (r["status"], r["resolved_at"], r["batch_key"], r["impact"],
                 r["evidence_json"], r["flag_id"]))
    conn.close()
    print(f"[SW] reverted {len(rows)} rows from {BACKUP}")
    return 0


def main() -> int:
    if "--revert" in sys.argv:
        return revert()
    backup()

    conn = sqlite3.connect(DB)
    iids = dict(conn.execute(
        "SELECT camera_id, intersection_id FROM cameras"))
    conn.close()
    for cam in sorted(CORRIDOR):
        res = qa.sweep(PROJECT, iids[cam])
        print(f"[SW] cam{cam} (intersection {iids[cam]}): "
              f"{res['open_before']} -> {res['open_after']} open, "
              f"by rule {res['by_rule']}", flush=True)

    # post-sweep re-join vs GT (same join, surviving open set)
    conn = sqlite3.connect(DB)
    base = json.loads(BASELINE.read_text())
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
        fails = [r for r in score(ours, mio, minutes) if not r["ok"]]
        rec = _rec_offset_seconds(PROJECT, cam) or 0
        flags = load_open_flags(conn, cam)          # excludes auto_resolved
        rows = []
        for r in fails:
            caught = any(flag_matches_bin(f, r["bin"], r["cell"], rec)
                         for f in flags)
            rows.append((abs(r["ours"] - r["ref"]), caught))
        big = [x for x in rows if x[0] >= BIG]
        cards = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(batch_key, 'f' || flag_id)) "
            "FROM review_flags WHERE camera_id=? AND status='open'",
            (cam,)).fetchone()[0]
        b = base[f"cam{cam}"]
        recall = round(100.0 * sum(c for _d, c in rows) / len(rows), 1)
        big_recall = round(100.0 * sum(c for _d, c in big) / len(big), 1)
        result[f"cam{cam}"] = {
            "open_flags": len(flags), "open_cards": cards,
            "recall_pct": recall, "big_recall_pct": big_recall,
            "recall_delta_vs_baseline": round(recall - b["recall_pct"], 1),
            "big_recall_delta_vs_baseline": round(
                big_recall - b["big_recall_pct"], 1),
            "g1_flags_pass": len(flags) <= 99, "g1_cards_pass": cards <= 99,
        }
        v = result[f"cam{cam}"]
        print(f"[SW] cam{cam}: open {v['open_flags']} cards {v['open_cards']} "
              f"recall {recall}% (d {v['recall_delta_vs_baseline']}) "
              f"big {big_recall}% (d {v['big_recall_delta_vs_baseline']}) "
              f"G1 flags {'PASS' if v['g1_flags_pass'] else 'FAIL'} "
              f"cards {'PASS' if v['g1_cards_pass'] else 'FAIL'}", flush=True)
    conn.close()

    tot_flags = sum(v["open_flags"] for v in result.values())
    g2 = all(v["big_recall_delta_vs_baseline"] >= 0 for v in result.values())
    result["_overall"] = {"open_flags": tot_flags, "g2_pass": g2}
    print(f"[SW] TOTAL open {tot_flags} (was 4,370); "
          f"G2 {'PASS' if g2 else 'FAIL'}", flush=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("SWEEP DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
