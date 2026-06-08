"""Validate cam2 match_thresh=0.90 in the SHIPPED HYBRID config (not the plain-
ByteTrack proxy the knob sweep used). Clean A/B: build the bank + BoT-SORT turns
ONCE (knob-independent), then run the ByteTrack throughs arm at m0.80 (control)
and m0.90 (test), merge each into the hybrid, and score with od_accuracy --camera 2.

The knob is toggled via the per-camera calibration plumbing (the integration path
a real reprocess uses), so this also end-to-end exercises that wiring. Does NOT
apply to project.db — review the A/B, then apply_hybrid --apply the winner.

Usage:  py scripts/cam2_hybrid_validate_m090.py --minutes 30
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import backend.database as db
from scripts.scratch import scratch_dir

PROJECT = "97a7849a"
CAM = 2
PY = sys.executable
NET_RE = re.compile(r"net agg_err\s*=\s*([\d.]+)%")


def run(cmd, label):
    print(f">> {label}", flush=True)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout[-2000:]); print(r.stderr[-2000:])
        raise SystemExit(f"FAILED: {label} (rc={r.returncode})")
    return r.stdout


def score(hy_db, minutes):
    out = subprocess.run(
        [PY, "scripts/od_accuracy.py", "--camera", str(CAM), "--db", str(hy_db),
         "--minutes", str(minutes)], capture_output=True, text=True).stdout
    m = NET_RE.search(out)
    cells = {}
    for name in ("SB thru", "NB thru"):
        cm = re.search(rf"^\s*{re.escape(name)}\s+(\d+)\s+(\d+)", out, re.M)
        if cm:
            cells[name] = (int(cm.group(1)), int(cm.group(2)))
    return (float(m.group(1)) if m else float("nan")), cells


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30.0)
    args = ap.parse_args()
    mins = str(args.minutes)
    scr = Path(scratch_dir(PROJECT)); scr.mkdir(parents=True, exist_ok=True)
    bank = str(scr / "cam2_val_bank.json")
    turns = str(scr / "cam2_val_turns.db")

    # Remember the live calib so we always restore it.
    saved = db.get_camera_calibration_params(PROJECT, CAM)["tracker_match_threshold"]
    print(f"cam2 hybrid m0.90 validation  window 07:00+{mins}min  (live match={saved})\n")
    try:
        run([PY, "scripts/build_bank.py", "--camera", str(CAM), "--minutes", mins,
             "--magnet-support-factor", "5", "--out", bank], "build_bank")
        run([PY, "scripts/apply_bank.py", "--camera", str(CAM), "--backend", "botsort",
             "--minutes", mins, "--bank", bank, "--out-db", turns], "botsort turns (shared)")

        results = {}
        for label, match in (("control m0.80", None), ("test m0.90", 0.90)):
            # Toggle the per-camera knob through the real calibration path; the
            # ByteTrack throughs retrack reads it via get_camera_calibration_params.
            db.update_camera_calibration(
                PROJECT, CAM,
                calib_tracker_match_threshold=(db.CLEAR_TO_DEFAULT if match is None else match))
            bt = str(scr / f"cam2_val_bt_{label.split()[-1]}.db")
            hy = str(scr / f"cam2_val_hy_{label.split()[-1]}.db")
            run([PY, "scripts/apply_bank.py", "--camera", str(CAM), "--backend", "bytetrack",
                 "--minutes", mins, "--bank", bank, "--out-db", bt], f"throughs [{label}]")
            run([PY, "scripts/apply_hybrid.py", "--camera", str(CAM), "--minutes", mins,
                 "--bank", bank, "--bot-db", turns, "--throughs-db", bt, "--out-db", hy],
                f"hybrid [{label}]")
            net, cells = score(hy, args.minutes)
            results[label] = (net, cells, hy)
            sb = cells.get("SB thru", ("-", "-")); nb = cells.get("NB thru", ("-", "-"))
            print(f"   {label}: net={net:.1f}%  SB-thru {sb[1]}/{sb[0]}  NB-thru {nb[1]}/{nb[0]}  (db {hy})\n", flush=True)
    finally:
        db.update_camera_calibration(
            PROJECT, CAM,
            calib_tracker_match_threshold=(db.CLEAR_TO_DEFAULT if saved is None else saved))
        print(f"restored cam2 match -> {saved}")

    c, t = results["control m0.80"][0], results["test m0.90"][0]
    print(f"\nRESULT  control(0.80)={c:.1f}%  test(0.90)={t:.1f}%  delta={t - c:+.1f}pp  "
          f"(shipped baseline 16.4%)")
    print("VERDICT:", "m0.90 WINS — apply" if t < c - 0.2 else
          "no clean hybrid win — keep calib on throughs evidence or revert")
    print(f"to apply the winner:\n  py scripts/apply_hybrid.py --camera 2 --minutes {args.minutes:g} "
          f"--bank {bank} --bot-db {turns} --throughs-db {results['test m0.90'][2]} --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
