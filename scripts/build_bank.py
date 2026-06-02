"""Derive a path bank for ANY corridor camera from raw BoT-SORT tracks + that
camera's Miovision OD geometry. Camera-parameterized generalization of the
former build_cam2_bank.py (which proved the pattern on cam2).

Per cell (origin_leg -> destination_leg, movement): the OD destinations come
from the camera's Miovision XML (authoritative — never hand-guess turn
geometry), gated by manual volume (>= min_support); each cell's polyline is fit
from raw BoT tracks on the camera's detection cache. Works for 3-leg (T) and
4-way intersections — the leg<->approach map is the data-driven cardinal join
in od_accuracy.leg_idx().

Writes evaluations/recal_cam<N>.json (paths). Throughs + turns, uniform OD-direct.

Usage:  py scripts/build_bank.py --camera 3 --start-hms 07:00:00 --minutes 5
"""
from __future__ import annotations
import argparse, json, math, sqlite3, sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))   # sibling scripts

from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path)
from backend.services.tracker import create_tracker_backend
from auto_calibrate import _fit_mean_polyline
from od_accuracy import leg_idx
from parse_miovision_xml import parse, slot_labels
from groundtruth import VIDEO_START

PROJECT = "97a7849a"
# slot_labels movement vocab (thru/left/right/uturn) -> DB movement vocab.
MV_OUT = {"thru": "through", "left": "left", "right": "right", "uturn": "u_turn"}


def cells_for_camera(camera_id: int, start_hms: str, minutes: float) -> dict:
    """(origin_leg, dest_leg, db_movement) -> manual count for the window, from
    the camera's Miovision OD + the cardinal leg<->approach map."""
    inv = {idx: leg for leg, idx in leg_idx(camera_id).items()}   # approach idx -> our leg
    data = parse(camera_id)
    movements = data["movements"]                                 # (Name, in_idx, out_idx)
    labels = slot_labels(data["movements"], camera_id)            # (in_name, mvt, out_name)
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{start_hms}")
    win = {(t0 + timedelta(minutes=i)).isoformat() for i in range(int(minutes))}
    cell_manual: dict = defaultdict(float)
    for tm, vols in data["per_min"].items():
        try:
            keep = datetime.fromisoformat(tm) in {datetime.fromisoformat(w) for w in win}
        except Exception:
            keep = tm in win
        if not keep:
            continue
        for i, (_, in_i, out_i) in enumerate(movements):
            mv = MV_OUT.get(labels[i][1])
            ol, dl = inv.get(in_i), inv.get(out_i)
            if mv and ol and dl:
                cell_manual[(ol, dl, mv)] += vols[i]
    return cell_manual


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--out", default=None, help="default evaluations/recal_cam<N>.json")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--min-support", type=int, default=5)
    ap.add_argument("--min-path", type=float, default=80.0)
    ap.add_argument("--poly-pts", type=int, default=15)
    # Snap-magnet defence: a TURN polyline that is geometrically STRAIGHT and
    # wildly OVER-SUPPORTED vs its manual volume is not a real turn — it's a
    # straight corridor (throughs) that endpoint-grouping mislabelled as a turn,
    # and at apply it captures throughs. Real turns curve (straightness well
    # below the floor) and have support ~ manual. The over-support condition is
    # what spares low-volume genuine turns (cam2). See memory
    # project_accuracy_snap_magnet_mechanism.
    ap.add_argument("--magnet-straight-thr", type=float, default=0.95,
                    help="reject turn polylines straighter than this (if also over-supported)")
    ap.add_argument("--magnet-support-factor", type=float, default=3.0,
                    help="a turn polyline is a magnet only if support > factor*manual")
    args = ap.parse_args()
    cam = args.camera
    out_path = args.out or f"evaluations/recal_cam{cam}.json"

    cell_manual = cells_for_camera(cam, args.start_hms, args.minutes)

    # video + leg origin points for THIS camera
    c = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    v = c.execute("SELECT path,file_size_bytes,total_frames,fps FROM videos "
                  "WHERE camera_id=? ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
    legs = {lid: json.loads(oz)[0] for lid, oz in
            c.execute("SELECT leg_id,origin_zone FROM legs WHERE camera_id=?", (cam,)) if oz}
    c.close()
    fps = float(v[3])
    ch, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path(PROJECT, cam, ch, DEFAULT_VARIANT)
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    f_lo = int((t0 - VIDEO_START).total_seconds() * fps)
    f_hi = f_lo + int(args.minutes * 60 * fps)
    frames = [(f, ds) for f, ds in DetectionCacheReader(pq).iter_frames() if f_lo <= f < f_hi]

    be = create_tracker_backend("botsort", track_activation_threshold=0.25, frame_rate=int(fps))
    tr = defaultdict(list)
    for fidx, dets in frames:
        for tk in be.update(dets, fidx):
            tr[tk["track_id"]].append(tuple(tk["center"]))

    def nearest(pt):
        return min(legs, key=lambda l: math.hypot(pt[0] - legs[l][0], pt[1] - legs[l][1]))

    def plen(p):
        return sum(math.hypot(p[i][0] - p[i-1][0], p[i][1] - p[i-1][1]) for i in range(1, len(p)))

    groups = defaultdict(list)
    for pts in tr.values():
        if len(pts) >= 4 and plen(pts) >= args.min_path:
            groups[(nearest(pts[0]), nearest(pts[-1]))].append(pts)

    paths = []
    print(f"cam{cam} bank — window {args.start_hms}+{args.minutes:.0f}min, {len(frames)} cached frames")
    print(f"{'cell':<22}{'manual':>7}{'rawtrk':>7}  status")
    for (ol, dl, mv), man in sorted(cell_manual.items(), key=lambda kv: -kv[1]):
        if man < args.min_support:
            continue
        g = groups.get((ol, dl), [])
        status = "ok" if len(g) >= args.min_support else f"too_few({len(g)})"
        print(f"{f'L{ol}->L{dl} {mv}':<22}{man:>7.0f}{len(g):>7}  {status}")
        if len(g) < args.min_support:
            continue
        poly = _fit_mean_polyline(g, args.poly_pts)
        # Snap-magnet polyline-quality gate (turns only): reject a straight,
        # over-supported "turn" path before it can capture throughs at apply.
        if mv in ("left", "right", "u_turn"):
            pl = plen(poly)
            straightness = (math.hypot(poly[-1][0] - poly[0][0], poly[-1][1] - poly[0][1]) / pl
                            if pl > 1e-9 else 1.0)
            if (straightness > args.magnet_straight_thr
                    and len(g) > args.magnet_support_factor * max(man, 1)):
                print(f"{f'L{ol}->L{dl} {mv}':<22}{man:>7.0f}{len(g):>7}  "
                      f"MAGNET_REJECTED (straightness={straightness:.3f}, support>{args.magnet_support_factor:.0f}x manual)")
                continue
        paths.append({"origin_leg_id": ol, "destination_leg_id": dl, "movement_label": mv,
                      "polyline": [[round(x, 1), round(y, 1)] for x, y in poly],
                      "supporting_count": len(g), "source": "data-driven-rawtrack"})
    out = {"project": PROJECT, "camera_id": cam, "updated_legs": [], "paths": paths}
    Path(out_path).write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}  ({len(paths)} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
