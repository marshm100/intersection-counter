"""Stills of each phantom (2026-10-13, operator: "go look for the problem ... see why it
is happening"). For every phantom in runs/v2_week1/phantoms_{dev,heldout}.log on the
chosen clips, a 4-panel strip: just before the phantom track is born, at its birth, at
mid-life, at its end. Drawn on each panel:
  RED thick      the phantom track's box (+ its path so far, red dots)
  GREEN          the labelled car it shadows (from the log), its box
  GREY thin      every other track's box, with its id
  YELLOW thin    the raw detector boxes this frame, with confidence
  MAGENTA        the gate lines, labelled by leg cardinal
Header: track id, bucket, gate tag, posterior source, movement, box class / conf.
Writes screenshots/phantoms/<clip>_t<tid>.png. Dev-validation only.
Usage: .venv/Scripts/python.exe -X utf8 scripts/viz_phantom_riders.py CLIP_ID [CLIP_ID ...]
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from scripts.eval_journeys import PROJ, locate  # noqa: E402

LOGS = ("runs/v2_week1/phantoms_dev.log", "runs/v2_week1/phantoms_heldout.log")
OUT = Path("screenshots/phantoms")


def phantom_list(clip_id: str) -> list[tuple[int, str, int | None]]:
    out, cur = [], None
    for log in LOGS:
        for line in open(log, encoding="utf-8"):
            m = re.match(r"== (\S+)", line)
            if m:
                cur = m.group(1)
            m = re.match(r"\s+t(\d+)\s+(\w+)\s+tag", line)
            if m and cur == clip_id:
                car = re.search(r"shadows car (\d+)", line)
                out.append((int(m.group(1)), m.group(2), int(car.group(1)) if car else None))
    return out


def box(img, cx, cy, w, h, col, th=1, label=None):
    x1, y1, x2, y2 = int(cx - w / 2), int(cy - h / 2), int(cx + w / 2), int(cy + h / 2)
    cv2.rectangle(img, (x1, y1), (x2, y2), col, th, cv2.LINE_AA)
    if label:
        cv2.putText(img, label, (x1, max(y1 - 3, 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.38, col, 1, cv2.LINE_AA)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    clips = {c["clip_id"]: c for c in list_clips(PROJ)}
    for clip_id in sys.argv[1:]:
        clip = clips[clip_id]
        cam = clip["camera_id"]
        window = "study_" + clip_id.split("_")[1]
        vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE video_id=?",
                                        (clip["video_id"],)).fetchone()
        fps = float(fps)
        db, rows = locate("dt2c", {}, cam, window, chash)
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        info = {int(r[0]): r[1:] for r in d.execute(
            "SELECT e.vehicle_track_id, f.gate_tag, e.posterior_source, e.origin_leg_id, "
            "e.destination_leg_id, e.movement FROM vehicle_events e LEFT JOIN track_fates f "
            "ON f.vehicle_track_id = e.vehicle_track_id AND f.camera_id = e.camera_id "
            "AND f.disposition = 'counted' WHERE e.camera_id=? AND COALESCE(e.rejected,0)=0", (cam,))}
        legs = {int(lid): (card, json.loads(seg)) for lid, card, seg in con.execute(
            "SELECT leg_id, cardinal_direction, gate_segment FROM legs WHERE camera_id=?", (cam,)) if seg}
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        labels = list_labels(PROJ, clip_id)
        byf = je.index_rows(rows, f_lo - 2, f_hi + 2)
        dups = je.duplicate_labels(labels, fps, byf)
        lab = [lb for lb in labels if lb["label_id"] not in dups]
        ein, eout = je._assign_clicks(lab, rows, byf, fps)
        tbl = pq.read_table(parquet_path(PROJ, cam, chash, window)).to_pandas()
        cap = cv2.VideoCapture(vpath)
        for tid, kind, car in phantom_list(clip_id):
            tr = rows[rows[:, 0] == tid]
            tr = tr[np.argsort(tr[:, 1])]
            f0, f1 = int(tr[0, 1]), int(tr[-1, 1])
            car_tids = {t for t in (ein.get(car), eout.get(car)) if t is not None} if car else set()
            frames = [max(f0 - int(fps), 0), f0, (f0 + f1) // 2, f1]
            panels = []
            for k, f in enumerate(frames):
                cap.set(cv2.CAP_PROP_POS_FRAMES, f)
                ok, img = cap.read()
                if not ok:
                    img = np.zeros((480, 640, 3), np.uint8)
                for lid, (card, seg) in legs.items():
                    p, q = (int(seg[0][0]), int(seg[0][1])), (int(seg[1][0]), int(seg[1][1]))
                    cv2.line(img, p, q, (255, 0, 255), 1, cv2.LINE_AA)
                    cv2.putText(img, card, ((p[0] + q[0]) // 2, (p[1] + q[1]) // 2), cv2.FONT_HERSHEY_SIMPLEX,
                                0.5, (255, 0, 255), 1, cv2.LINE_AA)
                for _, r in tbl[tbl.frame_idx == f].iterrows():
                    cx, cy = (r.bbox_x1 + r.bbox_x2) / 2, (r.bbox_y1 + r.bbox_y2) / 2
                    box(img, cx, cy, r.bbox_x2 - r.bbox_x1, r.bbox_y2 - r.bbox_y1, (0, 220, 255), 1,
                        f"{r.confidence:.2f}")
                for r in rows[rows[:, 1] == f]:
                    t = int(r[0])
                    if t == tid:
                        continue
                    green = t in car_tids
                    box(img, r[2], r[3], r[4], r[5], (0, 255, 0) if green else (170, 170, 170),
                        2 if green else 1, f"t{t}")
                past = tr[tr[:, 1] <= f]
                for r in past[:: max(len(past) // 30, 1)]:
                    cv2.circle(img, (int(r[2]), int(r[3])), 2, (0, 0, 255), -1)
                now = tr[tr[:, 1] == f]
                if len(now):
                    r = now[0]
                    box(img, r[2], r[3], r[4], r[5], (0, 0, 255), 2, f"PHANTOM t{tid} c{int(r[7])} {r[6]:.2f}")
                cv2.putText(img, ["1s before birth", "birth", "mid-life", "end"][k] + f"  f{f}",
                            (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)
                panels.append(img)
            tag, src, o, de, mv = info.get(tid, (None,) * 5)
            strip = np.vstack([np.hstack(panels[:2]), np.hstack(panels[2:])])
            head = np.zeros((28, strip.shape[1], 3), np.uint8)
            cv2.putText(head, f"{clip_id} t{tid} {kind}  tag {tag} src {src}  {o}->{de} {mv}  life "
                        f"{(f1 - f0) / fps:.1f}s  shadows car {car} (green)", (6, 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1, cv2.LINE_AA)
            out = OUT / f"{clip_id}_t{tid}.png"
            cv2.imwrite(str(out), np.vstack([head, strip]))
            print(f"wrote {out}  ({kind}, tag {tag}, src {src}, {o}->{de} {mv})")
        cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
