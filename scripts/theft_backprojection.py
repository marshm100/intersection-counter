"""Back-projection signal for the theft class (measured 2026-09-10).

Operator's reel-4 shape: a box waiting near a mouth is taken by cross
traffic and "launched" along the thief's road. The speed alone did
not separate (theft_speed_signal.py). This tests the GEOMETRY of the
launch: take the post-launch heading, trace it BACKWARD from the
launch point, and see which gate that ray enters over.
  theft   -> the thief's gate (N on cam2/cam3), not the box's origin
  clean   -> the box's own origin gate (a right from W traces back
             toward W), or no gate (a curve)
Read-only, on the 17 ruled clips. Prints origin gate, back gate,
launch strength, and whether the two gates agree.
"""
from __future__ import annotations

import math
import sqlite3
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import GATE_EXTENSION_MARGIN  # noqa: E402
from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import (_seg_cross, build_gates,  # noqa: E402
                                          classify_pair, extend_gates)
from backend.services.pass2_replay import tracks_dir  # noqa: E402

PROJ = "97a7849a"
RULED = [
    (1, "study_0700", 2,      "clean", "reel1 through, corner spawn"),
    (1, "study_0700", 4829,   "clean", "reel1 through, glare"),
    (1, "study_0700", 9205,   "clean?", "reel1 through, occlusion (identity doubt)"),
    (1, "study_0700", 14948,  "clean", "reel1 through, occlusion"),
    (1, "study_0700", 22270,  "clean", "reel1 right, corner spawn"),
    (2, "study_0700", 16722,  "clean", "clean right"),
    (2, "study_0700", 17526,  "clean", "waiting right"),
    (2, "study_1600", 4383,   "clean", "reel2 right, corner spawn"),
    (2, "study_1600", 18964,  "clean", "reel2 right, corner spawn"),
    (2, "study_1600", 112,    "THEFT", "reel2 N->S through stole the waiting car"),
    (2, "study_1600", 9031,   "THEFT", "reel2 occlusion theft"),
    (2, "study_1600", 26259,  "THEFT", "reel2 occlusion theft"),
    (3, "study_0600", 14634,  "THEFT", "reel4 lock disrupted, lingers, dies"),
    (3, "study_0600", 154504, "THEFT", "reel4 last-minute theft at N exit"),
    (3, "study_0600", 281674, "THEFT", "reel4 lingers, stolen, runs away"),
    (3, "study_0600", 302741, "THEFT", "reel4 misfire + theft"),
    (3, "study_0600", 332755, "THEFT", "reel4 launched in reverse"),
]


def back_gate(p, heading, gates, reach=2000.0):
    """first gate hit by the ray from p along -heading."""
    hx, hy = -heading[0], -heading[1]
    q = (p[0] + hx * reach, p[1] + hy * reach)
    best = None
    for lg, (p1, p2, _inw) in gates.items():
        t = _seg_cross(p, q, p1, p2)
        if t is not None and (best is None or t < best[0]):
            best = (t, lg)
    return best[1] if best else None


def main() -> int:
    cache = {}
    print(f"{'cam':>3} {'tid':>7} {'class':6} {'origin':>6} {'back':>5} "
          f"{'jump':>5} {'agree':>5}  ruling")
    for cam, variant, tid, cls, ruling in RULED:
        key = (cam, variant)
        if key not in cache:
            con = sqlite3.connect(
                f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
            chash, fps = con.execute(
                "SELECT content_hash, fps FROM videos WHERE camera_id=?",
                (cam,)).fetchone()
            legs = dict(con.execute(
                "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
                (cam,)))
            con.close()
            geom = leg_geometry_for_camera(PROJ, cam)
            gates = build_gates(
                {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
                list_paths_for_camera(PROJ, cam),
                {lg: g.get("heading") for lg, g in geom.items()},
                leg_gates={lg: g["gate"] for lg, g in geom.items()
                           if g.get("gate")})
            td = tracks_dir(parquet_path(PROJ, cam, chash, variant))
            n = int((Path(td) / "count.txt").read_text())
            rows = np.asarray(np.load(Path(td) / "rows.npy", mmap_mode="r")[:n])
            cache[key] = (rows, float(fps), legs, gates)
        rows, fps, legs, gates = cache[key]
        card = lambda lg: legs.get(lg, "-") if lg is not None else "-"  # noqa: E731
        trk = rows[rows[:, 0] == float(tid)]
        trk = trk[np.argsort(trk[:, 1])]
        if len(trk) < 4:
            print(f"{cam:>3} {tid:>7} {cls:6} no track")
            continue
        corner = {}
        for sign, k in ((-1.0, "L"), (1.0, "R")):
            corner[k] = [(float(r[1]), float(r[2]) + sign * float(r[4]) / 2,
                          float(r[3]) + float(r[5]) / 2) for r in trk]
        o, d, *_rest = classify_pair(corner["L"], corner["R"], gates, fps)
        x = trk[:, 2]
        y = trk[:, 3] + trk[:, 5] / 2.0
        f = trk[:, 1]
        df = np.maximum(np.diff(f), 1.0)
        spd = np.hypot(np.diff(x), np.diff(y)) / df
        w = max(3, int(2.0 * fps))
        jump, li = 0.0, None
        for i in range(w, len(spd)):
            base = np.median(spd[i - w:i]) + 0.5
            if spd[i] / base > jump:
                jump, li = spd[i] / base, i
        if li is None:
            li = 0
        k = min(len(trk) - 1, li + max(2, int(1.5 * fps)))
        hx, hy = x[k] - x[li], y[k] - y[li]
        hl = math.hypot(hx, hy)
        if hl < 1e-6:
            bg = None
        else:
            bg = back_gate((x[li], y[li]), (hx / hl, hy / hl),
                           extend_gates(gates, GATE_EXTENSION_MARGIN))
        agree = ("same" if (o is not None and bg == o)
                 else ("DIFF" if (o is not None and bg is not None) else "n/a"))
        print(f"{cam:>3} {tid:>7} {cls:6} {card(o):>6} {card(bg):>5} "
              f"{jump:>5.1f} {agree:>5}  {ruling}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
