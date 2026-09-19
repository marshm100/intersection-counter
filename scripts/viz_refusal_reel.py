"""Refusal reel for the operator's ruling (Phase B, 2026-09-19).

The held-box guard (TRACKER_RECOVERY_HELD_IOU, the default since 2026-09-15)
refuses a position recovery onto a box that overlaps, IoU >= 0.6, a box some
other id already took this frame. Re-tracked, it cut thefts and breaks on all
three sites, but the film has to say what the refusals ARE: the neighbour's
second box (the guard is right) or the vehicle's own box in traffic (the
guard is refusing its own car). Each clip, full frame, never cropped:
  ORANGE box + path = the id whose recovery was refused (its rg1 track)
  CYAN ring         = the box the id would have taken (refused)
  WHITE ring        = the box another id took this frame, that the cyan box
                      sits on (the holder's id labelled white)
  GREY boxes + ids  = the other tracker ids near the pair
2.5 s either side of the refusal, every frame once (a sprite sheet).
Picks: at least a minute clear of the window ends, the refused box >= 15 px
wide, the id not already picked, evenly through the window; N per site.
Usage: .venv/Scripts/python.exe -X utf8 scripts/viz_refusal_reel.py PROJ CAM VARIANT PREFIX [N]
Writes screenshots/{PREFIX}_sprite_{n}.jpg and screenshots/{PREFIX}_index.json,
and runs/v2_week1/refusals_{proj}_{cam}_{variant}.json (every refusal).
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from viz_theft_reel import ORANGE, CYAN, GREY, BLACK, WHITE, W_OUT, PAD_S, tbox, ring  # noqa: E402


def refusal_run(proj, cam, variant, meta, frame_size):
    """The dump's tracker in process with the refusal log on -> list of records."""
    from backend.services.detection_cache import DetectionCacheReader
    from backend.services.pipeline import _class_agnostic_nms
    from backend.services.tracker import create_tracker_backend
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    pq = parquet_path(proj, cam, chash, variant)
    kw = {}
    if meta.get("lost_buffer") is not None:
        kw["lost_track_buffer"] = int(meta["lost_buffer"])
    be = create_tracker_backend("bytetrack", track_activation_threshold=float(meta["activation"]),
                                minimum_matching_threshold=float(meta["match"]), frame_rate=int(fps),
                                frame_size=frame_size, collect_backfill=True, **kw)
    be.byte_track.refusal_log = []
    nms = meta.get("nms_iou")
    f0, f1 = meta["frames"]
    it = DetectionCacheReader(pq).iter_frames()
    nxt = next(it, None)
    for f in range(f0, f1):
        while nxt is not None and nxt[0] < f:
            nxt = next(it, None)
        dets = []
        if nxt is not None and nxt[0] == f:
            dets = nxt[1]
            nxt = next(it, None)
        if nms is not None and len(dets) > 1:
            dets = _class_agnostic_nms(dets, float(nms))
        be.update(dets, f)
        be.pop_backfill()
    return be.byte_track.refusal_log


