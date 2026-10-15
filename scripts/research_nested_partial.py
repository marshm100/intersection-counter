"""THE NESTED PARTIAL, offline (2026-10-15, operator: "fix double counting for all cameras").
Candidate rule, one for every camera: a counted PARTIAL journey (entry_only / exit_only) whose
track lives entirely inside the life of a counted FULL journey's track, with boxes touching in
>= TOUCH_FRAC of their common frames, centres within STITCH_STAT_DIST, and the same witnessed
line on its witnessed side (an exit_only's exit = the full one's exit; an entry_only's entry =
the full one's entry), is the full car's second track - a real car riding beside a fully seen
car through the same line at the same time would have been seen crossing the other line too.
The partial event is rejected. Labelled clips (research_double_det): 5 of 7 one-car pairs have
this shape, 2 of 20 two-car pairs.
Applies the rule to COPIES of an arm's working DBs (12 windows), scores them, prints the fleet.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_nested_partial.py [STEM] [OUT]
then:  scripts/eval_journeys.py STEM OUT  (car by car)
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services.mouth_from_motion import _load  # noqa: E402
from eval_journeys import BASE, PROJ, locate  # noqa: E402
from research_near_twins import TOUCH_FRAC, WINDOWS  # noqa: E402
from backend.services.track_chains import STITCH_STAT_DIST  # noqa: E402
from v2_score_dev import CORRIDOR, NORM, SITES, leg_dir_for  # noqa: E402


def nested_partials(db: Path, rows: np.ndarray, cam: int) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    evs = [e for e in _load(c, cam) if e["tid"] is not None and e["tid"] >= 0]
    c.close()
    sel = rows[np.isin(rows[:, 0], [e["tid"] for e in evs])]
    sel = sel[np.lexsort((sel[:, 1], sel[:, 0]))]
    tids, i0 = np.unique(sel[:, 0], return_index=True)
    tr = dict(zip(tids.astype(int), np.split(sel, i0[1:])))
    full = [e for e in evs if e["tag"] == "full" and e["tid"] in tr]
    out, taken = [], set()
    for p in evs:
        if p["tag"] not in ("entry_only", "exit_only") or p["tid"] not in tr:
            continue
        b = tr[p["tid"]]
        for f in full:
            if f["tid"] in taken:
                continue
            if p["tag"] == "exit_only" and p["d"] != f["d"]:
                continue
            if p["tag"] == "entry_only" and p["o"] != f["o"]:
                continue
            a = tr[f["tid"]]
            if not (a[0, 1] <= b[0, 1] and b[-1, 1] <= a[-1, 1]):
                continue
            com, ia, ib = np.intersect1d(a[:, 1], b[:, 1], return_indices=True)
            if len(com) < 5:
                continue
            pa, pb = a[ia], b[ib]
            if np.median(np.hypot(pa[:, 2] - pb[:, 2], pa[:, 3] - pb[:, 3])) > STITCH_STAT_DIST:
                continue
            x1 = np.maximum(pa[:, 2] - pa[:, 4] / 2, pb[:, 2] - pb[:, 4] / 2)
            x2 = np.minimum(pa[:, 2] + pa[:, 4] / 2, pb[:, 2] + pb[:, 4] / 2)
            y1 = np.maximum(pa[:, 3] - pa[:, 5] / 2, pb[:, 3] - pb[:, 5] / 2)
            y2 = np.minimum(pa[:, 3] + pa[:, 5] / 2, pb[:, 3] + pb[:, 5] / 2)
            if ((x2 > x1) & (y2 > y1)).mean() < TOUCH_FRAC:
                continue
            out.append({"drop": p, "keep": f})
            taken.add(p["tid"])
            break
    return out


def score(db: Path) -> tuple[float, float, dict]:
    subprocess.run([sys.executable, "-X", "utf8", "scripts/v2_score_dev.py", str(db)], capture_output=True)
    d = json.loads(Path(f"runs/v2_week1/score_{db.stem}.json").read_text())
    return d["v2"]["pct"], d["v2_approach"]["pct"], {k: (v[0], v[1]) for k, v in d["totals"].items()}


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    arm = sys.argv[2] if len(sys.argv) > 2 else "np1"
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    res = []
    for cam, w in WINDOWS:
        chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
        src, rows = locate(stem, {}, cam, w, chash)
        dst = BASE / f"{arm}_cam{cam}_{w}.db"
        shutil.copy2(src, dst)
        hits = nested_partials(dst, rows, cam)
        with sqlite3.connect(dst) as c:
            c.executemany("UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
                          [(int(h["drop"]["eid"]),) for h in hits])
        b, a = score(src), score(dst)
        ld = leg_dir_for(CORRIDOR, cam, SITES[CORRIDOR])
        cells = Counter(f"{ld.get(h['drop']['o'])} {NORM.get(h['drop']['mv'], h['drop']['mv'])}" for h in hits)
        moved = sorted(((k, b[2][k][0], b[2][k][1], a[2][k][1]) for k in a[2] if a[2][k][1] != b[2][k][1]),
                       key=lambda r: -abs(r[3] - r[2]))[:6]
        res.append((cam, w, b, a))
        print(f"cam{cam} {w}: rejected {len(hits):4}  movement {b[0]} -> {a[0]}  approach {b[1]} -> {a[1]}  "
              f"by cell {cells.most_common(4)}\n      (cell, Mio, {stem}, {arm}): {moved}", flush=True)
    n = len(res)
    print(f"\nFLEET movement {sum(r[2][0] for r in res) / n:.2f} -> {sum(r[3][0] for r in res) / n:.2f}   "
          f"approach {sum(r[2][1] for r in res) / n:.2f} -> {sum(r[3][1] for r in res) / n:.2f}")
    for cam in sorted({r[0] for r in res}):
        rr = [r for r in res if r[0] == cam]
        print(f"  cam{cam} mean {sum(r[2][0] for r in rr) / len(rr):.2f} -> {sum(r[3][0] for r in rr) / len(rr):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
