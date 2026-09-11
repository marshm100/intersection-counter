"""G-TH-1 step 1: appearance separability on the 17 ruled clips.

For each ruled track: decode its frames, crop the box, embed with the
production ReID model (osnet_x0_25 via boxmot, the same call the
tracker makes), then find the largest APPEARANCE BREAK along the
track: the cosine distance between the mean embedding of the K frames
before a point and the K after it, maximised over the track (K = 1 s).
Prints one row per clip with the break, where it sits (seconds from
birth, and relative to the machine's entry/exit frames), and a
separability summary: the best single threshold and how many thefts /
clean tracks it puts on each side.
Read-only. Usage:  .venv\\Scripts\\python.exe -X utf8 scripts/theft_appearance.py
"""
from __future__ import annotations

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
RULED = [
    (1, "study_0700", 2,      "clean", "reel1 through, corner spawn"),
    (1, "study_0700", 4829,   "clean", "reel1 through, glare"),
    (1, "study_0700", 9205,   "clean?", "reel1 through, 18-wheeler occlusion (identity doubt)"),
    (1, "study_0700", 14948,  "clean", "reel1 through, box-truck occlusion"),
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
K_S = 1.0


def embed_track(model, cap, trk):
    """(frames, embs) for one track: one crop per row, decoded in order."""
    f0 = int(trk[0, 1])
    cap.set(cv2.CAP_PROP_POS_FRAMES, f0)
    cur = f0
    want = {int(r[1]): r for r in trk}
    frames, embs = [], []
    last = int(trk[-1, 1])
    while cur <= last:
        ok, img = cap.read()
        if not ok:
            break
        r = want.get(cur)
        if r is not None:
            x1, y1 = max(0.0, r[2] - r[4] / 2), max(0.0, r[3] - r[5] / 2)
            x2, y2 = min(img.shape[1] - 1.0, r[2] + r[4] / 2), min(img.shape[0] - 1.0, r[3] + r[5] / 2)
            if x2 - x1 >= 4 and y2 - y1 >= 4:
                f = np.asarray(model.get_features(
                    np.array([[x1, y1, x2, y2]], dtype=np.float32), img), dtype=np.float32)[0]
                n = np.linalg.norm(f) or 1.0
                frames.append(cur)
                embs.append(f / n)
        cur += 1
    return np.asarray(frames), np.asarray(embs)


def largest_break(frames, embs, k):
    """max over i of cosine distance between mean(embs[i-k:i]) and mean(embs[i:i+k])."""
    best, at = 0.0, None
    n = len(embs)
    for i in range(k, n - k + 1):
        a = embs[i - k:i].mean(axis=0)
        b = embs[i:i + k].mean(axis=0)
        na, nb = np.linalg.norm(a) or 1.0, np.linalg.norm(b) or 1.0
        d = 1.0 - float(a @ b) / (na * nb)
        if d > best:
            best, at = d, frames[i]
    return best, at


def best_split(embs, min_seg=3):
    """max over split points of cosine distance between mean(before) and
    mean(after), each side at least min_seg frames — sees a break at the
    very end of a track, which the symmetric window cannot."""
    n = len(embs)
    best, at = 0.0, None
    if n < 2 * min_seg:
        return best, at
    cs = np.cumsum(embs, axis=0)
    for i in range(min_seg, n - min_seg + 1):
        a = cs[i - 1] / i
        b = (cs[-1] - cs[i - 1]) / (n - i)
        na, nb = np.linalg.norm(a) or 1.0, np.linalg.norm(b) or 1.0
        d = 1.0 - float(a @ b) / (na * nb)
        if d > best:
            best, at = d, i
    return best, at


def main() -> int:
    from boxmot.reid.core.reid import ReID
    model = ReID(weights="osnet_x0_25_msmt17.pt", device="cuda:0").model
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    cache = {}
    results = []
    print(f"{'cam':>3} {'tid':>7} {'class':6} {'rows':>5} {'box':>5} {'break':>6} {'at +s':>6} {'split':>6} {'at +s':>6} {'entry':>6} {'exit':>6}  ruling")
    for cam, variant, tid, cls, ruling in RULED:
        key = (cam, variant)
        if key not in cache:
            vpath, chash, fps = con.execute(
                "SELECT path, content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
            rows = np.asarray(load_dump(tracks_dir(parquet_path(PROJ, cam, chash, variant))))
            geom = leg_geometry_for_camera(PROJ, cam)
            gates = build_gates(
                {lg: g["mouth"] for lg, g in geom.items() if g.get("mouth")},
                list_paths_for_camera(PROJ, cam),
                {lg: g.get("heading") for lg, g in geom.items()},
                leg_gates={lg: g["gate"] for lg, g in geom.items() if g.get("gate")})
            cache[key] = (rows, float(fps), gates, cv2.VideoCapture(vpath))
        rows, fps, gates, cap = cache[key]
        trk = rows[rows[:, 0] == float(tid)]
        trk = trk[np.argsort(trk[:, 1])]
        if len(trk) < 3:
            print(f"{cam:>3} {tid:>7} {cls:6} no track")
            continue
        frames, embs = embed_track(model, cap, trk)
        k = max(2, int(round(K_S * fps)))
        brk, at = largest_break(frames, embs, k)
        pl = [(float(r[1]), float(r[2]) - float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
        pr = [(float(r[1]), float(r[2]) + float(r[4]) / 2, float(r[3]) + float(r[5]) / 2) for r in trk]
        _o, _d, fo, fd, *_rest = classify_pair(pl, pr, gates, fps)
        at_s = (at - trk[0, 1]) / fps if at is not None else float("nan")
        fe = f"{(fo - trk[0, 1]) / fps:+.1f}" if fo is not None else "-"
        fx = f"{(fd - trk[0, 1]) / fps:+.1f}" if fd is not None else "-"
        sp, spi = best_split(embs)
        sp_s = (frames[spi] - trk[0, 1]) / fps if spi is not None else float("nan")
        box = float(np.median(trk[:, 4] * trk[:, 5]) ** 0.5)
        results.append((cls, brk, sp, tid))
        print(f"{cam:>3} {tid:>7} {cls:6} {len(trk):>5} {box:>5.0f} {brk:>6.3f} {at_s:>+6.1f} {sp:>6.3f} {sp_s:>+6.1f} {fe:>6} {fx:>6}  {ruling}")
    for name, idx in (("break (1 s windows)", 1), ("split (any point)", 2)):
        print(f"\n== {name} ==")
        thefts = sorted(r[idx] for r in results if r[0] == "THEFT")
        clean = sorted(r[idx] for r in results if r[0].startswith("clean"))
        _summ(thefts, clean)
    return 0


def _summ(thefts, clean):
    print(f"\nthefts: min {thefts[0]:.3f}  median {np.median(thefts):.3f}  max {thefts[-1]:.3f}")
    print(f"clean : min {clean[0]:.3f}  median {np.median(clean):.3f}  max {clean[-1]:.3f}")
    best = None
    for thr in sorted(set(thefts + clean)):
        tp = sum(b >= thr for b in thefts)
        fp = sum(b >= thr for b in clean)
        score = (tp, -fp)
        if best is None or score > best[0]:
            best = (score, thr, tp, fp)
    _s, thr, tp, fp = best
    print(f"best single threshold {thr:.3f}: thefts above {tp}/{len(thefts)}, clean above {fp}/{len(clean)}")
    print("G-TH-1 step 1:", "PASS" if (tp == len(thefts) and fp <= 1) else "MISS")


if __name__ == "__main__":
    raise SystemExit(main())
