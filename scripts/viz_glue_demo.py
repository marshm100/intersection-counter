"""Track Repair Stage-2 demo — glued families on real frames.

For each requested composite: every member fragment in its own color,
dotted bridge lines between consecutive members, per-member gate verdicts,
the union verdict, and whether the family carried counted production
events. The picture answers the operator question: is this ONE interrupted
vehicle re-joined (the intended repair), or a QUEUE of different vehicles
daisy-chained into a phantom journey?

Usage:
  py -X utf8 scripts/viz_glue_demo.py --window study_1600 --comps 674,937
Writes screenshots/gluedemo_cam2_comp<id>.png
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from auto_calibrate_viz import load_video_frame                       # noqa: E402
from backend.database import leg_geometry_for_camera, list_paths_for_camera  # noqa: E402
from backend.services.entry_gates import build_gates, classify        # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir       # noqa: E402
from backend.services.track_cut import CUT_SEG_BASE, ensure_cut_dump  # noqa: E402
from backend.services.two_pass import (                               # noqa: E402
    _camera_parquet, _tracks_from_rows, gate_axes_for,
)

PROJ = "97a7849a"
FPS = 25.0
SEG_COLORS = [(80, 220, 80), (60, 60, 230), (0, 165, 255), (255, 200, 0),
              (200, 80, 220), (60, 200, 200), (255, 120, 120), (30, 120, 255),
              (160, 255, 120)]
COLOR_NAMES = ["GREEN", "RED", "ORANGE", "CYAN", "PURPLE", "TEAL",
               "PINK", "BLUE", "LIME"]


def base_of(seg: float) -> int:
    return (int((seg - CUT_SEG_BASE) // 10) if seg >= CUT_SEG_BASE
            else int(seg))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="study_1600")
    ap.add_argument("--comps", required=True)
    ap.add_argument("--camera", type=int, default=2)
    args = ap.parse_args()
    cam = args.camera

    tdir = tracks_dir(_camera_parquet(PROJ, cam, args.window))
    base_meta = json.loads((tdir / "meta.json").read_text())
    base_rows = load_dump(tdir)
    _v, _t, meta2, glued_rows = ensure_cut_dump(
        PROJ, cam, args.window, "viz", FPS, tdir, base_rows, base_meta)
    fams = meta2["a3_cut"]["glue"]["families"]

    # member fragments live in the cut-only rows: rebuild them via the same
    # transform with glue off (cheap: reuse the glued families to slice)
    from backend.services.track_cut import cut_dump_rows, FALLBACK_KIN
    geom = leg_geometry_for_camera(PROJ, cam)
    mouths = {lid: g["mouth"] for lid, g in geom.items()}
    heads = {lid: g["heading"] for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}
    base_tracks = _tracks_from_rows(base_rows)
    gates = build_gates(mouths, list_paths_for_camera(PROJ, cam), heads,
                        leg_axes=gate_axes_for(mouths, base_tracks.values()),
                        leg_gates=drawn or None)
    npz = Path("runs/v2_week1") / f"tracklets_cam{cam}_{args.window}.npz"
    kin = dict(FALLBACK_KIN)
    if npz.exists():
        try:
            from v2_common import fit_motion_residual, load_table
            kin = fit_motion_residual(load_table(npz))
        except Exception:
            pass
    cut_rows, _ = cut_dump_rows(np.asarray(base_rows), gates, FPS, kin)
    cut_tracks = _tracks_from_rows(cut_rows)
    glued_tracks = _tracks_from_rows(glued_rows)

    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                          uri=True)
    vpath = con.execute("SELECT path FROM videos WHERE camera_id=?",
                        (cam,)).fetchone()[0]

    for comp in args.comps.split(","):
        members = fams[comp]
        union = sorted(glued_tracks[float(comp)])
        uo, ud, *_r, utag = classify(union, gates, FPS)

        mid_f = union[len(union) // 2][0]
        img = load_video_frame(vpath, mid_f / FPS)
        if img is None:
            img = cv2.imread(
                f"data/projects/{PROJ}/calibration_backdrop_cam{cam}.png")
        img = img.copy()
        for _g, (g1, g2) in drawn.items():
            cv2.line(img, (int(g1[0]), int(g1[1])), (int(g2[0]), int(g2[1])),
                     (255, 0, 255), 2, cv2.LINE_AA)

        lines = [f"composite {comp}  cam{cam} {args.window}  |  "
                 f"{len(members)} member fragments glued  |  union verdict: "
                 f"{utag}" + (f" {uo}->{ud}" if utag == "full" else "")]
        prev_end = None
        for k, m in enumerate(members):
            pts = sorted(cut_tracks[float(m)])
            col = SEG_COLORS[k % len(SEG_COLORS)]
            arr = np.array([[int(p[1]), int(p[2])] for p in pts], np.int32)
            cv2.polylines(img, [arr], False, col, 2, cv2.LINE_AA)
            cv2.circle(img, tuple(arr[0]), 4, (0, 230, 230), -1, cv2.LINE_AA)
            cv2.circle(img, tuple(arr[-1]), 5, col, -1, cv2.LINE_AA)
            if prev_end is not None:      # dotted bridge
                p, q = np.array(prev_end, float), arr[0].astype(float)
                n = max(int(np.hypot(*(q - p)) / 8), 1)
                for i in range(0, n + 1, 2):
                    a = p + (q - p) * (i / max(n, 1))
                    cv2.circle(img, (int(a[0]), int(a[1])), 2,
                               (255, 255, 255), -1, cv2.LINE_AA)
            prev_end = tuple(arr[-1])
            o, d, *_sr, tag = classify(pts, gates, FPS)
            btid = base_of(float(m))
            ev = con.execute(
                "SELECT movement, origin_leg_id, destination_leg_id FROM "
                "vehicle_events WHERE camera_id=? AND vehicle_track_id=? "
                "AND COALESCE(rejected,0)=0", (cam, btid)).fetchall()
            evs = ("; ".join(f"counted '{e[0]}' {e[1]}->{e[2]}" for e in ev)
                   or "not counted")
            gap = ""
            if k:
                pf = sorted(cut_tracks[float(members[k - 1])])[-1][0]
                gap = f"  gap {(pts[0][0] - pf) / FPS:.1f}s"
            lines.append(
                f"member {k + 1} ({COLOR_NAMES[k % len(COLOR_NAMES)]}, "
                f"{len(pts)} pts): verdict {tag}"
                + (f" {o}->{d}" if tag == "full" else "")
                + f"  |  base tid {btid}: {evs}{gap}")

        strip = np.zeros((18 * len(lines) + 10, img.shape[1], 3), np.uint8)
        for i, ln in enumerate(lines):
            cv2.putText(strip, ln[:110], (8, 18 * (i + 1)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, (230, 230, 230), 1,
                        cv2.LINE_AA)
        out = f"screenshots/gluedemo_cam{cam}_comp{comp}.png"
        cv2.imwrite(out, np.vstack([img, strip]))
        print(f"wrote {out}  members={len(members)} union={utag} {uo}->{ud}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
