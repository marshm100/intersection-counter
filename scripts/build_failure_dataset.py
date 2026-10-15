"""THE FAILURE DATASET (2026-10-15; plan C:\\Users\\marsh\\.claude\\plans\\proud-wiggling-swan.md step 1).
One row per INSTANCE a human could review, on every labelled journey clip, with runtime-only features and the
truth from the labels:
  C  a COUNTED journey (event)           truth OK / WRONG / DOUBLE / PHANTOM
  U  an UNCOUNTED moving track that crossed a line (gap_items.candidate_items, the gap cards' filter)
                                          truth MISSED (a labelled car the counts lack) / NOT
Features never name a camera or a site. Clips: corridor dev (_m5), corridor held-out (_m50), FM 51 (held-out site).
Truth (journey_eval's own assignment: duplicate labels dropped, one-to-one clicks, a track owned by the car that
entered on it, else the one that left on it):
  C: owned by a full-journey car -> its counted events: the one whose (o, d) is the car's (on its longest track) OK,
     any other DOUBLE; if none matches, the first WRONG and the rest DOUBLE. Owned by no car -> PHANTOM, unless the
     track runs past the clip's edge or is owned by a part-journey label (the clip-end artefact): skipped.
  U: under a click of a full-journey car with NO counted event -> MISSED; owned by a counted car, or by nobody -> NOT.
Usage: .venv/Scripts/python.exe -X utf8 scripts/build_failure_dataset.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.database import leg_geometry_for_camera, list_paths_for_camera  # noqa: E402
from backend.services import journey_eval as je  # noqa: E402
from backend.services.encounter_flags import encounter_flags  # noqa: E402
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.failure_features import c_features, u_features  # noqa: E402
from backend.services.gap_items import candidate_items  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from research_cell_risk import CORR_BASE, FM51_BASE, rows_for  # noqa: E402

CORRIDOR, FM51 = "97a7849a", "0acb12c0"
PAD_S = 60


def clip_sets():
    for proj in (CORRIDOR, FM51):
        for clip in list_clips(proj):
            labels = list_labels(proj, clip["clip_id"])
            if not labels:
                continue
            if proj == FM51:
                part, base, variant = "fm51", FM51_BASE, "vl3_l1_study_" + clip["clip_id"].split("_")[1]
            else:
                part = "heldout" if clip["clip_id"].endswith("_m50") else "dev"
                base, variant = CORR_BASE, "study_" + clip["clip_id"].split("_")[1]
            yield proj, clip, labels, part, base, variant


def load_clip(proj, clip, base, variant, stem):
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    cam = clip["camera_id"]
    chash, fps, width, height = con.execute(
        "SELECT content_hash, fps, width, height FROM videos WHERE video_id=?", (clip["video_id"],)).fetchone()
    con.row_factory = sqlite3.Row
    legs_full = {int(r["leg_id"]): dict(r) for r in con.execute("SELECT * FROM legs WHERE camera_id=?", (cam,))}
    con.close()
    db = base / f"{stem}_cam{cam}_{variant}.db"
    rows = rows_for(proj, cam, chash, variant, db)
    return cam, float(fps), float(width or 640), float(height or 480), legs_full, db, rows


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    out = []
    for proj, clip, labels, part, base, variant in clip_sets():
        cam, fps, fw, fh, legs_full, db, rows = load_clip(proj, clip, base, variant, stem)
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        pad = int(PAD_S * fps)
        win = rows[(rows[:, 1] >= f_lo - pad) & (rows[:, 1] <= f_hi + pad)]
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        d.row_factory = sqlite3.Row
        evs = [dict(r) for r in d.execute(
            "SELECT e.*, f.gate_tag FROM vehicle_events e LEFT JOIN track_fates f ON f.vehicle_track_id = "
            "e.vehicle_track_id AND f.camera_id = e.camera_id AND f.disposition = 'counted' "
            "WHERE e.camera_id=? AND COALESCE(e.rejected,0)=0", (cam,))]
        rejected = {int(r[0]) for r in d.execute(
            "SELECT vehicle_track_id FROM vehicle_events WHERE camera_id=? AND rejected=1", (cam,))}
        d.close()
        # the scorer's assignment
        byf = je.index_rows(rows, f_lo - je.SEARCH_FRAMES, f_hi + je.SEARCH_FRAMES)
        dups = je.duplicate_labels(labels, fps, byf)
        labs = [lb for lb in labels if lb["label_id"] not in dups]
        ein, eout = je._assign_clicks(labs, rows, byf, fps)
        owner: dict = {}
        for side in (eout, ein):
            for lid, t in side.items():
                owner[t] = lid
        lab = {lb["label_id"]: lb for lb in labs}
        full = {lid for lid, lb in lab.items() if lb.get("entry_frame") is not None and lb.get("exit_frame") is not None}
        ev_by_t = defaultdict(list)
        for e in evs:
            ev_by_t[int(e["vehicle_track_id"])].append(e)
        counted_lids = {owner[t] for t in ev_by_t if t in owner}
        # features shared by both instance types
        tag = {int(e["vehicle_track_id"]): e["gate_tag"] for e in evs if e["vehicle_track_id"] is not None}
        fl = encounter_flags(tag, win, fps)
        inclip = [e for e in evs if f_lo <= int(e.get("start_frame") or e["frame_number"]) <= f_hi]
        ctx = {"rows": win, "fps": fps, "fw": fw, "fh": fh, "flags": fl, "events": evs, "tag": tag}
        # C instances
        by_lid = defaultdict(list)
        for e in inclip:
            t = int(e["vehicle_track_id"])
            lid = owner.get(t)
            if lid is None:
                tr = win[win[:, 0] == t]
                if not len(tr) or tr[0, 1] < f_lo or tr[-1, 1] > f_hi:
                    continue                                   # runs past the clip's edge
                truth = "PHANTOM"
            elif lid not in full:
                continue                                       # part-journey label: unknown
            else:
                by_lid[lid].append(e)
                continue
            out.append({"type": "C", "truth": truth, **c_features(e, ctx), **_meta(proj, clip, part, cam, e)})
        for lid, es in by_lid.items():
            lb = lab[lid]
            want = (lb["entry_leg_id"], lb["exit_leg_id"])
            life = {id(e): int((win[:, 0] == int(e["vehicle_track_id"])).sum()) for e in es}
            es = sorted(es, key=lambda e: -life[id(e)])
            ok = next((e for e in es if (e["origin_leg_id"], e["destination_leg_id"]) == want), None)
            for e in es:
                if ok is not None:
                    truth = "OK" if e is ok else "DOUBLE"
                else:
                    truth = "WRONG" if e is es[0] else "DOUBLE"
                out.append({"type": "C", "truth": truth, **c_features(e, ctx), **_meta(proj, clip, part, cam, e)})
        # U instances
        geom = leg_geometry_for_camera(proj, cam)
        gates = build_gates({l: g["mouth"] for l, g in geom.items() if g.get("mouth")},
                            list_paths_for_camera(proj, cam), {l: g.get("heading") for l, g in geom.items()},
                            leg_gates={l: g["gate"] for l, g in geom.items() if g.get("gate")} or None)
        sl = win[(win[:, 1] >= f_lo) & (win[:, 1] <= f_hi)]
        items, _ = candidate_items(win[np.isin(win[:, 0], np.unique(sl[:, 0]))], set(ev_by_t), rejected,
                                   gates, legs_full, fps)
        for it in items:
            if not (f_lo / fps <= it["t_cross"] <= f_hi / fps):
                continue
            lid = owner.get(it["tid"])
            truth = "MISSED" if (lid in full and lid not in counted_lids) else "NOT"
            out.append({"type": "U", "truth": truth, **u_features(it, ctx),
                        **_meta(proj, clip, part, cam, {"vehicle_track_id": it["tid"], "event_id": None})})
        n = Counter((r["type"], r["truth"]) for r in out if r["clip"] == clip["clip_id"] and r["project"] == proj)
        print(f"{proj} {clip['clip_id']:14} ({part}): " + ", ".join(f"{k[0]}:{k[1]} {v}" for k, v in sorted(n.items())),
              flush=True)
    df = pd.DataFrame(out)
    dst = Path(f"runs/v2_week1/failure_dataset_{stem}.parquet")
    df.to_parquet(dst, index=False)
    print(f"\n{len(df)} instances -> {dst}")
    print(df.groupby(["part", "type", "truth"]).size().to_string())
    return 0


def _meta(proj, clip, part, cam, e):
    return {"project": proj, "clip": clip["clip_id"], "part": part, "cam": cam,
            "tid": int(e["vehicle_track_id"]), "event_id": e.get("event_id")}


if __name__ == "__main__":
    raise SystemExit(main())
