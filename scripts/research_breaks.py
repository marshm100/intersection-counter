"""Why does a track break? The miss log joined to the break events (plan
ok-plan-it-out-breezy-kernighan.md, 2026-09-19; operator method: instrument first).

A BREAK (research_tracker_break.label_hits): a yardstick chain's hit k is
labelled with dump id A and hit k+1 with a different id or none. The break
yardstick only sees the dump's output boxes (Kalman posteriors); this script
re-runs the dump's tracker in process with the match log and the MISS LOG on
(tracker.py `miss_log`: every track that ends a frame without a box, with its
PREDICTED box and its LAST OBSERVED box) and, for every break, says what
happened to the vehicle's next real box at frame f_{k+1}:
  NOT_IN_INPUT        the box never reached the tracker (conf <= 0.10, or dropped
                      by the 0.8 input dedup)
  LABEL_ARTEFACT      id A DID take the box; the yardstick labelled the hit with
                      a twin whose posterior overlapped it better
  TAKEN               another id took the box (which id, which stage, twin or not)
  ID_MATCHED_ELSEWHERE id A took a different box that frame (it left the vehicle)
  MISSED              id A was in the pool and ended the frame without a box: the
                      FIRST FAILING GATE in stage order (stage 1 fused IoU x conf
                      >= 0.2 / stage 2 IoU >= 0.5 / recovery: patience, size
                      ratio, min IoU 0.2, held guard, reach 0.9), and whether the
                      LAST OBSERVED box would have passed where the prediction
                      failed (the "prediction worse than observation" hypothesis)
  NO_RECORD           neither matched nor missed (removed by edge exit / age /
                      dedup before f_{k+1}, or f_{k+1} beyond the id's life)
  BACKFILL_AT_K       hit k's id came from a back-filled row (not a live track)
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_breaks.py PROJ CAM VARIANT
Writes runs/v2_week1/breaks_<proj>_<cam>_<variant>.json (every break, every field).
"""
from __future__ import annotations

import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from research_tracker_break import base_variant, label_hits  # noqa: E402
from research_thefts import iou_mat  # noqa: E402

FUSED_MIN = 0.2       # stage 1: match_thresh 0.8 on 1 - IoU x conf
S2_IOU = 0.5          # stage 2
BOX_MATCH = 0.9       # "the same detection" between the chain hit and the tracker's input / a match record
MAP_IOU = 0.95        # dump output box == in-process output box


def recipe_check(meta: dict) -> None:
    """The in-process backend is built from the live config: it must equal the dump's recipe."""
    from backend import config as c
    from backend.services import two_pass as tp
    want = {"fuse_score": bool(c.TRACKER_FUSE_SCORE),
            "position_recovery": bool(c.TRACKER_POSITION_RECOVERY),
            "recovery_min_iou": float(c.TRACKER_RECOVERY_MIN_IOU),
            "recovery_guard": tp._cfg_recovery_guard(),
            "confirm_by_position": bool(c.TRACKER_CONFIRM_BY_POSITION),
            "edge_exit": bool(c.TRACKER_EDGE_EXIT),
            "dup_box_iou": float(c.TRACKER_DUP_BOX_IOU),
            "stack_iou": float(c.TRACKER_STACK_IOU),
            "weak_birth": tp._cfg_weak_birth()}
    bad = {k: (meta.get(k), v) for k, v in want.items() if meta.get(k) != v}
    assert not bad, f"dump recipe differs from the live config: {bad}"
    assert float(meta.get("bbox_buffer") or 1.0) == 1.0, "bbox buffer != 1 not reproduced"
    assert meta.get("resumed") in (None, False, 0), "a resumed dump is not reproduced"


