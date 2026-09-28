"""Counting-line dry run (2026-09-27, declared in docs/plan_basis_2026-09-11.md).

Would a counting line derived per leg from the operator's leg line + the
window's own tracks decide crossings better than the leg line itself? No
production change; reports numbers only.

Candidate per leg: the operator's line translated toward the box centroid
(mean of the four line midpoints) by s x (midpoint-to-centroid distance),
s in {0, 0.05, ..., 0.35}; TURNOVER(s) = (births + deaths inside the strip
s +- 0.025) / (distinct tracks with a point in it); s* = argmin.
Reports: s* per leg; gate-tag transitions of COUNTED events; (origin, dest)
changes among tracks full under both; and, where a theft census exists
(cam4 / cam5 study_1600, kind THEFT), thefts falling INSIDE a journey under
old vs candidate lines.

Usage: .venv\\Scripts\\python.exe -X utf8 scripts/research_counting_lines.py [CAM ...]
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.database import leg_geometry_for_camera, list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates, classify_pair  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.two_pass import _tracks_from_rows, gate_axes_for  # noqa: E402

PROJ = "97a7849a"
BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"),
           (2, "study_1100"), (2, "study_1600"), (3, "study_0600"),
           (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
           (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]
SHIFTS = [round(0.05 * i, 2) for i in range(8)]      # 0 .. 0.35
HALF = 0.025


def journeys(rows, fps, gates):
    """{tid: (origin, dest, f_origin, f_dest, tag)} by the journey state machine."""
    out = {}
    order = np.argsort(rows[:, 0], kind="stable")
    rs = rows[order]
    tids, starts = np.unique(rs[:, 0], return_index=True)
    ends = np.append(starts[1:], len(rs))
    for tid, a, b in zip(tids, starts, ends):
        sel = rs[a:b]
        sel = sel[np.argsort(sel[:, 1])]
        if len(sel) < 2:
            continue
        f, x, y, w, h = sel[:, 1], sel[:, 2], sel[:, 3], sel[:, 4], sel[:, 5]
        yb = y + h / 2.0
        pl = list(zip(f.tolist(), (x - w / 2.0).tolist(), yb.tolist()))
        pr = list(zip(f.tolist(), (x + w / 2.0).tolist(), yb.tolist()))
        o, d, fo, fd, _op, _dp, tag = classify_pair(pl, pr, gates, fps)
        out[int(tid)] = (o, d, fo, fd, tag)
    return out


def main() -> int:
    cams = {int(c) for c in sys.argv[1:]} or {c for c, _ in WINDOWS}
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    for cam, variant in WINDOWS:
        if cam not in cams:
            continue
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?",
                                 (cam,)).fetchone()
        fps = float(fps)
        card = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
                                (cam,)))
        geom = leg_geometry_for_camera(PROJ, cam)
        drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}
        heads = {lid: g["heading"] for lid, g in geom.items()}
        paths = list_paths_for_camera(PROJ, cam)
        rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
        mouths0 = {lid: g["mouth"] for lid, g in geom.items()}
        axes = gate_axes_for(mouths0, _tracks_from_rows(rows).values())
        mids = {lid: ((l[0][0] + l[1][0]) / 2, (l[0][1] + l[1][1]) / 2) for lid, l in drawn.items()}
        cx = np.mean([m[0] for m in mids.values()])
        cy = np.mean([m[1] for m in mids.values()])

        # births / deaths per track, and every point, in one pass
        order = np.argsort(rows[:, 0], kind="stable")
        rs = rows[order]
        _t, st = np.unique(rs[:, 0], return_index=True)
        en = np.append(st[1:], len(rs)) - 1
        births, deaths = rs[st], rs[en]
        px, py, ptid = rows[:, 2], rows[:, 3] + rows[:, 5] / 2.0, rows[:, 0]

        cand = {}
        report = []
        for lid, line in drawn.items():
            (x1, y1), (x2, y2) = line
            mx, my = mids[lid]
            dx, dy = x2 - x1, y2 - y1
            L2 = dx * dx + dy * dy
            nx, ny = cx - mx, cy - my
            D = float(np.hypot(nx, ny))
            ux, uy = nx / D, ny / D

            def strip(xs, ys, s):
                t = ((xs - x1) * dx + (ys - y1) * dy) / L2
                dist = (xs - mx) * ux + (ys - my) * uy
                return (t >= -0.1) & (t <= 1.1) & (np.abs(dist - s * D) <= HALF * D)

            turn = {}
            for s in SHIFTS:
                bd = strip(births[:, 2], births[:, 3] + births[:, 5] / 2.0, s).sum() + \
                    strip(deaths[:, 2], deaths[:, 3] + deaths[:, 5] / 2.0, s).sum()
                thru = len(np.unique(ptid[strip(px, py, s)]))
                turn[s] = bd / thru if thru else float("inf")
            s_star = min(SHIFTS, key=lambda s: turn[s])
            off = (s_star * D * ux, s_star * D * uy)
            cand[lid] = ((x1 + off[0], y1 + off[1]), (x2 + off[0], y2 + off[1]))
            report.append(f"{card.get(lid)}: s*={s_star:.2f} ({s_star * D:.0f}px) "
                          f"turnover {turn[0.0]:.2f} -> {turn[s_star]:.2f}")

        mouths1 = {lid: ((l[0][0] + l[1][0]) / 2, (l[0][1] + l[1][1]) / 2) for lid, l in cand.items()}
        g_old = build_gates(mouths0, paths, heads, leg_axes=axes, leg_gates=drawn)
        g_new = build_gates(mouths1, paths, heads, leg_axes=axes, leg_gates=cand)
        j_old, j_new = journeys(rows, fps, g_old), journeys(rows, fps, g_new)

        tag = f"vl3_{variant}" if cam in (4, 5) else variant
        db = sqlite3.connect(f"file:{BASE / f'gx2_cam{cam}_{tag}.db'}?mode=ro", uri=True)
        counted = {int(t) for (t,) in db.execute(
            "SELECT vehicle_track_id FROM vehicle_events WHERE camera_id=? AND "
            "COALESCE(rejected,0)=0 AND vehicle_track_id>=0", (cam,))}
        trans = Counter((j_old[t][4], j_new[t][4]) for t in counted if t in j_old and t in j_new)
        both_full = [t for t in j_old if j_old[t][4] == "full" and j_new.get(t, (0,) * 5)[4] == "full"]
        od_changed = sum(1 for t in both_full if j_old[t][:2] != j_new[t][:2])

        print(f"\ncam{cam} {variant}: tracks {len(j_old)}, counted {len(counted)}")
        print("   lines: " + " | ".join(report))
        moved = {k: v for k, v in trans.items() if k[0] != k[1]}
        print(f"   counted-event tag changes: {sorted(moved.items(), key=lambda kv: -kv[1])[:6]}")
        print(f"   counted tags old {dict(Counter(j_old[t][4] for t in counted if t in j_old))}")
        print(f"   counted tags new {dict(Counter(j_new[t][4] for t in counted if t in j_new))}")
        print(f"   full under both: {len(both_full)}, (origin, dest) changed: {od_changed} "
              f"({100 * od_changed / max(len(both_full), 1):.1f}%)")

        tf = Path(f"runs/v2_week1/thefts_{PROJ}_{cam}_vl3_{variant}.json")
        if tf.exists():
            thefts = [e for e in json.loads(tf.read_text()) if e.get("kind") == "THEFT"]

            def inside(j, f):
                if j is None:
                    return False
                o, d, fo, fd, tg = j
                if tg == "full" and fo is not None and fd is not None:
                    return fo <= f <= fd
                if tg == "entry_only" and fo is not None:
                    return f >= fo
                if tg == "exit_only" and fd is not None:
                    return f <= fd
                return False

            a = sum(inside(j_old.get(e["track"]), e["f_first_B"]) for e in thefts)
            b = sum(inside(j_new.get(e["track"]), e["f_first_B"]) for e in thefts)
            print(f"   thefts {len(thefts)}: inside a journey old {a} -> new {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
