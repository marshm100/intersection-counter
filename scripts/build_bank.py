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


# --- Heading-based OD recovery (Phase: fix the build_bank blind spot) ---------
# Primary grouping is nearest-leg-anchor on the track endpoints (cheap, correct
# for most cells). It FAILS for turns whose tracks start/end near the SAME leg
# anchor — e.g. a right turn that queues by the cross-street's anchor: both
# endpoints bin to that leg, so the real (origin,dest) cell gets zero tracks and
# the Miovision movement is silently dropped (cam5 EB-right 38->39: 36 real BoT
# tracks all mis-binned to (39,39); the data-driven bank then had no path, so the
# pipeline's polyline attribution had nothing to match and the whole movement read
# 0). Heading recovery re-bins by DIRECTION OF TRAVEL vs each leg's calibrated
# reference_heading (entry bearing ~= origin leg heading; exit bearing ~= reverse
# of dest leg heading), which is robust to where the track happens to start/end.
# It is used ONLY to RECOVER a Miovision cell that nearest-anchor left
# under-supported (never to override a cell that already works), so it cannot
# regress cameras whose anchors are fine (e.g. cam3 T: no dropped cells -> no-op).
def _seg_bearing(a, b) -> float:
    """Bearing a->b, 0deg=N(up), 90deg=E(right). Image coords (y down)."""
    return math.degrees(math.atan2(b[0] - a[0], -(b[1] - a[1]))) % 360


def _avg_bearing(poly, k: int = 3, tail: bool = False):
    """Circular mean of the first (or last, if tail) k segment bearings.
    Returns None if degenerate (too short / all zero-length)."""
    pts = poly[-k - 1:] if tail else poly[:k + 1]
    s = co = 0.0
    n = 0
    for i in range(len(pts) - 1):
        h = math.radians(_seg_bearing(pts[i], pts[i + 1]))
        s += math.sin(h); co += math.cos(h); n += 1
    if n == 0 or (abs(s) < 1e-9 and abs(co) < 1e-9):
        return None
    return math.degrees(math.atan2(s, co)) % 360


