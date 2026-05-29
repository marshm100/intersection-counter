"""Retrack a suggestion bank into a persistent temp DB (OC-SORT) and print the
per-minute + OD-level accuracy (scripts/od_accuracy.py). Thin driver to measure a
freshly-derived bank under the corrected leg labels.

Usage:  py scripts/measure_bank.py --suggestion evaluations/recal_cam1_relabeled.json
"""
from __future__ import annotations
import argparse, json, sqlite3, sys
from datetime import datetime, timedelta
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.config import get_processing_mode_config
from backend.database import get_calibration_params
from backend.services.detection_cache import DEFAULT_VARIANT, compute_video_content_hash, parquet_path
from reprocess_camera import _load_camera_context
from hybrid_prototype import retrack
from od_accuracy import manual_per_minute, our_per_minute, LEG_IDX, IDX_NAME
from groundtruth import VIDEO_START


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suggestion", default="evaluations/recal_cam1_relabeled.json")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--out-db", default="data/projects/97a7849a/_hybrid_tmp/relabeled.db")
    args = ap.parse_args()
    camera = 1
    conn = sqlite3.connect("data/projects/97a7849a/project.db"); ctx = _load_camera_context(conn, camera); conn.close()
    video = ctx["video"]; fps = float(video["fps"])
    calib = get_calibration_params("97a7849a", ctx["intersection_id"]); mode_cfg = get_processing_mode_config("balanced")
    sug = json.loads(Path(args.suggestion).read_text())
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    start = (t0 - VIDEO_START).total_seconds()
    s = int(start * fps); e = s + int(args.minutes * 60 * fps)
    s = max(0, min(s, video["total_frames"])); e = max(s, min(e, video["total_frames"]))
    chash, _ = compute_video_content_hash(video["path"], file_size_bytes=video.get("file_size_bytes"), total_frames=video["total_frames"])
    pq = parquet_path("97a7849a", camera, chash, DEFAULT_VARIANT)
    tdb = Path(args.out_db)
    retrack(tdb, "ocsort", video, ctx, calib, mode_cfg, sug, s, e, pq, camera)

    mins = [t0 + timedelta(minutes=i) for i in range(int(args.minutes))]
    m_od, m_mv, _ = manual_per_minute()
    o_od, o_mv = our_per_minute(tdb, start, start + args.minutes * 60, legmap=LEG_IDX)
    cells = set()
    for mn in mins: cells |= set(m_mv.get(mn, {})) | set(o_mv.get(mn, {}))
    print(f"bank={args.suggestion}\n{'cell':<16}{'manual':>7}{'ours':>6}{'net':>6}{'gross':>7}")
    tman = tnet = tgross = 0
    for c in sorted(cells, key=lambda c: -sum(abs(o_mv.get(mn,{}).get(c,0)-m_mv.get(mn,{}).get(c,0)) for mn in mins)):
        man = sum(m_mv.get(mn, {}).get(c, 0) for mn in mins); ours = sum(o_mv.get(mn, {}).get(c, 0) for mn in mins)
        gross = sum(abs(o_mv.get(mn, {}).get(c, 0) - m_mv.get(mn, {}).get(c, 0)) for mn in mins)
        tman += man; tnet += abs(ours - man); tgross += gross
        if man == 0 and ours == 0: continue
        in_i, mvt = c
        print(f"{IDX_NAME[in_i]+' '+mvt:<16}{man:>7}{ours:>6}{abs(ours-man):>6}{gross:>7}")
    print(f"{'TOTAL':<16}{tman:>7}{'':>6}{tnet:>6}{tgross:>7}")
    print(f"  net agg_err = {tnet/tman*100:.1f}%   per-min gross = {tgross/tman*100:.1f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
