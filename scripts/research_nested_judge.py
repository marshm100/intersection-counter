"""THE NESTED PARTIAL, judged car by car (2026-10-15, operator: "dive into it").
Arm np1 (research_nested_partial) was a wash: fleet 91.92 -> 91.73, labels +1 dev / -1 held-out.
Here every NESTED candidate on every labelled clip (dev and held-out) - a counted partial whose
track lives inside a counted full track's life, same witnessed line - with np1's geometric clauses
LOOSENED so the near-misses show, judged by the labels (ONE car on both tracks = double count;
TWO labelled cars = a real car np1 would lose), with the measures that might tell them apart:
  iou      median IoU of the two boxes over common frames
  touch    share of common frames the boxes overlap at all
  cont     median share of the PARTIAL's box inside the full one's box
  area     median partial box area / full box area
  lat      median offset of the partial's centre ACROSS the full car's direction of travel, in box widths
  lon      same ALONG the direction of travel (+ = ahead)
  vcos     cosine between the two tracks' displacements over the common frames
  life     partial life / full life;  birth / death gaps in frames
  np1      whether np1's clauses took it
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_nested_judge.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from backend.services.mouth_from_motion import _load  # noqa: E402
from backend.services.track_chains import STITCH_STAT_DIST  # noqa: E402
from eval_journeys import PROJ, locate  # noqa: E402
from research_near_twins import TOUCH_FRAC  # noqa: E402


def features(a: np.ndarray, b: np.ndarray) -> dict | None:
    com, ia, ib = np.intersect1d(a[:, 1], b[:, 1], return_indices=True)
    if len(com) < 5:
        return None
    pa, pb = a[ia], b[ib]
    dist = np.hypot(pa[:, 2] - pb[:, 2], pa[:, 3] - pb[:, 3])
    x1 = np.maximum(pa[:, 2] - pa[:, 4] / 2, pb[:, 2] - pb[:, 4] / 2)
    x2 = np.minimum(pa[:, 2] + pa[:, 4] / 2, pb[:, 2] + pb[:, 4] / 2)
    y1 = np.maximum(pa[:, 3] - pa[:, 5] / 2, pb[:, 3] - pb[:, 5] / 2)
    y2 = np.minimum(pa[:, 3] + pa[:, 5] / 2, pb[:, 3] + pb[:, 5] / 2)
    inter = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    aa, ab = pa[:, 4] * pa[:, 5], pb[:, 4] * pb[:, 5]
    iou = inter / np.maximum(aa + ab - inter, 1e-6)
    # direction of travel of the full car, over the common frames (smoothed by span)
    k = max(1, len(pa) // 4)
    v = np.c_[pa[k:, 2] - pa[:-k, 2], pa[k:, 3] - pa[:-k, 3]] if len(pa) > k else np.zeros((1, 2))
    vm = v.sum(0)
    u = vm / max(np.linalg.norm(vm), 1e-6)
    off = np.c_[pb[:, 2] - pa[:, 2], pb[:, 3] - pa[:, 3]]
    w = np.maximum(pa[:, 4], 1.0)
    lat = np.abs(off @ np.array([-u[1], u[0]])) / w
    lon = (off @ u) / w
    da = pa[-1, 2:4] - pa[0, 2:4]
    db = pb[-1, 2:4] - pb[0, 2:4]
    vcos = float(da @ db / max(np.linalg.norm(da) * np.linalg.norm(db), 1e-6))
    return dict(n=len(com), dist=float(np.median(dist)), iou=float(np.median(iou)),
                touch=float((iou > 0).mean()), cont=float(np.median(inter / np.maximum(ab, 1e-6))),
                area=float(np.median(ab) / max(np.median(aa), 1.0)),
                lat=float(np.median(lat)), lon=float(np.median(lon)), vcos=vcos,
                life=float((b[-1, 1] - b[0, 1]) / max(a[-1, 1] - a[0, 1], 1)),
                birth=int(b[0, 1] - a[0, 1]), death=int(a[-1, 1] - b[-1, 1]),
                w=float(np.median(pa[:, 4])))


def candidates(db: Path, rows: np.ndarray, cam: int):
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    evs = [e for e in _load(c, cam) if e["tid"] is not None and e["tid"] >= 0]
    c.close()
    sel = rows[np.isin(rows[:, 0], [e["tid"] for e in evs])]
    sel = sel[np.lexsort((sel[:, 1], sel[:, 0]))]
    tids, i0 = np.unique(sel[:, 0], return_index=True)
    tr = dict(zip(tids.astype(int), np.split(sel, i0[1:])))
    full = [e for e in evs if e["tag"] == "full" and e["tid"] in tr]
    for p in evs:
        if p["tag"] not in ("entry_only", "exit_only") or p["tid"] not in tr:
            continue
        b = tr[p["tid"]]
        best = None
        for f in full:
            if p["tag"] == "exit_only" and p["d"] != f["d"]:
                continue
            if p["tag"] == "entry_only" and p["o"] != f["o"]:
                continue
            a = tr[f["tid"]]
            if not (a[0, 1] <= b[0, 1] and b[-1, 1] <= a[-1, 1]):
                continue
            m = features(a, b)
            if m is None or m["dist"] > 3 * STITCH_STAT_DIST:
                continue
            if best is None or m["dist"] < best[2]["dist"]:
                best = (p, f, m)
        if best:
            p, f, m = best
            m["np1"] = m["dist"] <= STITCH_STAT_DIST and m["touch"] >= TOUCH_FRAC
            yield p, f, m


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    groups = defaultdict(list)
    for clip in list_clips(PROJ):
        labels = list_labels(PROJ, clip["clip_id"])
        if not labels:
            continue
        cam = clip["camera_id"]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        fps = float(fps)
        db, rows = locate(stem, {}, cam, "study_" + clip["clip_id"].split("_")[1], chash)
        if db is None:
            continue
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        byf = je.index_rows(rows, f_lo - 2, f_hi + 2)
        ein, eout = je._assign_clicks(labels, rows, byf, fps)
        owner = defaultdict(set)
        for side in (eout, ein):
            for lid, t in side.items():
                owner[t].add(lid)
        for p, f, m in candidates(db, rows, cam):
            bp = rows[rows[:, 0] == p["tid"]][:, 1]
            if not (f_lo <= bp.min() <= f_hi):
                continue
            la, lb = owner.get(f["tid"], set()), owner.get(p["tid"], set())
            if lb and not (lb <= la):
                k = "TWO"                          # the partial owns a car the full one does not
            elif la or lb:
                k = "ONE"
            else:
                k = "unl"
            groups[k].append(m)
            print(f"{k:4} {clip['clip_id']:14} full t{f['tid']} {f['o']}->{f['d']}  {p['tag']:10} t{p['tid']} "
                  f"{p['o']}->{p['d']}  np1={'Y' if m['np1'] else '.'} w {m['w']:.0f} iou {m['iou']:.2f} "
                  f"touch {m['touch']:.2f} cont {m['cont']:.2f} area {m['area']:.2f} lat {m['lat']:.2f} "
                  f"lon {m['lon']:+.2f} vcos {m['vcos']:+.2f} life {m['life']:.2f} birth +{m['birth']} "
                  f"death -{m['death']}  labels {sorted(la)}/{sorted(lb)}", flush=True)
    print()
    for k, ms in groups.items():
        med = {x: np.median([m[x] for m in ms]) for x in ("iou", "touch", "cont", "area", "lat", "lon", "vcos", "life")}
        print(f"{k}: n={len(ms)} np1 took {sum(m['np1'] for m in ms)}  " +
              "  ".join(f"{x} {v:.2f}" for x, v in med.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