def run(proj: str, cam: int, variant: str, meta: dict, frame_size):
    """The dump's tracker in process, match + miss logs on. Returns inputs
    {f: (boxes (N,4), confs (N,), kept mask (N,))}, by_box {f: [(box, id)]},
    match {(f, id): rec}, match_by_frame {f: [rec]}, miss {(f, id): rec},
    miss_by_id {id: [rec]} and the backend."""
    from backend.services.detection_cache import DetectionCacheReader
    from backend.services.pipeline import _class_agnostic_nms
    from backend.services.tracker import _dedup_boxes, create_tracker_backend
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    pq = parquet_path(proj, cam, chash, variant)
    kw = {}
    if meta.get("lost_buffer") is not None:
        kw["lost_track_buffer"] = int(meta["lost_buffer"])
    be = create_tracker_backend("bytetrack", track_activation_threshold=float(meta["activation"]),
                                minimum_matching_threshold=float(meta["match"]), frame_rate=int(fps),
                                frame_size=frame_size, collect_backfill=True, **kw)
    bt = be.byte_track
    bt.match_log = []
    bt.miss_log = []
    nms = meta.get("nms_iou")
    dup = float(getattr(be, "dup_box_iou", 0.0))
    f0, f1 = meta["frames"]
    inputs, by_box = {}, {}
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
        kept = dets
        if dup > 0 and len(dets) > 1:
            kept = _dedup_boxes(dets, dup)          # idempotent: be.update repeats it without effect
        kept_ids = {id(d) for d in kept}
        if dets:
            inputs[f] = (np.asarray([d["bbox"] for d in dets], dtype=np.float64),
                         np.asarray([float(d["confidence"]) for d in dets], dtype=np.float64),
                         np.asarray([id(d) in kept_ids for d in dets], dtype=bool))
        out = be.update(kept, f)
        by_box[f] = [(r["bbox"], int(r["track_id"])) for r in out]
        be.pop_backfill()
    match = {(r[0], r[1]): r for r in bt.match_log}
    match_by_frame = defaultdict(list)
    for r in bt.match_log:
        match_by_frame[r[0]].append(r)
    miss = {(r[0], r[1]): r for r in bt.miss_log}
    miss_by_id = defaultdict(list)
    for r in bt.miss_log:
        miss_by_id[r[1]].append(r)
    return inputs, by_box, match, match_by_frame, miss, miss_by_id, be


def rec_cost(track_box, det_box, size_ratio: float):
    """_recovery_cost for one pair: (cost in widths or inf, width ratio)."""
    tw, dw = track_box[2] - track_box[0], det_box[2] - det_box[0]
    if tw <= 0 or dw <= 0:
        return math.inf, 0.0
    tc = ((track_box[0] + track_box[2]) / 2, (track_box[1] + track_box[3]) / 2)
    dc = ((det_box[0] + det_box[2]) / 2, (det_box[1] + det_box[3]) / 2)
    ratio = min(tw, dw) / max(tw, dw)
    cost = math.hypot(tc[0] - dc[0], tc[1] - dc[1]) / max(tw, dw)
    return (cost if ratio >= size_ratio else math.inf), ratio


