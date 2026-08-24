"""Stage-4 arm pass-1: the locked recipe with a generous buffer, without
touching production calibration (the wrapper injects tracker_lost_buffer;
dump meta records it — armed-verification reads it back)."""
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

variant = sys.argv[1] if len(sys.argv) > 1 else "s4_study_1100"
window = {"s4_study_0700": (629950, 809950),
          "s4_study_1100": (989950, 1169950),
          "s4_study_1600": (1439950, 1619950)}[variant]
res = run_pass1("97a7849a", 2, variant=variant,
                start_frame=window[0], end_frame=window[1],
                backend="botsort_locked", resume=False)
print("pass1 done:", res)

# instrumentation: persist the breaks + verify the re-stamp actually landed
import json as _json
from pathlib import Path as _P

import numpy as _np

from backend.services import two_pass as _tp2

tdir = _P(res["tracks_dir"])
n = int((tdir / "count.txt").read_text())
rows = _np.load(tdir / "rows.npy", mmap_mode="r")[:n]
breaks = []
import backend.services.tracker as _trk  # noqa: F401
# the backend object is gone (function-local); recover breaks via meta count
meta = _json.loads((tdir / "meta.json").read_text())
print("VERIFY distinct tids:", len(_np.unique(rows[:, 0])),
      "meta gate_breaks:", meta.get("gate_breaks"))
