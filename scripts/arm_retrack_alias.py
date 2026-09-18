"""Re-track one window from its EXISTING detection cache into a scratch
variant, under whatever tracker defaults the environment sets (e.g.
TRACKER_FUSE_SCORE=0). The parquet is aliased (copied) to
<prefix>_<variant>; run_pass1 finds the cache and tracks it; nothing in
production changes. The dump's meta records the recipe.
Usage:  TRACKER_FUSE_SCORE=0 .venv/Scripts/python.exe -X utf8 scripts/arm_retrack_alias.py PROJ CAM VARIANT PREFIX
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402


def main() -> int:
    proj, cam, variant, prefix = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
    new = f"{prefix}_{variant}"
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, = con.execute("SELECT content_hash FROM videos WHERE camera_id=?", (cam,)).fetchone()
    src = parquet_path(proj, cam, chash, variant)
    dst = parquet_path(proj, cam, chash, new)
    meta = json.load(open(src.with_suffix(".meta.json")))
    f0, f1 = meta["windows"][0] if "windows" in meta else meta["frames"]
    if not dst.exists():
        shutil.copy2(src, dst)
        meta["derived_from"] = f"alias of {variant} for a re-track arm ({prefix}, 2026-09-12)"
        dst.with_suffix(".meta.json").write_text(json.dumps(meta))
    from backend.services.two_pass import run_pass1
    t = time.time()
    run_pass1(proj, cam, variant=new, start_frame=f0, end_frame=f1, resume=False)
    tm = json.load(open(tracks_dir(dst) / "meta.json"))
    rows = int((tracks_dir(dst) / "count.txt").read_text())
    print(f"pass-1 cam{cam} {new}: {rows} rows in {time.time() - t:.0f}s; recipe backend={tm.get('backend')} "
          f"fuse_score={tm.get('fuse_score')} position_recovery={tm.get('position_recovery')} "
          f"bbox_buffer={tm.get('bbox_buffer')} activation={tm.get('activation')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
