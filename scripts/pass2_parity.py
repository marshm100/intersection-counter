"""A2 tier-1/tier-2 parity gate (docs/plan_pass2_replay_A2_2026-07-09.md).

Tier 1 (HARD): replay-from-dump vs retrack-from-cache on IDENTICAL inputs —
same detection cache, tracker knobs (balanced mode == dump defaults; calib
overrides resolve identically on both paths), live bank, window. Bar:
per-cell |Δ| ≤ 2 vehicles over the window. Divergence = hidden statefulness
between tracker.update and the DB write; investigate, never tune.

Tier 2 (context): replay vs the live shipped table over the same window —
documents recipe-history drift per camera; not a gate.

Usage:  py scripts/pass2_parity.py --camera 1 [--skip-retrack]
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.config import get_processing_mode_config
from backend.database import get_camera_calibration_params
from backend.services.detection_cache import compute_video_content_hash, parquet_path
from backend.services.pass2_replay import replay_camera, tracks_dir
from hybrid_prototype import retrack
from measure_cam2_reid_spike import load_events_db
from reprocess_camera import _load_camera_context

PROJECT = "97a7849a"
SCRATCH = Path(r"C:\Users\onkar\AppData\Local\Temp\ic_scratch_97a7849a")


def window_cells(db: str, cam: int, minutes: list[time]) -> dict[tuple, int]:
    per_min = load_events_db(db, cam)
    per_min.pop("_n_events", None)
    wset = set(minutes)
    out: dict[tuple, int] = defaultdict(int)
    for t, cells in per_min.items():
        if isinstance(t, time) and t in wset:
            for cell, n in cells.items():
                out[cell] += n
    return out


def diff_tables(a: dict, b: dict, la: str, lb: str) -> int:
    cells = sorted(set(a) | set(b), key=lambda c: -(abs(a.get(c, 0) - b.get(c, 0))))
    worst = 0
    print(f"    {'cell':<12}{la:>9}{lb:>9}{'delta':>7}")
    for cell in cells:
        va, vb = a.get(cell, 0), b.get(cell, 0)
        d = vb - va
        worst = max(worst, abs(d))
        if d or va or vb:
            mark = "   <<<" if abs(d) > 2 else ""
            print(f"    {cell[0] + '-' + cell[1]:<12}{va:>9}{vb:>9}{d:>+7}{mark}")
    print(f"    total {sum(a.values())} vs {sum(b.values())}   worst cell |d| = {worst}")
    return worst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", default="study_0700")
    ap.add_argument("--skip-retrack", action="store_true",
                    help="reuse the existing tier-1 reference DB")
    ap.add_argument("--start-hms", default=None,
                    help="scope the gate to a sub-window of the dump (e.g. a "
                         "24h dump gated on 07:00-09:00 — a full-day reference "
                         "retrack is pointless compute)")
    ap.add_argument("--minutes", type=float, default=None)
    args = ap.parse_args()
    cam = args.camera
    SCRATCH.mkdir(parents=True, exist_ok=True)

    proj_db = f"data/projects/{PROJECT}/project.db"
    conn = sqlite3.connect(proj_db)
    ctx = _load_camera_context(conn, cam)
    live_paths = [
        {"origin_leg_id": o, "destination_leg_id": d, "polyline": json.loads(pl),
         "movement_label": mv, "supporting_count": sc}
        for o, d, pl, mv, sc in conn.execute(
            "SELECT origin_leg_id, destination_leg_id, polyline, movement_label, "
            "supporting_count FROM intersection_paths WHERE camera_id = ?", (cam,))]
    conn.close()
    video = ctx["video"]

    chash, _ = compute_video_content_hash(
        video["path"], file_size_bytes=video.get("file_size_bytes"),
        total_frames=video["total_frames"])
    pq = parquet_path(PROJECT, cam, chash, args.variant)
    meta = json.loads((tracks_dir(pq) / "meta.json").read_text())
    f_lo, f_hi = meta["frames"]
    fps = float(video["fps"])
    if args.start_hms is not None:
        h, m, s = (int(x) for x in args.start_hms.split(":"))
        w_lo = int((h * 3600 + m * 60 + s) * fps)
        w_hi = w_lo + int((args.minutes or 120.0) * 60 * fps)
        if not (f_lo <= w_lo and w_hi <= f_hi):
            raise SystemExit(f"--start-hms window [{w_lo},{w_hi}) outside the "
                             f"dump's [{f_lo},{f_hi})")
        f_lo, f_hi = w_lo, w_hi
    m0 = int(f_lo / fps // 60)
    n_min = int((f_hi - f_lo) / fps // 60)
    minutes = [time((m0 + i) // 60, (m0 + i) % 60) for i in range(n_min)]
    print(f"cam{cam} {args.variant}: frames [{f_lo},{f_hi}) = "
          f"{minutes[0]}–{n_min}min  (dump meta: nms={meta.get('nms_iou')} "
          f"match={meta.get('match')} activation={meta.get('activation')})")

    # --- tier-1 reference: retrack-from-cache, identical inputs -------------
    # The reference tracker must match the DUMP's recipe — comparing a botsort
    # dump against a bytetrack retrack would fail on tracker family, not
    # mechanics (plan_cam3_regate_2026-07-13). A +reid dump gets the same
    # sidecar embeddings fed to the reference (the process_camera_reid
    # pattern), so both arms see identical appearance signals.
    recipe = meta.get("backend") or "bytetrack"
    ref_backend = recipe.replace("+reid", "")
    tracker_kwargs = None
    if recipe.endswith("+reid"):
        from reid_embedding_cache import ReidEmbeddingCache
        side = pq.with_name(pq.stem + ".reid")
        if not side.exists():
            side = pq.with_name(pq.stem + ".reid.npz")
        tracker_kwargs = {"with_reid": True,
                          "reid_embeddings": ReidEmbeddingCache(side)}
    ref_db = SCRATCH / f"parity_ref_cam{cam}.db"
    if not args.skip_retrack or not ref_db.exists():
        print(f"[tier1-ref] retrack ({recipe}) from cache -> {ref_db}")
        sug = {"paths": live_paths, "updated_legs": []}   # live bank, live legs
        calib = get_camera_calibration_params(PROJECT, cam)
        mode_cfg = get_processing_mode_config("balanced")
        retrack(ref_db, ref_backend, video, ctx, calib, mode_cfg, sug,
                f_lo, f_hi, pq, cam, tracker_kwargs=tracker_kwargs)
    else:
        print(f"[tier1-ref] reusing {ref_db}")

    # --- candidate: replay-from-dump -----------------------------------------
    rep_db = SCRATCH / f"parity_replay_cam{cam}.db"
    print(f"[replay] dump -> {rep_db}")
    stats = replay_camera(PROJECT, cam, variant=args.variant, out_db=rep_db,
                          start_frame=f_lo, end_frame=f_hi)
    print(f"  {stats['rows']} rows, {stats['tracks']} tracks -> {stats['events']} events "
          f"(insufficient {stats['insufficient_data']}, quality {stats['quality_filtered']})")

    print(f"\n=== TIER 1: retrack-from-cache vs replay-from-dump (cam{cam}) ===")
    ref = window_cells(str(ref_db), cam, minutes)
    rep = window_cells(str(rep_db), cam, minutes)
    worst = diff_tables(ref, rep, "retrack", "replay")
    print(f"    TIER-1 {'PASS' if worst <= 2 else 'FAIL'} (bar: worst |d| <= 2)")

    print(f"\n=== TIER 2 (context): live shipped table vs replay (cam{cam}) ===")
    live = window_cells(proj_db, cam, minutes)
    diff_tables(live, rep, "live", "replay")
    return 0


if __name__ == "__main__":
    sys.exit(main())
