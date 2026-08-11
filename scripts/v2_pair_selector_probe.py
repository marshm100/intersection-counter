"""G-P1 — does a GT-FREE signal predict the evidence pair's per-window value?

docs/plan_v2_pair_adjudication_2026-08-11.md

Block 0 measured what turning the gate+posterior pair ON is worth per window
(+11.5 at cam3 down to -13.2 at cam5 study_1600). EVIDENCE_ACTIVATION_COVERAGE
= 0.45 is a threshold on a blind coverage proxy and cannot express that. This
probe asks whether CORRIDOR LINK AGREEMENT can.

WHY THIS SIGNAL AND NOT THE OBVIOUS ONE. The gate-evidence census is
DISQUALIFIED as circular: the pair attributes USING gate evidence, so a
pair-on result agrees better with a gate-evidence census by construction
(entry_gates.cell_census carries an explicit guard for the same reason), and
every apply-gate guard is computed against that census. Corridor links are
structurally independent — the neighbour's count comes from a different
camera, geometry and calibration.

TWO THINGS MEASURED FIRST, both of which shape the method:

1. UNSCOPED links are dominated by COVERAGE, not counting. On production the
   shipped check reports gaps of 0.58-0.64 on every link touching
   intersection 3 — because cam3 is the 24-hour camera (34955 events) and its
   neighbours only cover peaks. Nothing to do with attribution. So every
   comparison here is scoped to wall-clock hours via timestamp_real
   (_cardinal_volumes uses timestamp_video, which is NOT comparable across
   cameras with different recording starts — hence the local query).

2. Per-hour coverage (production): cam1/2/4/5 carry events ONLY in 07-09,
   11-13, 16-18; cam3 carries 06-20. So study_0700/1100/1600 can be compared
   across all five cameras, and cam3's study_0600 can only be compared on the
   OVERLAP hours. That overlap is used rather than skipping the window,
   because study_0600 is the one carrying the +11.5.

Usage:
  py -X utf8 scripts/v2_pair_selector_probe.py
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCRATCH = Path("data/projects/97a7849a/_replay_scratch")
SCORES = Path("runs/v2_week1")
ORDER = [1, 2, 3, 4, 5]          # sort_order from the intersections table
UP, DOWN = "N", "S"              # corridor axis (every leg set has N and S)
MIN_LINK_VOLUME = 30             # conservation_qa's own floor

# hours each window may be scored on: the window's own hours intersected with
# the hours the NEIGHBOURS actually cover (measured, not assumed)
PEAK_HOURS = [7, 8, 11, 12, 16, 17]
WINDOW_HOURS = {
    "study_0700": [7, 8],
    "study_1100": [11, 12],
    "study_1600": [16, 17],
    "study_0600": PEAK_HOURS,     # cam3 covers 06-20; neighbours only peaks
}

WINDOWS = [
    (1, "study_0700"), (1, "study_1600"),
    (2, "study_0700"), (2, "study_1100"), (2, "study_1600"),
    (3, "study_0600"),
    (4, "study_0700"), (4, "study_1100"), (4, "study_1600"),
    (5, "study_0700"), (5, "study_1100"), (5, "study_1600"),
]


def _arm_dbs(cam: int, var: str) -> dict[str, Path]:
    out = {"B": SCRATCH / "v2_week1" / f"twopass_cam{cam}_v2c_{var}.db"}
    for sub in ("armC", "armC2"):
        p = SCRATCH / "v2_confound" / sub / f"armC_cam{cam}_v2c_{var}.db"
        if p.exists():
            out["C"] = p
    return out


def directional_io(db: Path, hours: list[int]) -> dict[int, dict]:
    """{intersection_id: {'in': {cardinal: n}, 'out': {cardinal: n}}} scoped to
    wall-clock hours. Mirrors conservation_qa._directional_io's convention:
    cardinal is the leg POSITION, so origin cardinal 'S' = arrived from the
    south arm, dest cardinal 'N' = left toward the north arm."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cam_int = dict(c.execute("SELECT camera_id, intersection_id FROM cameras"))
    card = {lid: (cd or "").upper() for lid, cd in
            c.execute("SELECT leg_id, cardinal_direction FROM legs")}
    leg_cam = dict(c.execute("SELECT leg_id, camera_id FROM legs"))
    hset = ",".join(str(h) for h in hours)
    rows = c.execute(
        f"SELECT origin_leg_id, destination_leg_id, COUNT(*) "
        f"FROM vehicle_events "
        f"WHERE COALESCE(rejected,0)=0 AND destination_leg_id IS NOT NULL "
        f"AND timestamp_real IS NOT NULL "
        f"AND CAST(strftime('%H', timestamp_real) AS INT) IN ({hset}) "
        f"GROUP BY 1,2").fetchall()
    c.close()
    io: dict[int, dict] = {}
    for ol, dl, n in rows:
        a, b = card.get(ol), card.get(dl)
        iid = cam_int.get(leg_cam.get(ol))
        if not a or not b or iid is None:
            continue
        d = io.setdefault(iid, {"in": {}, "out": {}})
        d["in"][a] = d["in"].get(a, 0) + n
        d["out"][b] = d["out"].get(b, 0) + n
    return io


