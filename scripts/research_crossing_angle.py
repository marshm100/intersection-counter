"""Crossing angles of right vs wrong counts (2026-10-01, operator: "the lines are drawn fine").

For every counted event inside the development journey clips, the gate crossings that set its
origin and destination (classify_pair on the bottom corners, production gates) and the angle
between the vehicle's motion around each crossing (+-0.5 s of the bottom-centre path) and the
gate line: 90 = straight across, 0 = running along it. Events are split by the journey labels
into CORRECT (the owning labelled vehicle's movement), WRONG (owned, other movement) and
PHANTOM (no labelled vehicle). If wrong / phantom crossings are the shallow ones, a minimum
crossing angle is on-screen evidence that separates a graze from a crossing.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_crossing_angle.py STEM
"""
from __future__ import annotations

import math
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_journeys as ej  # noqa: E402
from backend.services import journey_eval as je  # noqa: E402
from backend.services.entry_gates import all_crossings, extend_gates  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from backend.services.two_pass import _pinned_gates  # noqa: E402


def angle_at(track, f, p1, p2, fps):
    """Angle (deg, 0-90) between the motion around frame f and the line p1-p2."""
    k = max(1, int(round(0.5 * fps)))
    pts = [(ff, x, y) for ff, x, y in track if f - k <= ff <= f + k]
    if len(pts) < 2:
        return None
    vx, vy = pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2]
    lx, ly = p2[0] - p1[0], p2[1] - p1[1]
    n = math.hypot(vx, vy) * math.hypot(lx, ly)
    if n < 1e-9:
        return None
    c = abs(vx * lx + vy * ly) / n
    return math.degrees(math.acos(min(1.0, c)))     # 0 = along the line


def main() -> int:
    stem = sys.argv[1]
    con = sqlite3.connect(f"file:data/projects/{ej.PROJ}/project.db?mode=ro", uri=True)
    res = ej.run_arm(stem, {})
    groups = defaultdict(list)
    for clip in list_clips(ej.PROJ):
        cid = clip["clip_id"]
        if cid not in res:
            continue
        cam = clip["camera_id"]
        window = "study_" + cid.split("_")[1]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        db, rows = ej.locate(stem, {}, cam, window, chash)
        gates, _ = _pinned_gates(ej.PROJ, cam, rows)
        from backend.config import GATE_EXTENSION_MARGIN
        egates = extend_gates(gates, GATE_EXTENSION_MARGIN)
        labels = {lb["label_id"]: lb for lb in list_labels(ej.PROJ, cid)}
        owner, truth = {}, {}
        for v in res[cid]["per_vehicle"]:
            for t in v["tracks"]:
                owner[t] = v["label_id"]
            truth[v["label_id"]] = v["truth"]
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for t, o, de in d.execute(
                "SELECT vehicle_track_id, origin_leg_id, destination_leg_id FROM vehicle_events "
                "WHERE camera_id=? AND COALESCE(rejected,0)=0 AND COALESCE(start_frame,frame_number) "
                "BETWEEN ? AND ?", (cam, clip["start_frame"], clip["end_frame"])):
            tr = rows[rows[:, 0] == t]
            tr = tr[np.argsort(tr[:, 1])]
            centre = [(float(r[1]), float(r[2]), float(r[3] + r[5] / 2)) for r in tr]
            lid = owner.get(int(t))
            kind = ("PHANTOM" if lid is None else
                    "CORRECT" if truth.get(lid) == (o, de) else "WRONG")
            for c in all_crossings(centre, egates, fps):
                if (c[2] and c[1] == o) or (not c[2] and c[1] == de):
                    p1, p2, _ = gates[c[1]]
                    a = angle_at(centre, c[0], p1, p2, fps)
                    if a is not None:
                        groups[kind].append((a, cam, "in" if c[2] else "out"))
    for kind in ("CORRECT", "WRONG", "PHANTOM"):
        a = np.array([x[0] for x in groups[kind]])
        if not len(a):
            continue
        q = np.percentile(a, [5, 10, 25, 50])
        under = {th: int((a < th).sum()) for th in (10, 15, 20, 25, 30)}
        print(f"{kind:8} n={len(a):4}  p5 {q[0]:.0f}  p10 {q[1]:.0f}  p25 {q[2]:.0f}  "
              f"median {q[3]:.0f}  | below 10/15/20/25/30 deg: {under}")
        by_cam = defaultdict(list)
        for ang, cam, side in groups[kind]:
            by_cam[cam].append(ang)
        print("          by camera, share below 20 deg: " + ", ".join(
            f"cam{c} {sum(x < 20 for x in v)}/{len(v)}" for c, v in sorted(by_cam.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
