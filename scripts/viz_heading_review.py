"""G-DEF-3 heading review (2026-09-11): per leg, three arrows on the frame.

  white    STORED reference_heading (the operator's arrow / May recal)
  magenta  the drawn line's PERPENDICULAR (inward)
  green    THROUGH-TRAFFIC direction, measured with no reference data:
           tracks whose gate journey enters over this leg and exits over
           the leg OPPOSITE it (the farthest gate), direction on the
           1.5 s approach before the entry crossing; needs >= 20 tracks.
           A leg with no opposite (a T stem) gets no green arrow.

Writes screenshots/headings_cam{N}.png and prints a ledger per leg
(headings in degrees, 0 = up the screen, clockwise) plus the angular
gaps between the three, so the operator can rule where they disagree.
Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/viz_heading_review.py [CAM:VARIANT ...]
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import GATE_EXTENSION_MARGIN  # noqa: E402
from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import (all_crossings, build_gates,  # noqa: E402
                                          classify_pair, extend_gates)
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ = "97a7849a"
DEFAULT = ["1:study_0700", "2:study_0700", "3:study_0600", "4:study_0700", "5:study_0700"]
WHITE, MAGENTA, GREEN, BLACK = (255, 255, 255), (255, 0, 220), (60, 230, 60), (0, 0, 0)
APPROACH_S, MIN_N = 1.5, 20


def _hd(vx, vy):
    return math.degrees(math.atan2(vx, -vy)) % 360.0


def _gap(a, b):
    if a is None or b is None:
        return None
    d = abs((a - b + 180.0) % 360.0 - 180.0)
    return d


def _arrow(im, origin, heading, length, col, thick):
    rad = math.radians(heading)
    tip = (int(origin[0] + math.sin(rad) * length),
           int(origin[1] - math.cos(rad) * length))
    cv2.arrowedLine(im, origin, tip, BLACK, thick + 3, tipLength=0.25)
    cv2.arrowedLine(im, origin, tip, col, thick, tipLength=0.25)


def run(cam: int, variant: str, ledger: list) -> None:
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    vpath, chash, fps = con.execute(
        "SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    legs = {r[0]: {"card": r[1], "label": r[2], "stored": r[3]} for r in con.execute(
        "SELECT leg_id, cardinal_direction, label, reference_heading FROM legs "
        "WHERE camera_id=?", (cam,))}
    con.close()
    fps = float(fps)
    geom = leg_geometry_for_camera(PROJ, cam)
    gates = build_gates(
        {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
        list_paths_for_camera(PROJ, cam),
        {lg: g.get("heading") for lg, g in geom.items()},
        leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})
    ext = extend_gates(gates, GATE_EXTENSION_MARGIN)
    mids = {lg: ((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2) for lg, (p1, p2, _i) in gates.items()}
    perp = {lg: _hd(*gates[lg][2]) for lg in gates}
    # the opposite leg = the farthest gate midpoint (needs >= 4 legs to be
    # meaningful; with 3 the stem has none, the two arterial legs have each other)
    opposite = {}
    for lg, m in mids.items():
        far = max(((math.hypot(m[0] - q[0], m[1] - q[1]), o) for o, q in mids.items() if o != lg),
                  default=(0, None))
        opposite[lg] = far[1]
    if len(mids) == 3:
        # T: the two legs whose gates are most nearly antiparallel are the
        # arterial pair; the third is the stem with no opposite
        best = None
        for a in mids:
            for b in mids:
                if a < b:
                    g = _gap(perp[a], (perp[b] + 180.0) % 360.0)
                    if best is None or g < best[0]:
                        best = (g, a, b)
        _g, a, b = best
        opposite = {a: b, b: a}
        for lg in mids:
            opposite.setdefault(lg, None)

    rows = load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant)))
    rows = np.asarray(rows)
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    back = int(round(APPROACH_S * fps))
    acc = {lg: [0.0, 0.0, 0] for lg in gates}
    _t, starts = np.unique(rows[:, 0], return_index=True)
    bounds = list(zip(starts, list(starts[1:]) + [len(rows)]))
    for a, b in bounds:
        trk = rows[a:b]
        if len(trk) < 5:
            continue
        pl = [(float(r[1]), float(r[2]) - float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
        pr = [(float(r[1]), float(r[2]) + float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
        o, d, fo, _fd, *_rest, tag = classify_pair(pl, pr, gates, fps)
        if tag != "full" or o is None or opposite.get(o) != d:
            continue
        pts = [(float(r[1]), float(r[2]), float(r[3]) + float(r[5]) / 2) for r in trk]
        frames = trk[:, 1]
        i = int(np.searchsorted(frames, fo))
        i1 = max(0, min(len(pts) - 1, i - 1))
        i0 = max(0, min(int(np.searchsorted(frames, fo - back)), i1 - 1))
        if i1 <= i0:
            continue
        vx, vy = pts[i1][1] - pts[i0][1], pts[i1][2] - pts[i0][2]
        n = math.hypot(vx, vy)
        if n < 1e-6:
            continue
        acc[o][0] += vx / n
        acc[o][1] += vy / n
        acc[o][2] += 1
    through = {lg: (_hd(v[0], v[1]) if v[2] >= MIN_N else None) for lg, v in acc.items()}

    cap = cv2.VideoCapture(vpath)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * 0.35))
    ok, fr = cap.read()
    cap.release()
    for lg, (p1, p2, _i) in gates.items():
        e1, e2 = ext[lg][:2]
        cv2.line(fr, (int(e1[0]), int(e1[1])), (int(e2[0]), int(e2[1])), MAGENTA, 1)
        cv2.line(fr, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), BLACK, 5)
        cv2.line(fr, (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1])), MAGENTA, 2)
    print(f"\n=== cam{cam} {variant} ===")
    print(f"  {'leg':>3} {'label':28} {'stored':>7} {'perp':>7} {'through':>8} {'n':>5}   gaps: s-p  s-t  p-t")
    for lg in gates:
        m = (int(mids[lg][0]), int(mids[lg][1]))
        st, pp, th = legs[lg]["stored"], perp[lg], through[lg]
        _arrow(fr, m, pp, 42, MAGENTA, 2)
        if st is not None:
            _arrow(fr, m, st, 56, WHITE, 2)
        if th is not None:
            _arrow(fr, m, th, 70, GREEN, 2)
        card = legs[lg]["card"]
        cv2.putText(fr, card, (m[0] - 10, m[1] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.8, BLACK, 4)
        cv2.putText(fr, card, (m[0] - 10, m[1] - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.8, WHITE, 2)
        gsp, gst, gpt = _gap(st, pp), _gap(st, th), _gap(pp, th)
        fmt = lambda v: "-" if v is None else f"{v:5.0f}"  # noqa: E731
        print(f"  {card:>3} {legs[lg]['label'][:28]:28} {fmt(st):>7} {fmt(pp):>7} {fmt(th):>8} "
              f"{acc[lg][2]:>5}   {fmt(gsp):>6}{fmt(gst):>5}{fmt(gpt):>5}"
              f"{'   <-- disagree' if (gst or 0) >= 15 or ((gsp or 0) >= 15 and th is None) else ''}")
        ledger.append({"cam": cam, "leg_id": lg, "card": card, "label": legs[lg]["label"],
                       "stored": st, "perpendicular": pp, "through": th, "n_through": acc[lg][2],
                       "opposite": legs.get(opposite.get(lg), {}).get("card")})
    cv2.rectangle(fr, (0, 0), (fr.shape[1], 26), BLACK, -1)
    cv2.putText(fr, f"cam{cam}  white=stored heading  magenta=line perpendicular  green=through traffic",
                (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
    out = Path(f"screenshots/headings_cam{cam}.png")
    cv2.imwrite(str(out), fr)
    print(f"  -> {out}")


def main() -> int:
    args = sys.argv[1:] or DEFAULT
    ledger: list = []
    for a in args:
        cam, variant = a.split(":")
        run(int(cam), variant, ledger)
    Path("runs/heading_review_2026-09-11.json").write_text(json.dumps(ledger, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