def main() -> int:
    proj, cam, variant, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    n_pick = int(sys.argv[5]) if len(sys.argv) > 5 else 2
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    vpath, chash, fps, vw, vh = con.execute(
        "SELECT path, content_hash, fps, width, height FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    d = tracks_dir(parquet_path(proj, cam, chash, variant))
    meta = json.loads((d / "meta.json").read_text())
    assert meta.get("recovery_guard") and meta["recovery_guard"]["held_iou"] > 0, "not a guarded dump"
    rows = np.asarray(load_dump(d))
    rows_f = rows[np.argsort(rows[:, 1], kind="stable")]
    uf, s_ = np.unique(rows_f[:, 1], return_index=True)
    e_ = np.append(s_[1:], len(rows_f))
    fidx = dict(zip(uf.astype(int), zip(s_, e_)))
    by_id = defaultdict(list)
    for r in rows:
        by_id[int(r[0])].append(r)

    log = refusal_run(proj, cam, variant, meta, (int(vw), int(vh)) if vw and vh else None)
    events = []
    for f, tid, was_lost, age, det, conf, hbox, hid, hiou in log:
        trk = by_id.get(tid, [])
        after = [r for r in trk if f < r[1] <= f + fps]      # the id's own rows in the next second
        events.append({"f": int(f), "track": int(tid), "lost": bool(was_lost), "age": int(age),
                       "box": list(det), "conf": round(conf, 2), "held_box": list(hbox), "held_id": int(hid),
                       "held_iou": round(hiou, 2), "w": round(det[2] - det[0], 1),
                       "seen_next_s": len(after)})
    f_lo, f_hi = float(rows[:, 1].min()) + 60 * fps, float(rows[:, 1].max()) - 60 * fps
    out = Path(f"runs/v2_week1/refusals_{proj}_{cam}_{variant}.json")
    out.write_text(json.dumps(events))
    n_lost = sum(1 for e in events if e["lost"])
    n_seen = sum(1 for e in events if e["seen_next_s"] > 0)
    med = np.median([e["conf"] for e in events]) if events else 0.0
    print(f"{proj} cam{cam} {variant}: {len(events)} refusals ({n_lost} of lost ids); "
          f"the id was seen again within 1 s after {n_seen} of them; conf median {med:.2f}; -> {out}")

    pool = [e for e in events if f_lo <= e["f"] <= f_hi and e["w"] >= 15]
    pool.sort(key=lambda e: e["f"])
    picks, used = [], set()
    if pool:
        targets = np.linspace(0, len(pool) - 1, n_pick + 2)[1:-1]
        for t in targets:
            order = sorted(range(len(pool)), key=lambda i: abs(i - t))
            for i in order:
                if pool[i]["track"] not in used:
                    picks.append(pool[i])
                    used.add(pool[i]["track"])
                    break
    picks.sort(key=lambda e: e["f"])
    print(f"  {len(pool)} filmable; filming {len(picks)}")

    cap = cv2.VideoCapture(vpath)
    index = []
    for n, e in enumerate(picks, 1):
        tid, fr0 = e["track"], e["f"]
        trk = np.asarray(sorted(by_id[tid], key=lambda r: r[1]))
        f_lo_, f_hi_ = int(fr0 - PAD_S * fps), int(fr0 + PAD_S * fps)
        frames = []
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo_)
        refs = [e["box"], e["held_box"]]
        for fno in range(f_lo_, f_hi_ + 1):
            ok, fr = cap.read()
            if not ok:
                break
            sc = W_OUT / fr.shape[1]
            im = cv2.resize(fr, (W_OUT, int(fr.shape[0] * sc)))
            ab = fidx.get(fno)
            if ab is not None:
                for r in rows_f[ab[0]:ab[1]]:
                    if int(r[0]) == tid:
                        continue
                    b = tbox(r)
                    cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
                    if any(abs(cx - (q[0] + q[2]) / 2) < 2.5 * (q[2] - q[0]) and
                           abs(cy - (q[1] + q[3]) / 2) < 2.5 * (q[2] - q[0]) for q in refs):
                        x1, y1, x2, y2 = (int(q * sc) for q in b)
                        col = WHITE if int(r[0]) == e["held_id"] else GREY
                        cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 3)
                        cv2.rectangle(im, (x1, y1), (x2, y2), col, 1)
                        cv2.putText(im, str(int(r[0])), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, BLACK, 3)
                        cv2.putText(im, str(int(r[0])), (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.42, col, 1)
            seen = trk[trk[:, 1] <= fno]
            if len(seen) >= 2:
                pth = (np.stack([seen[:, 2], seen[:, 3] + seen[:, 5] / 2.0], axis=1) * sc).astype(int)
                cv2.polylines(im, [pth], False, BLACK, 4)
                cv2.polylines(im, [pth], False, ORANGE, 2)
            cur = trk[trk[:, 1] == fno]
            if len(cur):
                x1, y1, x2, y2 = (int(q * sc) for q in tbox(cur[0]))
                cv2.rectangle(im, (x1, y1), (x2, y2), BLACK, 5)
                cv2.rectangle(im, (x1, y1), (x2, y2), ORANGE, 3)
                cv2.putText(im, str(tid), (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, BLACK, 4)
                cv2.putText(im, str(tid), (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, ORANGE, 1)
            if fno == fr0:
                ring(im, e["held_box"], WHITE, sc)
                ring(im, e["box"], CYAN, sc)
            cv2.rectangle(im, (0, 0), (W_OUT, 50), BLACK, -1)
            head = f"#{n}  ORANGE = id {tid}   CYAN ring = the refused box   WHITE ring = box held by id {e['held_id']}"
            cv2.putText(im, head, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.47, WHITE, 1)
            cv2.putText(im, f"f{fno}   {(fno - fr0) / fps:+.1f}s from the refusal", (8, 42),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, WHITE, 1)
            frames.append(im)
        fh, fw = frames[0].shape[:2]
        cols = 8
        sheet = np.zeros((((len(frames) + cols - 1) // cols) * fh, cols * fw, 3), dtype=np.uint8)
        for i, im in enumerate(frames):
            r_, c_ = divmod(i, cols)
            sheet[r_ * fh:(r_ + 1) * fh, c_ * fw:(c_ + 1) * fw] = im
        sprite = Path(f"screenshots/{prefix}_sprite_{n}.jpg")
        cv2.imwrite(str(sprite), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
        index.append({**e, "clip": n, "first_frame": f_lo_, "frames": len(frames), "switch_index": fr0 - f_lo_,
                      "fps": fps, "sprite": str(sprite), "w_px": fw, "h_px": fh, "cols": cols})
        print(f"  #{n} id {tid} at f{fr0}: refused a {e['w']:.0f} px box (conf {e['conf']}, IoU {e['held_iou']} "
              f"with the box of id {e['held_id']}); lost {e['lost']} age {e['age']}; seen again in the next s: "
              f"{e['seen_next_s']} frames -> {sprite}")
    Path(f"screenshots/{prefix}_index.json").write_text(json.dumps(index, indent=1))
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