def links_touching(io: dict, iid: int) -> list[dict]:
    out = []
    for a, b in zip(ORDER, ORDER[1:]):
        if iid not in (a, b):
            continue
        for label, send, recv in (
                (f"{a}->{b} ({UP}bound)",
                 io.get(a, {}).get("out", {}).get(UP, 0),
                 io.get(b, {}).get("in", {}).get(DOWN, 0)),
                (f"{b}->{a} ({DOWN}bound)",
                 io.get(b, {}).get("out", {}).get(DOWN, 0),
                 io.get(a, {}).get("in", {}).get(UP, 0))):
            big = max(send, recv)
            if big < MIN_LINK_VOLUME:
                continue
            out.append({"link": label, "sent": send, "received": recv,
                        "gap": abs(send - recv) / big})
    return out


def pair_delta(cam: int, var: str) -> float | None:
    """The pair's measured 5/95 value = arm B - arm C (Block 0)."""
    def pct(p: Path):
        if not p.exists():
            return None
        return (json.loads(p.read_text(encoding="utf-8")).get("v2") or {}).get("pct")
    b = pct(SCORES / f"score_twopass_cam{cam}_v2c_{var}.json")
    c = pct(SCORES / f"score_armC_cam{cam}_v2c_{var}.json")
    return None if (b is None or c is None) else b - c


def main() -> int:
    print("G-P1 — corridor link agreement vs the pair's measured 5/95 value")
    print("  link gap scoped to wall-clock hours (timestamp_real); lower = better")
    print("  PREDICTION: pair ON should IMPROVE link agreement where it helps,")
    print("  i.e. sign(gap_C - gap_B) should match sign(5/95 delta).")
    print()
    hdr = (f"{'window':17s} {'hours':>14s} {'gapB':>7s} {'gapC':>7s} "
           f"{'gapC-gapB':>10s} {'5/95 delta':>11s} {'sign':>5s} {'n':>3s}")
    print(hdr)
    print("-" * len(hdr))
    rows = []
    for cam, var in WINDOWS:
        dbs = _arm_dbs(cam, var)
        if "B" not in dbs or "C" not in dbs or not dbs["B"].exists():
            print(f"cam{cam} {var:12s}  (missing arm)")
            continue
        hours = WINDOW_HOURS[var]
        gb = links_touching(directional_io(dbs["B"], hours), cam)
        gc = links_touching(directional_io(dbs["C"], hours), cam)
        if not gb or not gc:
            print(f"cam{cam} {var:12s}  (no link above MIN_LINK_VOLUME)")
            continue
        mb = sum(l["gap"] for l in gb) / len(gb)
        mc = sum(l["gap"] for l in gc) / len(gc)
        d = pair_delta(cam, var)
        if d is None:
            continue
        improve = mc - mb          # >0 means pair ON has the SMALLER gap
        ok = "OK" if (improve > 0) == (d > 0) else "MISS"
        hs = f"{hours[0]:02d}-{hours[-1]+1:02d}" if len(hours) <= 2 else "peaks"
        print(f"cam{cam} {var:12s} {hs:>14s} {mb:>7.3f} {mc:>7.3f} "
              f"{improve:>+10.3f} {d:>+11.1f} {ok:>5s} {len(gb):>3d}")
        rows.append((f"cam{cam} {var}", improve, d, ok))
    if not rows:
        return 1
    hit = sum(1 for r in rows if r[3] == "OK")
    big = [r for r in rows if abs(r[2]) >= 7.0]
    bighit = sum(1 for r in big if r[3] == "OK")
    print()
    print(f"G-P1 sign agreement: {hit}/{len(rows)}   (gate: >= 9/12)")
    print(f"        on |delta| >= 7.0: {bighit}/{len(big)}   (gate: ALL)")
    # Spearman without scipy: rank correlation on (improve, delta)
    def rank(v):
        s = sorted(range(len(v)), key=lambda i: v[i])
        r = [0.0] * len(v)
        for pos, i in enumerate(s):
            r[i] = pos
        return r
    x, y = rank([r[1] for r in rows]), rank([r[2] for r in rows])
    n = len(rows)
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    den = (sum((a - mx) ** 2 for a in x) * sum((b - my) ** 2 for b in y)) ** 0.5
    rho = num / den if den else 0.0
    print(f"G-P2 Spearman rho: {rho:+.3f}   (gate: >= 0.60)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
