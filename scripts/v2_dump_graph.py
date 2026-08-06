"""Pipeline-V2 D1 — pass-1 dump -> tracklet table (plan_v2_week1_derisk §D1).

Reads a raw-track dump (format 2), groups rows per tracklet, computes
endpoint kinematics + quality features + leg-gate crossings via the SHARED
backend.services.entry_gates machinery (GT-free: operator geometry + the
applied bank's polylines). Writes a self-contained npz:
runs/v2_week1/tracklets_cam{cam}_{variant}.npz holding the sorted point
rows plus per-tracklet offsets and features — the single input every later
V2 stage (instrument, greedy, assembler) loads.

Read-only against project.db. Miovision is NEVER touched here (D5 only).

Usage:
  py -X utf8 scripts/v2_dump_graph.py --camera 2 --variant study_0700
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from backend.services import two_pass as TP                    # noqa: E402
from backend.services.entry_gates import build_gates, classify  # noqa: E402

EXPECTED_COLS = ["track_id", "frame", "cx", "cy", "bw", "bh", "conf", "class_id"]
KIN_PTS = 8          # endpoint velocity fit — points per end
OUT_DIR = Path("runs/v2_week1")

TAGS = {"full": 0, "entry_only": 1, "exit_only": 2, "no_crossing": 3}


def load_geometry(project_id: str, camera_id: int):
    """Legs mouths + reference headings + applied bank polylines (read-only)."""
    conn = sqlite3.connect(f"file:data/projects/{project_id}/project.db?mode=ro",
                           uri=True)
    conn.row_factory = sqlite3.Row
    legs, heads = {}, {}
    for r in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id=?", (camera_id,)):
        zone = json.loads(r["origin_zone"]) if r["origin_zone"] else None
        if zone:
            xs = [p[0] for p in zone]
            ys = [p[1] for p in zone]
            legs[r["leg_id"]] = (sum(xs) / len(xs), sum(ys) / len(ys))
        heads[r["leg_id"]] = r["reference_heading"]
    paths = [dict(origin_leg_id=r["origin_leg_id"],
                  destination_leg_id=r["destination_leg_id"],
                  polyline=json.loads(r["polyline"]))
             for r in conn.execute(
                 "SELECT origin_leg_id, destination_leg_id, polyline "
                 "FROM intersection_paths WHERE camera_id=?", (camera_id,))]
    conn.close()
    return legs, heads, paths


def load_dump(project_id: str, camera_id: int, variant: str):
    pq = TP._camera_parquet(project_id, camera_id, variant)
    tdir = TP.tracks_dir(pq)
    meta = json.loads((tdir / "meta.json").read_text())
    if meta.get("format") != 2 or meta.get("cols") != EXPECTED_COLS:
        raise SystemExit(f"dump schema drift: format={meta.get('format')} "
                         f"cols={meta.get('cols')} — expected {EXPECTED_COLS}")
    n = int((tdir / "count.txt").read_text())
    rows = np.asarray(np.load(tdir / "rows.npy", mmap_mode="r")[:n])
    return rows, meta


def endpoint_velocity(fr: np.ndarray, xy: np.ndarray, fps: float, head: bool):
    """Least-squares velocity (px/s) over the first/last KIN_PTS points."""
    k = min(KIN_PTS, len(fr))
    sl = slice(0, k) if head else slice(len(fr) - k, len(fr))
    f, p = fr[sl], xy[sl]
    if k < 2 or f[-1] == f[0]:
        return 0.0, 0.0
    t = (f - f[0]) / fps
    den = ((t - t.mean()) ** 2).sum() or 1e-9
    vx = (((t - t.mean()) * (p[:, 0] - p[:, 0].mean())).sum() / den)
    vy = (((t - t.mean()) * (p[:, 1] - p[:, 1].mean())).sum() / den)
    return float(vx), float(vy)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    args = ap.parse_args()

    t0 = time.time()
    rows, meta = load_dump(args.project, args.camera, args.variant)
    fps = {1: 10.0, 2: 25.0, 3: 10.0, 4: 10.0, 5: 10.0}[args.camera]

    # sort by (track_id, frame) -> contiguous per-track slices
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows = rows[order]
    tids, starts = np.unique(rows[:, 0], return_index=True)
    ends = np.append(starts[1:], len(rows))

    legs, heads, paths = load_geometry(args.project, args.camera)
    gates = build_gates(legs, paths, heads)

    n_tr = len(tids)
    feat = {k: np.zeros(n_tr, dtype=np.float64) for k in
            ("track_id", "n_pts", "f0", "f1", "x0", "y0", "x1", "y1",
             "vx0", "vy0", "vx1", "vy1", "mean_conf", "mean_area",
             "cls", "path_len", "disp", "max_gap_s",
             "origin_leg", "dest_leg", "o_frame", "d_frame", "tag")}

    for i, (s, e) in enumerate(zip(starts, ends)):
        tr = rows[s:e]
        fr, xy = tr[:, 1], tr[:, 2:4]
        feat["track_id"][i] = tids[i]
        feat["n_pts"][i] = e - s
        feat["f0"][i], feat["f1"][i] = fr[0], fr[-1]
        feat["x0"][i], feat["y0"][i] = xy[0]
        feat["x1"][i], feat["y1"][i] = xy[-1]
        feat["vx0"][i], feat["vy0"][i] = endpoint_velocity(fr, xy, fps, True)
        feat["vx1"][i], feat["vy1"][i] = endpoint_velocity(fr, xy, fps, False)
        feat["mean_conf"][i] = tr[:, 6].mean()
        feat["mean_area"][i] = (tr[:, 4] * tr[:, 5]).mean()
        vals, cnts = np.unique(tr[:, 7], return_counts=True)
        feat["cls"][i] = vals[cnts.argmax()]
        d = np.diff(xy, axis=0)
        feat["path_len"][i] = np.hypot(d[:, 0], d[:, 1]).sum()
        feat["disp"][i] = float(np.hypot(*(xy[-1] - xy[0])))
        feat["max_gap_s"][i] = (np.diff(fr).max() / fps) if e - s > 1 else 0.0
        o, dst, ofr, dfr, _op, _dp, tag = classify(
            [(float(f), float(x), float(y)) for f, (x, y) in zip(fr, xy)],
            gates, fps)
        feat["origin_leg"][i] = o or 0
        feat["dest_leg"][i] = dst or 0
        feat["o_frame"][i] = ofr or -1
        feat["d_frame"][i] = dfr or -1
        feat["tag"][i] = TAGS[tag]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"tracklets_cam{args.camera}_{args.variant}.npz"
    np.savez_compressed(
        out, rows=rows.astype(np.float32), starts=starts, ends=ends,
        meta=json.dumps({**meta, "fps": fps,
                         "gates": {str(k): [list(v[0]), list(v[1]), list(v[2])]
                                   for k, v in gates.items()}}),
        **{k: v for k, v in feat.items()})

    tags, tcnt = np.unique(feat["tag"], return_counts=True)
    tagsum = {name: int(tcnt[list(tags).index(code)]) if code in tags else 0
              for name, code in TAGS.items()}
    print(f"[D1] cam{args.camera} {args.variant}: {n_tr} tracklets "
          f"({len(rows)} pts) tags={tagsum} "
          f"median_dur={np.median((feat['f1']-feat['f0'])/fps):.1f}s "
          f"-> {out} ({time.time()-t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
