"""Overlay Miovision approach label positions vs OUR leg origins on a real frame,
to confirm/deny the suspected L22/L23 and L24/L25 mislabel (od_accuracy.py finding).

Miovision approach positions (GREEN, normalized->px) vs our leg origins+heading
arrows (YELLOW), over faded real trajectories so actual flow direction is visible.
Usage:  py scripts/viz_leg_vs_miovision.py
"""
from __future__ import annotations
import json, math, re, sqlite3, sys
import xml.etree.ElementTree as ET
from pathlib import Path
import cv2, numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB = "data/projects/97a7849a/_hybrid_tmp/oc.db"
XML = "docs/historic data/405051_0035_20260512_000002_NBeltLineRd-NorthwestDr_1401964_05-12-2026.xml"


def miovision_positions(W, H):
    txt = re.sub(r"<\?xml[^>]*\?>", "", open(XML, encoding="utf-8-sig").read(), count=1).lstrip()
    r = ET.fromstring(txt); s = lambda t: t.split("}")[-1]
    out = []
    for ap in (x for x in r.iter() if s(x.tag) == "Approach"):
        al = next((x for x in ap.iter() if s(x.tag) == "ApproachLabel"), None)
        out.append((ap.findtext("Name"), float(al.findtext("xPosition")) * W, float(al.findtext("yPosition")) * H))
    return out


def main() -> int:
    c = sqlite3.connect(DB)
    vp = c.execute("SELECT path FROM videos WHERE camera_id=1 ORDER BY sort_order LIMIT 1").fetchone()[0]
    cap = cv2.VideoCapture(vp); cap.set(cv2.CAP_PROP_POS_FRAMES, 252030)
    ok, frame = cap.read(); cap.release()
    if not ok: frame = np.zeros((480, 640, 3), np.uint8)
    H, W = frame.shape[:2]

    ov = frame.copy()
    for (tj,) in c.execute("SELECT trajectory_data FROM vehicle_events WHERE camera_id=1 AND rejected=0 LIMIT 1500"):
        if tj: cv2.polylines(ov, [np.array(json.loads(tj), np.int32)], False, (160, 160, 160), 1, cv2.LINE_AA)
    frame = cv2.addWeighted(ov, 0.35, frame, 0.65, 0)

    # our legs (YELLOW) origin + heading arrow
    for lid, oz, ref in c.execute("SELECT leg_id,origin_zone,reference_heading FROM legs WHERE camera_id=1"):
        if not oz: continue
        ox, oy = json.loads(oz)[0]
        cv2.circle(frame, (int(ox), int(oy)), 7, (0, 220, 220), 2)
        rr = math.radians(ref); cv2.arrowedLine(frame, (int(ox), int(oy)), (int(ox+math.sin(rr)*55), int(oy-math.cos(rr)*55)), (0, 220, 220), 2, tipLength=0.3)
        appr = {22: "SB", 23: "NB", 24: "WB", 25: "EB"}[lid]
        cv2.putText(frame, f"ours L{lid}={appr}", (int(ox)+8, int(oy)+4), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 220, 220), 1, cv2.LINE_AA)
    c.close()

    # Miovision approach positions (GREEN)
    for name, x, y in miovision_positions(W, H):
        cv2.drawMarker(frame, (int(x), int(y)), (0, 255, 0), cv2.MARKER_CROSS, 22, 2)
        short = name.replace(" N Belt Line Rd", "").replace(" Northwest Dr", "").replace(" Private Driveway", "")
        cv2.putText(frame, f"MV:{short}", (int(x)+6, int(y)-6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2, cv2.LINE_AA)

    cv2.putText(frame, "GREEN=Miovision approach  YELLOW=our leg origin+heading", (6, 472), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2, cv2.LINE_AA)
    out = "screenshots/leg_vs_miovision_7am.png"
    cv2.imwrite(out, frame); print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
