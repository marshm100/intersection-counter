"""Task-1 detector de-risk spike (MASTER_PLAN §4 item 1, post-Gate-B): are the
missing vehicles in the failing per-approach cells absent from DETECTIONS, or
dropped downstream (tracking/attribution)?

Method: define each failing zone in image space from the operator's drawn
channels (cams 2/5) or the live bank polylines (cam1 — no drawn channels), as a
buffered corridor around the movement curve. Count in-zone detections per frame
in the balanced_960 cache vs the accurate profile (yolo26l @1280): the cached
accurate_1280 for cams 1/5, or a sampled fresh pass for cam2. A healthy
high-volume zone on the same camera is the CONTROL: if the accurate uplift in
the failing zone matches the control's, the bigger detector is a uniform gain,
not a failing-zone recovery — and the miss is downstream (tracking) or a
resolution wall, justifying the §3-D fine-tune instead of a config lever.

Detections only — no tracker, no ground truth. Confidence cuts at 0.10 (the
balanced cache floor, so both configs are compared above a COMMON floor) and
0.25 (the tracker birth gate track_high_thresh — what a track can be born from).
Curve thirds (by arclength) localize WHERE any gap sits (entry third = where
births fail, e.g. cam2 SB-right's FOV-edge entry).

Usage:
  py scripts/detector_zone_recall.py --camera 1
  py scripts/detector_zone_recall.py --camera 2 --accurate <sampled.parquet> --match-frames
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT = "97a7849a"
DB = f"data/projects/{PROJECT}/project.db"
CACHE = f"data/projects/{PROJECT}/detections"
HASHES = {
    1: "40be14d816e2326b276abf601d57e78a97fb2066cb846979771b78dbe008bcce",
    2: "9446ff1f8376a97e1d7f3021fd27ae69554f93301c8990268a584a8504de4419",
    5: "2076a59b59f93fbd898f690e7aa055d5a35cc923f626489772900ffef2acd49e",
}
FPS = {1: 10.0, 2: 25.0, 5: 10.0}

# Zone registry: failing cell + same-camera healthy control.
#   kind "channel": operator-drawn quad Bezier rows from `channels` (channel_id list)
#   kind "bank":    live-bank polylines from `intersection_paths` (path_id list)
ZONES = {
    1: {"failing": ("NB approach (thru+left)", "bank", [12, 13]),
        "control": ("SB-thru (support 773)", "bank", [11])},
    2: {"failing": ("SB-right (58% recall cell)", "channel", [72]),
        "control": ("NB-thru (support 630)", "channel", [82])},
    5: {"failing": ("EB approach (thru+right+left)", "channel", [50, 51, 52]),
        "control": ("SB-thru (support 341)", "channel", [54])},
}


def _resample(pts: np.ndarray, n: int = 96) -> np.ndarray:
    """Evenly resample a polyline by arclength to n points."""
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    t = np.linspace(0, s[-1], n)
    return np.stack([np.interp(t, s, pts[:, 0]), np.interp(t, s, pts[:, 1])], axis=1)


def load_curves(camera: int, kind: str, ids: list[int]) -> list[np.ndarray]:
    c = sqlite3.connect(DB)
    curves = []
    if kind == "channel":
        for cid in ids:
            e, a, x = c.execute(
                "SELECT entry_pt, apex_pt, exit_pt FROM channels WHERE channel_id=?",
                (cid,)).fetchone()
            p0, p1, p2 = (np.array(json.loads(v), dtype=float) for v in (e, a, x))
            t = np.linspace(0, 1, 96)[:, None]
            bez = (1 - t) ** 2 * p0 + 2 * t * (1 - t) * p1 + t ** 2 * p2
            curves.append(_resample(bez))
    else:
        for pid in ids:
            (pl,) = c.execute(
                "SELECT polyline FROM intersection_paths WHERE path_id=?",
                (pid,)).fetchone()
            curves.append(_resample(np.array(json.loads(pl), dtype=float)))
    c.close()
    return curves


def in_zone(df: pd.DataFrame, curves: list[np.ndarray], radius: float):
    """Boolean mask: det CENTER within radius of any curve; plus per-det arclength
    third (0/1/2) of the NEAREST curve point on the winning curve."""
    cx = ((df.bbox_x1 + df.bbox_x2) / 2).to_numpy()
    cy = ((df.bbox_y1 + df.bbox_y2) / 2).to_numpy()
    best_d = np.full(len(df), np.inf)
    best_third = np.zeros(len(df), dtype=int)
    for cur in curves:
        d = np.sqrt((cx[:, None] - cur[None, :, 0]) ** 2
                    + (cy[:, None] - cur[None, :, 1]) ** 2)
        j = d.argmin(axis=1)
        dm = d[np.arange(len(df)), j]
        upd = dm < best_d
        best_d[upd] = dm[upd]
        best_third[upd] = np.minimum(j[upd] * 3 // cur.shape[0], 2)
    return best_d <= radius, best_third


def summarize(tag: str, df: pd.DataFrame, curves, radius, n_frames) -> dict:
    mask, third = in_zone(df, curves, radius)
    z = df[mask].copy()
    z["third"] = third[mask]
    out = {"tag": tag, "n_frames": n_frames}
    for cut in (0.10, 0.25):
        zc = z[z.confidence >= cut]
        out[f"per_frame_{cut}"] = len(zc) / n_frames
        out[f"entry_pf_{cut}"] = (zc.third == 0).sum() / n_frames
    out["mean_conf"] = float(z.confidence[z.confidence >= 0.10].mean()) if len(z) else float("nan")
    return out


def novel_per_frame(acc: pd.DataFrame, bal: pd.DataFrame, curves, radius,
                    n_frames, cut=0.25, match_px=25.0) -> tuple[float, float]:
    """Accurate dets (conf>=cut, in-zone) with NO balanced det (conf>=0.10,
    anywhere) within match_px on the same frame — i.e., vehicles the balanced
    config does not see AT ALL, not just extra boxes on seen vehicles.
    Returns (novel dets/frame, novel fraction of accurate in-zone dets)."""
    mask, _ = in_zone(acc, curves, radius)
    a = acc[mask & (acc.confidence >= cut)]
    b = bal[bal.confidence >= 0.10]
    bx = ((b.bbox_x1 + b.bbox_x2) / 2).to_numpy()
    by = ((b.bbox_y1 + b.bbox_y2) / 2).to_numpy()
    b_by_frame: dict[int, np.ndarray] = {
        int(f): np.stack([bx[i], by[i]], axis=1)
        for f, i in b.groupby(b.frame_idx.astype(int)).indices.items()}
    ax = ((a.bbox_x1 + a.bbox_x2) / 2).to_numpy()
    ay = ((a.bbox_y1 + a.bbox_y2) / 2).to_numpy()
    af = a.frame_idx.astype(int).to_numpy()
    novel = 0
    for i in range(len(a)):
        pts = b_by_frame.get(af[i])
        if pts is None or not len(pts):
            novel += 1
            continue
        if np.min(np.hypot(pts[:, 0] - ax[i], pts[:, 1] - ay[i])) > match_px:
            novel += 1
    return novel / n_frames, (novel / len(a) if len(a) else float("nan"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True, choices=(1, 2, 5))
    ap.add_argument("--accurate", default=None,
                    help="accurate-profile parquet (default: the accurate_1280 cache)")
    ap.add_argument("--match-frames", action="store_true",
                    help="restrict balanced to the accurate parquet's frame set "
                         "(REQUIRED for a sampled accurate pass)")
    ap.add_argument("--radius", type=float, default=30.0)
    args = ap.parse_args()
    cam = args.camera

    base = Path(CACHE) / str(cam) / HASHES[cam]
    bal = pd.read_parquet(base / "balanced_960_skip1.parquet")
    acc_path = Path(args.accurate) if args.accurate else base / "accurate_1280_skip1.parquet"
    acc = pd.read_parquet(acc_path)

    # common frame basis
    if args.match_frames:
        frames = np.intersect1d(bal.frame_idx.unique(), acc.frame_idx.unique())
        bal = bal[bal.frame_idx.isin(frames)]
        acc = acc[acc.frame_idx.isin(frames)]
        n_bal = n_acc = len(frames)
        basis = f"{len(frames)} matched sampled frames"
    else:
        lo = max(bal.frame_idx.min(), acc.frame_idx.min())
        hi = min(bal.frame_idx.max(), acc.frame_idx.max())
        bal = bal[(bal.frame_idx >= lo) & (bal.frame_idx <= hi)]
        acc = acc[(acc.frame_idx >= lo) & (acc.frame_idx <= hi)]
        n_bal = n_acc = int(hi - lo + 1)
        basis = f"frames {int(lo)}..{int(hi)} (skip1)"

    print(f"\n=== cam{cam} zone detection density  ({basis}, radius {args.radius}px)")
    print(f"    balanced={base / 'balanced_960_skip1.parquet'}")
    print(f"    accurate={acc_path}")
    for role in ("failing", "control"):
        name, kind, ids = ZONES[cam][role]
        curves = load_curves(cam, kind, ids)
        b = summarize("balanced_960", bal, curves, args.radius, n_bal)
        a = summarize("accurate_1280", acc, curves, args.radius, n_acc)
        print(f"\n  [{role.upper()}] {name}   ({kind} {ids})")
        print(f"    {'config':<14}{'dets/frame >=.10':>18}{'>=.25':>10}"
              f"{'entry-third >=.10':>19}{'>=.25':>10}{'mean conf':>11}")
        for r in (b, a):
            print(f"    {r['tag']:<14}{r['per_frame_0.1']:>18.3f}{r['per_frame_0.25']:>10.3f}"
                  f"{r['entry_pf_0.1']:>19.3f}{r['entry_pf_0.25']:>10.3f}{r['mean_conf']:>11.3f}")
        for cut in (0.10, 0.25):
            pb, pa = b[f"per_frame_{cut}"], a[f"per_frame_{cut}"]
            eb, ea = b[f"entry_pf_{cut}"], a[f"entry_pf_{cut}"]
            print(f"    uplift @>={cut}: zone x{pa / pb if pb else float('inf'):.2f}"
                  f"   entry-third x{ea / eb if eb else float('inf'):.2f}")
        npf, nfrac = novel_per_frame(acc, bal, curves, args.radius, n_acc)
        print(f"    NOVEL accurate dets (>=0.25 in-zone, no balanced det within 25px):"
              f" {npf:.3f}/frame = {nfrac * 100:.1f}% of accurate in-zone dets")
    return 0


if __name__ == "__main__":
    sys.exit(main())
