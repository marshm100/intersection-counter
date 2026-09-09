"""Red-team of the operator's line-extension idea (2026-09-09).

His idea, his words: "create extensions of the lines to infinity to
the edge of the frame so the user draws the intersection lines as they
exist and the program 'mentally' extends them ... only an idea and it
needs to be redteamed and tested."

Measures, per camera:
  GEOMETRY  where each gate's extension goes: which other gates /
            extensions it crosses inside the frame, and whether those
            crossings sit inside the intersection polygon.
  POPULATION on one window's pass-1 rows, both bottom corners:
            crossings under the DRAWN gates vs the EXTENDED gates.
            For every crossing the extension ADDS, classify it:
              completes  -- the other corner crossed the DRAWN segment
                            of the same gate, same direction, within
                            the pairing window (the wide-body pair)
              lone       -- no drawn crossing of that gate by either
                            corner: a corner hit an extension the
                            vehicle never approached (spurious risk)
            and reports how many tracks gain a PAIRED entry / exit.
Read-only. Usage:
  .venv\\Scripts\\python.exe -X utf8 scripts/redteam_line_extension.py 1:study_0700 2:study_1600 3:study_0600
"""
from __future__ import annotations

import math
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import CORNER_PAIR_WINDOW_S  # noqa: E402
from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import _seg_cross, all_crossings, build_gates  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"


def extend_to_frame(p1, p2, w, h):
    """The full line through p1-p2 clipped to the frame rectangle."""
    dx, dy = p2[0] - p1[0], p2[1] - p1[1]
    ts = []
    if abs(dx) > 1e-9:
        ts += [(0 - p1[0]) / dx, (w - p1[0]) / dx]
    if abs(dy) > 1e-9:
        ts += [(0 - p1[1]) / dy, (h - p1[1]) / dy]
    pts = []
    for t in ts:
        x, y = p1[0] + t * dx, p1[1] + t * dy
        if -1e-6 <= x <= w + 1e-6 and -1e-6 <= y <= h + 1e-6:
            pts.append((t, (min(max(x, 0.0), w), min(max(y, 0.0), h))))
    pts.sort()
    return pts[0][1], pts[-1][1]


def point_in_poly(pt, poly):
    x, y = pt
    inside = False
    for i in range(len(poly)):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % len(poly)]
        if (y1 > y) != (y2 > y):
            xi = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < xi:
                inside = not inside
    return inside


def hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def run(cam: int, variant: str) -> None:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=?",
        (cam,)).fetchone()
    legs = dict(con.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (cam,)))
    con.close()
    fps = float(fps)
    cap = cv2.VideoCapture(vpath)
    W, H = cap.get(cv2.CAP_PROP_FRAME_WIDTH), cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    cap.release()
    geom = leg_geometry_for_camera(PROJ, cam)
    gates = build_gates(
        {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
        list_paths_for_camera(PROJ, cam),
        {lg: g.get("heading") for lg, g in geom.items()},
        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})
    card = lambda lg: legs.get(lg, f"L{lg}")  # noqa: E731
    # EXT_MARGIN: extend each end by this fraction of the drawn length
    # (bounded extension); unset = to the frame edge (his idea as stated)
    import os
    margin = os.environ.get("EXT_MARGIN")
    if margin is None:
        ext = {lg: (*extend_to_frame(p1, p2, W, H), inw)
               for lg, (p1, p2, inw) in gates.items()}
    else:
        m = float(margin)
        ext = {}
        for lg, (p1, p2, inw) in gates.items():
            dx, dy = p2[0] - p1[0], p2[1] - p1[1]
            ext[lg] = ((p1[0] - m * dx, p1[1] - m * dy),
                       (p2[0] + m * dx, p2[1] + m * dy), inw)
    poly = hull([p for g in gates.values() for p in g[:2]])

    print(f"\n=== cam{cam} {variant}  frame {W:.0f}x{H:.0f}  {len(gates)} gates ===")
    for lg, (p1, p2, _i) in gates.items():
        e1, e2 = ext[lg][:2]
        seg = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        full = math.hypot(e2[0] - e1[0], e2[1] - e1[1])
        print(f"  gate {card(lg):>2}: drawn {seg:5.0f}px  extended {full:5.0f}px "
              f"({full / seg:.1f}x)")
    print("  extension crossings inside the frame:")
    lgs = list(gates)
    for i, a in enumerate(lgs):
        for b in lgs[i + 1:]:
            ea, eb = ext[a], ext[b]
            t = _seg_cross(ea[0], ea[1], eb[0], eb[1])
            if t is None:
                continue
            x = ea[0][0] + t * (ea[1][0] - ea[0][0])
            y = ea[0][1] + t * (ea[1][1] - ea[0][1])
            on_a = _seg_cross(gates[a][0], gates[a][1], eb[0], eb[1]) is not None
            on_b = _seg_cross(gates[b][0], gates[b][1], ea[0], ea[1]) is not None
            where = "INSIDE polygon" if point_in_poly((x, y), poly) else "outside"
            print(f"    ext {card(a)} x ext {card(b)} at ({x:.0f},{y:.0f}) {where}"
                  f"{'  [hits drawn ' + card(a) + ']' if on_a else ''}"
                  f"{'  [hits drawn ' + card(b) + ']' if on_b else ''}")

    td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
    n = int((Path(td) / "count.txt").read_text())
    rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    win = CORNER_PAIR_WINDOW_S * fps
    _t, starts = np.unique(rows[:, 0], return_index=True)
    bounds = list(zip(starts, list(starts[1:]) + [len(rows)]))
    tracks = 0
    added = Counter()          # (kind, gate, dir)
    gain_pair_in = gain_pair_out = 0
    drawn_pair_in = 0
    lone_by_gate = Counter()
    for a, b in bounds:
        trk = rows[a:b]
        if len(trk) < 5:
            continue
        tracks += 1
        corner = {}
        for sign, key in ((-1.0, "L"), (1.0, "R")):
            corner[key] = [(float(r[1]), float(r[2]) + sign * float(r[4]) / 2,
                            float(r[3]) + float(r[5]) / 2) for r in trk]
        drawn = {k: all_crossings(v, gates, fps) for k, v in corner.items()}
        exten = {k: all_crossings(v, ext, fps) for k, v in corner.items()}

        def paired(cr, inward):
            for x in cr["L"]:
                if x[2] != inward:
                    continue
                if any(y[1] == x[1] and y[2] == inward and abs(y[0] - x[0]) <= win
                       for y in cr["R"]):
                    return True
            return False
        d_in, d_out = paired(drawn, True), paired(drawn, False)
        e_in, e_out = paired(exten, True), paired(exten, False)
        drawn_pair_in += d_in
        gain_pair_in += (e_in and not d_in)
        gain_pair_out += (e_out and not d_out)
        for key in ("L", "R"):
            other = "R" if key == "L" else "L"
            for c in exten[key]:
                if any(abs(x[0] - c[0]) < 1.0 and x[1] == c[1] and x[2] == c[2]
                       for x in drawn[key]):
                    continue                     # the drawn segment had it
                completes = any(x[1] == c[1] and x[2] == c[2]
                                and abs(x[0] - c[0]) <= win
                                for x in drawn[other])
                if completes:
                    added[("completes", card(c[1]), "in" if c[2] else "out")] += 1
                else:
                    added[("lone", card(c[1]), "in" if c[2] else "out")] += 1
                    lone_by_gate[card(c[1])] += 1
    print(f"  tracks {tracks}: paired ENTRY under drawn gates {drawn_pair_in}; "
          f"extension ADDS a paired entry to {gain_pair_in} tracks "
          f"(+{gain_pair_in / max(drawn_pair_in, 1):.1%}), a paired exit to "
          f"{gain_pair_out}")
    comp = sum(v for k, v in added.items() if k[0] == "completes")
    lone = sum(v for k, v in added.items() if k[0] == "lone")
    print(f"  crossings the extension adds: {comp} complete a wide-body pair, "
          f"{lone} are LONE hits on an extension no corner approached")
    for k, v in sorted(added.items(), key=lambda kv: -kv[1])[:12]:
        print(f"      {k[0]:9} {k[1]:>2} {k[2]:3} {v}")


def main() -> int:
    for arg in sys.argv[1:]:
        cam, variant = arg.split(":")
        run(int(cam), variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
