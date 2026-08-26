"""Identity-stack arm pass-1: botsort_locked + buffer 750 over the C2
id_ detector caches (the s4_pass1_runner pattern; production calib
untouched)."""
import sys

sys.path.insert(0, ".")

import backend.database as dbm

_real = dbm.get_camera_calibration_params


def _patched(project_id, camera_id):
    calib = dict(_real(project_id, camera_id))
    calib["tracker_lost_buffer"] = 750
    return calib


dbm.get_camera_calibration_params = _patched

from backend.services.two_pass import run_pass1  # noqa: E402

variant = sys.argv[1]
window = {"id_study_0700": (629950, 809950),
          "id_study_1100": (989950, 1169950),
          "id_study_1600": (1439950, 1619950)}[variant]
res = run_pass1("97a7849a", 2, variant=variant,
                start_frame=window[0], end_frame=window[1],
                backend="botsort_locked", resume=False)
print("pass1 done:", res)

import json as _json
from pathlib import Path as _P

import numpy as _np

tdir = _P(res["tracks_dir"])
n = int((tdir / "count.txt").read_text())
rows = _np.load(tdir / "rows.npy", mmap_mode="r")[:n]
meta = _json.loads((tdir / "meta.json").read_text())
print("VERIFY backend:", meta.get("backend"), "lost_buffer:",
      meta.get("lost_buffer"), "distinct tids:",
      len(_np.unique(rows[:, 0])), "gate_breaks:", meta.get("gate_breaks"),
      "straddle:", meta.get("gate_straddle_splits"))
