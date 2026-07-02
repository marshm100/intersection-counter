"""Classify each camera's MISSING bank cells as REAL vs PHANTOM, using Miovision
approach volume per leg (a cell is only a real bank-completeness candidate if BOTH
its legs are substantial approaches). Mirrors the cam1 check (leg 25/WB = 28 veh =
phantom). Fast: Miovision XML + small SQL counts. ASCII prints."""
from __future__ import annotations
import sqlite3, sys
from collections import defaultdict
from pathlib import Path
sys.path.insert(0, str(Path("scripts").resolve())); sys.path.insert(0, str(Path(".").resolve()))
import triangulate_manual as T

PROJECT = "97a7849a"
REAL_MIN = 200   # Miovision approach total below this => phantom/negligible leg
db = f"data/projects/{PROJECT}/project.db"
conn = sqlite3.connect(db)

for cam in (1, 2, 3, 4, 5):
    try:
        mio = T.load_miovision(cam)
    except Exception as e:
        print(f"\ncam{cam}: no Miovision ({e})"); continue
    appr = defaultdict(int)
    for _minute, cells in mio.items():
        for (d, _mv), n in cells.items():
            appr[d] += n
    legs = {lid: (cd or "").upper() for lid, cd in conn.execute(
        "SELECT leg_id,cardinal_direction FROM legs WHERE camera_id=?", (cam,))}
    leg_appr = {lid: T._CARD_TO_DIR.get(cd) for lid, cd in legs.items()}
    # per-leg Miovision volume (its approach total)
    leg_vol = {lid: appr.get(leg_appr.get(lid), 0) for lid in legs}
    paths = {(o, dd) for o, dd in conn.execute(
        "SELECT origin_leg_id,destination_leg_id FROM intersection_paths WHERE camera_id=?", (cam,))}
    print(f"\n=== cam{cam}  Miovision approach vol: "
          f"{ {k: appr[k] for k in sorted(appr, key=lambda x:-appr[x])} } ===")
    real_missing = []
    for o in legs:
        for dd in legs:
            if o == dd or (o, dd) in paths:
                continue
            vo, vd = leg_vol[o], leg_vol[dd]
            real = vo >= REAL_MIN and vd >= REAL_MIN
            tag = "REAL?" if real else "phantom"
            if real:
                real_missing.append((o, dd))
            print(f"    L{o}({legs[o]}/{leg_appr[o]},{vo})->L{dd}({legs[dd]}/{leg_appr[dd]},{vd})"
                  f"  [{tag}]")
    print(f"    -> REAL missing-cell candidates: "
          f"{['L%d->L%d' % (o, d) for o, d in real_missing] or 'none'}")
conn.close()
