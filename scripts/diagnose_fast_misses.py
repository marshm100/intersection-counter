"""Phase 0.2 fast-vehicle miss diagnostic (plan: implementation_plan_architecture_2026-06-11).

Answers ONE question per camera/window: when a vehicle never shows up in
vehicle_events, did the detector ever see it?

Method: stream the raw detection cache (POST-YOLO, PRE-TRACKER — written before
any NMS/tracking), subtract every detection that lies on a finalized event's
trajectory, and chain what's left into spatiotemporal "orphan clusters". An
orphan cluster that moves coherently across >=3 frames is a vehicle the
detector emitted but the tracker never turned into an event.

Cluster verdicts:
  birth_gate       max conf < TRACKER_ACTIVATION_THRESHOLD (0.25): every box
                   lived in the birth-dead band [conf_floor, 0.25) — ByteTrack
                   can match such boxes into EXISTING tracks but can never
                   START one, so this vehicle could not have been counted no
                   matter what association did. The research-predicted fast/
                   blurred failure mode.
  assoc_or_filtered max conf >= 0.25: a track was birth-eligible yet no event
                   matched — association broke (large 10fps inter-frame
                   displacement), or the track died mid-pipeline (min-points /
                   origin-assignment / finalize filters).

Speed is reported in px/frame (median step displacement). At 10 fps sources,
fast movers are the high-px/frame clusters; compare against the matched-
detection baseline printed alongside.

Usage:
  py scripts/diagnose_fast_misses.py --camera 1
  py scripts/diagnose_fast_misses.py --camera 1 --variant accurate_1280_skip1
  py scripts/diagnose_fast_misses.py --camera 2 --variant balanced_960_skip1
Writes evaluations/fast_misses_cam{N}_{variant}.json; console = summary +
top clusters by speed (frame ranges -> easy to scrub to in the source video).
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import TRACKER_ACTIVATION_THRESHOLD
from backend.services.detection_cache import DetectionCacheReader

# Events whose frame span ends/starts within this many frames of a detection
# still count as covering it (trajectory points thin out near track death).
FRAME_SPAN_PAD = 15
# A detection within this distance of an event polyline (scaled by box size)
# is "explained" by that event.
MATCH_BASE_RADIUS = 45.0
MATCH_DIAG_FACTOR = 0.75
# Orphan chaining gates. Generous distance per frame-gap because the whole
# point is catching LARGE inter-frame displacement at 10 fps.
CHAIN_MAX_GAP = 8           # frames
CHAIN_DIST_PER_GAP = 260.0  # px per frame of gap
# A cluster is "vehicle-like" when it persists and actually travels.
MIN_CLUSTER_DETS = 3
MIN_CLUSTER_TRAVEL_PX = 100.0


def _seg_dist(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from point P to segment AB."""
    vx, vy = bx - ax, by - ay
    L2 = vx * vx + vy * vy
    if L2 <= 1e-9:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
    return math.hypot(px - (ax + t * vx), py - (ay + t * vy))


