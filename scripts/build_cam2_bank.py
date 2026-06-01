"""Derive a cam2 path bank from raw BoT tracks + cam2's Miovision OD geometry
(Phase D, deadline build). cam2 = N Belt Line Rd & E Town East Blvd (4-way), legs
L26 WB / L27 SB / L28 EB / L29 NB. Same structure as cam1 (Belt Line arterial x
E-W cross). OD destinations come from cam2's Miovision XML (authoritative — no
hand-guessing the turn geometry). Each cell's polyline is fit from raw BoT tracks
on the cam2 detection cache, gated by manual volume (>= min_support).

Writes evaluations/recal_cam2.json (paths). Throughs + turns, uniform OD-direct.

Usage:  py scripts/build_cam2_bank.py --start-hms 07:00:00 --minutes 5
"""
from __future__ import annotations
import argparse, json, math, re, sqlite3, sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path)
from backend.services.tracker import create_tracker_backend
from scripts.auto_calibrate import _fit_mean_polyline
from parse_miovision_xml import camera_xml
from groundtruth import VIDEO_START

CAMERA = 2
MV = {"T": "through", "R": "right", "L": "left", "U": "u_turn"}


def cam2_cells():
    """(origin_leg, dest_leg, movement, manual_count) for the 07:00-07:05 window,
    from cam2 Miovision OD geometry + leg labels."""
    c = sqlite3.connect("data/projects/97a7849a/project.db")
    a2l = {lab: lid for lid, lab in c.execute("SELECT leg_id,label FROM legs WHERE camera_id=2")}
    c.close()
    txt = camera_xml(CAMERA).read_text(encoding="utf-8-sig")
    txt = re.sub(r"<\?xml[^>]*\?>", "", txt, count=1).lstrip()
    root = ET.fromstring(txt); s = lambda t: t.split("}")[-1]
    idx2name = {i: a.findtext("Name") for i, a in enumerate(root.find("Approaches").findall("Approach"))}
    movements = [(MV.get((m.findtext("Name") or "").upper()[:1]),
                  int(m.findtext("InApproachIndex")), int(m.findtext("OutApproachIndex")))
                 for m in (x for x in root.iter() if s(x.tag) == "Movement")]
    per = defaultdict(lambda: [0] * len(movements))
    for b in (x for x in root.iter() if s(x.tag) == "Bin"):
        for i, v in enumerate(b.find("volumes")):
            per[b.findtext("Time")][i] += int(v.text)
    return a2l, idx2name, movements, per


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="evaluations/recal_cam2.json")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=5.0)
    ap.add_argument("--min-support", type=int, default=5)
    ap.add_argument("--min-path", type=float, default=80.0)
    ap.add_argument("--poly-pts", type=int, default=15)
    args = ap.parse_args()

    a2l, idx2name, movements, per = cam2_cells()
    from datetime import datetime, timedelta
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    win = {(t0 + timedelta(minutes=i)).isoformat() for i in range(int(args.minutes))}
    cell_manual = defaultdict(float)  # (origin_leg,dest_leg,mv) -> manual count
    for tm, vols in per.items():
        try:
            keep = datetime.fromisoformat(tm) in {datetime.fromisoformat(w) for w in win}
        except Exception:
            keep = tm in win
        if not keep:
            continue
        for i, (mv, ii, oo) in enumerate(movements):
            if mv is None:
                continue
            ol, dl = a2l.get(idx2name[ii]), a2l.get(idx2name[oo])
            if ol and dl:
                cell_manual[(ol, dl, mv)] += vols[i]

    # raw BoT tracks on cam2 cache
    c = sqlite3.connect("data/projects/97a7849a/project.db")
    v = c.execute("SELECT path,file_size_bytes,total_frames,fps FROM videos WHERE camera_id=2 ORDER BY sort_order LIMIT 1").fetchone()
    legs = {lid: json.loads(oz)[0] for lid, oz in c.execute("SELECT leg_id,origin_zone FROM legs WHERE camera_id=2") if oz}
    c.close()
    fps = float(v[3])
    ch, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path("97a7849a", CAMERA, ch, DEFAULT_VARIANT)
    f_lo = int((t0 - VIDEO_START).total_seconds() * fps); f_hi = f_lo + int(args.minutes * 60 * fps)
    frames = [(f, ds) for f, ds in DetectionCacheReader(pq).iter_frames() if f_lo <= f < f_hi]
    be = create_tracker_backend("botsort", track_activation_threshold=0.25, frame_rate=int(fps))
    tr = defaultdict(list)
    for fidx, dets in frames:
        for tk in be.update(dets, fidx):
            tr[tk["track_id"]].append(tuple(tk["center"]))

    def nearest(pt):
        return min(legs, key=lambda l: math.hypot(pt[0]-legs[l][0], pt[1]-legs[l][1]))

    def plen(p):
        return sum(math.hypot(p[i][0]-p[i-1][0], p[i][1]-p[i-1][1]) for i in range(1, len(p)))

    groups = defaultdict(list)
    for pts in tr.values():
        if len(pts) >= 4 and plen(pts) >= args.min_path:
            groups[(nearest(pts[0]), nearest(pts[-1]))].append(pts)

    paths = []
    print(f"{'cell':<22}{'manual':>7}{'rawtrk':>7}  status")
    for (ol, dl, mv), man in sorted(cell_manual.items(), key=lambda kv: -kv[1]):
        if man < args.min_support:
            continue
        g = groups.get((ol, dl), [])
        status = "ok" if len(g) >= args.min_support else f"too_few({len(g)})"
        nm = f"L{ol}->L{dl} {mv}"
        print(f"{nm:<22}{man:>7.0f}{len(g):>7}  {status}")
        if len(g) < args.min_support:
            continue
        poly = _fit_mean_polyline(g, args.poly_pts)
        paths.append({"origin_leg_id": ol, "destination_leg_id": dl, "movement_label": mv,
                      "polyline": [[round(x, 1), round(y, 1)] for x, y in poly],
                      "supporting_count": len(g), "source": "data-driven-rawtrack"})
    out = {"project": "97a7849a", "camera_id": CAMERA, "updated_legs": [], "paths": paths}
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nwrote {args.out}  ({len(paths)} paths)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
