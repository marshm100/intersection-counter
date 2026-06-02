"""Scratch-DB location for retrack/hybrid intermediates.

OneDrive holds file locks on data/projects/<proj>/_hybrid_tmp that cause
intermittent 'attempt to write a readonly database' errors AND — worse — SILENT
DOUBLE-WRITES on the retry (verified 2026-06-02: a cam2 bytetrack retrack wrote
527 SB->NB throughs into _hybrid_tmp on OneDrive vs 393 into system temp; the
134-event gap was duplicated events from the lock retry). That corrupts every
retrack-based measurement.

Fix: keep ALL scratch in the system temp dir (no OneDrive sync -> no lock).
Only the FINAL project.db write touches OneDrive, as one controlled operation.
reprocess_camera.py already does this for its cache-only scratch; this helper
gives apply_bank/apply_hybrid/process_camera_reid the same safety with a STABLE,
predictable path so cross-script references (apply_bank writes camN_bank.db,
apply_hybrid reads it) still resolve.
"""
from __future__ import annotations

import tempfile
from pathlib import Path


def scratch_dir(project: str = "97a7849a") -> Path:
    """A stable per-project scratch directory in the system temp dir."""
    d = Path(tempfile.gettempdir()) / f"ic_scratch_{project}"
    d.mkdir(parents=True, exist_ok=True)
    return d
