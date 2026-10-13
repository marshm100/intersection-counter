"""Arm mm, after the step 3 verdict (2026-10-13): what separates a partial
track's unseen entry line where two lane maps coincide (cam2's far corner:
EB right vs SB thru) and what flipped cam5 07:00's NB thru counts. Dev only.

  A. MAP: a still of the window with the gate lines, the clean (full) tracks of
     the movements into DEST (one colour per entry leg) and the first point of
     every exit_only count into DEST, coloured by the control's origin, ringed
     when the resolver (apply=False) changes it.
     -> screenshots/mm/cam{C}_{W}_into{DEST}.png
     A negative DEST (-ORIGIN) draws the mirror: clean tracks out of ORIGIN by
     exit leg and the LAST point of every entry_only count from ORIGIN.
     -> screenshots/mm/cam{C}_{W}_from{ORIGIN}.png
  B. LABELS: every counted partial event on the window's dev clip whose track a
     label owns, with truth, the control's legs, the resolver's legs, evidence,
     fits, ray leg and the ray's angle to the line it hits.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_mm_corner.py CAM WINDOW DEST_LEG [STEM]
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.entry_gates import extend_gates, _seg_cross  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from backend.services.mouth_from_motion import (_load, build_lane_maps, decide,  # noqa: E402
                                                tracks_from_rows)
from backend.services.two_pass import _pinned_gates  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402
from v2_score_dev import CORRIDOR, SITES, leg_dir_for  # noqa: E402

OUT = Path("screenshots/mm")
PALETTE = [(0, 200, 255), (255, 120, 0), (0, 255, 0), (255, 0, 255), (0, 0, 255), (255, 255, 0)]


def ray_angle(pt, vel, gates, leg, entering=True):
    """Angle (deg) between the motion and the line `leg` where the ray meets
    it; 90 = head-on, 0 = parallel."""
    if leg is None or leg not in gates:
        return None
    p1, p2, _ = gates[leg]
    lx, ly = p2[0] - p1[0], p2[1] - p1[1]
    n = math.hypot(*vel) * math.hypot(lx, ly)
    if n < 1e-9:
        return None
    return round(math.degrees(math.asin(min(1.0, abs(vel[0] * ly - vel[1] * lx) / n))), 1)


def main() -> int:
    cam, w, dest = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
    mirror = dest < 0
    dest = abs(dest)
    stem = sys.argv[4] if len(sys.argv) > 4 else "dt2c"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    v = con.execute("SELECT video_id, path, content_hash, fps, width, height FROM videos "
                    "WHERE camera_id=?", (cam,)).fetchone()
    fps = float(v["fps"])
    ld = leg_dir_for(CORRIDOR, cam, SITES[CORRIDOR])
    db, rows = locate(stem, {}, cam, w, v["content_hash"])
    gates, _ = _pinned_gates(PROJ, cam, rows)
    legs = [dict(r) for r in con.execute("SELECT * FROM legs WHERE camera_id=?", (cam,))]
    d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    evs = _load(d, cam)
    d.close()
    tracks = tracks_from_rows(rows, fps, tids={e["tid"] for e in evs})
    clean = {e["tid"]: (e["o"], e["d"], e["mv"]) for e in evs
             if e["tag"] == "full" and e["o"] is not None and e["d"] is not None}
    lm = build_lane_maps(tracks, clean, gates)
    counted_origin = {e["tid"]: e["o"] for e in evs if e["o"] is not None}
    ids = np.array(sorted(t for t in counted_origin if t in tracks), dtype=int)
    counted_origin["_index"] = (ids, np.array([tracks[t].f[0] for t in ids]),
                                np.array([tracks[t].f[-1] for t in ids]))
    dec = {}
    for e in evs:
        t = tracks.get(e["tid"])
        if t is None or len(t.f) < 2:
            continue
        if e["tag"] == "exit_only" and e["d"] is not None:
            leg, ev, det = decide(t, "entry", e["d"], lm, gates, fps, tracks, counted_origin,
                                  (v["width"], v["height"]))
        elif e["tag"] == "entry_only" and e["o"] is not None:
            leg, ev, det = decide(t, "exit", e["o"], lm, gates, fps)
        else:
            continue
        i = 0 if e["tag"] == "exit_only" else -1
        det["ray_ang"] = ray_angle((t.x[i], t.y[i]), (t.vx[i], t.vy[i]), gates, det.get("ray"))
        dec[e["tid"]] = (leg, ev, det)

    # A. the map
    OUT.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(v["path"])
    f_mid = int(np.median(rows[:, 1]))
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_mid)
    ok, img = cap.read()
    if not ok:
        img = np.zeros((v["height"], v["width"], 3), np.uint8)
    img = (img * 0.55).astype(np.uint8)
    # mirror: "dest" is the known origin, "origins" are the exit legs
    side = (lambda o, d: (d, o)) if mirror else (lambda o, d: (o, d))
    origins = sorted({side(o, dd)[0] for (o, dd, _) in clean.values() if side(o, dd)[1] == dest})
    col = {o: PALETTE[i % len(PALETTE)] for i, o in enumerate(origins)}
    rng = np.random.default_rng(0)
    for o in origins:
        tids = [t for t, (oo, dd, _) in clean.items() if side(oo, dd) == (o, dest) and t in tracks]
        for t in rng.permutation(tids)[:40]:
            tr = tracks[int(t)]
            pts = np.stack([tr.x, tr.y], 1).astype(np.int32)
            cv2.polylines(img, [pts], False, col[o], 1, cv2.LINE_AA)
    for lg, (p1, p2, inw) in gates.items():
        a, b = tuple(int(c) for c in p1), tuple(int(c) for c in p2)
        cv2.line(img, a, b, (255, 255, 255), 2, cv2.LINE_AA)
        m = ((a[0] + b[0]) // 2, (a[1] + b[1]) // 2)
        cv2.arrowedLine(img, m, (int(m[0] + 25 * inw[0]), int(m[1] + 25 * inw[1])), (255, 255, 255), 1)
        cv2.putText(img, f"{lg} {ld.get(lg)}", (m[0] + 4, m[1] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (255, 255, 255), 1, cv2.LINE_AA)
    for e in evs:
        tag, known, unknown, i = (("entry_only", e["o"], e["d"], -1) if mirror
                                  else ("exit_only", e["d"], e["o"], 0))
        if e["tag"] != tag or known != dest or e["tid"] not in tracks:
            continue
        tr = tracks[e["tid"]]
        c = col.get(unknown, (128, 128, 128))
        p = (int(tr.x[i]), int(tr.y[i]))
        cv2.circle(img, p, 3, c, -1, cv2.LINE_AA)
        leg = dec.get(e["tid"], (None,))[0]
        if leg is not None and leg != unknown:
            cv2.circle(img, p, 6, col.get(leg, (128, 128, 128)), 1, cv2.LINE_AA)
    y = 20
    for o in origins:
        txt = (f"from {dest} {ld.get(dest)} out {o} {ld.get(o)}" if mirror
               else f"from {o} {ld.get(o)} into {dest} {ld.get(dest)}")
        cv2.putText(img, txt, (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, col[o], 1, cv2.LINE_AA)
        y += 20
    out = OUT / f"cam{cam}_{w}_{'from' if mirror else 'into'}{dest}.png"
    cv2.imwrite(str(out), img)
    print(f"map -> {out}")

    # B. labelled partials
    clip = next((c for c in list_clips(PROJ) if c["camera_id"] == cam
                 and c["clip_id"].startswith(f"cam{cam}_{w[-4:]}_") and not c["clip_id"].endswith("_m50")), None)
    if clip is None:
        print("no dev clip for this window")
        return 0
    labels = list_labels(PROJ, clip["clip_id"])
    f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
    byf = je.index_rows(rows, f_lo - je.SEARCH_FRAMES, f_hi + je.SEARCH_FRAMES)
    dups = je.duplicate_labels(labels, fps, byf)
    labels = [lb for lb in labels if lb["label_id"] not in dups]
    ein, eout = je._assign_clicks(labels, rows, byf, fps)
    owner = {}
    for side in (eout, ein):
        for lid, t in side.items():
            owner[t] = lid
    lab = {lb["label_id"]: lb for lb in labels}
    tally = Counter()
    print(f"\n{clip['clip_id']}: counted partial events owned by a label")
    print("  tid    tag        truth      ctrl       resolver   evidence  fits / ray(angle)")
    for e in evs:
        if e["tid"] not in owner or e["tid"] not in dec:
            continue
        lb = lab[owner[e["tid"]]]
        truth = (lb["entry_leg_id"], lb["exit_leg_id"])
        if None in truth:
            continue
        leg, ev, det = dec[e["tid"]]
        new = ((leg, e["d"]) if e["tag"] == "exit_only" else (e["o"], leg)) if leg is not None else (e["o"], e["d"])
        ctrl_ok, new_ok = (e["o"], e["d"]) == truth, new == truth
        tally[(ev, ctrl_ok, new_ok)] += 1
        fmt = lambda od: f"{ld.get(od[0])}>{ld.get(od[1])}"  # noqa: E731
        print(f"  t{e['tid']:<6} {e['tag']:10} {fmt(truth):10} {fmt((e['o'], e['d'])):10}"
              f"{'+' if ctrl_ok else '-'} {fmt(new):10}{'+' if new_ok else '-'} {ev:9} "
              f"{det.get('fits')} / {det.get('ray')}({det.get('ray_ang')})")
    print("  tally (evidence, ctrl right, resolver right):")
    for k, n in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"    {k}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
