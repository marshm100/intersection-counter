"""G-DEF-3 heading review CLIPS (2026-09-11): the operator ruled a still
is unusable ("How should I know there is no movement"). One full-frame
WebM per disagreeing leg: the 15 s of the window with the most vehicles
ENTERING over that leg, every tracked box drawn (green = a track whose
journey entered over this leg, grey = others), the gate lines, and the
three heading arrows at the leg's gate midpoint:
  white   stored heading   magenta  line perpendicular   green  through traffic
Reads runs/heading_review_2026-09-11.json for the arrows.
Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/viz_heading_clips.py CAM:VARIANT:LEGCARD ...
Writes screenshots/heading_cam{N}_{leg}.webm
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

from backend.database import leg_geometry_for_camera  # noqa: E402
from backend.database import list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates, classify_pair  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

PROJ = "97a7849a"
WHITE, MAGENTA, GREEN, GREY, BLACK = (255, 255, 255), (255, 0, 220), (60, 230, 60), (170, 170, 170), (0, 0, 0)
SPAN_S, W_OUT, OUT_FPS = 15.0, 480, 10.0


def _arrow(im, origin, heading, length, col, thick):
    rad = math.radians(heading)
    tip = (int(origin[0] + math.sin(rad) * length), int(origin[1] - math.cos(rad) * length))
    cv2.arrowedLine(im, origin, tip, BLACK, thick + 3, tipLength=0.25)
    cv2.arrowedLine(im, origin, tip, col, thick, tipLength=0.25)


def main() -> int:
    ledger = json.loads(Path("runs/heading_review_2026-09-11.json").read_text())
    for arg in sys.argv[1:]:
        cam, variant, card = arg.split(":")
        cam = int(cam)
        con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
        vpath, chash, fps = con.execute(
            "SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
        legs = dict(con.execute(
            "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,)))
        con.close()
        fps = float(fps)
        lg = next(k for k, v in legs.items() if v == card)
        entry = next(r for r in ledger if r["cam"] == cam and r["leg_id"] == lg)
        geom = leg_geometry_for_camera(PROJ, cam)
        gates = build_gates(
            {l: g["mouth"] for l, g in geom.items() if g.get("mouth")},
            list_paths_for_camera(PROJ, cam),
            {l: g.get("heading") for l, g in geom.items()},
            leg_gates={l: g["gate"] for l, g in geom.items() if g.get("gate")})
        p1, p2, _i = gates[lg]
        mid = (int((p1[0] + p2[0]) / 2), int((p1[1] + p2[1]) / 2))

        rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
        rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
        # journeys: which tracks entered over this leg, and when
        entries = []
        origin_of = {}
        _t, starts = np.unique(rows[:, 0], return_index=True)
        for a, b in zip(starts, list(starts[1:]) + [len(rows)]):
            trk = rows[a:b]
            if len(trk) < 5:
                continue
            pl = [(float(r[1]), float(r[2]) - float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
            pr = [(float(r[1]), float(r[2]) + float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
            o, _d, fo, *_rest = classify_pair(pl, pr, gates, fps)
            if o is not None:
                origin_of[int(trk[0, 0])] = o
                if o == lg and fo is not None:
                    entries.append(fo)
        entries = np.sort(np.asarray(entries))
        span = SPAN_S * fps
        best_f, best_n = None, -1
        for f in entries:
            n = int(np.searchsorted(entries, f + span) - np.searchsorted(entries, f))
            if n > best_n:
                best_n, best_f = n, f
        if best_f is None:
            print(f"cam{cam} {card}: no entries")
            continue
        f_lo = int(best_f - 2 * fps)
        f_hi = int(f_lo + span + 2 * fps)
        print(f"cam{cam} {card}: {best_n} entries in the span f{f_lo}-{f_hi}")
        byframe = {}
        sel = rows[(rows[:, 1] >= f_lo) & (rows[:, 1] < f_hi)]
        for r in sel:
            byframe.setdefault(int(r[1]), []).append(r)

        cap = cv2.VideoCapture(vpath)
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        step = max(1, int(round(fps / OUT_FPS)))
        vw = None
        out = Path(f"screenshots/heading_cam{cam}_{card}.webm")
        for fno in range(f_lo, f_hi):
            ok, fr = cap.read()
            if not ok:
                break
            if (fno - f_lo) % step:
                continue
            for l, (q1, q2, _n) in gates.items():
                cv2.line(fr, (int(q1[0]), int(q1[1])), (int(q2[0]), int(q2[1])), BLACK, 5)
                cv2.line(fr, (int(q1[0]), int(q1[1])), (int(q2[0]), int(q2[1])),
                         MAGENTA if l == lg else (160, 60, 140), 2)
            for r in byframe.get(fno, []):
                x1, x2 = int(r[2] - r[4] / 2), int(r[2] + r[4] / 2)
                y1, y2 = int(r[3] - r[5] / 2), int(r[3] + r[5] / 2)
                col = GREEN if origin_of.get(int(r[0])) == lg else GREY
                cv2.rectangle(fr, (x1, y1), (x2, y2), BLACK, 3)
                cv2.rectangle(fr, (x1, y1), (x2, y2), col, 1)
            _arrow(fr, mid, entry["perpendicular"], 46, MAGENTA, 2)
            if entry["stored"] is not None:
                _arrow(fr, mid, entry["stored"], 62, WHITE, 2)
            if entry["through"] is not None:
                _arrow(fr, mid, entry["through"], 78, GREEN, 2)
            cv2.rectangle(fr, (0, 0), (fr.shape[1], 44), BLACK, -1)
            th = entry["through"]
            cap_txt = (f"cam{cam} leg {card}   white=stored {entry['stored']:.0f}  "
                       f"magenta=perpendicular {entry['perpendicular']:.0f}  "
                       f"green=through {'-' if th is None else f'{th:.0f}'}")
            cv2.putText(fr, cap_txt, (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            cv2.putText(fr, "green boxes = tracks that entered over this leg   f%d" % fno,
                        (8, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.45, GREY, 1)
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            if vw is None:
                vw = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"VP80"), fps / step,
                                     (im.shape[1], im.shape[0]))
            vw.write(im)
        cap.release()
        if vw:
            vw.release()
            print(f"   -> {out} ({out.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
