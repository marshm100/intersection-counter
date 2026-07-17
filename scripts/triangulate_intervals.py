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
import interval_metric as IM   # the canonical AVG |err| + PASS/FAIL summary


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
    o_pairs: list[tuple] = []      # (label, ours, manual) for full bins
    mi_pairs: list[tuple] = []     # (label, miovision, manual) for full bins
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
        if len(mins) >= IM.MIN_BIN_MINUTES and m:   # full bins only (1-min boundary bins are artifacts)
            o_pairs.append((b.strftime('%H:%M'), o, m))
            mi_pairs.append((b.strftime('%H:%M'), mi, m))
    me = f"{100*(gMi-gM)/gM:+.1f}%" if gM else "-"
    oe = f"{100*(gO-gM)/gM:+.1f}%" if gM else "-"
    print(f"{'TOTAL':<9}{'':>4}{gM:>8}{gMi:>8}{gO:>8}{me:>9}{oe:>9}")
    # Canonical acceptance metric (interval_metric.summarize_bins): mean ABSOLUTE
    # per-interval error vs the manual hand count, with the <=5% PASS/FAIL verdict
    # and the Miovision benchmark to match.
    o_sum, mi_sum = IM.summarize_bins(o_pairs), IM.summarize_bins(mi_pairs)
    if o_sum["verdict"] != "n/a":
        print(f"{'AVG |err|':<9}{'':>4}{'':>8}{'':>8}{'':>8}"
              f"{mi_sum['avg_abs_err_pct']:>8.1f}%{o_sum['avg_abs_err_pct']:>8.1f}%"
              f"   vs manual; target <= {IM.TARGET_PCT:.0f}%/interval")
        print(f"{'VERDICT':<9}{'':>4}{'':>8}{'':>8}{'':>8}"
              f"{'['+mi_sum['verdict']+']':>9}{'['+o_sum['verdict']+']':>9}"
              f"   OURS {o_sum['n_over_target']}/{o_sum['n_bins']} bins over target")


def main():
    for cam in sorted(T.MANUAL_BY_CAM):
        report(cam)
    return 0


if __name__ == "__main__":
    sys.exit(main())
