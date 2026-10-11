"""Why a labelled vehicle has NO TRACK under a click (2026-10-11, operator: "move to
no-track cars"). Label-free beyond the existing journey labels; dev-validation only.

For every vehicle scored no_track by eval_journeys on an arm, each click that got no
track is put in one bucket:
  CONTESTED   a track was under the click but the one-to-one assignment gave it to
              another labelled vehicle's click (two cars, one track)
  DET_STRONG  no track box here, but the detector had a box under the click at
              conf >= TRACKER_ACTIVATION_THRESHOLD (the tracker dropped a good box)
  DET_WEAK    only boxes under the activation threshold (0.10-0.25) under the click
  NO_DET      no detector box under the click at all (+-2 frames)
plus: the nearest track in time near the click, the box width, the click's distance
from the image edge, and whether the vehicle's OTHER click's track carries a counted
event with the labelled movement (the count may be right though the scorer says no_track).
Usage: .venv\\Scripts\\python.exe -X utf8 scripts/research_no_track.py STEM[:PREFIXES] [--heldout]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import backend.config as cfg  # noqa: E402
from backend.services import journey_eval as je  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from scripts.eval_journeys import PROJ, is_heldout, locate, parse  # noqa: E402

ACT = cfg.TRACKER_ACTIVATION_THRESHOLD
NEAR_S = 3.0          # look this far either side of a click for the nearest track
NEAR_BOXES = 2.0      # ... within this many box widths of the click


def dets_under(det: dict, frame: int, x: float, y: float) -> tuple[float, float | None]:
    """Max confidence and width of detector boxes under the click (padded as the scorer)."""
    best_c, best_w = 0.0, None
    for f in range(frame - je.SEARCH_FRAMES, frame + je.SEARCH_FRAMES + 1):
        d = det.get(f)
        if d is None:
            continue
        cx, cy = (d[:, 0] + d[:, 2]) / 2, (d[:, 1] + d[:, 3]) / 2
        bw, bh = d[:, 2] - d[:, 0], d[:, 3] - d[:, 1]
        m = (np.abs(x - cx) <= bw * (0.5 + je.BOX_PAD)) & (np.abs(y - cy) <= bh * (0.5 + je.BOX_PAD))
        if m.any():
            i = int(np.argmax(np.where(m, d[:, 4], -1)))
            if d[i, 4] > best_c:
                best_c, best_w = float(d[i, 4]), float(bw[i])
    return best_c, best_w


def nearest_track(rows: np.ndarray, frame: int, x: float, y: float, fps: float,
                  w: float | None) -> tuple[float, int] | None:
    """Nearest-in-time track row within NEAR_BOXES widths of the click: (dt seconds, tid)."""
    lo, hi = frame - NEAR_S * fps, frame + NEAR_S * fps
    sel = rows[(rows[:, 1] >= lo) & (rows[:, 1] <= hi)]
    if not len(sel):
        return None
    dist = np.hypot(sel[:, 2] - x, sel[:, 3] - y) / np.maximum(sel[:, 4], w or 1.0)
    sel = sel[dist <= NEAR_BOXES]
    if not len(sel):
        return None
    i = int(np.argmin(np.abs(sel[:, 1] - frame)))
    return float(sel[i, 1] - frame) / fps, int(sel[i, 0])


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    held = "--heldout" in sys.argv
    stem, prefixes = parse(args[0] if args else "dt2c")
    con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
    tot: Counter = Counter()
    for clip in list_clips(PROJ):
        if is_heldout(clip["clip_id"]) != held:
            continue
        labels = list_labels(PROJ, clip["clip_id"])
        if not labels:
            continue
        cam = clip["camera_id"]
        window = "study_" + clip["clip_id"].split("_")[1]
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?",
                                 (clip["video_id"],)).fetchone()
        fps = float(fps)
        db, rows = locate(stem, prefixes, cam, window, chash)
        if db is None:
            continue
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        events = [dict(zip(("vehicle_track_id", "origin_leg_id", "destination_leg_id", "start_frame"), r))
                  for r in d.execute("SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
                                     "COALESCE(start_frame, frame_number) FROM vehicle_events "
                                     "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,))]
        res = je.score_clip(labels, rows, events, clip, fps=fps)
        f_lo, f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        byf = je.index_rows(rows, f_lo - je.SEARCH_FRAMES, f_hi + je.SEARCH_FRAMES)
        dups = je.duplicate_labels(labels, fps, byf)
        lab = {lb["label_id"]: lb for lb in labels if lb["label_id"] not in dups}
        entry_of, exit_of = je._assign_clicks(list(lab.values()), rows, byf, fps)
        first, last = je._ends(rows)
        tbl = pq.read_table(parquet_path(PROJ, cam, chash, window)).to_pandas()
        tbl = tbl[(tbl.frame_idx >= f_lo - 10) & (tbl.frame_idx <= f_hi + 10)]
        det = {int(f): g[["bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"]].to_numpy()
               for f, g in tbl.groupby("frame_idx")}
        ev_by: dict = {}
        for e in events:
            ev_by.setdefault(int(e["vehicle_track_id"]), []).append(e)
        W = float(max(tbl.bbox_x2.max(), 640.0))
        H = float(max(tbl.bbox_y2.max(), 360.0))
        print(f"\n== {clip['clip_id']} ({stem}; fps {fps:g}; frame ~{W:.0f}x{H:.0f})")
        for v in res["per_vehicle"]:
            if v["outcome"] != "no_track":
                continue
            lb = lab[v["label_id"]]
            other_ok = any((e["origin_leg_id"], e["destination_leg_id"]) == v["truth"]
                           for got in (entry_of, exit_of) if v["label_id"] in got
                           for e in ev_by.get(got[v["label_id"]], ()))
            tot["vehicles"] += 1
            if other_ok:
                tot["vehicles counted right via the other click"] += 1
            for side, got, sd, ends in (("entry", entry_of, "in", first), ("exit", exit_of, "out", last)):
                if v["label_id"] in got:
                    continue
                f, x, y = int(lb[f"{side}_frame"]), float(lb[f"{side}_x"]), float(lb[f"{side}_y"])
                cand = je._candidates(byf, ends, f, x, y, fps, sd)
                conf, w = dets_under(det, f, x, y)
                taker = []
                if cand:
                    taker = [lid for lid, t in got.items() if t in cand]
                    kind = "CONTESTED"
                elif conf >= ACT:
                    kind = "DET_STRONG"
                elif conf > 0:
                    kind = "DET_WEAK"
                else:
                    kind = "NO_DET"
                nt = nearest_track(rows, f, x, y, fps, w)
                edge = min(x, y, W - x, H - y)
                tot[kind] += 1
                tot[f"{kind} | {side}"] += 1
                if edge < 20:
                    tot[f"{kind} | within 20px of the edge"] += 1
                near = "none" if nt is None else f"{nt[0]:+.2f}s t{nt[1]}"
                # the vehicle's OWN track from its other click: where was it at this click?
                other = (exit_of if side == "entry" else entry_of).get(v["label_id"])
                own = "no other track"
                if other is not None:
                    tr = rows[rows[:, 0] == other]
                    at = tr[np.abs(tr[:, 1] - f) <= je.SEARCH_FRAMES]
                    if len(at):
                        r = at[np.argmin(np.abs(at[:, 1] - f))]
                        dd = float(np.hypot(r[2] - x, r[3] - y) / max(float(r[4]), 1.0))
                        own = f"own track t{other} HERE, {dd:.1f} box widths from the click"
                        tot[f"{kind} | own track present at the click"] += 1
                        if dd <= 1.0:
                            tot[f"{kind} | own track within 1 box of the click"] += 1
                    else:
                        gap = (float(tr[:, 1].min()) - f if side == "entry" else f - float(tr[:, 1].max())) / fps
                        own = (f"own track t{other} born {gap:+.1f}s after" if side == "entry"
                               else f"own track t{other} ended {gap:+.1f}s before")
                        tot[f"{kind} | own track absent at the click"] += 1
                print(f"      {own}")
                print(f"  car {v['label_id']:4} {side:5} legs {v['truth'][0]}->{v['truth'][1]}  {kind:10} "
                      f"det conf {conf:.2f} w {w or 0:5.1f}px  edge {edge:5.0f}px  nearest track {near}"
                      + (f"  (taken by car {taker})" if kind == "CONTESTED" else "")
                      + ("  [other click's track counted the right movement]" if other_ok else ""))
    print("\nTOTALS (buckets are per missing click):")
    for k, n in sorted(tot.items()):
        print(f"  {k:50} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
