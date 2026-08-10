"""Would heading-derived gate orientation fix FM51 - and would it HARM
the corridor? Offline probe only; nothing in the chain is touched.

Variant A (shipped): orientation = mean of channel tangents at the mouth.
Variant B (probe):   orientation = the leg's operator reference_heading
                     (the fallback build_gates already uses when a leg has
                     no channels at all).
Reports classify tags, strict full journeys, and blind coverage proxy.
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
    GATE_MIN_HALF, GATE_PAD_PX, _closest_on_polyline, build_gates,
    cell_census, classify,
)
from backend.services.pass2_replay import load_dump, tracks_dir      # noqa: E402

CASES = [("0acb12c0", 2, "ftv2n_am", "FM51 AM"),
         ("0acb12c0", 2, "ftv2n_pm", "FM51 PM"),
         ("97a7849a", 2, "study_1100", "corridor cam2"),
         ("97a7849a", 4, "study_1100", "corridor cam4"),
         ("97a7849a", 5, "study_1100", "corridor cam5")]


def gates_from_heading(legs, bank_paths, leg_head):
    """build_gates with the ORIENTATION taken from reference_heading; span
    still from the channels' lane spread (same padding/floor/de-overlap
    inputs), so only the direction source changes."""
    centroid = (sum(m[0] for m in legs.values()) / len(legs),
                sum(m[1] for m in legs.values()) / len(legs))
    gates = {}
    for leg, mouth in legs.items():
        hd = math.radians(float((leg_head or {}).get(leg) or 0.0))
        tx, ty = math.sin(hd), -math.cos(hd)
        gx, gy = -ty, tx
        cpts = []
        for p in bank_paths:
            if p["origin_leg_id"] != leg and p["destination_leg_id"] != leg:
                continue
            cpt, _t, _d = _closest_on_polyline(p["polyline"], mouth)
            if cpt is not None:
                cpts.append(cpt)
        spread = [(c[0]-mouth[0])*gx + (c[1]-mouth[1])*gy for c in cpts] + [0.0]
        half = max(GATE_MIN_HALF,
                   max(abs(min(spread)), abs(max(spread))) + GATE_PAD_PX)
        p1 = (mouth[0]-gx*half, mouth[1]-gy*half)
        p2 = (mouth[0]+gx*half, mouth[1]+gy*half)
        s = 1.0 if ((centroid[0]-mouth[0])*tx + (centroid[1]-mouth[1])*ty) > 0 else -1.0
        gates[leg] = (p1, p2, (s*tx, s*ty))
    return gates


for proj, cam, variant, tag in CASES:
    conn = get_connection(proj)
    chash = conn.execute("SELECT content_hash FROM videos WHERE camera_id=? "
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
    rows = load_dump(tracks_dir(parquet_path(proj, cam, chash, variant)))
    tracks = defaultdict(list)
    for r in rows:
        tracks[int(r[0])].append((float(r[1]), float(r[2]), float(r[3])))
    n_tr = len(tracks)

    print(f"\n===== {tag} (cam{cam} {variant}, {n_tr} tracks)")
    for name, g in (("A shipped (channel tangents)",
                     build_gates(mouths, paths, heads)),
                    ("B probe   (reference_heading)",
                     gates_from_heading(mouths, paths, heads))):
        tags = defaultdict(int)
        fulls = defaultdict(int)
        for tr in tracks.values():
            o, d, _of, _df, _op, _dp, t = classify(tr, g, 10.0)
            tags[t] += 1
            if t == "full":
                fulls[(o, d)] += 1
        cc = cell_census(tracks.values(), g, 10.0)
        cov = (tags["full"] + tags["entry_only"]) / max(n_tr, 1)
        print(f"  {name}: full={tags['full']:5d} entry_only={tags['entry_only']:5d} "
              f"exit_only={tags['exit_only']:5d} no_cross={tags['no_crossing']:5d}"
              f"  | census={sum(cc.values()):8.0f}  origin-evidence coverage~{cov:.3f}")
