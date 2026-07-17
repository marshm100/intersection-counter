"""Phase 2a (MASTER_PLAN §3-A) — build a GT-free path bank from within the app.

Wraps the proven builder (scripts/build_bank_gtfree.build_gtfree_bank) in a
background job that mirrors the v3 processing pattern (in-memory registry +
daemon thread + status poll). The candidate bank + QA land under
data/projects/<pid>/banks/ for the operator to REVIEW before applying (Phase 2b),
per the runbook's human QA checkpoint — build is never auto-chained into apply.

The builder logic stays in scripts/ (the CLI's proven implementation); it is
imported lazily inside the worker so a scripts-side import hiccup can never break
app startup, only the individual build job.
"""
from __future__ import annotations

import sys
import threading
import traceback
from pathlib import Path

from backend.config import PROJECTS_DIR

_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"

_bank_jobs: dict = {}
_bank_jobs_lock = threading.Lock()


def banks_dir(project_id: str) -> Path:
    d = PROJECTS_DIR / project_id / "banks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_build_status(project_id: str, camera_id: int) -> dict:
    """Job state for the build on this camera; {'status': 'idle'} if none."""
    with _bank_jobs_lock:
        job = _bank_jobs.get((project_id, camera_id))
        return dict(job) if job else {"status": "idle"}


def _qa_summary(result: dict) -> dict:
    """Compact, operator-facing rollup of the builder's QA report."""
    qa = result.get("qa", {})
    cells = qa.get("cells", [])
    return {
        "n_paths": len(result.get("paths", [])),
        "n_admitted": sum(1 for c in cells if c.get("status") == "admitted"),
        "n_rejected": sum(1 for c in cells if "rejected" in (c.get("status") or "")),
        "n_tracks_usable": qa.get("n_tracks_usable"),
        "missing_movements": qa.get("missing_movements", []),
        "leg_sanity_warnings": [w for w in qa.get("leg_sanity", [])
                                if w.get("verdict") != "ok"],
        "straight_turn_warnings": [{"cell": c["cell"]} for c in cells
                                   if c.get("warn") == "straight_turn"],
        "ambiguous_pairs": qa.get("ambiguous_pairs", []),
    }


def _run_build(project_id: str, camera_id: int, params: dict) -> None:
    key = (project_id, camera_id)
    try:
        if str(_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS_DIR))
        from build_bank_gtfree import build_gtfree_bank, BankBuildError
        out_path = banks_dir(project_id) / f"cam{camera_id}.json"
        try:
            result = build_gtfree_bank(
                camera=camera_id, project=project_id, out=str(out_path), **params)
        except BankBuildError as e:
            # Operator-actionable (no cache / no video): surface the message, not a stack.
            with _bank_jobs_lock:
                _bank_jobs[key].update({"status": "error", "error": str(e), "actionable": True})
            return
        with _bank_jobs_lock:
            _bank_jobs[key].update({
                "status": "complete",
                "bank_path": result.get("out_path"),
                "qa_path": result.get("qa_path"),
                "summary": _qa_summary(result),
                "qa": result.get("qa", {}),
            })
    except Exception as e:  # unexpected — keep the trace for debugging
        with _bank_jobs_lock:
            _bank_jobs[key].update({"status": "error", "error": str(e),
                                    "traceback": traceback.format_exc()})


def start_build(project_id: str, camera_id: int, *, start_hms: str = "07:00:00",
                minutes: float = 30.0, channel_buffer_px: float = 20.0,
                variant: str | None = None) -> dict:
    """Kick off a background GT-free bank build for one camera. One build per
    camera at a time; returns {'status': 'running'} (or 'running'+already)."""
    key = (project_id, camera_id)
    params = {"start_hms": start_hms, "minutes": float(minutes),
              "channel_buffer_px": float(channel_buffer_px), "variant": variant}
    with _bank_jobs_lock:
        existing = _bank_jobs.get(key)
        if existing and existing.get("status") == "running":
            return {"status": "running", "kind": existing.get("kind"), "already": True}
        _bank_jobs[key] = {"status": "running", "kind": "build", "camera_id": camera_id,
                           "window": f"{start_hms}+{float(minutes):.0f}min", "error": None}
    threading.Thread(target=_run_build, args=(project_id, camera_id, params),
                     daemon=True).start()
    return {"status": "running", "kind": "build",
            "window": f"{start_hms}+{float(minutes):.0f}min"}


def _run_apply(project_id: str, camera_id: int, params: dict) -> None:
    key = (project_id, camera_id)
    try:
        if str(_SCRIPTS_DIR) not in sys.path:
            sys.path.insert(0, str(_SCRIPTS_DIR))
        from apply_bank import apply_bank_to_db, BankApplyError
        bank_path = params.pop("bank_path")
        try:
            r = apply_bank_to_db(camera=camera_id, project=project_id, bank_path=bank_path,
                                 apply=True, **params)
        except BankApplyError as e:
            with _bank_jobs_lock:
                _bank_jobs[key].update({"status": "error", "error": str(e), "actionable": True})
            return
        with _bank_jobs_lock:
            _bank_jobs[key].update({
                "status": "complete",
                "events_before": r.get("events_before"),
                "events_after": r.get("events_after"),
                "backup_path": r.get("backup_path"),
                "n_paths": r.get("n_paths"),
            })
    except Exception as e:
        with _bank_jobs_lock:
            _bank_jobs[key].update({"status": "error", "error": str(e),
                                    "traceback": traceback.format_exc()})


def start_apply(project_id: str, camera_id: int, *, bank_path: str,
                start_hms: str = "07:00:00", minutes: float = 30.0) -> dict:
    """Kick off a background bank APPLY (retrack the window + swap the camera's
    events + install the bank paths; project.db is backed up first). One job per
    camera at a time (build/apply share the registry). DESTRUCTIVE — the caller
    must have confirmed and checked the bank exists + no processing is active."""
    key = (project_id, camera_id)
    with _bank_jobs_lock:
        existing = _bank_jobs.get(key)
        if existing and existing.get("status") == "running":
            return {"status": "running", "kind": existing.get("kind"), "already": True}
        _bank_jobs[key] = {"status": "running", "kind": "apply", "camera_id": camera_id,
                           "window": f"{start_hms}+{float(minutes):.0f}min", "error": None}
    params = {"bank_path": bank_path, "start_hms": start_hms, "minutes": float(minutes)}
    threading.Thread(target=_run_apply, args=(project_id, camera_id, params),
                     daemon=True).start()
    return {"status": "running", "kind": "apply"}
