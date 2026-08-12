"""Block H1 — event-level per-regime hybrid composer
(docs/plan_h1_hybrid_2026-08-12.md).

Composes a hybrid vehicle_events DB from two pass-2 working DBs of the SAME
window: the base-tracker DB supplies through + u_turn events, the OC-SORT DB
supplies the turn movements in --take (variant P: left,right; fallback F:
left). NO cross-backend dedup (measured harmful 2026-06-01: 154
false-deleted throughs — "Use --no-dedup"); the 5/95 per-bin gate is the
conservation arbiter, and this script REPORTS a co-temporal overlap
diagnostic instead (inserted oc turns with a kept base event on the same
origin leg within +/- overlap-window-s = an UPPER BOUND on double-counts).

Copies are WAL-safe (sqlite3 backup API — scratch DBs carry live -wal
sidecars). Inserted oc rows keep provenance: vehicle_track_id + 1,000,000.
OC rejected rows are never imported; base rejected rows stay in place.

Usage:
  py -X utf8 scripts/v2_hybrid_merge.py --camera 2 --window study_0700 \
      --base-db <h1base db> --oc-db <h1oc db> --out <h1 db>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

TRACK_OFFSET = 1_000_000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--window", required=True, help="e.g. study_0700 (naming only)")
    ap.add_argument("--base-db", required=True)
    ap.add_argument("--oc-db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--take", default="left,right",
                    help="movements supplied by the oc DB (P: left,right; F: left)")
    ap.add_argument("--overlap-window-s", type=float, default=3.0)
    args = ap.parse_args()
    take = tuple(m.strip() for m in args.take.split(",") if m.strip())
    cam = args.camera
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    # WAL-safe copy of the base DB into the output slot
    src = sqlite3.connect(args.base_db)
    dst = sqlite3.connect(out)
    src.backup(dst)
    src.close()

    qmarks = ",".join("?" for _ in take)
    cols = [r[1] for r in dst.execute("PRAGMA table_info(vehicle_events)")
            if r[1] != "event_id"]
    collist = ", ".join(cols)
    sel = ", ".join(f"vehicle_track_id + {TRACK_OFFSET}"
                    if c == "vehicle_track_id" else c for c in cols)

    n_base_kept_before = dst.execute(
        "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? "
        "AND COALESCE(rejected,0)=0", (cam,)).fetchone()[0]
    with dst:
        dst.execute("ATTACH DATABASE ? AS oc", (f"file:{args.oc_db}?mode=ro",))
        dropped = dst.execute(
            f"DELETE FROM vehicle_events WHERE camera_id=? "
            f"AND COALESCE(rejected,0)=0 AND movement IN ({qmarks})",
            (cam, *take)).rowcount
        inserted = dst.execute(
            f"INSERT INTO vehicle_events ({collist}) "
            f"SELECT {sel} FROM oc.vehicle_events WHERE camera_id=? "
            f"AND COALESCE(rejected,0)=0 AND movement IN ({qmarks})",
            (cam, *take)).rowcount
    dst.execute("DETACH DATABASE oc")

    # per-movement composition + the overlap diagnostic
    comp = {m: n for m, n in dst.execute(
        "SELECT movement, COUNT(*) FROM vehicle_events WHERE camera_id=? "
        "AND COALESCE(rejected,0)=0 GROUP BY movement", (cam,))}
    w = args.overlap_window_s
    overlap_rows = dst.execute(
        "SELECT COUNT(DISTINCT o.event_id) FROM vehicle_events o "
        "JOIN vehicle_events b ON b.camera_id = o.camera_id "
        " AND COALESCE(b.rejected,0)=0 AND b.vehicle_track_id < ? "
        " AND b.origin_leg_id = o.origin_leg_id "
        " AND ABS(b.timestamp_video - o.timestamp_video) <= ? "
        "WHERE o.camera_id=? AND COALESCE(o.rejected,0)=0 "
        " AND o.vehicle_track_id >= ?",
        (TRACK_OFFSET, w, cam, TRACK_OFFSET)).fetchone()[0]
    dst.close()

    diag = {"camera": cam, "window": args.window, "take": list(take),
            "base_kept_before": n_base_kept_before,
            "base_rows_dropped": dropped, "oc_rows_inserted": inserted,
            "kept_after_by_movement": comp,
            "oc_turns_with_cotmp_base_neighbor": overlap_rows,
            "overlap_window_s": w,
            "note": "overlap = inserted oc events with >=1 kept base event, "
                    "same origin leg, within the window — an UPPER BOUND on "
                    "double-counts; no dedup by design (2026-06-01 finding)"}
    dpath = out.parent / f"h1merge_cam{cam}_{args.window}.json"
    dpath.write_text(json.dumps(diag, indent=1))
    print(f"[h1merge] cam{cam} {args.window} take={','.join(take)}: "
          f"dropped {dropped} base, inserted {inserted} oc; kept now " +
          " ".join(f"{m}={n}" for m, n in sorted(comp.items())) +
          f"; overlap<= {overlap_rows}")
    print(f"[h1merge] -> {out}")
    print(f"[h1merge] -> {dpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
