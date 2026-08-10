"""G-OR1 evidence measurement: track-derived gate axes vs the shipped
channel-tangent orientation, per camera-window (plan_v2_gate_axis).

Offline and read-only: builds both gate sets from the same dump and
reports strict full journeys, the loose census, and the blind coverage
proxy (full+entry_only)/tracks — the quantity EVIDENCE_ACTIVATION_COVERAGE
tests. No Miovision, nothing written.

Usage: py -X utf8 scripts/v2_gate_axis_measure.py
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

from backend.database import get_connection, list_paths_for_camera   # noqa: E402
from backend.services.detection_cache import parquet_path            # noqa: E402
from backend.services.entry_gates import (                           # noqa: E402
    build_gates, cell_census, classify, derive_gate_axes,
)
from backend.services.pass2_replay import load_dump, tracks_dir      # noqa: E402

WINDOWS = [
    ("97a7849a", 1, "study_0700"), ("97a7849a", 1, "study_1600"),
    ("97a7849a", 2, "study_0700"), ("97a7849a", 2, "study_1100"),
    ("97a7849a", 2, "study_1600"),
    ("97a7849a", 3, "study_0600"),
    ("97a7849a", 4, "study_0700"), ("97a7849a", 4, "study_1100"),
    ("97a7849a", 4, "study_1600"),
    ("97a7849a", 5, "study_0700"), ("97a7849a", 5, "study_1100"),
    ("97a7849a", 5, "study_1600"),
    ("0acb12c0", 2, "ftv2n_am"), ("0acb12c0", 2, "ftv2n_pm"),
]


def ang(u, v):
    d = max(-1.0, min(1.0, u[0]*v[0] + u[1]*v[1]))
    return math.degrees(math.acos(abs(d)))


def main() -> int:
    print(f"{'window':22} {'legs':>9} {'full A':>7} {'full B':>7} {'d%':>7} "
          f"{'cov A':>6} {'cov B':>6} {'census A':>9} {'census B':>9}")
    rows_out = []
    for proj, cam, variant in WINDOWS:
        conn = get_connection(proj)
        chash = conn.execute(
            "SELECT content_hash FROM videos WHERE camera_id=? "
            "ORDER BY sort_order LIMIT 1", (cam,)).fetchone()[0]
        mouths, heads = {}, {}
        for lid, oz, rh in conn.execute(
                "SELECT leg_id,origin_zone,reference_heading FROM legs "
                "WHERE camera_id=?", (cam,)):
            if oz:
                mouths[lid] = tuple(json.loads(oz)[0])
                heads[lid] = rh
        conn.close()
        paths = list_paths_for_camera(proj, cam)
        try:
            rows = load_dump(tracks_dir(parquet_path(proj, cam, chash, variant)))
        except Exception as exc:
            print(f"{proj[:4]} cam{cam} {variant:12} -- dump unavailable ({exc})")
            continue
        tracks = defaultdict(list)
        for r in rows:
            tracks[int(r[0])].append((float(r[1]), float(r[2]), float(r[3])))
        n_tr = len(tracks)
        axes = derive_gate_axes(mouths, tracks.values())
        gA = build_gates(mouths, paths, heads)
        gB = build_gates(mouths, paths, heads, leg_axes=axes)

        def measure(g):
            tags = defaultdict(int)
            for tr in tracks.values():
                tags[classify(tr, g, 10.0)[6]] += 1
            cc = cell_census(tracks.values(), g, 10.0)
            cov = (tags["full"] + tags["entry_only"]) / max(n_tr, 1)
            return tags["full"], cov, sum(cc.values())

        fA, cA, censA = measure(gA)
        fB, cB, censB = measure(gB)
        d = (fB - fA) / fA * 100 if fA else float("nan")
        label = f"{'FM51' if proj.startswith('0acb') else 'corr'} cam{cam} {variant}"
        print(f"{label:22} {len(axes)}/{len(mouths):<7} {fA:7d} {fB:7d} "
              f"{d:+6.1f}% {cA:6.3f} {cB:6.3f} {censA:9.0f} {censB:9.0f}")
        rows_out.append({"project": proj, "camera": cam, "variant": variant,
                         "legs_with_axis": len(axes), "legs": len(mouths),
                         "full_shipped": fA, "full_axis": fB,
                         "coverage_shipped": round(cA, 4),
                         "coverage_axis": round(cB, 4),
                         "census_shipped": round(censA),
                         "census_axis": round(censB),
                         "rotation_deg": {str(l): round(ang(gA[l][2], gB[l][2]), 1)
                                          for l in sorted(axes)}})
    out = "runs/v2_week1/gate_axis_measurement.json"
    with open(out, "w") as fh:
        json.dump(rows_out, fh, indent=1)
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
