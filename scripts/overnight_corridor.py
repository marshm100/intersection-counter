"""Unattended overnight corridor run (2026-06-01 EOD).

Two goals, ordered so the important/safe work lands first even if a later step fails:

  PHASE 1 — FINISH cam4 + cam5 at 5-min (they have no shipped state):
            GPU cache -> bank -> measure BoT+bank vs bytetrack-hybrid -> APPLY the
            winner (lower per-min gross), atomic backup auto-created. Fast safety net.
  PHASE 2 — 30-min on the whole balanced-stack corridor (cam2,3,4,5):
            * cam4,5: full chain at 30-min -> APPLY winner (supersedes the 5-min ship).
            * cam2,3 (ALREADY SHIPPED): NON-DESTRUCTIVE --cache-only 30-min cache ->
              BoT+bank measure into a side DB -> PREVIEW only (project.db untouched).
              30-min preview banks are written to recal_cam{N}_30min.json so the live
              recal_cam{N}.json is never clobbered. The engineer gates the 30-min ship.

Robustness: every step is wrapped — a failure is logged and the run continues with the
next camera. Detector is the proven Intel-GPU path (DEVICE=openvino default). All output
is teed to a log; a morning summary table is written at the end.

Run unattended:  py scripts/overnight_corridor.py    (run_in_background)
Morning:         read evaluations/overnight_summary_2026-06-01.md
"""
from __future__ import annotations
import re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
LOG = ROOT / "evaluations" / "overnight_2026-06-01.log"
SUMMARY = ROOT / "evaluations" / "overnight_summary_2026-06-01.md"

_logf = open(LOG, "a", encoding="utf-8", buffering=1)


def log(msg: str):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    _logf.write(line + "\n")


def run(cmd: list[str], label: str) -> tuple[int, str]:
    """Run a subprocess, tee combined output to the log, return (rc, output)."""
    log(f"$ {label}  ::  {' '.join(str(c) for c in cmd)}")
    buf = []
    try:
        p = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, bufsize=1)
        for ln in p.stdout:
            buf.append(ln)
            # keep the log readable — skip the spammy per-frame + tracker config noise
            if not re.search(r"ECC did not|^\s*(WARNING|INFO)|track_|iou_|appearance_|"
                             r"proximity_|fuse_|reid_model|det_thresh|cmc_method|Loading |Using ", ln):
                _logf.write("    " + ln)
        p.wait()
        return p.returncode, "".join(buf)
    except Exception as ex:  # never let a crash kill the whole night
        log(f"  !! EXCEPTION running {label}: {ex}")
        return 1, "".join(buf) + f"\nEXC {ex}"


def metrics(out: str) -> tuple[float | None, float | None]:
    """Pull (net%, gross%) from od_accuracy output."""
    n = re.search(r"net agg_err\s*=\s*([\d.]+)%", out)
    g = re.search(r"per-min gross\s*=\s*([\d.]+)%", out)
    return (float(n.group(1)) if n else None, float(g.group(1)) if g else None)


def measure(cam: int, db: str, minutes: float) -> tuple[float | None, float | None]:
    rc, out = run([PY, "scripts/od_accuracy.py", "--camera", str(cam), "--db", db,
                   "--start-hms", "07:00:00", "--minutes", str(minutes)],
                  f"measure cam{cam} {db}")
    return metrics(out)


RESULTS: list[dict] = []


def finish_camera(cam: int, minutes: float, apply_winner: bool):
    """cam4/cam5 path: destructive reprocess -> bank -> measure both trackers -> apply winner."""
    tag = f"cam{cam}@{minutes:g}min"
    bank = f"evaluations/recal_cam{cam}.json"
    bank_db = f"data/projects/97a7849a/_hybrid_tmp/cam{cam}_bank.db"
    hyb_db = f"data/projects/97a7849a/_hybrid_tmp/cam{cam}_hybrid.db"
    rec = {"tag": tag, "camera": cam, "minutes": minutes, "mode": "finish",
           "bank": None, "hybrid": None, "applied": None, "ok": False}
    try:
        rc, _ = run([PY, "scripts/reprocess_camera.py", "--camera", str(cam), "--mode", "balanced",
                     "--start-hms", "07:00:00", "--minutes", str(minutes), "--yes"], f"{tag} cache")
        if rc != 0:
            log(f"  {tag}: reprocess failed rc={rc}; skipping camera"); RESULTS.append(rec); return
        run([PY, "scripts/build_bank.py", "--camera", str(cam), "--start-hms", "07:00:00",
             "--minutes", str(minutes), "--out", bank], f"{tag} build_bank")
        # BoT+bank candidate
        run([PY, "scripts/apply_bank.py", "--camera", str(cam), "--bank", bank,
             "--start-hms", "07:00:00", "--minutes", str(minutes)], f"{tag} apply_bank")
        rec["bank"] = measure(cam, bank_db, minutes)
        # bytetrack-throughs hybrid candidate
        run([PY, "scripts/apply_hybrid.py", "--camera", str(cam), "--start-hms", "07:00:00",
             "--minutes", str(minutes)], f"{tag} apply_hybrid")
        rec["hybrid"] = measure(cam, hyb_db, minutes)
        gb = rec["bank"][1] if rec["bank"] else None
        gh = rec["hybrid"][1] if rec["hybrid"] else None
        if apply_winner and (gb is not None or gh is not None):
            use_bank = gh is None or (gb is not None and gb <= gh)
            if use_bank:
                run([PY, "scripts/apply_bank.py", "--camera", str(cam), "--bank", bank,
                     "--start-hms", "07:00:00", "--minutes", str(minutes), "--apply"], f"{tag} APPLY bank")
                rec["applied"] = f"bank (gross {gb})"
            else:
                run([PY, "scripts/apply_hybrid.py", "--camera", str(cam), "--start-hms", "07:00:00",
                     "--minutes", str(minutes), "--apply"], f"{tag} APPLY hybrid")
                rec["applied"] = f"hybrid (gross {gh})"
        rec["ok"] = True
    except Exception as ex:
        log(f"  !! {tag} finish_camera exception: {ex}")
    RESULTS.append(rec)
    log(f"  {tag} DONE: bank={rec['bank']} hybrid={rec['hybrid']} applied={rec['applied']}")


