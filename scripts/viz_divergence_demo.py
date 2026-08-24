"""Divergence-arbitration failure demo (Stage 0 of plan_divergence_arbitration).

What the picture proves: vehicles that the tracker lost BEFORE the point where
the EB-right and EB-through guides split are being decided by shape anyway.
Each PNG shows one real flipped vehicle from the G-DG-1 regate: its full raw
track (white), both sibling guides (green=right, orange=through), the
divergence point (cyan circle — where the guides first separate by >30 px),
and where the track died (red dot). The caption carries the production
scorer's own numbers (mdh cost + tail prior via trajectory_classifier's real
helpers) plus the ctrl vs arm decisions.

Usage:
  py -X utf8 scripts/viz_divergence_demo.py [--n 5] [--window study_1600] [--tids 105,215]
Writes screenshots/divergence_demo_cam2_tid<id>.png + a printed summary.
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from auto_calibrate_viz import load_video_frame                     # noqa: E402
from backend.services.entry_gates import (                          # noqa: E402
    build_gates, classify as gate_classify, parse_gate_segment,
)
from backend.services.path_divergence import (                      # noqa: E402
    _arc_positions, coverage_s_max, divergence_s,
)
from backend.services.trajectory_classifier import (                # noqa: E402
    _densify_polyline, _mdh_cost, _resample_to, _unit,
)

WD = "data/projects/97a7849a/_replay_scratch/regate_20260823"
PROD = "data/projects/97a7849a/project.db"
FPS = 25.0
FINALIZE_LAG = 60          # config.TRACK_FINALIZE_GAP_FRAMES
COL_TRACK = (255, 255, 255)
COL_RIGHT = (80, 200, 80)      # BGR green
COL_THRU = (0, 165, 255)       # BGR orange
COL_DIV = (255, 255, 0)        # cyan
COL_DEATH = (60, 60, 230)      # red


def _ro(db):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def score_like_joint(raw_traj, poly):
    """The scorer's own per-candidate numbers (trajectory_classifier.py:764-795,
    mdh metric): (cost, tail_prior). Uses the REAL private helpers."""
    traj = _resample_to(raw_traj, 30)
    poly_dense = _densify_polyline(poly, 12.0)
    cost = _mdh_cost(traj, poly_dense)
    tw = min(7, len(traj))
    tail = traj[-tw:]
    tail_dir = _unit(tail[-1][0] - tail[0][0], tail[-1][1] - tail[0][1])
    ex, ex_prev = poly_dense[-1], poly_dense[-2]
    exit_dir = _unit(ex[0] - ex_prev[0], ex[1] - ex_prev[1])
    tail_prior = (tail_dir[0] * exit_dir[0] + tail_dir[1] * exit_dir[1] + 1.0) / 2.0
    return cost, tail_prior


def point_at_s(poly, s):
    """(x, y) at arc position s along poly."""
    pts = [(float(p[0]), float(p[1])) for p in poly]
    arcs = _arc_positions(pts)
    for i in range(1, len(pts)):
        if arcs[i] >= s:
            span = arcs[i] - arcs[i - 1]
            t = 0.0 if span <= 1e-9 else (s - arcs[i - 1]) / span
            return (pts[i - 1][0] + t * (pts[i][0] - pts[i - 1][0]),
                    pts[i - 1][1] + t * (pts[i][1] - pts[i - 1][1]))
    return pts[-1]


def draw_poly(img, poly, color, thickness=2):
    arr = np.array([[int(p[0]), int(p[1])] for p in poly], dtype=np.int32)
    cv2.polylines(img, [arr], False, color, thickness, cv2.LINE_AA)


def caption_strip(width, lines):
    strip = np.zeros((18 * len(lines) + 10, width, 3), dtype=np.uint8)
    for i, line in enumerate(lines):
        cv2.putText(strip, line, (8, 18 * (i + 1)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, (230, 230, 230), 1, cv2.LINE_AA)
    return strip


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="study_1600")
    ap.add_argument("--n", type=int, default=5)
    ap.add_argument("--tids", default=None, help="comma-separated override")
    args = ap.parse_args()

    ctrl = _ro(f"{WD}/regatectrl_cam2_{args.window}.db")
    arm = _ro(f"{WD}/regatearm_cam2_{args.window}.db")

    # the two sibling guides, from the ARM path set (which has both)
    guides = {}
    for r in arm.execute(
        "SELECT destination_leg_id AS d, movement_label AS mv, polyline, "
        "supporting_count AS sup FROM intersection_paths "
        "WHERE camera_id=2 AND origin_leg_id=28 AND destination_leg_id IN (26, 29)"
    ):
        guides[r["mv"]] = {"poly": json.loads(r["polyline"]), "sup": r["sup"], "dest": r["d"]}
    right, thru = guides["right"]["poly"], guides["through"]["poly"]

    # the operator's drawn gates + the gate classifier (the machinery whose
    # verdict matched the operator's hand labels 5/5)
    mouths, heads, drawn_gates = {}, {}, {}
    for lg in ctrl.execute("SELECT leg_id, origin_zone, reference_heading, gate_segment FROM legs WHERE camera_id=2"):
        oz = json.loads(lg["origin_zone"])
        mouths[lg["leg_id"]] = tuple(oz[0]); heads[lg["leg_id"]] = lg["reference_heading"]
        g = parse_gate_segment(lg["gate_segment"])
        if g: drawn_gates[lg["leg_id"]] = g
    gpaths = [dict(r) | {"polyline": json.loads(r["polyline"])} for r in
              ctrl.execute("SELECT origin_leg_id, destination_leg_id, polyline FROM intersection_paths WHERE camera_id=2")]
    gates = build_gates(mouths, gpaths, heads, leg_gates=drawn_gates or None)
    GATE_COLOR = (255, 0, 255)   # magenta: the operator's drawn gate lines

    # divergence: arc position along each guide where it separates from its sibling
    s_div_right = divergence_s(right, thru)
    s_div_thru = divergence_s(thru, right)
    print(f"divergence along RIGHT : {'NEVER (guides within 30px over its whole extent)' if s_div_right is None else f's={s_div_right:.0f}px'}")
    print(f"divergence along THROUGH: {'NEVER' if s_div_thru is None else f's={s_div_thru:.0f}px'}")
    # the decisive arc position: where the pair becomes distinguishable at all
    s_split = s_div_thru if s_div_thru is not None else s_div_right

    # the flip population: ctrl said 28->29 right, arm said 28->26 through
    q = ("SELECT vehicle_track_id AS tid, movement, destination_leg_id AS d, "
         "trajectory_data, frame_number, start_frame FROM vehicle_events "
         "WHERE camera_id=2 AND origin_leg_id=28 AND COALESCE(rejected,0)=0")
    cr = {r["tid"]: r for r in ctrl.execute(q)}
    ar = {r["tid"]: r for r in arm.execute(q)}
    flips = [t for t in cr.keys() & ar.keys()
             if cr[t]["movement"] == "right" and cr[t]["d"] == 29
             and ar[t]["movement"] == "through" and ar[t]["d"] == 26]
    print(f"flip population ({args.window}): {len(flips)} tracks (right->through)")

    # summary: how many died before the split?
    pre_split = 0
    for t in flips:
        traj = json.loads(cr[t]["trajectory_data"])
        if coverage_s_max(traj, thru) <= (s_split or 0):
            pre_split += 1
    print(f"of those, died BEFORE the split (never reached divergence): "
          f"{pre_split} ({100.0 * pre_split / max(1, len(flips)):.0f}%)")

    # video for backgrounds
    prod = _ro(PROD)
    vpath = prod.execute("SELECT path FROM videos WHERE camera_id=2").fetchone()[0]
    prod.close()

    if args.tids:
        chosen = [int(x) for x in args.tids.split(",")]
    else:
        # spread across death distances: mostly clear pre-split cases
        scored = []
        for t in flips:
            traj = json.loads(cr[t]["trajectory_data"])
            cov = coverage_s_max(traj, thru)
            scored.append((t, cov, len(traj)))
        scored.sort(key=lambda x: x[1])
        idxs = [int(i * (len(scored) - 1) / max(1, args.n - 1)) for i in range(args.n)]
        chosen = [scored[i][0] for i in idxs]

    out_dir = Path("screenshots")
    out_dir.mkdir(exist_ok=True)
    for tid in chosen:
        r = cr[tid]
        traj = json.loads(r["trajectory_data"])
        death_frame = max(0, (r["frame_number"] or 0) - FINALIZE_LAG)
        img = load_video_frame(vpath, death_frame / FPS)
        if img is None:
            img = cv2.imread("data/projects/97a7849a/calibration_backdrop_cam2.png")
        img = img.copy()

        for glid, (g1, g2) in drawn_gates.items():
            cv2.line(img, (int(g1[0]), int(g1[1])), (int(g2[0]), int(g2[1])),
                     GATE_COLOR, 2, cv2.LINE_AA)
            cv2.putText(img, f"gate {glid}", (int((g1[0]+g2[0])/2)+4, int((g1[1]+g2[1])/2)-4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, GATE_COLOR, 1, cv2.LINE_AA)
        draw_poly(img, right, COL_RIGHT, 2)
        draw_poly(img, thru, COL_THRU, 2)
        draw_poly(img, traj, COL_TRACK, 2)
        # divergence circles on both guides
        for poly, s in ((right, s_div_right), (thru, s_div_thru)):
            if s is not None:
                dx, dy = point_at_s(poly, s)
                cv2.circle(img, (int(dx), int(dy)), 9, COL_DIV, 2, cv2.LINE_AA)
        # start + death dots
        cv2.circle(img, (int(traj[0][0]), int(traj[0][1])), 4, (0, 230, 230), -1, cv2.LINE_AA)
        cv2.circle(img, (int(traj[-1][0]), int(traj[-1][1])), 6, COL_DEATH, -1, cv2.LINE_AA)

        f0 = r["start_frame"] or 0
        gpts = [(float(f0 + i), float(pt[0]), float(pt[1])) for i, pt in enumerate(traj)]
        g_o, g_d, _, _, _, _, g_tag = gate_classify(gpts, gates, FPS)
        cov = coverage_s_max(traj, thru)
        gap = (s_split or 0) - cov
        c_r, tp_r = score_like_joint(traj, right)
        c_t, tp_t = score_like_joint(traj, thru)
        lines = [
            f"tid {tid}  cam2 {args.window}  |  track: {len(traj)} pts, dies {gap:+.0f}px BEFORE the split"
            if gap > 0 else
            f"tid {tid}  cam2 {args.window}  |  track: {len(traj)} pts, reaches {-gap:.0f}px past the split",
            f"GREEN right guide (sup {guides['right']['sup']}): mdh {c_r:.1f}  tail_prior {tp_r:.2f}"
            f"  -> turn gate {'REJECTS (tail<0.85)' if tp_r < 0.85 else 'admits'}",
            f"ORANGE through guide (sup {guides['through']['sup']}): mdh {c_t:.1f}  tail_prior {tp_t:.2f}"
            f"  -> exempt from turn gate",
            f"decision: CTRL = RIGHT | ARM = THROUGH | GATES (magenta): origin={g_o} dest={g_d} tag={g_tag}",
            f"NEW PIPELINE (gate supremacy): "
            + ("NOT A COUNTED FULL JOURNEY - falls to entry-only/no-crossing handling"
               if g_tag != "full" else
               f"classified by gate crossings -> {g_o}->{g_d}"),
            f"RIGHT guide NEVER leaves 30px of THROUGH (max ~13px over its whole 216px arc)"
            if s_div_right is None else "guides separate at the cyan circles",
            "cyan circle = first point the pair is distinguishable   red dot = where the tracker lost it",
        ]
        panel = np.vstack([img, caption_strip(img.shape[1], lines)])
        out = out_dir / f"divergence_demo_cam2_tid{tid}.png"
        cv2.imwrite(str(out), panel)
        print(f"wrote {out}")

    ctrl.close(); arm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