def main() -> int:
    proj, cam, variant = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps, vw, vh = con.execute("SELECT content_hash, fps, width, height FROM videos WHERE camera_id=?",
                                     (cam,)).fetchone()
    fps = float(fps)
    d = tracks_dir(parquet_path(proj, cam, chash, variant))
    meta = json.loads((d / "meta.json").read_text())
    recipe_check(meta)
    f0, f1 = meta["frames"]
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    rows = np.asarray(load_dump(d))
    rows = rows[np.argsort(rows[:, 1], kind="stable")]
    ufr, s_ = np.unique(rows[:, 1], return_index=True)
    e_ = np.append(s_[1:], len(rows))
    fidx = dict(zip(ufr.astype(int), zip(s_, e_)))
    backfill = set()
    bf = d / "backfill.npy"
    if bf.exists():
        arr = np.load(bf)
        backfill = {(int(r[0]), int(r[1])) for r in arr}
    print(f"{proj} cam{cam} {variant}: {len(rows)} dump rows, {len(veh)} yardstick vehicles, "
          f"{len(backfill)} back-fill rows, stop-fracture relabels {meta.get('stop_fracture_collapsed')}")

    inputs, by_box, match, match_by_frame, miss, miss_by_id, be = run(
        proj, cam, variant, meta, (int(vw), int(vh)) if vw and vh else None)
    bt = be.byte_track
    patience = int(bt.lost_patience_frames)
    activation = float(meta["activation"])
    size_ratio = float(bt.recovery_size_ratio)
    reach = float(bt.recovery_reach)
    min_iou = float(bt.recovery_min_iou)
    held_iou = float(getattr(bt, "recovery_held_iou", 0.0))
    print(f"  in-process run: {len(match)} matches, {len(miss)} miss records; patience {patience} f, "
          f"reach {reach}, min IoU {min_iou}, held {held_iou}")

    # ---- the break events (exactly as timeline) ----
    labelled = label_hits(veh, rows, fidx)
    events = []
    n_end = 0
    for vi, tl in enumerate(labelled):
        for k in range(len(tl) - 1):
            cur, nxt = tl[k], tl[k + 1]
            if cur[3] is None or nxt[3] == cur[3]:
                continue
            if nxt[0] >= f1:
                n_end += 1
                continue
            events.append({"veh": vi, "k": k, "f_k": int(cur[0]), "A": int(cur[3]), "det_k": [float(v) for v in cur[1]],
                           "conf_k": float(cur[2]), "dump_box_k": [float(v) for v in cur[4]],
                           "f_n": int(nxt[0]), "B": (int(nxt[3]) if nxt[3] is not None else None),
                           "det_n": [float(v) for v in nxt[1]], "conf_n": float(nxt[2]),
                           "gap": int(nxt[0] - cur[0]), "x": float(cur[1][2]),
                           "w_n": float(nxt[1][2] - nxt[1][0]), "next_is_backfill": bool(
                               nxt[3] is not None and (int(nxt[3]), int(nxt[0])) in backfill)})
    print(f"  breaks {len(events) + n_end} (as the yardstick counts them); {n_end} at the window end dropped "
          f"(the dump stops at f1); {len(events)} joined")

    # ---- map dump id A at f_k to the in-process id ----
    mapping = Counter()
    for e in events:
        boxes = by_box.get(e["f_k"], [])
        ip = None
        same = [b for b, t in boxes if t == e["A"]]
        if same and float(iou_mat(np.asarray([e["dump_box_k"]]), np.asarray(same))[0].max()) > MAP_IOU:
            ip = e["A"]; mapping["same id"] += 1
        elif boxes:
            m = iou_mat(np.asarray([e["dump_box_k"]]), np.asarray([b for b, _ in boxes]))[0]
            j = int(m.argmax())
            if m[j] > MAP_IOU:
                ip = boxes[j][1]; mapping["by box (relabelled)"] += 1
        if ip is None:
            if (e["A"], e["f_k"]) in backfill:
                e["cls"] = "BACKFILL_AT_K"; mapping["BACKFILL_AT_K"] += 1
            else:
                e["cls"] = "UNMAPPED"; mapping["UNMAPPED"] += 1
        e["ip"] = ip
    print("  mapping: " + ", ".join(f"{k} {v}" for k, v in mapping.most_common()))

    # ---- classify at f_n ----
    for e in events:
        if e.get("cls"):
            continue
        ip, fn, det_n = e["ip"], e["f_n"], np.asarray([e["det_n"]])
        # the tracker's input at f_n
        inp = inputs.get(fn)
        in_conf = None
        if inp is not None and len(inp[0]):
            m = iou_mat(det_n, inp[0])[0]
            j = int(m.argmax())
            if m[j] > BOX_MATCH:
                if not inp[2][j]:
                    e["cls"] = "NOT_IN_INPUT"; e["why"] = "dropped by input dedup"
                    continue
                in_conf = float(inp[1][j])
        if in_conf is None:
            e["cls"] = "NOT_IN_INPUT"
            e["why"] = "conf <= 0.10" if e["conf_n"] <= 0.10 else "not in the cache frame"
            continue
        e["conf_in"] = in_conf
        # the BOX's fate this frame (independent of id A): free / taken by an existing
        # id at a stage / born as a new id / confirmed a newborn
        taker = None
        for r in match_by_frame.get(fn, []):
            if r[1] != ip and float(iou_mat(det_n, np.asarray([r[6]]))[0, 0]) > BOX_MATCH:
                taker = r
                break
        if taker is not None:
            e["taker"] = int(taker[1]); e["taker_stage"] = taker[2]; e["taker_lost"] = bool(taker[3])
            tb = [b for b, t in by_box.get(e["f_k"], []) if t == taker[1]]
            e["twin"] = bool(tb and float(iou_mat(np.asarray([e["det_k"]]), np.asarray(tb))[0].max()) >= 0.5)
            e["box_fate"] = ("new id" if taker[2] in ("birth", "confirm_pos", "unconf")
                             else ("twin " + taker[2] if e["twin"] else "other id " + taker[2]))
        else:
            e["box_fate"] = "free"
        # id A's status this frame
        own = match.get((fn, ip))
        if own is not None and float(iou_mat(det_n, np.asarray([own[6]]))[0, 0]) > BOX_MATCH:
            e["cls"] = "LABEL_ARTEFACT"; e["stage"] = own[2]
            continue
        if own is not None:
            e["cls"] = "ID_MATCHED_ELSEWHERE"; e["stage"] = own[2]
            e["other_iou"] = round(float(iou_mat(det_n, np.asarray([own[6]]))[0, 0]), 3)
            c1 = ((own[6][0] + own[6][2]) / 2, (own[6][1] + own[6][3]) / 2)
            c2 = ((e["det_n"][0] + e["det_n"][2]) / 2, (e["det_n"][1] + e["det_n"][3]) / 2)
            e["other_dist_w"] = round(math.hypot(c1[0] - c2[0], c1[1] - c2[1]) / max(1.0, e["w_n"]), 2)
            continue
        rec = miss.get((fn, ip))
        if rec is None:
            e["cls"] = "NO_RECORD"
            prev = [r for r in miss_by_id.get(ip, []) if r[0] < fn]
            e["last_fate"] = int(prev[-1][10]) if prev else None
            e["last_miss_age"] = int(fn - prev[-1][0]) if prev else None
            e["alive_after"] = bool(any(t == ip for _, t in by_box.get(fn, [])))
            continue
        # ---- MISSED: the gates ----
        _, _, was_lost, age, pred, obs, kvx, kvy, ovx, ovy, fate = rec
        e["cls"] = "MISSED"; e["lost"] = bool(was_lost); e["age"] = int(age); e["fate"] = int(fate)
        e["pred"] = list(pred); e["obs"] = (list(obs) if obs is not None else None)
        iou_p = float(iou_mat(det_n, np.asarray([pred]))[0, 0])
        iou_o = float(iou_mat(det_n, np.asarray([obs]))[0, 0]) if obs is not None else 0.0
        conf = in_conf
        e["iou_pred"] = round(iou_p, 3); e["iou_obs"] = round(iou_o, 3)
        e["fused_pred"] = round(iou_p * conf, 3); e["fused_obs"] = round(iou_o * conf, 3)
        cp, rp = rec_cost(pred, e["det_n"], size_ratio)
        co, ro = rec_cost(obs, e["det_n"], size_ratio) if obs is not None else (math.inf, 0.0)
        e["cost_pred"] = (round(cp, 3) if math.isfinite(cp) else None)
        e["cost_obs"] = (round(co, 3) if math.isfinite(co) else None)
        e["ratio_pred"] = round(rp, 3); e["ratio_obs"] = round(ro, 3)
        held = [b for b, t in by_box.get(fn, [])
                if (fn, t) in match and match[(fn, t)][2] in ("s1", "s2")]
        e["held_overlap"] = round(float(iou_mat(det_n, np.asarray(held))[0].max()), 3) if held else 0.0
        # conf class and the ordinary stage
        if conf > activation:
            e["box"] = "high"
            gate1 = "s1_fused<0.2" if iou_p * conf < FUSED_MIN else "s1_assignment_lost"
            e["obs_passes_stage"] = bool(iou_o * conf >= FUSED_MIN)
        elif conf > 0.10:
            e["box"] = "low"
            if was_lost:
                gate1 = "s2_ineligible(lost)"
                e["obs_passes_stage"] = None
            else:
                gate1 = "s2_iou<0.5" if iou_p < S2_IOU else "s2_assignment_lost"
                e["obs_passes_stage"] = bool(iou_o >= S2_IOU)
        else:
            e["box"] = "none"
            gate1 = "no_stage(conf==0.10/0.25)"
            e["obs_passes_stage"] = None
        e["gate1"] = gate1
        # recovery (stage 2.5)
        if was_lost and age > patience:
            gate2 = "lost_age>patience"
        elif not math.isfinite(cp) and not math.isfinite(co):
            gate2 = "size_ratio<0.3"
        elif max(iou_p, iou_o) < min_iou:
            gate2 = "min_iou<0.2"
        elif held_iou > 0 and e["held_overlap"] >= held_iou:
            gate2 = "held_guard"
        elif min(cp, co) >= reach:
            gate2 = "reach>=0.9"
        else:
            gate2 = "recovery_unexplained"
        e["gate2"] = gate2
        e["obs_passes_recovery"] = bool(obs is not None and iou_o >= min_iou and math.isfinite(co) and co < reach
                                        and e["held_overlap"] < held_iou)
        # error vectors in next-box widths, velocities
        nc = ((e["det_n"][0] + e["det_n"][2]) / 2, (e["det_n"][1] + e["det_n"][3]) / 2)
        pc = ((pred[0] + pred[2]) / 2, (pred[1] + pred[3]) / 2)
        w = max(1.0, e["w_n"])
        e["err_pred_w"] = round(math.hypot(pc[0] - nc[0], pc[1] - nc[1]) / w, 3)
        if obs is not None:
            oc = ((obs[0] + obs[2]) / 2, (obs[1] + obs[3]) / 2)
            e["err_obs_w"] = round(math.hypot(oc[0] - nc[0], oc[1] - nc[1]) / w, 3)
            e["pred_w_over_obs_w"] = round((pred[2] - pred[0]) / max(1.0, obs[2] - obs[0]), 3)
        else:
            e["err_obs_w"] = None; e["pred_w_over_obs_w"] = None
        lc = None
        if obs is not None:
            lc = ((obs[0] + obs[2]) / 2, (obs[1] + obs[3]) / 2)
            # what the car actually did since the last observation vs what the filter thought
            e["actual_v_w"] = round(math.hypot(nc[0] - lc[0], nc[1] - lc[1]) / w / max(1, age), 3)
            e["kf_v_w"] = round(math.hypot(kvx, kvy) / w, 3)
            e["obs_v_w"] = (round(math.hypot(ovx, ovy) / w, 3) if not math.isnan(ovx) else None)
        e["kf_v"] = [round(kvx, 2), round(kvy, 2)]
        e["obs_v"] = [None if math.isnan(ovx) else round(ovx, 2), None if math.isnan(ovy) else round(ovy, 2)]

    # ---- tables ----
    cls = Counter(e["cls"] for e in events)
    print("  id A at f_n: " + "  ".join(f"{k} {cls[k]}" for k in
          ("MISSED", "ID_MATCHED_ELSEWHERE", "LABEL_ARTEFACT", "NO_RECORD", "NOT_IN_INPUT", "BACKFILL_AT_K", "UNMAPPED")))
    nii = Counter(e.get("why") for e in events if e["cls"] == "NOT_IN_INPUT")
    if nii:
        print("     NOT_IN_INPUT: " + ", ".join(f"{k} {v}" for k, v in nii.most_common()))
    bf_ = Counter(e.get("box_fate", "-") for e in events)
    print("  the next real box at f_n: " + ", ".join(f"{k} {v}" for k, v in bf_.most_common()))
    print("  id A status x box fate:")
    for (c, b), n in Counter((e["cls"], e.get("box_fate", "-")) for e in events).most_common(14):
        print(f"     {n:5d}  {c:<22} {b}")
    nr = [e for e in events if e["cls"] == "NO_RECORD"]
    if nr:
        ft = Counter((e["last_fate"], e["alive_after"]) for e in nr)
        print("     NO_RECORD (last fate, alive at f_n): " + ", ".join(f"{k} {v}" for k, v in ft.most_common(8)))
    ms = [e for e in events if e["cls"] == "MISSED"]
    print(f"  MISSED {len(ms)}: by box class x state: " + ", ".join(
        f"{k[0]}/{'lost' if k[1] else 'tracked'} {v}" for k, v in
        Counter((e["box"], e["lost"]) for e in ms).most_common()))
    print("     gate 1 (the ordinary stage): " + ", ".join(f"{k} {v}" for k, v in Counter(e["gate1"] for e in ms).most_common()))
    print("     gate 2 (recovery):           " + ", ".join(f"{k} {v}" for k, v in Counter(e["gate2"] for e in ms).most_common()))
    print("     gate 1 x gate 2 (top 10):")
    for (g1, g2), n in Counter((e["gate1"], e["gate2"]) for e in ms).most_common(10):
        sub = [e for e in ms if e["gate1"] == g1 and e["gate2"] == g2]
        ops = [e["obs_passes_stage"] for e in sub if e["obs_passes_stage"] is not None]
        opr = [e["obs_passes_recovery"] for e in sub]
        print(f"        {n:5d}  {g1:<28} {g2:<22} obs would pass the stage {sum(ops)}/{len(ops)}   "
              f"obs would pass recovery {sum(opr)}/{len(opr)}   "
              f"IoU pred med {np.median([e['iou_pred'] for e in sub]):.2f}  IoU obs med {np.median([e['iou_obs'] for e in sub]):.2f}  "
              f"conf med {np.median([e['conf_in'] for e in sub]):.2f}  w med {np.median([e['w_n'] for e in sub]):.0f} px")
    ep = [e["err_pred_w"] for e in ms]
    eo = [e["err_obs_w"] for e in ms if e["err_obs_w"] is not None]
    both = [(e["err_pred_w"], e["err_obs_w"]) for e in ms if e["err_obs_w"] is not None]
    if ms:
        print(f"     prediction error median {np.median(ep):.2f} widths; last-observation error median "
              f"{np.median(eo) if eo else float('nan'):.2f}; observation closer than prediction in "
              f"{sum(1 for p, o in both if o < p)} of {len(both)}; pred width / obs width median "
              f"{np.median([e['pred_w_over_obs_w'] for e in ms if e['pred_w_over_obs_w'] is not None]):.2f}")
        far = [e for e in ms if e["x"] >= 550]
        print(f"     x >= 550 (cam4's floor band): {len(far)} of the MISSED; gate 2 there: " + ", ".join(
            f"{k} {v}" for k, v in Counter(e["gate2"] for e in far).most_common(4)))
        for name, sub in (("gap == 1 (next hit the very next frame)", [e for e in ms if e["gap"] == 1]),
                          ("gap > 1", [e for e in ms if e["gap"] > 1])):
            if not sub:
                continue
            av = [e["actual_v_w"] for e in sub if e.get("actual_v_w") is not None]
            kv = [e["kf_v_w"] for e in sub if e.get("kf_v_w") is not None]
            print(f"     {name}: {len(sub)}; gap median {np.median([e['gap'] for e in sub]):.0f}; "
                  f"pred err med {np.median([e['err_pred_w'] for e in sub]):.2f} w, obs err med "
                  f"{np.median([e['err_obs_w'] for e in sub if e['err_obs_w'] is not None]):.2f} w; "
                  f"actual speed med {np.median(av) if av else float('nan'):.2f} w/f vs Kalman {np.median(kv) if kv else float('nan'):.2f} w/f; "
                  f"box fate: " + ", ".join(f"{k} {v}" for k, v in Counter(e["box_fate"] for e in sub).most_common(4)))
        print("     MISSED by box fate x gate 2:")
        for (b, g), n in Counter((e["box_fate"], e["gate2"]) for e in ms).most_common(10):
            print(f"        {n:5d}  {b:<22} {g}")
    out = Path(f"runs/v2_week1/breaks_{proj}_{cam}_{variant}.json")
    out.write_text(json.dumps(events, default=lambda o: o.item() if hasattr(o, "item") else str(o)))
    print(f"  -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