def preview_camera(cam: int, minutes: float):
    """cam2/cam3 path (SHIPPED): non-destructive cache-only -> BoT+bank measure, NO apply."""
    tag = f"cam{cam}@{minutes:g}min-preview"
    bank = f"evaluations/recal_cam{cam}_{int(minutes)}min.json"   # never clobber the live bank
    bank_db = f"data/projects/97a7849a/_hybrid_tmp/cam{cam}_bank.db"
    rec = {"tag": tag, "camera": cam, "minutes": minutes, "mode": "preview",
           "bank": None, "hybrid": None, "applied": "NONE (preview — gate in AM)", "ok": False}
    try:
        rc, _ = run([PY, "scripts/reprocess_camera.py", "--camera", str(cam), "--mode", "balanced",
                     "--start-hms", "07:00:00", "--minutes", str(minutes), "--yes", "--cache-only"],
                    f"{tag} cache-only")
        if rc != 0:
            log(f"  {tag}: cache-only reprocess failed rc={rc}; skipping"); RESULTS.append(rec); return
        run([PY, "scripts/build_bank.py", "--camera", str(cam), "--start-hms", "07:00:00",
             "--minutes", str(minutes), "--out", bank], f"{tag} build_bank")
        run([PY, "scripts/apply_bank.py", "--camera", str(cam), "--bank", bank,
             "--start-hms", "07:00:00", "--minutes", str(minutes)], f"{tag} apply_bank(no-apply)")
        rec["bank"] = measure(cam, bank_db, minutes)
        rec["ok"] = True
    except Exception as ex:
        log(f"  !! {tag} preview_camera exception: {ex}")
    RESULTS.append(rec)
    log(f"  {tag} DONE: BoT+bank 30min preview gross={rec['bank']}")


def write_summary(t0: float):
    lines = ["# Overnight corridor run — 2026-06-01", "",
             f"Elapsed: {(time.time()-t0)/3600:.1f} h.  Log: `{LOG.name}`.", "",
             "net% / gross% = per-minute OD error vs Miovision (lower better).", "",
             "| run | mode | BoT+bank (net/gross) | bytetrack-hybrid (net/gross) | applied |",
             "|---|---|---|---|---|"]
    for r in RESULTS:
        b = f"{r['bank'][0]}/{r['bank'][1]}" if r.get("bank") and r["bank"][0] is not None else "—"
        h = f"{r['hybrid'][0]}/{r['hybrid'][1]}" if r.get("hybrid") and r["hybrid"][0] is not None else "—"
        lines.append(f"| {r['tag']} | {r['mode']} | {b} | {h} | {r['applied'] or '—'} |")
    lines += ["", "## Morning actions",
              "- cam4/cam5: applied automatically (winner by gross, atomic backup). Verify + visual-gate.",
              "- cam2/cam3 30-min: PREVIEW only (project.db untouched). If the 30-min number beats the",
              "  shipped 5-min, ship it with a gated destructive run, e.g.:",
              "  `py scripts/reprocess_camera.py --camera 2 --minutes 30 --yes` then `build_bank`/`apply_*` --apply.",
              "- All applies make a backup in data/projects/97a7849a/backups/."]
    SUMMARY.write_text("\n".join(lines), encoding="utf-8")
    log(f"summary -> {SUMMARY}")
    print("\n".join(lines))


def main() -> int:
    t0 = time.time()
    log("=" * 70)
    log("OVERNIGHT corridor run START (DEVICE=openvino default, GPU)")
    # PHASE 1 — finish cam4, cam5 at 5-min (fast safety net)
    log("--- PHASE 1: finish cam4, cam5 @ 5-min ---")
    for cam in (4, 5):
        finish_camera(cam, 5, apply_winner=True)
    # PHASE 2 — 30-min across the balanced-stack corridor
    log("--- PHASE 2a: cam4, cam5 @ 30-min (apply winner) ---")
    for cam in (4, 5):
        finish_camera(cam, 30, apply_winner=True)
    log("--- PHASE 2b: cam2, cam3 @ 30-min NON-DESTRUCTIVE preview ---")
    for cam in (3, 2):    # cam3 (10fps) first — faster; cam2 (25fps) is the long pole
        preview_camera(cam, 30)
    log("OVERNIGHT corridor run COMPLETE")
    write_summary(t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