def _bearing_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def heading_origin_dest(poly, refh: dict):
    """(origin_leg, dest_leg) for a track by matching its entry bearing to each
    leg's reference_heading and its exit bearing to the reverse heading.
    Either may be None when the bearing is degenerate."""
    eb = _avg_bearing(poly, 3, tail=False)
    xb = _avg_bearing(poly, 3, tail=True)
    o = (min(refh, key=lambda l: _bearing_diff(eb, refh[l]))
         if eb is not None and refh else None)
    d = (min(refh, key=lambda l: _bearing_diff(xb, (refh[l] + 180) % 360))
         if xb is not None and refh else None)
    return o, d


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
    ap.add_argument("--magnet-min-manual", type=int, default=20,
                    help="never magnet-reject a movement Miovision counts >= this many "
                         "times in the window: a phantom magnet is a RARE turn (manual ~5-6) "
                         "whose support is inflated 30-100x; an established movement (manual "
                         "dozens-to-hundreds) that happens to be straight + over-collected is "
                         "real (cam2 PM EB-right manual 182, SB-left 77). Apply-side "
                         "origin-rewrite gate handles its attribution quality.")
    ap.add_argument("--recovery-overcollect-factor", type=float, default=3.0,
                    help="reject a heading-recovered cell whose support exceeds this "
                         "factor * manual (over-collection guard; independent of the "
                         "straightness-paired magnet gate)")
    ap.add_argument("--variant", default=None, help="detection-cache variant (default DEFAULT_VARIANT)")
    args = ap.parse_args()
    cam = args.camera
    out_path = args.out or f"evaluations/recal_cam{cam}.json"

    cell_manual = cells_for_camera(cam, args.start_hms, args.minutes)

    # video + leg origin points for THIS camera
    c = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    v = c.execute("SELECT path,file_size_bytes,total_frames,fps FROM videos "
                  "WHERE camera_id=? ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
    leg_rows = c.execute("SELECT leg_id,origin_zone,reference_heading FROM legs "
                         "WHERE camera_id=?", (cam,)).fetchall()
    legs = {lid: json.loads(oz)[0] for lid, oz, _ in leg_rows if oz}
    refh = {lid: rh for lid, _, rh in leg_rows if rh is not None}
    c.close()
    fps = float(v[3])
    ch, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path(PROJECT, cam, ch, args.variant or DEFAULT_VARIANT)
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

    groups = defaultdict(list)        # primary: nearest-anchor (origin,dest)
    hgroups = defaultdict(list)       # recovery: heading-based (origin,dest)
    for pts in tr.values():
        if len(pts) >= 4 and plen(pts) >= args.min_path:
            groups[(nearest(pts[0]), nearest(pts[-1]))].append(pts)
            ho, hd = heading_origin_dest(pts, refh)
            if ho is not None and hd is not None:
                hgroups[(ho, hd)].append(pts)

    paths = []
    print(f"cam{cam} bank — window {args.start_hms}+{args.minutes:.0f}min, {len(frames)} cached frames")
    print(f"{'cell':<22}{'manual':>7}{'rawtrk':>7}  status")
    for (ol, dl, mv), man in sorted(cell_manual.items(), key=lambda kv: -kv[1]):
        if man < args.min_support:
            continue
        g = groups.get((ol, dl), [])
        source = "data-driven-rawtrack"
        # Blind-spot recovery: nearest-anchor left this real Miovision cell
        # under-supported. Re-bin by direction of travel (heading vs the legs'
        # calibrated reference_headings) before giving up. Only RECOVERS dropped
        # cells; never overrides a working one — so it is a no-op where anchors
        # already suffice and cannot regress those cameras.
        if len(g) < args.min_support:
            hg = hgroups.get((ol, dl), [])
            if len(hg) >= args.min_support:
                # Over-collection gate: heading re-binning is looser than
                # nearest-anchor, so on dense/ID-switchy cameras it can sweep in
                # unrelated tracks. If it collects FAR more than Miovision says
                # exist, it's noise, not a recovered movement — reject (the cell
                # falls through to its under-supported primary and is skipped).
                # Distinct from the magnet gate (which also needs straightness):
                # a recovered TURN curves, so only over-collection flags it.
                # cam2 SB-left 27->26: 75 tracks vs manual 19 -> rejected (would
                # snap-magnet 66 at apply); EB-thru 25/31 and WB-left 22/14 kept.
                if len(hg) > args.recovery_overcollect_factor * max(man, 1):
                    print(f"{f'L{ol}->L{dl} {mv}':<22}{man:>7.0f}{len(g):>7}  "
                          f"RECOVERY_REJECTED (heading {len(hg)} > "
                          f"{args.recovery_overcollect_factor:.0f}x manual {man:.0f} — over-collecting)")
                else:
                    print(f"{f'L{ol}->L{dl} {mv}':<22}{man:>7.0f}{len(g):>7}  "
                          f"RECOVERED via heading ({len(hg)} tracks)")
                    g = hg
                    source = "data-driven-heading-recovered"
        status = "ok" if len(g) >= args.min_support else f"too_few({len(g)})"
        if source == "data-driven-rawtrack":
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
            recovered = source == "data-driven-heading-recovered"
            # A real turn CURVES (cam5 EB-right 0.43, cam2 WB-left 0.54). A
            # heading-recovered "turn" that is geometrically STRAIGHT is arterial
            # throughs mis-binned by exit heading — it snap-magnets throughs at
            # apply (cam4 35->34: straightness 0.993, support 12 but captures 184).
            # For recovered turns, straightness alone is the magnet signal: the
            # over-support condition can't be required (recovery support is low by
            # construction, so it would evade the gate). Primary turns keep the
            # straightness+over-support pairing that spares low-volume genuine
            # turns (cam2). See memory project_build_bank_recovery.
            #
            # ABSOLUTE-MANUAL GUARD: the magnet mechanism is a RARE turn stealing
            # throughs — every phantom we've caught has tiny manual (cam4 EB-left 6,
            # cam5 NB-right 5) and support inflated 30-100x. A movement Miovision
            # robustly observes is established, not a phantom, even if its fitted
            # polyline is straight and over-collected (cam2 PM EB-right: manual 182,
            # support 573 = 3.15x; SB-left: manual 77). The straight+3x heuristic was
            # tuned on the AM sample where these turns were absent; without this guard
            # it overfits and collapses cam2's dominant PM turns into adjacent throughs.
            established = man >= args.magnet_min_manual
            magnet = (not established
                      and straightness > args.magnet_straight_thr
                      and len(g) > args.magnet_support_factor * max(man, 1))
            straight_recovery = (not established and recovered
                                 and straightness > args.magnet_straight_thr)
            if magnet or straight_recovery:
                why = ("straight recovery — mis-binned throughs" if straight_recovery
                       else f"support>{args.magnet_support_factor:.0f}x manual")
                print(f"{f'L{ol}->L{dl} {mv}':<22}{man:>7.0f}{len(g):>7}  "
                      f"MAGNET_REJECTED (straightness={straightness:.3f}, {why})")
                continue
        paths.append({"origin_leg_id": ol, "destination_leg_id": dl, "movement_label": mv,
                      "polyline": [[round(x, 1), round(y, 1)] for x, y in poly],
                      "supporting_count": len(g), "source": source})
    out = {"project": PROJECT, "camera_id": cam, "updated_legs": [], "paths": paths}
    Path(out_path).write_text(json.dumps(out, indent=2))
    print(f"\nwrote {out_path}  ({len(paths)} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
