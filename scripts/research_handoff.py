"""THE OVERLAPPING HANDOFF, offline (2026-10-15, double-counting dive). 10 of the 19 labelled doubles
under the default are one car handed from track A to track B a few frames EARLY: B is born in A's
last frames, the two boxes ride together for those frames, A dies and B carries on - the linker
joins only pieces that do not overlap, so both are counted. Candidate rule, one for every camera:
a counted track B whose birth falls within HANDOFF_FRAMES before the death of a counted track A,
that outlives A, with the boxes overlapping (IoU > 0) in >= TOUCH of their common frames and
centres within CENTRE_W box widths, and compatible witnessed lines (B's entry unseen or = A's
entry; A's exit unseen or = B's exit) - is A's continuation. The two become ONE count: A's origin
(or B's if A's is unseen), B's destination; B's event rejected, A's rewritten.
Applies to COPIES of an arm's working DBs (12 windows), scores them, prints the fleet.
Also required: the two tracks head the same way (cosine >= SAME_WAY, ho2: stops merging two cars
passing head-on), and the merged count is kept on the LONGER track (ho2). --established (ho3): the
dying track A must have lived longer than B - a long track handing over to a short tail, not a blip
touching a following car (ho2's two lost cars on cam3). ho3: labels 448 -> 454 dev (6 won / 0 lost,
p 0.031), held-out 272 -> 272; fleet 91.92 -> 92.32; cam3 -1.5 and cam5 -1.33 (cells already under Mio).
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_handoff.py [STEM] [OUT] [--established]
then:  scripts/eval_journeys.py STEM OUT  (car by car, dev and --heldout)
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services.mouth_from_motion import _load  # noqa: E402
from eval_journeys import BASE, PROJ, locate  # noqa: E402
from research_near_twins import WINDOWS  # noqa: E402
from research_nested_partial import score  # noqa: E402
from research_phantoms_mm1 import touch  # noqa: E402
from v2_score_dev import CORRIDOR, NORM, SITES, leg_dir_for  # noqa: E402

HANDOFF_FRAMES = 20
TOUCH = 0.5
CENTRE_W = 1.2
ESTABLISHED = "--established" in sys.argv
SAME_WAY = 0.5        # cosine between the two tracks' headings over their last / first frames
SEES_ENTRY = ("full", "entry_only")
SEES_EXIT = ("full", "exit_only")


def _heading(r: np.ndarray, tail: bool) -> np.ndarray:
    seg = r[-HANDOFF_FRAMES:] if tail else r[:HANDOFF_FRAMES]
    if len(seg) < 2:
        seg = r
    return seg[-1, 2:4] - seg[0, 2:4]


def heading_cos(a: np.ndarray, b: np.ndarray) -> float:
    """A's heading over its last frames against B's over its first (whole tracks if too short)."""
    ha, hb = _heading(a, True), _heading(b, False)
    return float(ha @ hb / max(np.linalg.norm(ha) * np.linalg.norm(hb), 1e-6))


def handoffs(db: Path, rows: np.ndarray, cam: int) -> list[dict]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    evs = {e["tid"]: e for e in _load(c, cam) if e["tid"] is not None and e["tid"] >= 0}
    c.close()
    sel = rows[np.isin(rows[:, 0], list(evs))]
    sel = sel[np.lexsort((sel[:, 1], sel[:, 0]))]
    tids, i0 = np.unique(sel[:, 0], return_index=True)
    tr = dict(zip(tids.astype(int), np.split(sel, i0[1:])))
    ids = np.array(sorted(tr), dtype=int)
    born = np.array([tr[t][0, 1] for t in ids])
    died = np.array([tr[t][-1, 1] for t in ids])
    out, used = [], set()
    for ia in np.argsort(died):
        A = int(ids[ia])
        if A in used:
            continue
        ea, a = evs[A], tr[A]
        cand = np.where((born >= died[ia] - HANDOFF_FRAMES) & (born <= died[ia]) & (died > died[ia]))[0]
        best = None
        for ib in cand:
            B = int(ids[ib])
            if B == A or B in used:
                continue
            eb = evs[B]
            if eb["tag"] in SEES_ENTRY and ea["tag"] in SEES_ENTRY and eb["o"] != ea["o"]:
                continue
            if eb["tag"] in SEES_ENTRY and ea["tag"] in SEES_ENTRY:
                continue                       # B saw its own entry: a car of its own
            if ea["tag"] in SEES_EXIT and eb["tag"] in SEES_EXIT and ea["d"] != eb["d"]:
                continue
            t, dist, n = touch(a, tr[B])
            if n < 2 or t < TOUCH or dist > CENTRE_W:
                continue
            if ESTABLISHED and len(a) <= len(tr[B]):
                continue                       # the dying track must be the established one
            if heading_cos(a, tr[B]) < SAME_WAY:
                continue                       # two cars passing each other
            if best is None or dist < best[1]:
                best = (B, dist)
        if best:
            B = best[0]
            eb = evs[B]
            o = ea["o"] if ea["tag"] in SEES_ENTRY or eb["o"] is None else eb["o"]
            d = eb["d"] if eb["tag"] in SEES_EXIT or ea["d"] is None else ea["d"]
            keep, drop = (ea, eb) if len(a) >= len(tr[B]) else (eb, ea)
            out.append({"A": ea, "B": eb, "keep": keep, "drop": drop, "o": o, "d": d})
            used |= {A, B}
    return out


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    arm = sys.argv[2] if len(sys.argv) > 2 else "ho1"
    from backend.services.mouth_from_motion import _movement  # noqa: F401
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    res = []
    for cam, w in WINDOWS:
        chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
        src, rows = locate(stem, {}, cam, w, chash)
        dst = BASE / f"{arm}_cam{cam}_{w}.db"
        shutil.copy2(src, dst)
        hits = handoffs(dst, rows, cam)
        with sqlite3.connect(dst) as c:
            for h in hits:
                k = h["keep"]
                c.execute("UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?", (int(h["drop"]["eid"]),))
                if (h["o"], h["d"]) != (k["o"], k["d"]):
                    mv = next((e["mv"] for e in (h["A"], h["B"]) if (e["o"], e["d"]) == (h["o"], h["d"])), None)
                    if mv is None:
                        row = c.execute("SELECT movement FROM vehicle_events WHERE camera_id=? AND origin_leg_id=? "
                                        "AND destination_leg_id=? AND COALESCE(rejected,0)=0 LIMIT 1",
                                        (cam, h["o"], h["d"])).fetchone()
                        mv = row[0] if row else k["mv"]
                    c.execute("UPDATE vehicle_events SET origin_leg_id=?, destination_leg_id=?, movement=? "
                              "WHERE event_id=?", (h["o"], h["d"], mv, int(k["eid"])))
        b, a = score(src), score(dst)
        ld = leg_dir_for(CORRIDOR, cam, SITES[CORRIDOR])
        cells = Counter(f"{ld.get(h['B']['o'])} {NORM.get(h['B']['mv'], h['B']['mv'])}" for h in hits)
        tags = Counter(f"{h['A']['tag']}+{h['B']['tag']}" for h in hits)
        moved = sorted(((k, b[2][k][0], b[2][k][1], a[2][k][1]) for k in a[2] if a[2][k][1] != b[2][k][1]),
                       key=lambda r: -abs(r[3] - r[2]))[:6]
        res.append((cam, w, b, a))
        print(f"cam{cam} {w}: merged {len(hits):4}  movement {b[0]} -> {a[0]}  approach {b[1]} -> {a[1]}  "
              f"paths {tags.most_common(4)}  by cell {cells.most_common(3)}\n"
              f"      (cell, Mio, {stem}, {arm}): {moved}", flush=True)
    n = len(res)
    print(f"\nFLEET movement {sum(r[2][0] for r in res) / n:.2f} -> {sum(r[3][0] for r in res) / n:.2f}   "
          f"approach {sum(r[2][1] for r in res) / n:.2f} -> {sum(r[3][1] for r in res) / n:.2f}")
    for cam in sorted({r[0] for r in res}):
        rr = [r for r in res if r[0] == cam]
        print(f"  cam{cam} mean {sum(r[2][0] for r in rr) / len(rr):.2f} -> {sum(r[3][0] for r in rr) / len(rr):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
