"""G-SM-1 diagnosis: WHY did the state machine lose entry coverage?

For every solo (one-corner) INWARD crossing that the journey state
machine refuses, ask where the OTHER corner was: did it get INSIDE the
line without ever crossing the drawn segment (it passed beyond the
segment's END — the gate is shorter than the lane), or did it stay
OUTSIDE (a box straddling the line: wobble / creep)? The truncation
split only anticipated the second kind.

Read-only, pass-1 rows. Usage:
  .venv\\Scripts\\python.exe -X utf8 scripts/diag_sm_solo_entries.py 1:study_0700 1:study_1600 2:study_1100
"""
from __future__ import annotations

import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import CORNER_PAIR_WINDOW_S, CROSSING_TRUNCATION_S  # noqa: E402
from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import all_crossings, build_gates  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"


def _side_and_proj(pt, gate):
    """signed distance along the inward normal (>0 = inside) and the
    projection along the segment as a fraction of its length."""
    (p1, p2, inw) = gate
    mid = ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
    side = (pt[0] - mid[0]) * inw[0] + (pt[1] - mid[1]) * inw[1]
    gl = math.hypot(p2[0] - p1[0], p2[1] - p1[1]) or 1.0
    proj = ((pt[0] - p1[0]) * (p2[0] - p1[0])
            + (pt[1] - p1[1]) * (p2[1] - p1[1])) / (gl * gl)
    return side, proj


def run(cam: int, variant: str) -> None:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    _v, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=?",
        (cam,)).fetchone()
    legs = dict(con.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (cam,)))
    con.close()
    fps = float(fps)
    geom = leg_geometry_for_camera(PROJ, cam)
    gates = build_gates(
        {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
        list_paths_for_camera(PROJ, cam),
        {lg: g.get("heading") for lg, g in geom.items()},
        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})
    td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows = rows[order]
    win = CORNER_PAIR_WINDOW_S * fps
    trunc = CROSSING_TRUNCATION_S * fps

    tracks_total = 0
    either_witnessed = 0          # legacy: any corner's first inward crossing
    paired_witnessed = 0          # SM: a paired inward crossing exists
    solo_accepted = 0             # SM: solo entry accepted (track ended)
    refused = Counter()           # category -> tracks losing their entry
    refused_by_leg = Counter()
    proj_hist = Counter()
    starts, ends = np.unique(rows[:, 0], return_index=True)
    bounds = list(zip(ends, list(ends[1:]) + [len(rows)]))
    for (a, b) in bounds:
        trk = rows[a:b]
        if len(trk) < 5:
            continue
        tracks_total += 1
        corner = {}
        for sign, key in ((-1.0, "L"), (1.0, "R")):
            corner[key] = [(float(r[1]), float(r[2]) + sign * float(r[4]) / 2,
                            float(r[3]) + float(r[5]) / 2) for r in trk]
        cr = {k: all_crossings(v, gates, fps) for k, v in corner.items()}
        ins = {k: [c for c in v if c[2]] for k, v in cr.items()}
        if not (ins["L"] or ins["R"]):
            continue
        either_witnessed += 1
        # any paired inward crossing?
        paired = False
        for x in ins["L"]:
            if any(y[1] == x[1] and abs(y[0] - x[0]) <= win for y in ins["R"]):
                paired = True
                break
        if paired:
            paired_witnessed += 1
            continue
        end_f = float(trk[-1, 1])
        # first solo inward crossing (either corner) — what SM sees
        solos = sorted(ins["L"] + ins["R"], key=lambda c: c[0])
        c0 = solos[0]
        me = "L" if c0 in ins["L"] else "R"
        other = "R" if me == "L" else "L"
        straddle = any(o[1] == c0[1] and not o[2] and abs(o[0] - c0[0]) <= win
                       for o in cr[other])
        if straddle:
            refused["straddle_veto"] += 1
            refused_by_leg[(legs.get(c0[1]), "straddle")] += 1
            continue
        if end_f - c0[0] <= trunc:
            solo_accepted += 1
            continue
        # where is the other corner one window later (or at track end)?
        f_probe = min(c0[0] + win, end_f)
        pts = corner[other]
        probe = min(pts, key=lambda p: abs(p[0] - f_probe))
        side, proj = _side_and_proj(probe[1:], gates[c0[1]])
        if side > 0:
            cat = "other_corner_INSIDE"
            side0, _p0 = _side_and_proj(pts[0][1:], gates[c0[1]])
            earlier = any(o[1] == c0[1] and o[2] and o[0] < c0[0] - win
                          for o in cr[other])
            if side0 > 0 and not earlier:
                cat += "_born_across"          # track began with it inside
            elif earlier:
                cat += "_crossed_before_window"
            elif proj < 0 or proj > 1:
                cat += "_beyond_segment_end"
            else:
                cat += "_unexplained"
        else:
            cat = "other_corner_still_OUTSIDE"
        refused[cat] += 1
        refused_by_leg[(legs.get(c0[1]), cat[:20])] += 1
        proj_hist[("beyond" if (proj < 0 or proj > 1) else "within")] += 1

    print(f"\n=== cam{cam} {variant} ({fps:.0f} fps) ===")
    print(f"tracks >=5 pts          {tracks_total}")
    print(f"either-corner witnessed {either_witnessed}  "
          f"({either_witnessed / max(tracks_total, 1):.3f} of tracks)")
    print(f"  paired (SM keeps)     {paired_witnessed}")
    print(f"  solo, track ended     {solo_accepted}  (SM keeps)")
    lost = sum(refused.values())
    print(f"  solo, REFUSED by SM   {lost}  "
          f"({lost / max(either_witnessed, 1):.1%} of witnessed entries)")
    for k, v in refused.most_common():
        print(f"      {k:48} {v}")
    print("  refused by leg:")
    for (leg, cat), v in sorted(refused_by_leg.items(),
                                key=lambda kv: -kv[1])[:12]:
        print(f"      {str(leg):>4} {cat:22} {v}")


def main() -> int:
    for arg in sys.argv[1:]:
        cam, variant = arg.split(":")
        run(int(cam), variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
