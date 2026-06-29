"""15-minute interval report: Manual vs Miovision vs our App, per corridor camera.

Reuses triangulate_manual's per-minute loaders. For fairness, each 15-min bin
sums ALL THREE sources over EXACTLY the minutes the human counted in that bin
(the manual sheets are partial), and flags bins with < 15 counted minutes.

Usage:  py scripts/triangulate_intervals.py
"""
from __future__ import annotations
import sys
from collections import defaultdict
from datetime import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import triangulate_manual as T


def _minute_total(permin, t):
    return sum(permin.get(t, {}).values())


def _bin(t: time) -> time:
    return time(t.hour, (t.minute // 15) * 15)


def report(cam: int):
    manual = T.parse_manual(T.MANUAL_BY_CAM[cam])
    mio, ours = T.load_miovision(cam), T.load_ours(cam)
    counted = sorted(manual.keys())
    bins = defaultdict(list)
    for t in counted:
        bins[_bin(t)].append(t)

    print(f"\n########## cam{cam}  {T.MANUAL_BY_CAM[cam].stem} ##########")
    print(f"{'interval':<9}{'min':>4}{'MANUAL':>8}{'MIOVIS':>8}{'OURS':>8}"
          f"{'Mio err':>9}{'Ours err':>9}")
    gM = gMi = gO = 0
    mi_errs: list[float] = []
    o_errs: list[float] = []
    for b in sorted(bins):
        mins = bins[b]
        m = sum(_minute_total(manual, t) for t in mins)
        mi = sum(_minute_total(mio, t) for t in mins)
        o = sum(_minute_total(ours, t) for t in mins)
        gM += m; gMi += mi; gO += o
        me = f"{100*(mi-m)/m:+.1f}%" if m else "-"
        oe = f"{100*(o-m)/m:+.1f}%" if m else "-"
        flag = "" if len(mins) >= 15 else f"  (partial {len(mins)}m)"
        print(f"{b.strftime('%H:%M'):<9}{len(mins):>4}{m:>8}{mi:>8}{o:>8}{me:>9}{oe:>9}{flag}")
        if len(mins) >= 10 and m:   # full bins only (1-min boundary bins are artifacts)
            mi_errs.append(100 * (mi - m) / m)
            o_errs.append(100 * (o - m) / m)
    me = f"{100*(gMi-gM)/gM:+.1f}%" if gM else "-"
    oe = f"{100*(gO-gM)/gM:+.1f}%" if gM else "-"
    print(f"{'TOTAL':<9}{'':>4}{gM:>8}{gMi:>8}{gO:>8}{me:>9}{oe:>9}")
    if mi_errs:
        n = len(mi_errs)
        avg_mi = sum(mi_errs) / n; avg_o = sum(o_errs) / n
        mae_mi = sum(abs(e) for e in mi_errs) / n; mae_o = sum(abs(e) for e in o_errs) / n
        print(f"{'AVG err':<9}{'':>4}{'':>8}{'':>8}{'':>8}{avg_mi:>+8.1f}%{avg_o:>+8.1f}%"
              f"   mean signed (cancels), n={n} full bins")
        print(f"{'AVG |err|':<9}{'':>4}{'':>8}{'':>8}{'':>8}{mae_mi:>8.1f}%{mae_o:>8.1f}%"
              f"   mean ABSOLUTE per-interval error")


def main():
    for cam in sorted(T.MANUAL_BY_CAM):
        report(cam)
    return 0


if __name__ == "__main__":
    sys.exit(main())
