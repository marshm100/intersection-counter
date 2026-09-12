"""Where the vehicles ARE (2026-09-11, the operating rule for line placement).

One still per (project, camera, dump): the frame with a heat overlay of
bottom-centre positions of all tracks (where tracking holds), the
BIRTH points (cyan) and DEATH points (orange) of every track, and the
operator's current gate lines (magenta). The operator draws each line
where the heat is dense and births are behind it.
Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/viz_track_density.py PROJ CAM VARIANT OUT.png
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import leg_geometry_for_camera, list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

MAGENTA, CYAN, ORANGE, BLACK, WHITE = (255, 0, 220), (255, 220, 0), (0, 140, 255), (0, 0, 0), (255, 255, 255)


def main() -> int:
    proj, cam, variant, out = sys.argv[1], int(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash = con.execute("SELECT path, content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
    legs = dict(con.execute("SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?", (cam,)))
    con.close()
    geom = leg_geometry_for_camera(proj, cam)
    gates = build_gates({l: g["mouth"] for l, g in geom.items() if g.get("mouth")}, list_paths_for_camera(proj, cam),
                        {l: g.get("heading") for l, g in geom.items()},
                        leg_gates={l: g["gate"] for l, g in geom.items() if g.get("gate")})
    rows = np.asarray(load_dump(tracks_dir(parquet_path(proj, cam, chash, variant))))
    rows = rows[np.lexsort((rows[:, 1], rows[:, 0]))]
    cap = cv2.VideoCapture(vpath)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); cap.set(cv2.CAP_PROP_POS_FRAMES, int(n * 0.35))
    ok, fr = cap.read(); cap.release()
    H, W = fr.shape[:2]
    heat = np.zeros((H, W), np.float32)
    xs = np.clip(rows[:, 2].astype(int), 0, W - 1); ys = np.clip((rows[:, 3] + rows[:, 5] / 2).astype(int), 0, H - 1)
    np.add.at(heat, (ys, xs), 1.0)
    heat = cv2.GaussianBlur(heat, (0, 0), 6)
    heat = heat / (np.percentile(heat, 99.5) or 1.0)
    heat = np.clip(heat, 0, 1)
    color = cv2.applyColorMap((heat * 255).astype(np.uint8), cv2.COLORMAP_TURBO)
    alpha = (heat * 0.75)[..., None]
    im = (fr * (1 - alpha) + color * alpha).astype(np.uint8)
    _t, starts = np.unique(rows[:, 0], return_index=True)
    ends = list(starts[1:] - 1) + [len(rows) - 1]
    for a, b in zip(starts, ends):
        if b - a + 1 < 5:
            continue
        r0, r1 = rows[a], rows[b]
        cv2.circle(im, (int(r0[2]), int(r0[3] + r0[5] / 2)), 2, CYAN, -1)
        cv2.circle(im, (int(r1[2]), int(r1[3] + r1[5] / 2)), 2, ORANGE, -1)
    for lg, (p1, p2, inw) in gates.items():
        a, b = (int(p1[0]), int(p1[1])), (int(p2[0]), int(p2[1]))
        cv2.line(im, a, b, BLACK, 6); cv2.line(im, a, b, MAGENTA, 3)
        mx, my = (a[0] + b[0]) // 2, (a[1] + b[1]) // 2
        cv2.putText(im, legs.get(lg, str(lg)), (mx - 8, my - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, BLACK, 4)
        cv2.putText(im, legs.get(lg, str(lg)), (mx - 8, my - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, MAGENTA, 2)
    cv2.rectangle(im, (0, 0), (W, 26), BLACK, -1)
    cv2.putText(im, f"{proj} cam{cam} {variant}: heat = where tracking holds, cyan = births, orange = deaths, magenta = your lines",
                (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, WHITE, 1)
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), im)
    print(f"-> {out}  tracks {len(starts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
