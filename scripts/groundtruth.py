"""Ground-truth diagnostic harness.

Compares vehicle_events from our pipeline against a manual TMC count
(CSV from a prior commercial study) for any time window. Reports per-leg
and per-movement recall + deltas so we can iterate on accuracy fixes
without guessing.

Usage:
  py scripts/groundtruth.py                          # full 24-bucket sweep
  py scripts/groundtruth.py --bucket "7:00 AM"       # single 15-min bucket
  py scripts/groundtruth.py --window 25200,26600     # custom footage-second window
  py scripts/groundtruth.py --save baseline          # save snapshot to evaluations/baseline.json
  py scripts/groundtruth.py --diff baseline          # diff against a saved snapshot

Configuration lives at the top of the file. Only Sunnyvale intersection 1
(camera 1, project 97a7849a) for now; other intersections come later.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

# --- Per-intersection config --------------------------------------------
PROJECT_DB = Path("data/projects/97a7849a/project.db")
# Per-camera Miovision files now live under "Sunnyvale, TX/camN .../" subfolders
# (all 5 corridor intersections present 2026-05-29). cam1 default below.
MANUAL_CSV = Path("docs/historic data/Sunnyvale, TX/cam1 405051 N Belt Line Rd & Northwest Dr/405051_0035_20260512_000002_NBeltLineRd-NorthwestDr_1401964_05-12-2026.csv")

# Video recording started at this wall-clock time (read from videos table)
# Used to convert manual-count bucket labels (7:00 AM) → footage-second offsets.
VIDEO_START = datetime(2026, 5, 12, 0, 0, 2)

# Map our leg_id -> CSV approach name (manual study uses street-named labels).
# Mapping was re-derived 2026-05-22 after the camera was recalibrated and
# new leg_ids landed: by origin-point spatial position vs manual study.
#   L22 origin (494, 217) -- upper-right of frame -- SB Belt Line entrance
#   L23 origin (143, 357) -- lower-left            -- NB Belt Line entrance
#   L24 origin (541, 357) -- lower-right           -- Private Driveway entrance
#   L25 origin (227, 227) -- upper-middle-left     -- Northwest Dr entrance
# Corrected 2026-05-29: the cam1 leg approach-labels were 180°-rotated (verified
# against the Miovision per-minute OD geometry — see memory
# project_leg_labels_swapped). Our legs are physically at the OPPOSITE approach
# vs their original (S/N/W/E) cardinal labels: L22 is NB, L23 SB, L24 EB, L25 WB.
LEG_TO_APPROACH = {
    22: "NB N Belt Line Rd",
    23: "SB N Belt Line Rd",
    24: "EB Northwest Dr",
    25: "WB Private Driveway",
}

# CSV column layout: 8 approach blocks of 9 columns each (HardR, Right,
# BearR, Thru, BearL, Left, HardL, U-Turn, Peds). Start indices are
# 0-based offsets into each row.
APPROACH_COLS = {
    "SB N Belt Line Rd":   1,
    "WB Private Driveway": 19,
    "NB N Belt Line Rd":   37,
    "EB Northwest Dr":     55,
}
MOVEMENT_OFFSETS = {
    "right": 1,
    "thru":  3,
    "left":  5,
    "uturn": 7,
}

EVAL_DIR = Path("evaluations")
BUCKET_SECONDS = 900   # 15-min TMC bucket

NORM_MVT = {"through": "thru", "left": "left", "right": "right", "u_turn": "uturn"}
ALL_MVT = ("thru", "left", "right", "uturn")


# --- CSV parsing --------------------------------------------------------

def parse_manual_csv() -> dict:
    """Return manual[bucket_label][approach_name][movement] = count.

    Sums Lights + Mediums + Articulated Trucks classes.
    """
    out: dict[str, dict[str, dict[str, int]]] = {}
    with open(MANUAL_CSV, encoding="utf-8") as f:
        rows = list(csv.reader(f))

    current_class = None
    for row in rows:
        if not row:
            continue
        if row[0] == "***NewClass":
            current_class = None
            continue
        if current_class is None and row[0] in ("Lights", "Mediums", "Articulated Trucks"):
            current_class = row[0]
            continue
        label = row[0].strip() if row else ""
        is_time_row = (("AM" in label or "PM" in label) and ":" in label)
        if not (is_time_row and current_class):
            continue
        bucket = out.setdefault(label, {a: {m: 0 for m in ALL_MVT} for a in APPROACH_COLS})
        for approach, start_col in APPROACH_COLS.items():
            for mvt, off in MOVEMENT_OFFSETS.items():
                if start_col + off < len(row):
                    cell = row[start_col + off].strip()
                    if cell.isdigit():
                        bucket[approach][mvt] += int(cell)
    return out


def bucket_to_footage_seconds(bucket_label: str) -> tuple[float, float]:
    """Convert '7:00 AM' to (start_seconds, end_seconds) into the video."""
    t = datetime.strptime(bucket_label.strip(), "%I:%M %p").time()
    target = VIDEO_START.replace(hour=t.hour, minute=t.minute, second=0)
    start_sec = (target - VIDEO_START).total_seconds()
    return (start_sec, start_sec + BUCKET_SECONDS)


# --- DB queries ---------------------------------------------------------

def fetch_our_counts(start_sec: float, end_sec: float) -> dict:
    """Return ours[leg_id][movement] = count for events whose
    timestamp_video falls in [start_sec, end_sec)."""
    conn = sqlite3.connect(str(PROJECT_DB))
    out = {lid: {m: 0 for m in ALL_MVT} for lid in LEG_TO_APPROACH}
    for r in conn.execute(
        "SELECT origin_leg_id, movement, COUNT(*) "
        "FROM vehicle_events "
        "WHERE rejected=0 AND timestamp_video >= ? AND timestamp_video < ? "
        "GROUP BY origin_leg_id, movement",
        (start_sec, end_sec),
    ):
        lid, mvt_raw, n = r
        mvt = NORM_MVT.get(mvt_raw)
        if lid in out and mvt:
            out[lid][mvt] = n
    conn.close()
    return out


def db_processed_window() -> tuple[float, float] | None:
    """Min/max timestamp_video across all events. None if no events."""
    conn = sqlite3.connect(str(PROJECT_DB))
    r = conn.execute(
        "SELECT MIN(timestamp_video), MAX(timestamp_video) "
        "FROM vehicle_events WHERE rejected=0"
    ).fetchone()
    conn.close()
    if r[0] is None:
        return None
    return (r[0], r[1])


# --- Comparison core ----------------------------------------------------

def compare_window(manual_bucket: dict, ours: dict, scale: float) -> dict:
    """Build a per-leg comparison row. scale = (our_window_minutes /
    manual_bucket_minutes) — used to apportion the manual bucket when
    we only processed part of it."""
    rows = []
    totals = {"manual": 0.0, "ours": 0}
    by_leg_recall = {}
    for lid, approach in LEG_TO_APPROACH.items():
        leg_manual = 0.0
        leg_ours = 0
        per_mvt = {}
        for mvt in ALL_MVT:
            m = manual_bucket[approach][mvt] * scale
            o = ours[lid][mvt]
            per_mvt[mvt] = {"manual": m, "ours": o, "delta": o - m}
            leg_manual += m
            leg_ours += o
        rows.append({
            "leg_id": lid,
            "approach": approach,
            "movements": per_mvt,
            "leg_total_manual": leg_manual,
            "leg_total_ours": leg_ours,
            "leg_delta": leg_ours - leg_manual,
            "leg_recall_pct": (leg_ours / leg_manual * 100) if leg_manual > 0 else None,
        })
        totals["manual"] += leg_manual
        totals["ours"] += leg_ours
        by_leg_recall[lid] = rows[-1]["leg_recall_pct"]
    totals["recall_pct"] = (
        totals["ours"] / totals["manual"] * 100 if totals["manual"] > 0 else None
    )
    return {"rows": rows, "totals": totals, "by_leg_recall": by_leg_recall}


# --- Output formatting --------------------------------------------------

def print_window_report(label: str, cmp: dict) -> None:
    print(f"\n=== {label} ===")
    print(f"{'Leg':<3} {'Approach':<24} {'Mvt':<6} "
          f"{'Manual':>8} {'Ours':>6} {'Delta':>8}")
    print("-" * 60)
    for row in cmp["rows"]:
        lid = row["leg_id"]
        for mvt in ALL_MVT:
            m = row["movements"][mvt]
            print(f"L{lid:<2} {row['approach']:<24} {mvt:<6} "
                  f"{m['manual']:>8.1f} {m['ours']:>6} {m['delta']:>+8.1f}")
        recall = row["leg_recall_pct"]
        recall_s = f"{recall:5.1f}%" if recall is not None else "  n/a"
        print(f"{'':<3} {'':<24} {'TOT':<6} "
              f"{row['leg_total_manual']:>8.1f} {row['leg_total_ours']:>6} "
              f"{row['leg_delta']:>+8.1f}  recall={recall_s}")
        print()
    t = cmp["totals"]
    overall = f"{t['recall_pct']:5.1f}%" if t["recall_pct"] is not None else "  n/a"
    print(f"{'GRAND':<3} {'':<24} {'':<6} {t['manual']:>8.1f} {t['ours']:>6} "
          f"{t['ours']-t['manual']:>+8.1f}  recall={overall}")


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def run_full_sweep(manual: dict, processed: tuple[float, float] | None) -> dict:
    """Iterate every manual bucket whose window overlaps with what we
    actually processed. Apportion partial overlap."""
    if processed is None:
        print("no events in DB; nothing to compare")
        return {"by_bucket": {}, "by_leg_recall": {}, "totals": {}}

    p_start, p_end = processed
    agg_manual = {lid: {m: 0.0 for m in ALL_MVT} for lid in LEG_TO_APPROACH}
    agg_ours = {lid: {m: 0 for m in ALL_MVT} for lid in LEG_TO_APPROACH}
    by_bucket = {}

    for label, bucket in manual.items():
        b_start, b_end = bucket_to_footage_seconds(label)
        ov = overlap_seconds(p_start, p_end + 1, b_start, b_end)
        if ov <= 0:
            continue
        scale = ov / BUCKET_SECONDS
        ours = fetch_our_counts(max(b_start, p_start), min(b_end, p_end + 1))
        cmp = compare_window(bucket, ours, scale)
        by_bucket[label] = {
            "overlap_sec": ov,
            "scale": scale,
            "totals": cmp["totals"],
            "by_leg_recall": cmp["by_leg_recall"],
        }
        # Accumulate for global summary
        for lid, approach in LEG_TO_APPROACH.items():
            for mvt in ALL_MVT:
                agg_manual[lid][mvt] += bucket[approach][mvt] * scale
                agg_ours[lid][mvt] += ours[lid][mvt]

    # Global table
    rows = []
    g_manual = g_ours = 0.0
    by_leg_recall = {}
    for lid, approach in LEG_TO_APPROACH.items():
        leg_manual = sum(agg_manual[lid].values())
        leg_ours = sum(agg_ours[lid].values())
        per_mvt = {
            mvt: {"manual": agg_manual[lid][mvt],
                  "ours":   agg_ours[lid][mvt],
                  "delta":  agg_ours[lid][mvt] - agg_manual[lid][mvt]}
            for mvt in ALL_MVT
        }
        recall = (leg_ours / leg_manual * 100) if leg_manual > 0 else None
        rows.append({
            "leg_id": lid, "approach": approach,
            "movements": per_mvt,
            "leg_total_manual": leg_manual,
            "leg_total_ours":   leg_ours,
            "leg_delta":        leg_ours - leg_manual,
            "leg_recall_pct":   recall,
        })
        g_manual += leg_manual
        g_ours += leg_ours
        by_leg_recall[lid] = recall

    totals = {
        "manual":     g_manual,
        "ours":       g_ours,
        "recall_pct": (g_ours / g_manual * 100) if g_manual > 0 else None,
    }
    print_window_report(
        f"FULL SWEEP — processed footage {p_start:.0f}–{p_end:.0f}s "
        f"(matches {len(by_bucket)} of {len(manual)} buckets)",
        {"rows": rows, "totals": totals, "by_leg_recall": by_leg_recall},
    )

    print(f"\n=== Per-bucket overall recall ===")
    for label, b in sorted(by_bucket.items(), key=lambda kv: bucket_to_footage_seconds(kv[0])[0]):
        rp = b["totals"]["recall_pct"]
        rp_s = f"{rp:5.1f}%" if rp is not None else "  n/a"
        print(f"  {label:<10} overlap={b['overlap_sec']/60:5.1f} min  "
              f"manual={b['totals']['manual']:6.1f}  ours={b['totals']['ours']:>4}  "
              f"recall={rp_s}")

    return {"by_bucket": by_bucket, "by_leg_recall": by_leg_recall, "totals": totals}


# --- Snapshot management ------------------------------------------------

def save_snapshot(name: str, payload: dict) -> Path:
    EVAL_DIR.mkdir(exist_ok=True)
    path = EVAL_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, indent=2))
    print(f"saved snapshot -> {path}")
    return path


def load_snapshot(name: str) -> dict | None:
    path = EVAL_DIR / f"{name}.json"
    if not path.exists():
        print(f"no snapshot at {path}", file=sys.stderr)
        return None
    return json.loads(path.read_text())


def diff_snapshots(prev: dict, curr: dict) -> None:
    print("\n=== Diff vs saved snapshot ===")
    pl, cl = prev.get("by_leg_recall", {}), curr.get("by_leg_recall", {})
    for lid in sorted(set(pl) | set(cl), key=int):
        a = pl.get(str(lid))
        b = cl.get(lid) if isinstance(lid, int) else cl.get(str(lid))
        if a is None or b is None:
            continue
        d = b - a
        marker = "✓" if d > 0 else ("✗" if d < 0 else " ")
        print(f"  L{lid}: {a:5.1f}% → {b:5.1f}%  ({d:+5.1f})  {marker}")
    po = prev.get("totals", {}).get("recall_pct")
    co = curr.get("totals", {}).get("recall_pct")
    if po is not None and co is not None:
        print(f"  OVERALL: {po:5.1f}% → {co:5.1f}%  ({co-po:+5.1f})")


# --- CLI ----------------------------------------------------------------

def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--bucket", help="single 15-min bucket label, e.g. '7:00 AM'")
    p.add_argument("--window", help="custom range in footage seconds, e.g. '25200,26600'")
    p.add_argument("--save", help="save current results as named snapshot")
    p.add_argument("--diff", help="diff current results against named snapshot")
    args = p.parse_args()

    manual = parse_manual_csv()
    processed = db_processed_window()

    if args.bucket:
        if args.bucket not in manual:
            print(f"unknown bucket; valid: {sorted(manual)}", file=sys.stderr)
            return 1
        b_start, b_end = bucket_to_footage_seconds(args.bucket)
        ov = overlap_seconds(processed[0], processed[1] + 1, b_start, b_end) if processed else 0
        scale = ov / BUCKET_SECONDS if ov > 0 else 0.0
        if scale == 0:
            print(f"no overlap with processed footage", file=sys.stderr)
            return 1
        ours = fetch_our_counts(max(b_start, processed[0]), min(b_end, processed[1] + 1))
        cmp = compare_window(manual[args.bucket], ours, scale)
        print_window_report(f"{args.bucket} (overlap {ov/60:.1f} min, scale {scale:.2f})", cmp)
        payload = {"mode": "bucket", "bucket": args.bucket,
                   "by_leg_recall": cmp["by_leg_recall"], "totals": cmp["totals"]}
    elif args.window:
        s, e = (float(x) for x in args.window.split(","))
        ours = fetch_our_counts(s, e)
        # No clean manual mapping; scale per overlapping bucket would
        # need re-implementation. Just dump our raw counts.
        print(f"=== Custom window {s:.0f}-{e:.0f}s — our counts only ===")
        for lid, approach in LEG_TO_APPROACH.items():
            total = sum(ours[lid].values())
            print(f"  L{lid} {approach:<24} {ours[lid]} total={total}")
        payload = {"mode": "window", "window": [s, e], "ours": ours}
    else:
        result = run_full_sweep(manual, processed)
        payload = {"mode": "sweep",
                   "totals": result["totals"],
                   "by_leg_recall": {str(k): v for k, v in result["by_leg_recall"].items()}}

    if args.save:
        save_snapshot(args.save, payload)
    if args.diff:
        prev = load_snapshot(args.diff)
        if prev:
            diff_snapshots(prev, payload)

    return 0


if __name__ == "__main__":
    sys.exit(main())
