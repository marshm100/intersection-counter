"""Offline cross-tabs of the recovery-guard census records (research_recovery_guard.py):
the angle of the recovery jump against the track's predicted motion, by jump size and
box confidence, thefts (OTHER) vs good recoveries (SAME), and the cost of candidate
rules. Usage: python scripts/research_recovery_guard_tab.py <recovery_guard_*.json>..."""
import json, sys
from collections import Counter
import numpy as np

for p in sys.argv[1:]:
    out = json.load(open(p))
    print(p, len(out))
    for k in ("OTHER", "SAME", "NONE"):
        sub = [o for o in out if o["kind"] == k]
        ang = [o for o in sub if o["angle"] is not None]
        print(f"  {k}: n={len(sub)}  angle known {len(ang)}  (no motion / no last box: {len(sub)-len(ang)})")
        if not ang:
            continue
        # angle bins x jump bins
        abins = [0, 30, 60, 90, 120, 150, 181]
        jbins = [0, 0.15, 0.3, 0.5, 0.9, 10]
        print("     angle\jump " + "".join(f"{lo:>7.2f}" for lo in jbins[:-1]))
        for a0, a1 in zip(abins, abins[1:]):
            row = [o for o in ang if a0 <= o["angle"] < a1]
            h, _ = np.histogram([o["jump"] for o in row], bins=jbins)
            print(f"     {a0:>3}-{a1:<3}     " + "".join(f"{n:>7d}" for n in h) + f"   n={len(row)}")
    print("  RULES (refused OTHER / SAME / NONE):")
    def rule(name, fn):
        c = Counter(o["kind"] for o in out if fn(o))
        print(f"     {name:<62} {c['OTHER']:>4} / {c['SAME']:>5} / {c['NONE']:>5}")
    A = lambda o: o["angle"] is not None
    for amin in (60, 90, 120):
        rule(f"angle > {amin}", lambda o, a=amin: A(o) and o["angle"] > a)
        for jmin in (0.15, 0.3):
            rule(f"angle > {amin} and jump >= {jmin} widths", lambda o, a=amin, j=jmin: A(o) and o["angle"] > a and o["jump"] >= j)
        rule(f"angle > {amin} and conf < 0.35", lambda o, a=amin: A(o) and o["angle"] > a and o["conf"] < 0.35)
        rule(f"angle > {amin} and jump >= 0.15 and conf < 0.35", lambda o, a=amin: A(o) and o["angle"] > a and o["jump"] >= 0.15 and o["conf"] < 0.35)
    rule("held-box IoU >= 0.6 (any id)", lambda o: o["ov_iou"] >= 0.6)
    rule("angle > 90 & jump >= 0.15  OR  held-box IoU >= 0.6", lambda o: (A(o) and o["angle"] > 90 and o["jump"] >= 0.15) or o["ov_iou"] >= 0.6)
    tot = Counter(o["kind"] for o in out)
    print(f"     {'(totals)':<62} {tot['OTHER']:>4} / {tot['SAME']:>5} / {tot['NONE']:>5}")
