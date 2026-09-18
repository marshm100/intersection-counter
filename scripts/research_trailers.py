"""Trailers: two tracker ids on one rig? (Phase C, 2026-09-13, plan
sure-plan-it-out-toasty-snowflake.md; hand-off reel clip 2, operator: "the
handoff from tailer to towing vehicle, same vehicle technically").

An ATTACHED PAIR = two dump tracks, one behind the other along their shared
direction of travel (headings within 20 deg, both moving >= 1 px/frame, the
sideways offset under half a box), boxes touching (gap along the direction
between -0.3 and +0.1 box sizes), for >= 1 s of shared frames, with the offset
between them STEADY (std < 0.1 box sizes, along and across) WHILE the pair's
speed changes >= 30% or its heading turns >= 15 deg - cars following in a lane
change their gap with speed; a rig does not. (The first instrument, side by
side with a steady offset alone, caught platoons: research_tracker_classes.py.)
Box size = the mean of the two boxes' extents along the direction.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_trailers.py PROJ CAM VARIANT
Writes runs/v2_week1/trailers_<proj>_<cam>_<variant>.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402

MIN_SPEED = 1.0
HEAD_TOL = np.deg2rad(20.0)
GAP_LO, GAP_HI = -0.3, 0.1
PERP_MAX = 0.5
STEADY = 0.1
SPEED_CHANGE = 1.3
TURN = np.deg2rad(15.0)


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    rows = np.array(load_dump(tracks_dir(parquet_path(proj, cam, chash, variant))), dtype=np.float64, copy=True)
    # per-row velocity: centre displacement over +-2 rows of the same track, per frame
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows = rows[order]
    vx = np.zeros(len(rows)); vy = np.zeros(len(rows))
    ut, st_ = np.unique(rows[:, 0], return_index=True); en_ = np.append(st_[1:], len(rows))
    for a, b in zip(st_, en_):
        if b - a < 3:
            continue
        idx = np.arange(a, b)
        lo = np.clip(idx - 2, a, b - 1); hi = np.clip(idx + 2, a, b - 1)
        dt = np.maximum(rows[hi, 1] - rows[lo, 1], 1)
        vx[a:b] = (rows[hi, 2] - rows[lo, 2]) / dt
        vy[a:b] = (rows[hi, 3] - rows[lo, 3]) / dt
    byf = np.argsort(rows[:, 1], kind="stable")
    fr = rows[byf, 1].astype(np.int64)
    uf, s_ = np.unique(fr, return_index=True); e_ = np.append(s_[1:], len(fr))

    obs = defaultdict(list)     # (lead, tail) -> [(frame, along/size, perp/size, speed, heading)]
    for f, a, b in zip(uf, s_, e_):
        if b - a < 2:
            continue
        I = byf[a:b]
        R = rows[I]; V = np.stack([vx[I], vy[I]], axis=1)
        sp = np.hypot(V[:, 0], V[:, 1])
        mv = sp >= MIN_SPEED
        if mv.sum() < 2:
            continue
        I, R, V, sp = I[mv], R[mv], V[mv], sp[mv]
        cx, cy, w, h = R[:, 2], R[:, 3], R[:, 4], R[:, 5]
        dist = np.hypot(cx[:, None] - cx[None, :], cy[:, None] - cy[None, :])
        reach = 2.0 * np.maximum(w[:, None], w[None, :])
        ii, jj = np.nonzero(np.triu(dist < reach, 1))
        for i, j in zip(ii, jj):
            hi_, hj = np.arctan2(V[i, 1], V[i, 0]), np.arctan2(V[j, 1], V[j, 0])
            dh = abs((hi_ - hj + np.pi) % (2 * np.pi) - np.pi)
            if dh > HEAD_TOL:
                continue
            u = (V[i] + V[j]); u = u / max(np.hypot(*u), 1e-9)
            d = np.array([cx[j] - cx[i], cy[j] - cy[i]])
            along = float(d @ u); perp = float(u[0] * d[1] - u[1] * d[0])
            ext_i = w[i] / 2 * abs(u[0]) + h[i] / 2 * abs(u[1])
            ext_j = w[j] / 2 * abs(u[0]) + h[j] / 2 * abs(u[1])
            size = ext_i + ext_j
            gap = (abs(along) - size) / size
            if not (GAP_LO <= gap <= GAP_HI) or abs(perp) > PERP_MAX * size:
                continue
            # lead = the one further along the direction; the offset is lead minus tail
            lead, tail, sgn = (j, i, 1.0) if along > 0 else (i, j, -1.0)
            key = (int(R[lead, 0]), int(R[tail, 0]))
            obs[key].append((int(f), abs(along) / size, sgn * perp / size,
                             float((sp[i] + sp[j]) / 2), float(np.arctan2(u[1], u[0])),
                             float(cx[lead]), float(cy[lead]), float(max(w[i], w[j]))))
    pairs = []
    n_long = 0
    for (lead, tail), ob in obs.items():
        if len(ob) < fps:
            continue
        n_long += 1
        ob = np.asarray(ob)
        al, pe, spd, hd = ob[:, 1], ob[:, 2], ob[:, 3], np.unwrap(ob[:, 4])
        steady = al.std() < STEADY and pe.std() < STEADY
        k = max(3, len(ob) // 5)
        s_lo, s_hi = np.percentile(spd, 10), np.percentile(spd, 90)
        chg = s_hi / max(s_lo, 1e-6)
        turn = abs(np.median(hd[-k:]) - np.median(hd[:k]))
        if steady and (chg >= SPEED_CHANGE or turn >= TURN):
            pairs.append({"lead": lead, "tail": tail, "f0": int(ob[0, 0]), "f1": int(ob[-1, 0]),
                          "frames": len(ob), "along_std": round(float(al.std()), 3), "perp_std": round(float(pe.std()), 3),
                          "speed_change": round(float(chg), 2), "turn_deg": round(float(np.rad2deg(turn)), 1),
                          "x": float(np.median(ob[:, 5])), "y": float(np.median(ob[:, 6])), "w": float(np.median(ob[:, 7]))})
    n_steady = sum(1 for p in obs.values() if len(p) >= fps and np.std([o[1] for o in p]) < STEADY
                   and np.std([o[2] for o in p]) < STEADY)
    print(f"{proj} cam{cam} {variant}: {len(ut)} tracks; touching nose-to-tail pairs >= 1 s: {n_long}; "
          f"steady offset: {n_steady}; steady THROUGH a speed change >= 30% or a turn >= 15 deg: {len(pairs)}")
    if pairs:
        print(f"  attached pairs: duration median {np.median([p['frames'] for p in pairs]) / fps:.1f} s; "
              f"box width median {np.median([p['w'] for p in pairs]):.0f} px; speed change median "
              f"{np.median([p['speed_change'] for p in pairs]):.2f}x; turn median {np.median([p['turn_deg'] for p in pairs]):.0f} deg")
    out = Path(f"runs/v2_week1/trailers_{proj}_{cam}_{variant}.json")
    out.write_text(json.dumps(pairs))
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