class EventIndex:
    """Frame-bucketed index of event trajectories for fast 'is this detection
    on any tracked path active around this frame?' queries."""

    BUCKET = 200  # frames

    def __init__(self, rows: list[tuple]):
        self.events = []
        self.buckets: dict[int, list[int]] = defaultdict(list)
        for (event_id, start_frame, end_frame, traj_json) in rows:
            try:
                pts = json.loads(traj_json) or []
            except (TypeError, json.JSONDecodeError):
                pts = []
            if len(pts) < 2:
                continue
            lo = min(start_frame or 0, end_frame or 0) - FRAME_SPAN_PAD
            hi = max(start_frame or 0, end_frame or 0) + FRAME_SPAN_PAD
            i = len(self.events)
            self.events.append((lo, hi, [(float(p[0]), float(p[1])) for p in pts]))
            for b in range(lo // self.BUCKET, hi // self.BUCKET + 1):
                self.buckets[b].append(i)

    def explains(self, frame: int, cx: float, cy: float, radius: float) -> bool:
        for i in self.buckets.get(frame // self.BUCKET, ()):
            lo, hi, pts = self.events[i]
            if not (lo <= frame <= hi):
                continue
            # cheap reject: bounding box of polyline inflated by radius
            for k in range(len(pts) - 1):
                if _seg_dist(cx, cy, *pts[k], *pts[k + 1]) <= radius:
                    return True
        return False


class Cluster:
    __slots__ = ("dets",)

    def __init__(self):
        self.dets: list[tuple[int, float, float, float, float]] = []  # frame, cx, cy, conf, diag

    @property
    def last(self):
        return self.dets[-1]

    def stats(self) -> dict:
        frames = [d[0] for d in self.dets]
        confs = [d[3] for d in self.dets]
        steps = []
        for a, b in zip(self.dets, self.dets[1:]):
            gap = max(1, b[0] - a[0])
            steps.append(math.hypot(b[1] - a[1], b[2] - a[2]) / gap)
        steps_sorted = sorted(steps)
        med_speed = steps_sorted[len(steps_sorted) // 2] if steps_sorted else 0.0
        travel = math.hypot(self.dets[-1][1] - self.dets[0][1],
                            self.dets[-1][2] - self.dets[0][2])
        return {
            "n_dets": len(self.dets),
            "frame_start": frames[0],
            "frame_end": frames[-1],
            "span_frames": frames[-1] - frames[0] + 1,
            "conf_max": max(confs),
            "conf_mean": sum(confs) / len(confs),
            "px_per_frame_median": round(med_speed, 1),
            "net_travel_px": round(travel, 1),
            "start_xy": [round(self.dets[0][1]), round(self.dets[0][2])],
            "end_xy": [round(self.dets[-1][1]), round(self.dets[-1][2])],
        }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", default="balanced_960_skip1")
    ap.add_argument("--top", type=int, default=15, help="top-N clusters to print")
    ap.add_argument("--db", default=None,
                    help="events DB to match against (default project.db; pass a retrack side-DB "
                         "to check whether a candidate config shrinks the orphan buckets)")
    args = ap.parse_args()

    proj = Path("data/projects") / args.project
    det_root = proj / "detections" / str(args.camera)
    pq_files = sorted(det_root.glob(f"*/{args.variant}.parquet"))
    if not pq_files:
        raise SystemExit(f"no cache {args.variant} under {det_root}")
    pq_path = pq_files[0]

    db = sqlite3.connect(args.db or str(proj / "project.db"))
    rows = db.execute(
        "SELECT event_id, start_frame, frame_number, trajectory_data "
        "FROM vehicle_events WHERE camera_id=?", (args.camera,)).fetchall()
    fps = db.execute("SELECT fps FROM videos WHERE camera_id=?",
                     (args.camera,)).fetchone()[0]
    db.close()
    index = EventIndex(rows)
    print(f"cam{args.camera} [{args.variant}] fps={fps}  events={len(rows)} "
          f"(indexed {len(index.events)})  cache={pq_path.name}")

    reader = DetectionCacheReader(pq_path)
    open_clusters: list[Cluster] = []
    done_clusters: list[Cluster] = []
    n_total = n_vehicle = n_matched = 0
    matched_speed_acc: list[float] = []   # sampled step speeds of matched dets
    last_matched: dict[int, tuple] = {}   # crude per-region last matched det for baseline speed
    band_floor: float | None = None
    band_dead = 0                          # vehicle dets with conf < activation

    for frame_idx, dets in reader.iter_frames():
        # retire stale clusters
        still = []
        for c in open_clusters:
            if frame_idx - c.last[0] > CHAIN_MAX_GAP:
                done_clusters.append(c)
            else:
                still.append(c)
        open_clusters = still

        for d in dets:
            n_total += 1
            if not d["is_vehicle"]:
                continue
            n_vehicle += 1
            conf = d["confidence"]
            band_floor = conf if band_floor is None else min(band_floor, conf)
            if conf < TRACKER_ACTIVATION_THRESHOLD:
                band_dead += 1
            cx, cy = d["center"]
            diag = math.hypot(d["bbox_width"], d["bbox_height"])
            radius = max(MATCH_BASE_RADIUS, MATCH_DIAG_FACTOR * diag)
            if index.explains(frame_idx, cx, cy, radius):
                n_matched += 1
                key = (int(cx // 160), int(cy // 160))
                prev = last_matched.get(key)
                if prev is not None and 0 < frame_idx - prev[0] <= 3:
                    matched_speed_acc.append(
                        math.hypot(cx - prev[1], cy - prev[2]) / (frame_idx - prev[0]))
                last_matched[key] = (frame_idx, cx, cy)
                continue
            # orphan: attach to nearest open cluster or start one
            best, best_d = None, None
            for c in open_clusters:
                lf, lx, ly, _, ld = c.last
                gap = frame_idx - lf
                if gap < 0 or gap > CHAIN_MAX_GAP:
                    continue
                dist = math.hypot(cx - lx, cy - ly)
                if dist <= CHAIN_DIST_PER_GAP * max(1, gap) and \
                        (best_d is None or dist < best_d):
                    best, best_d = c, dist
            if best is None:
                best = Cluster()
                open_clusters.append(best)
            best.dets.append((frame_idx, cx, cy, conf, diag))

    done_clusters.extend(open_clusters)
    vehicle_like = [c for c in done_clusters
                    if len(c.dets) >= MIN_CLUSTER_DETS
                    and c.stats()["net_travel_px"] >= MIN_CLUSTER_TRAVEL_PX]

    out = []
    for c in vehicle_like:
        s = c.stats()
        s["verdict"] = ("birth_gate" if s["conf_max"] < TRACKER_ACTIVATION_THRESHOLD
                        else "assoc_or_filtered")
        s["t_video_hms"] = f"{int(s['frame_start']/fps//3600):02d}:" \
                           f"{int(s['frame_start']/fps%3600//60):02d}:" \
                           f"{int(s['frame_start']/fps%60):02d}"
        out.append(s)
    out.sort(key=lambda s: -s["px_per_frame_median"])

    msa = sorted(matched_speed_acc)
    baseline = msa[len(msa) // 2] if msa else 0.0
    n_birth = sum(1 for s in out if s["verdict"] == "birth_gate")

    print(f"\ndetections: total={n_total:,} vehicle={n_vehicle:,} "
          f"matched-to-events={n_matched:,} ({n_matched/max(1,n_vehicle)*100:.1f}%)")
    print(f"conf floor seen={band_floor}  birth-dead band [<{TRACKER_ACTIVATION_THRESHOLD}]: "
          f"{band_dead:,} dets ({band_dead/max(1,n_vehicle)*100:.1f}% of vehicle dets)")
    print(f"orphan clusters: {len(done_clusters)} raw -> {len(vehicle_like)} vehicle-like "
          f"(>= {MIN_CLUSTER_DETS} dets, >= {MIN_CLUSTER_TRAVEL_PX:.0f}px travel)")
    print(f"verdicts: birth_gate={n_birth}  assoc_or_filtered={len(vehicle_like)-n_birth}")
    print(f"matched-detection baseline speed (median): {baseline:.1f} px/frame\n")

    print(f"top {min(args.top, len(out))} orphan clusters by speed "
          f"(scrub video to t_video to eyeball):")
    hdr = f"{'t_video':>9} {'frames':>15} {'n':>3} {'conf_max':>8} {'px/fr':>6} {'travel':>7} {'verdict':>18} {'start->end'}"
    print(hdr); print("-" * len(hdr))
    for s in out[:args.top]:
        print(f"{s['t_video_hms']:>9} {s['frame_start']:>7}-{s['frame_end']:<7} "
              f"{s['n_dets']:>3} {s['conf_max']:>8.3f} {s['px_per_frame_median']:>6.1f} "
              f"{s['net_travel_px']:>7.0f} {s['verdict']:>18} "
              f"{s['start_xy']}->{s['end_xy']}")

    suffix = f"_{Path(args.db).stem}" if args.db else ""
    out_path = Path("evaluations") / f"fast_misses_cam{args.camera}_{args.variant}{suffix}.json"
    out_path.write_text(json.dumps({
        "camera": args.camera, "variant": args.variant, "fps": fps,
        "n_detections_vehicle": n_vehicle, "n_matched": n_matched,
        "birth_dead_band_dets": band_dead,
        "matched_speed_median_px_per_frame": round(baseline, 2),
        "n_orphan_clusters_vehicle_like": len(vehicle_like),
        "n_birth_gate": n_birth,
        "clusters": out,
    }, indent=1))
    print(f"\nwrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
