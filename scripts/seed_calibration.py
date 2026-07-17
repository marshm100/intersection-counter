"""Seed correct leg calibration for corridor cameras from Miovision geometry.

The cam1 legs were 180°-mislabeled (memory project_leg_labels_swapped) because
cardinal directions were assigned by hand. The Miovision per-minute XML carries
each approach's NAME (bound direction) and normalized POSITION, so we can seed
legs that are correct BY CONSTRUCTION — no hand-labeling, no swap possible:
  - origin  = approach label position x (640,480)
  - cardinal = bound letter from the approach name (NB->N, SB->S, EB->E, WB->W)
  - reference_heading = bearing(origin -> intersection center)  [entry direction;
    a rough seed — refine from data via recalibrate_camera after processing]
  - label = the Miovision approach name

Writes legs to the project DB (backs up first; cam2-5 have NO existing legs, so
this is additive, not destructive) and renders a verification overlay per camera
for the engineer visual gate. Default seeds cam2-5 (cam1 already calibrated).

Usage:  py scripts/seed_calibration.py            # dry-run (print only)
        py scripts/seed_calibration.py --write     # write to DB + render overlays
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from parse_miovision_xml import camera_xml

DB = Path("data/projects/97a7849a/project.db")
W, H = 640, 480


def approaches(camera_id):
    """Return [(name, (px,py)), ...] from a camera's Miovision XML."""
    txt = re.sub(r"<\?xml[^>]*\?>", "", camera_xml(camera_id).read_text(encoding="utf-8-sig"), count=1).lstrip()
    r = ET.fromstring(txt); s = lambda t: t.split("}")[-1]
    out = []
    for ap in (x for x in r.iter() if s(x.tag) == "Approach"):
        al = next((x for x in ap.iter() if s(x.tag) == "ApproachLabel"), None)
        x = float(al.findtext("xPosition")) * W
        y = float(al.findtext("yPosition")) * H
        out.append((ap.findtext("Name"), (x, y)))
    return out


def cardinal_of(name):
    tok = name.strip().split()[0].upper()       # 'NB' / 'SB' / 'EB' / 'WB'
    return {"NB": "N", "SB": "S", "EB": "E", "WB": "W"}.get(tok, tok[:1])


def bearing(frm, to):
    return math.degrees(math.atan2(to[0] - frm[0], -(to[1] - frm[1]))) % 360


def seed_for(camera_id):
    apps = approaches(camera_id)
    cx = sum(p[0] for _, p in apps) / len(apps)
    cy = sum(p[1] for _, p in apps) / len(apps)
    legs = []
    for i, (name, pos) in enumerate(apps):
        legs.append({
            "label": name,
            "cardinal_direction": cardinal_of(name),
            "sort_order": i,
            "origin_zone": [[round(pos[0], 1), round(pos[1], 1)]],
            "reference_heading": round(bearing(pos, (cx, cy)), 1),
        })
    return legs, (cx, cy)


def overlay(camera_id, legs):
    c = sqlite3.connect(str(DB))
    vp = c.execute("SELECT path FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1", (camera_id,)).fetchone()[0]
    c.close()
    cap = cv2.VideoCapture(vp); cap.set(cv2.CAP_PROP_POS_FRAMES, 252030)
    ok, frame = cap.read(); cap.release()
    if not ok:
        frame = np.zeros((H, W, 3), np.uint8)
    for lg in legs:
        ox, oy = lg["origin_zone"][0]
        cv2.circle(frame, (int(ox), int(oy)), 7, (0, 255, 255), -1)
        rr = math.radians(lg["reference_heading"])
        cv2.arrowedLine(frame, (int(ox), int(oy)),
                        (int(ox + math.sin(rr) * 55), int(oy - math.cos(rr) * 55)), (0, 255, 255), 2, tipLength=0.3)
        cv2.putText(frame, f"{lg['cardinal_direction']} {lg['label'][:22]}", (int(ox) + 8, int(oy) - 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)
    out = f"screenshots/seed_cam{camera_id}.png"
    Path("screenshots").mkdir(exist_ok=True)
    cv2.imwrite(out, frame)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cameras", default="2,3,4,5")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    cams = [int(x) for x in args.cameras.split(",")]

    plan = {cam: seed_for(cam) for cam in cams}
    for cam, (legs, center) in plan.items():
        print(f"\n=== cam{cam}  (center=({center[0]:.0f},{center[1]:.0f})) ===")
        for lg in legs:
            print(f"  {lg['cardinal_direction']:<2} {lg['label']:<28} origin={lg['origin_zone'][0]} ref={lg['reference_heading']}")

    if not args.write:
        print("\nDRY-RUN. Pass --write to back up the DB, insert legs, and render overlays.")
        return 0

    bak = DB.parent / "backups" / "20260529_pre_seed_cam2-5.db"
    conn = sqlite3.connect(str(DB))
    conn.execute("VACUUM INTO ?", (str(bak),));
    next_id = (conn.execute("SELECT MAX(leg_id) FROM legs").fetchone()[0] or 0) + 1
    with conn:
        for cam, (legs, _) in plan.items():
            conn.execute("DELETE FROM legs WHERE camera_id=?", (cam,))  # cam2-5 have none; idempotent
            for lg in legs:
                conn.execute("INSERT INTO legs (leg_id, camera_id, label, cardinal_direction, sort_order, origin_zone, reference_heading) "
                             "VALUES (?,?,?,?,?,?,?)",
                             (next_id, cam, lg["label"], lg["cardinal_direction"], lg["sort_order"],
                              json.dumps(lg["origin_zone"]), lg["reference_heading"]))
                next_id += 1
    conn.close()
    print(f"\nbacked up -> {bak}; wrote legs for cams {cams}")
    for cam, (legs, _) in plan.items():
        print(f"  overlay: {overlay(cam, legs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
