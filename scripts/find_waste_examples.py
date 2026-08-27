"""Waste-examples selector — concrete scenes of the identity layer
wasting recovered detections, for the operator's diagnosis.

Context (docs/plan_identity_stack_2026-08-25.md, solo-C 2026-08-27):
the yolo26l@1280 detections through the STOCK production stack scored
flat — real recovered vehicles are double-counted, misattributed, or
die uncounted at roughly the rate the deficits heal. This script picks
~8 concrete examples from the 0700 arm (the worst window) into a
manifest the renderer turns into an animated reel. Read-only.

Usage:
  py -X utf8 scripts/find_waste_examples.py
Writes runs/v2_week1/waste_scenes_0700.json
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import numpy as np

from backend.services.detection_cache import parquet_path
from backend.services.pass2_replay import load_dump, tracks_dir
from backend.services.two_pass import _tracks_from_rows

PROJ = "97a7849a"
CAM = 2
FPS = 25.0
ARM_DB = ("data/projects/97a7849a/_replay_scratch/soloc_20260827/"
          "soloc_cam2_study_0700.db")
T_LO, T_HI = 25200.0, 32400.0          # 07:00-09:00 video seconds


def follows(cs, refs, near=40.0, need=0.8):
    hit = sum(1 for ref in refs if any(abs(p[0] - ref[0]) <= 12
              and math.hypot(p[1] - ref[1], p[2] - ref[2]) <= near
              for p in cs))
    return hit >= max(1, int(need * len(refs)))


def track_refs(pts, k=6):
    """k evenly spaced reference points along a track."""
    idx = np.linspace(0, len(pts) - 1, k).astype(int)
    return [pts[i] for i in idx]


def spans(pts):
    return pts[0][0], pts[-1][0]


def main() -> int:
    con = sqlite3.connect(f"file:{ARM_DB}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    arm_ev = [dict(r) for r in con.execute(
        "SELECT event_id, vehicle_track_id AS tid, movement, "
        "origin_leg_id, destination_leg_id, timestamp_video, frame_number "
        "FROM vehicle_events WHERE camera_id=? AND rejected=0 AND "
        "timestamp_video>=? AND timestamp_video<?", (CAM, T_LO, T_HI))]
    legs = {int(r["leg_id"]): r["cardinal_direction"] for r in con.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id=?",
        (CAM,))}
    con.close()

    pcon = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro",
                           uri=True)
    pcon.row_factory = sqlite3.Row
    prod_ev = [dict(r) for r in pcon.execute(
        "SELECT event_id, vehicle_track_id AS tid, movement, "
        "origin_leg_id, timestamp_video FROM vehicle_events WHERE "
        "camera_id=? AND rejected=0 AND timestamp_video>=? AND "
        "timestamp_video<?", (CAM, T_LO, T_HI))]
    chash = pcon.execute("SELECT content_hash FROM videos WHERE camera_id=?",
                         (CAM,)).fetchone()[0]
    pcon.close()

    def bound(o):
        c = legs.get(int(o)) if o is not None else None
        return {"N": "SB", "S": "NB", "E": "WB", "W": "EB"}.get(c, "?")

    def cell(e):
        mv = (e["movement"] or "?").replace("u_turn", "uturn")
        return f'{bound(e["origin_leg_id"])}_{mv}'

    arm = _tracks_from_rows(load_dump(tracks_dir(
        parquet_path(PROJ, CAM, chash, "idc_study_0700"))))
    prod = _tracks_from_rows(load_dump(tracks_dir(
        parquet_path(PROJ, CAM, chash, "study_0700"))))
    arm_sorted = {t: sorted(p) for t, p in arm.items()}
    prod_sorted = {t: sorted(p) for t, p in prod.items()}

    scenes = []

    # ---- 1. DOUBLE-COUNT: overcounted cells, event pairs that ride the
    # same path within 6 s -----------------------------------------------
    over_cells = ("WB_right", "WB_thru", "NB_thru")
    by_cell: dict[str, list] = {}
    for e in arm_ev:
        by_cell.setdefault(cell(e), []).append(e)
    found_pairs = []
    for cl in over_cells:
        evs = sorted(by_cell.get(cl, []), key=lambda e: e["timestamp_video"])
        for i, e1 in enumerate(evs):
            if len(found_pairs) >= 3:
                break
            for e2 in evs[i + 1:]:
                dt = e2["timestamp_video"] - e1["timestamp_video"]
                if dt > 10.0:
                    break
                t1, t2 = int(e1["tid"]), int(e2["tid"])
                if t1 == t2 or t1 not in arm_sorted or t2 not in arm_sorted:
                    continue
                p1, p2 = arm_sorted[t1], arm_sorted[t2]
                if len(p1) < 8 or len(p2) < 8:
                    continue
                # one-directional follow: the SHORTER track's refs must be
                # covered by the longer (a counted fragment shadowing a
                # counted full journey is the common dup shape)
                short, full = (p1, p2) if len(p1) <= len(p2) else (p2, p1)
                if follows(full, track_refs(short)):
                    found_pairs.append((cl, e1, e2))
                    break
        if len(found_pairs) >= 3:
            break
    for cl, e1, e2 in found_pairs[:3]:
        p1 = arm_sorted[int(e1["tid"])]; p2 = arm_sorted[int(e2["tid"])]
        f_lo = min(p1[0][0], p2[0][0]); f_hi = max(p1[-1][0], p2[-1][0])
        scenes.append({
            "klass": "DOUBLE-COUNT", "cell": cl,
            "claim": (f"two counted {cl} events "
                      f"(#{e1['event_id']} and #{e2['event_id']}, "
                      f"{e2['timestamp_video']-e1['timestamp_video']:.1f}s "
                      f"apart) whose tracks ride the same path"),
            "question": "Same physical vehicle counted twice?",
            "arm_tids": [int(e1["tid"]), int(e2["tid"])], "prod_tids": [],
            "event_ids": [e1["event_id"], e2["event_id"]],
            "f_lo": int(f_lo), "f_hi": int(f_hi)})

    # ---- 2. WASTED RECOVERY: novel arm tracks (no production match)
    # that never counted ---------------------------------------------------
    counted_tids = {int(e["tid"]) for e in arm_ev if e["tid"] is not None}
    prod_list = list(prod_sorted.items())
    novel_uncounted, novel_counted_sb = [], []
    for t, pts in arm_sorted.items():
        if len(pts) < 40:               # substantial track, not jitter
            continue
        dist = math.hypot(pts[-1][1] - pts[0][1], pts[-1][2] - pts[0][2])
        if dist < 120:                  # actually travels
            continue
        f0, f1 = spans(pts)
        refs = track_refs(pts)
        matched = any(
            ps[-1][0] >= f0 and ps[0][0] <= f1 and follows(ps, refs)
            for _pt, ps in prod_list
            if len(ps) >= 8)
        if matched:
            continue
        if int(t) not in counted_tids:
            novel_uncounted.append((int(t), pts))
        else:
            novel_counted_sb.append((int(t), pts))
        if len(novel_uncounted) >= 2 and novel_counted_sb:
            break
    for t, pts in novel_uncounted[:2]:
        scenes.append({
            "klass": "WASTED-RECOVERY", "cell": "-",
            "claim": (f"track {t} exists only under the new detector "
                      f"(production never tracked this vehicle), travels "
                      f"{math.hypot(pts[-1][1]-pts[0][1], pts[-1][2]-pts[0][2]):.0f}px, "
                      f"and produced NO count"),
            "question": ("Real vehicle the count missed? And where does "
                         "its track go wrong?"),
            "arm_tids": [t], "prod_tids": [],
            "event_ids": [],
            "f_lo": int(pts[0][0]), "f_hi": int(pts[-1][0])})

    # ---- 3. LOST ATTRIBUTION: production EB_left events whose arm
    # counterpart changed cell or vanished --------------------------------
    lost = []
    arm_by_tid_ev = {}
    for e in arm_ev:
        if e["tid"] is not None:
            arm_by_tid_ev.setdefault(int(e["tid"]), []).append(e)
    for e in prod_ev:
        if len(lost) >= 2:
            break
        if cell(e) != "EB_left" or e["tid"] is None:
            continue
        pt = prod_sorted.get(int(e["tid"]))
        if not pt or len(pt) < 12:
            continue
        refs = track_refs(pt)
        f0, f1 = spans(pt)
        match = None
        for t, ps in arm_sorted.items():
            if ps[-1][0] < f0 or ps[0][0] > f1 or len(ps) < 8:
                continue
            if follows(ps, refs):
                match = int(t)
                break
        if match is None:
            continue
        m_evs = arm_by_tid_ev.get(match, [])
        m_cells = {cell(me) for me in m_evs}
        if "EB_left" in m_cells:
            continue                    # attribution held; not a loss
        new = (sorted(m_cells)[0] if m_cells else "NOT COUNTED")
        lost.append((e, match, new))
    for e, match, new in lost[:2]:
        pt = prod_sorted[int(e["tid"])]
        scenes.append({
            "klass": "LOST-ATTRIBUTION", "cell": "EB_left",
            "claim": (f"production counted event #{e['event_id']} as "
                      f"EB_left; the new arm's track {match} for the same "
                      f"vehicle became: {new}"),
            "question": "Watch the vehicle — which reading is right?",
            "arm_tids": [match], "prod_tids": [int(e["tid"])],
            "event_ids": [e["event_id"]],
            "f_lo": int(pt[0][0]), "f_hi": int(pt[-1][0])})

    # ---- 4. CLEAN RECOVERY: a novel vehicle counted correctly -----------
    for t, pts in novel_counted_sb[:1]:
        evs = arm_by_tid_ev.get(t, [])
        cl = cell(evs[0]) if evs else "?"
        scenes.append({
            "klass": "CLEAN-RECOVERY", "cell": cl,
            "claim": (f"track {t} exists only under the new detector and "
                      f"WAS counted ({cl}, event "
                      f"#{evs[0]['event_id'] if evs else '?'}) — the "
                      f"recovery working as intended"),
            "question": "Real vehicle, correctly counted?",
            "arm_tids": [t], "prod_tids": [],
            "event_ids": [evs[0]["event_id"]] if evs else [],
            "f_lo": int(pts[0][0]), "f_hi": int(pts[-1][0])})

    out = Path("runs/v2_week1/waste_scenes_0700.json")
    out.write_text(json.dumps({"window": "idc_study_0700 vs study_0700",
                               "scenes": scenes}, indent=2))
    print(f"wrote {out} with {len(scenes)} scenes:")
    for i, s in enumerate(scenes, 1):
        print(f"  {i}. [{s['klass']}] {s['claim'][:90]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
