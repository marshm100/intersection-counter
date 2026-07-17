"""Engineer visual gate (Phase C, docs/reid_project_plan_2026-06-01.md).

Renders the FINAL production result onto the camera's frame for human sign-off BEFORE
applying to production: the path bank (polylines colored by movement, incl. the
recovered EB-right), each leg origin labeled with its CORRECTED cardinal (NB/SB/EB/WB
— memory project_leg_labels_swapped), and a per-OD-cell our-vs-manual count table.
The engineer confirms paths follow the roads, labels are right, no phantom turns, and
counts are sane — then process_camera_reid.py --apply is run.

Usage:
  py scripts/visual_gate.py --camera 1 --bank evaluations/recal_cam1_odturns_ebr.json \
     --db data/projects/97a7849a/_hybrid_tmp/prod_final_cam1.db
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from auto_calibrate_viz import draw_path, draw_zone, load_video_frame, MOVEMENT_COLORS
from od_accuracy import manual_per_minute, our_per_minute, LEG_IDX, IDX_NAME
from groundtruth import VIDEO_START

PROJECT = "97a7849a"
_CARD_FULL = {"N": "NB", "S": "SB", "E": "EB", "W": "WB"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--bank", default="evaluations/recal_cam1_odturns_ebr.json")
    ap.add_argument("--db", default=f"data/projects/{PROJECT}/_hybrid_tmp/prod_final_cam1.db")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    vrow = conn.execute("SELECT path FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
                        (args.camera,)).fetchone()
    legs = {}
    card = {}
    for lid, oz, cd in conn.execute("SELECT leg_id,origin_zone,cardinal_direction FROM legs WHERE camera_id=?", (args.camera,)):
        legs[lid] = json.loads(oz)[0] if oz else None
        card[lid] = _CARD_FULL.get(cd, cd or "?")
    conn.close()
    video = vrow[0]
    secs = (datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}") - VIDEO_START).total_seconds()
    frame = load_video_frame(video, secs)
    if frame is None:
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
    img = frame.copy()

    bank = json.loads(Path(args.bank).read_text())
    for p in bank.get("paths", []):
        draw_path(img, p["polyline"], MOVEMENT_COLORS.get(p.get("movement_label"), (160, 160, 160)), 2)
    for lid, origin in legs.items():
        if origin is None:
            continue
        draw_zone(img, origin, radius=16, color=(255, 255, 255), label=f"L{lid} {card.get(lid,'?')}")

    # per-cell our vs manual (movement level)
    t0 = datetime.fromisoformat(f"{VIDEO_START.date().isoformat()}T{args.start_hms}")
    start_sec = (t0 - VIDEO_START).total_seconds()
    mins = [t0 + timedelta(minutes=i) for i in range(int(args.minutes))]
    _, m_mv, _ = manual_per_minute()
    _, o_mv = our_per_minute(Path(args.db), start_sec, start_sec + args.minutes * 60, legmap=LEG_IDX)
    cells = set()
    for mn in mins:
        cells |= set(m_mv.get(mn, {})) | set(o_mv.get(mn, {}))
    rows = []
    for cell in sorted(cells):
        man = sum(m_mv.get(mn, {}).get(cell, 0) for mn in mins)
        ours = sum(o_mv.get(mn, {}).get(cell, 0) for mn in mins)
        if man == 0 and ours == 0:
            continue
        in_i, mvt = cell
        rows.append((f"{IDX_NAME[in_i]} {mvt}", man, ours))

    # table panel on the right
    panel = np.zeros((img.shape[0], 230, 3), dtype=np.uint8)
    cv2.putText(panel, "cell           man  ours", (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (220, 220, 220), 1, cv2.LINE_AA)
    for i, (name, man, ours) in enumerate(rows):
        y = 36 + i * 16
        col = (120, 230, 120) if abs(ours - man) <= max(3, 0.15 * man) else (120, 170, 255)
        cv2.putText(panel, f"{name:<14}{man:>4.0f}{ours:>5}", (6, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1, cv2.LINE_AA)
    out_img = np.hstack([img, panel])
    cv2.rectangle(out_img, (0, 0), (img.shape[1], 20), (0, 0, 0), -1)
    cv2.putText(out_img, f"VISUAL GATE cam{args.camera}  bank={Path(args.bank).name}  {args.start_hms}+{args.minutes:.0f}m",
                (6, 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

    out = Path(args.out) if args.out else Path("screenshots") / f"visual_gate_cam{args.camera}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), out_img)
    print(f"wrote {out}  ({len(bank.get('paths', []))} paths, {len(rows)} cells)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
