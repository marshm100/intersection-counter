"""Overnight accuracy runner — NON-DESTRUCTIVE. Builds candidate DBs + a
measurement log for the morning visual gate. NEVER applies to project.db.

Phases (each task wrapped in try/except — one failure never aborts the night;
results are flushed to the log incrementally so a crash at hour 8 keeps hours 0-8):

  0. DIAGNOSE (cheap, 960 cache): build_bank's manual-vs-rawtrk table per recall
     target. A missing cell with rawtrk~0 is detection/tracking-bound (a 1280 GPU
     build may help); a cell with rawtrk>=manual is already tracked (1280 won't).
  A. cam2 DUPLICATION SWEEP (CPU, 960 cache): sweep bytetrack params to cut the
     25fps through-duplication. Measures net per config vs the current 21.1%.
  B. yolo26l@1280 RECALL BUILDS (GPU, ~frames/1.5s each): build the accurate
     cache (separate variant, cache-only, non-destructive), retrack throughs+turns
     over it, build hybrid, measure. Does better recall recover missing vehicles
     (cam5 EB-right 39->1, cam1/cam3 NB-thru undercounts)? Skips a camera whose
     window would exceed --max-hours-per-build.

Usage:
  py scripts/overnight_accuracy.py --scope full
  py scripts/overnight_accuracy.py --scope cam5-eb
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from scratch import scratch_dir

PY = sys.executable
PROJECT = "97a7849a"
PROJ_DB = f"data/projects/{PROJECT}/project.db"
SCR = scratch_dir(PROJECT)
LOG_PATH = None  # set in main


def log(msg: str):
    line = f"[{time.strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    if LOG_PATH:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def run(cmd: list[str], tag: str, timeout=None, env=None) -> tuple[int, str]:
    log(f">> {tag}: {' '.join(str(c) for c in cmd)}")
    try:
        runenv = {**os.environ, **env} if env else None
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=runenv)
        out = (p.stdout or "") + (p.stderr or "")
        # keep noisy ECC/WARNING lines out of the log
        clean = "\n".join(l for l in out.splitlines()
                          if "ECC did not converge" not in l and not l.startswith("WARNING"))
        if p.returncode != 0:
            log(f"   !! rc={p.returncode} (last lines): " + " | ".join(clean.splitlines()[-3:]))
        return p.returncode, clean
    except subprocess.TimeoutExpired:
        log(f"   !! TIMEOUT after {timeout}s")
        return 124, ""


def parse_net(out: str):
    m = re.search(r"net agg_err\s*=\s*([\d.]+)%", out)
    g = re.search(r"per-min gross\s*=\s*([\d.]+)%", out)
    return (float(m.group(1)) if m else None, float(g.group(1)) if g else None)


def video_fps_frames(cam: int, minutes: float):
    import sqlite3
    c = sqlite3.connect(PROJ_DB)
    fps = float(c.execute("SELECT fps FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1", (cam,)).fetchone()[0])
    c.close()
    return fps, int(minutes * 60 * fps)


def measure(cam: int, db: str, minutes: float):
    rc, out = run([PY, "scripts/od_accuracy.py", "--camera", str(cam), "--db", db,
                   "--start-hms", "07:00:00", "--minutes", str(minutes)], f"measure cam{cam}")
    return parse_net(out)


# ---------------------------------------------------------------------------
def phase0_diag(cam: int, minutes: float):
    log(f"=== PHASE 0 diag cam{cam} (960 rawtrk vs manual) ===")
    rc, out = run([PY, "scripts/build_bank.py", "--camera", str(cam), "--minutes", str(minutes),
                   "--out", str(SCR / f"_diag_cam{cam}.json")], f"diag build_bank cam{cam}")
    for line in out.splitlines():
        if re.search(r"L\d+->L\d+|rawtrk|status|MAGNET", line):
            log("   " + line.rstrip())


# ---------------------------------------------------------------------------
def phase_a_cam2_sweep(minutes: float):
    """cam2 duplication is double-box driven; sweep class-agnostic NMS strictness
    (the only clean pipeline-level lever — the bytetrack core knobs conflict with
    VehicleTracker's explicit args and would need deeper plumbing). Higher IoU =
    suppress only true double-boxes (spare distinct dense throughs); lower = more
    aggressive. Measures net per setting over the 960 cache at the full window."""
    log("=== PHASE A: cam2 NMS-strictness sweep (960 cache) ===")
    cam = 2
    bank = str(SCR / "cam2_sweep_bank.json")
    run([PY, "scripts/build_bank.py", "--camera", str(cam), "--minutes", str(minutes),
         "--magnet-support-factor", "5", "--out", bank], "cam2 build_bank")
    # botsort turns once (NMS off — turns aren't the duplication problem)
    turns_db = str(SCR / "cam2_sweep_turns.db")
    run([PY, "scripts/apply_bank.py", "--camera", str(cam), "--backend", "botsort",
         "--minutes", str(minutes), "--bank", bank, "--out-db", turns_db], "cam2 botsort turns")
    configs = {  # name -> PRE_TRACK_NMS_IOU env ('off' or a float)
        "baseline": "off", "nms0.85": "0.85", "nms0.75": "0.75", "nms0.6": "0.6",
    }
    results = {}
    for name, nms in configs.items():
        bt_db = str(SCR / f"cam2_sweep_bt_{name}.db")
        hy_db = str(SCR / f"cam2_sweep_hy_{name}.db")
        rc, _ = run([PY, "scripts/apply_bank.py", "--camera", str(cam), "--backend", "bytetrack",
                     "--minutes", str(minutes), "--bank", bank, "--out-db", bt_db],
                    f"cam2 throughs [{name}]", env={"PRE_TRACK_NMS_IOU": nms})
        if rc != 0:
            results[name] = None; continue
        run([PY, "scripts/apply_hybrid.py", "--camera", str(cam), "--minutes", str(minutes),
             "--bank", bank, "--bot-db", turns_db, "--throughs-db", bt_db, "--out-db", hy_db],
            f"cam2 hybrid [{name}]")
        net, gross = measure(cam, hy_db, minutes)
        results[name] = net
        log(f"   cam2 [{name}, nms={nms}]: net={net}% gross={gross}%")
    valid = {k: v for k, v in results.items() if v is not None}
    best = min(valid, key=valid.get) if valid else None
    log(f"   cam2 SWEEP BEST: {best} -> {results.get(best)}% net @ {minutes:g}min "
        f"(note: cam2 has no 30-min shipped baseline; this IS the first clean 30-min read)")
    return results


# ---------------------------------------------------------------------------
def phase_b_recall(cam: int, minutes: float, max_hours: float):
    log(f"=== PHASE B: yolo26l@1280 recall cam{cam} ===")
    fps, frames = video_fps_frames(cam, minutes)
    est_h = frames / 1.5 / 3600
    log(f"   cam{cam}: fps={fps} frames={frames} est build ~{est_h:.1f}h (1.5 fps)")
    if est_h > max_hours:
        log(f"   SKIP cam{cam}: {est_h:.1f}h > --max-hours-per-build {max_hours}h. "
            f"Re-run with smaller --minutes to fit.")
        return None
    var = "accurate_1280_skip1"
    bank = f"evaluations/recal_cam{cam}_1280.json"
    # 1. build 1280 cache (non-destructive)
    rc, _ = run([PY, "scripts/reprocess_camera.py", "--camera", str(cam), "--mode", "accurate",
                 "--device", "openvino", "--cache-only", "--variant", var,
                 "--start-hms", "07:00:00", "--minutes", str(minutes), "--yes"],
                f"cam{cam} build 1280 cache", timeout=int(max_hours * 3600) + 1800)
    if rc != 0:
        log(f"   !! cam{cam} 1280 cache build failed; skipping"); return None
    # 2. bank over 1280
    run([PY, "scripts/build_bank.py", "--camera", str(cam), "--minutes", str(minutes),
         "--variant", var, "--out", bank], f"cam{cam} build_bank@1280")
    # 3. throughs + turns over 1280
    bt_db = str(SCR / f"cam{cam}_bt1280.db")
    turns_db = str(SCR / f"cam{cam}_bank1280.db")
    run([PY, "scripts/apply_bank.py", "--camera", str(cam), "--backend", "bytetrack",
         "--variant", var, "--minutes", str(minutes), "--bank", bank, "--out-db", bt_db], f"cam{cam} throughs@1280")
    run([PY, "scripts/apply_bank.py", "--camera", str(cam), "--backend", "botsort",
         "--variant", var, "--minutes", str(minutes), "--bank", bank, "--out-db", turns_db], f"cam{cam} turns@1280")
    # 4. hybrid + measure (full OD so EB-right etc. are visible)
    hy_db = str(SCR / f"cam{cam}_hybrid1280.db")
    run([PY, "scripts/apply_hybrid.py", "--camera", str(cam), "--minutes", str(minutes),
         "--bank", bank, "--bot-db", turns_db, "--throughs-db", bt_db, "--out-db", hy_db], f"cam{cam} hybrid@1280")
    net, gross = measure(cam, hy_db, minutes)
    rc, od = run([PY, "scripts/od_accuracy.py", "--camera", str(cam), "--db", hy_db,
                  "--start-hms", "07:00:00", "--minutes", str(minutes), "--show-od"], f"cam{cam} OD@1280")
    log(f"   cam{cam}@1280: net={net}% gross={gross}%  (DB {hy_db})")
    for line in od.splitlines():
        if re.search(r"thru|right|left|OD cell", line):
            log("      " + line.rstrip())
    return net


# ---------------------------------------------------------------------------
def main() -> int:
    global LOG_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["full", "cam5-eb"], default="full")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--max-hours-per-build", type=float, default=4.0)
    ap.add_argument("--tag", default=None)
    args = ap.parse_args()

    tag = args.tag or datetime.now().strftime("%Y-%m-%d_%H%M")
    LOG_PATH = f"evaluations/overnight_accuracy_{tag}.log"
    Path("evaluations").mkdir(exist_ok=True)

    phase_b_cams = [5] if args.scope == "cam5-eb" else [5, 1, 3]
    diag_cams = phase_b_cams

    t0 = time.time()
    log(f"##### OVERNIGHT ACCURACY RUN scope={args.scope} minutes={args.minutes} #####")
    log(f"NON-DESTRUCTIVE — project.db is never modified. Candidates in {SCR} for the AM visual gate.")
    log(f"Applied baseline (net): cam1 7.2 | cam2 21.1 | cam3 9.8 | cam4 8.4 | cam5 9.5")

    for cam in diag_cams:
        try: phase0_diag(cam, args.minutes)
        except Exception as ex: log(f"   !! phase0 cam{cam} EXC: {ex}")

    try: phase_a_cam2_sweep(args.minutes)
    except Exception as ex: log(f"   !! phase A EXC: {ex}")

    for cam in phase_b_cams:
        try: phase_b_recall(cam, args.minutes, args.max_hours_per_build)
        except Exception as ex: log(f"   !! phase B cam{cam} EXC: {ex}")

    log(f"##### DONE in {(time.time()-t0)/3600:.1f}h. Review {LOG_PATH}; apply winners after visual gate. #####")
    return 0


if __name__ == "__main__":
    sys.exit(main())
