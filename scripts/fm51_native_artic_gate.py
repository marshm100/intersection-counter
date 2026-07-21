"""FM51 held-out gate for NATIVE ARTICULATED wiring
(plan_articulated_native_2026-07-17).

Re-detects the audited FM51 windows (AM 07-09, PM 16-18) with the PROMOTED
fine-tuned model under the native class map (0->2, 1->8, 2->7 — detector
_FT_CLASS_MAP after the native-articulated revision), writes cache variants
ftv1n_am/pm, tracks with production pass-1, replays through the production
chain (through-gate applied to the out DBs, mirroring the promotion gate's
scoring basis), and scores:

  1. Articulated: our fhwa-9 events vs Miovision's Articulated Trucks over
     the same 15-min intervals (dev scorer ONLY — FM51 trains nothing).
  2. No-regression: window totals + per-interval error vs the promoted ftv1
     baseline (runs/finetune_v1/fm51_fullchain.json) — classes 0/2 mapping
     is unchanged, so totals should be near-identical.

Usage:  py scripts/fm51_native_artic_gate.py        # all stages, resumable
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PROJECT = "0acb12c0"
CAMERA = 2
# The flow below is the FROZEN gate; only these three pointers move per
# candidate model (plan_finetune_v2_retrain_2026-07-20 — env overrides, v1
# defaults so the promoted-model invocation stays bit-reproducible).
# finetune_v2 invocation:
#   GATE_WEIGHTS=<runs/finetune_v2 best export>  GATE_VARIANT=ftv2n \
#   GATE_CLASS_MAP=0:2,1:8,2:9,3:9  py scripts/fm51_native_artic_gate.py
import os as _os
WEIGHTS = _os.environ.get(
    "GATE_WEIGHTS",
    "yolo26s_ft1_openvino_model")        # the PROMOTED export (imgsz 640 baked)
CONF = 0.10                              # the balanced profile's floor
CLASS_MAP = ({int(k): int(v) for k, v in
              (kv.split(":") for kv in _os.environ["GATE_CLASS_MAP"].split(","))}
             if _os.environ.get("GATE_CLASS_MAP")
             else {0: 2, 1: 8, 2: 7})    # native scheme (plan_articulated_native)
_VAR = _os.environ.get("GATE_VARIANT", "ftv1n")
WINDOWS = [(f"{_VAR}_am", "07:00", "09:00"), (f"{_VAR}_pm", "16:00", "18:00")]
SCRATCH = Path(r"C:\Users\onkar\AppData\Local\Temp\ic_scratch_fm51")
BASELINE = Path("runs/finetune_v1/fm51_fullchain.json")
XML = Path("docs/historic data/26097 TIA for Wise County, TX/Cam 1 FM51-CORD4699/"
           "405051_0029_20260430_000003_FM51-CORD4699_1398466_04-30-2026.xml")
_MIO_GROUP = {"Lights": "Lights", "Mediums": "Mediums",
              "Articulated Trucks": "Articulated Trucks"}


def _video():
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    conn.row_factory = sqlite3.Row
    v = dict(conn.execute(
        "SELECT * FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (CAMERA,)).fetchone())
    conn.close()
    return v


def _iv(dt):
    return dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)


def load_mio_per_interval_class():
    """{(interval, group): n} and {interval: total} from the Miovision XML."""
    txt = re.sub(r"<\?xml[^>]*\?>", "", XML.read_text(encoding="utf-8-sig"),
                 count=1).lstrip()
    root = ET.fromstring(txt)
    s = lambda t: t.split("}")[-1]
    per_iv_cls = defaultdict(int)
    per_iv = defaultdict(int)
    for g in (x for x in root.iter() if s(x.tag) == "Group"):
        cls = _MIO_GROUP.get(g.findtext("Name") or g.get("Name"), "Lights")
        for b in (x for x in g.iter() if s(x.tag) == "Bin"):
            t = datetime.fromisoformat(b.findtext("Time"))
            iv = _iv(t)
            for v in b.find("volumes"):
                per_iv_cls[(iv, cls)] += int(v.text)
                per_iv[iv] += int(v.text)
    return dict(per_iv_cls), dict(per_iv)


def stage_a_detect(v, chash):
    import cv2
    from backend.services.detection_cache import (
        DetectionCacheWriter, cache_exists, parquet_path)
    from ultralytics import YOLO

    model = None
    fps = float(v["fps"])
    t0 = datetime.fromisoformat(v["recording_start_datetime"])
    for variant, hs, he in WINDOWS:
        pq = Path(parquet_path(PROJECT, CAMERA, chash, variant))
        if cache_exists(pq):
            print(f"[A] {variant}: cache exists, skip", flush=True)
            continue
        if model is None:
            model = YOLO(WEIGHTS, task="detect")
        f_lo = int((datetime.fromisoformat(f"{t0.date()}T{hs}:00") - t0)
                   .total_seconds() * fps)
        f_hi = int((datetime.fromisoformat(f"{t0.date()}T{he}:00") - t0)
                   .total_seconds() * fps)
        cap = cv2.VideoCapture(v["path"])
        cap.set(cv2.CAP_PROP_POS_FRAMES, f_lo)
        w = DetectionCacheWriter(pq_path=pq, metadata={
            "method_note": "native_artic_gate", "model": WEIGHTS,
            "imgsz": 640, "conf": CONF, "frames": [f_lo, f_hi],
            "class_scheme": "finetune_v1_native",
            "class_map": {str(k): vv for k, vv in CLASS_MAP.items()}})
        n = 0
        for f in range(f_lo, f_hi):
            ok, img = cap.read()
            if not ok:
                break
            r = model(img, conf=CONF, imgsz=640, verbose=False,
                      device="intel:gpu")[0]
            dets = []
            for b in r.boxes:
                x1, y1, x2, y2 = (float(x) for x in b.xyxy[0])
                dets.append({"bbox": [x1, y1, x2, y2],
                             "confidence": float(b.conf[0]),
                             "class_id": CLASS_MAP.get(int(b.cls[0]), 2)})
                n += 1
            w.add(f, dets)
            if (f - f_lo) % 9000 == 0:
                print(f"[A] {variant}: frame {f - f_lo}/{f_hi - f_lo} "
                      f"({n} dets)", flush=True)
        cap.release()
        w.close()
        print(f"[A] {variant}: wrote {n} detections", flush=True)


def stage_b_track(v):
    from backend.services.two_pass import run_pass1
    fps = float(v["fps"])
    t0 = datetime.fromisoformat(v["recording_start_datetime"])
    for variant, hs, he in WINDOWS:
        f_lo = int((datetime.fromisoformat(f"{t0.date()}T{hs}:00") - t0)
                   .total_seconds() * fps)
        f_hi = int((datetime.fromisoformat(f"{t0.date()}T{he}:00") - t0)
                   .total_seconds() * fps)
        res = run_pass1(PROJECT, CAMERA, variant=variant,
                        start_frame=f_lo, end_frame=f_hi, resume=True)
        print(f"[B] {variant}: pass-1 {res.get('status', res)}", flush=True)


def stage_c_replay():
    from backend.services.pass2_replay import replay_camera
    from backend.services.through_gate import bank_turn_pairs, is_invalid_through
    from backend.database import list_paths_for_camera
    from backend.config import THROUGH_GATE_MIN_SUPPORT

    SCRATCH.mkdir(parents=True, exist_ok=True)
    turn_pairs = bank_turn_pairs(list_paths_for_camera(PROJECT, CAMERA),
                                 THROUGH_GATE_MIN_SUPPORT)
    outs = {}
    for variant, _hs, _he in WINDOWS:
        out = SCRATCH / f"fullchain_{variant}.db"
        stats = replay_camera(PROJECT, CAMERA, variant=variant, out_db=out)
        # The promotion gate's scoring basis includes the through-gate's
        # kills (FM51 is its validated site) — apply it to the out DB.
        c = sqlite3.connect(out)
        rows = c.execute(
            "SELECT rowid, origin_leg_id, destination_leg_id FROM vehicle_events "
            "WHERE camera_id=? AND movement='through' AND COALESCE(rejected,0)=0",
            (CAMERA,)).fetchall()
        bogus = [rid for rid, o, d in rows
                 if is_invalid_through("through", o, d, turn_pairs)]
        with c:
            c.executemany("UPDATE vehicle_events SET rejected=1 WHERE rowid=?",
                          [(i,) for i in bogus])
        c.close()
        print(f"[C] {variant}: events {stats['events']}, through-gate "
              f"killed {len(bogus)}", flush=True)
        outs[variant] = out
    return outs


def stage_d_score(outs, v):
    from backend.services.classifier import fhwa_to_class_group

    t0 = datetime.fromisoformat(v["recording_start_datetime"])
    mio_iv_cls, mio_iv = load_mio_per_interval_class()
    ours_iv = defaultdict(int)
    ours_cls = defaultdict(int)
    for out in outs.values():
        c = sqlite3.connect(out)
        for tsv, fhwa in c.execute(
                "SELECT timestamp_video, fhwa_class FROM vehicle_events "
                "WHERE camera_id=? AND COALESCE(rejected,0)=0", (CAMERA,)):
            iv = _iv(t0 + timedelta(seconds=float(tsv)))
            ours_iv[iv] += 1
            ours_cls[fhwa_to_class_group(fhwa)] += 1
        c.close()

    windows_ivs = sorted(ours_iv)
    base = (json.loads(BASELINE.read_text())
            if BASELINE.exists() else {"rows": []})
    base_by_iv = {r["interval"]: r for r in base.get("rows", [])}

    print(f"\n{'interval':17} {'mio':>5} {'ftv1':>5} {'nat':>5} "
          f"{'ftv1Err%':>9} {'natErr%':>8}")
    sm = sb = sn = 0
    errs = []
    rows = []
    for iv in windows_ivs:
        m = mio_iv.get(iv, 0)
        b = base_by_iv.get(iv.isoformat(), {}).get("new", 0)
        nn = ours_iv[iv]
        sm += m; sb += b; sn += nn
        e = 100.0 * (nn - m) / m if m else 0.0
        eb = 100.0 * (b - m) / m if m else 0.0
        errs.append(abs(e))
        rows.append({"interval": iv.isoformat(), "mio": m, "ftv1": b,
                     "native": nn, "err_pct": round(e, 1)})
        print(f"{iv.isoformat()[5:16]:17} {m:>5} {b:>5} {nn:>5} "
              f"{eb:>8.1f}% {e:>7.1f}%")
    print(f"{'TOTAL':17} {sm:>5} {sb:>5} {sn:>5} "
          f"{100.0 * (sb - sm) / sm:>8.1f}% {100.0 * (sn - sm) / sm:>7.1f}%")
    print(f"interval MAE (native): {sum(errs) / len(errs):.1f}%")

    print("\n=== L/M/A over the processed windows (dev scorer) ===")
    mio_cls_w = defaultdict(int)
    for (iv, cls), n in mio_iv_cls.items():
        if iv in ours_iv:
            mio_cls_w[cls] += n
    for k in ("Lights", "Mediums", "Articulated Trucks"):
        print(f"  {k:<20} Miovision {mio_cls_w.get(k, 0):>5}   "
              f"ours {ours_cls.get(k, 0):>5}")

    outp = Path("runs/finetune_v1/fm51_native_artic.json")
    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text(json.dumps({
        "rows": rows,
        "totals": {"mio": sm, "ftv1_baseline": sb, "native": sn},
        "classes": {"mio": dict(mio_cls_w), "ours": dict(ours_cls)},
    }, indent=1))
    print(f"wrote {outp}\nNATIVE ARTIC GATE DONE", flush=True)


def main() -> int:
    from backend.services.detection_cache import compute_video_content_hash
    v = _video()
    chash, _ = compute_video_content_hash(
        v["path"], file_size_bytes=v["file_size_bytes"],
        total_frames=v["total_frames"])
    stage_a_detect(v, chash)
    stage_b_track(v)
    outs = stage_c_replay()
    stage_d_score(outs, v)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
