"""Reconnect source videos after the machine transition (2026-08-23).

The videos tables still point at the old machine's OneDrive paths. This script
takes a directory of retrieved video files (extracted from the OneDrive zips),
matches each file BY FILENAME against every project's videos rows, verifies it
against the recorded content hash — blake2b over size + total_frames + the
first 128 MiB, the exact recipe the caches were built under — and only then
moves it into data/videos/<original folder name>/ and repoints the DB row.

A hash mismatch means the file is NOT the original the detection caches were
built from; it is left where it is and reported, never installed.

  py scripts/reconnect_videos.py --src "C:/Users/marsh/Downloads/extracted" [--dry-run]
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")

from backend.services.detection_cache import compute_video_content_hash  # noqa: E402

PROJECTS = Path("data/projects")
DEST_ROOT = Path("data/videos")


def _video_rows():
    """Every videos row across every project, keyed for filename matching."""
    out = []
    for db in sorted(PROJECTS.glob("*/project.db")):
        pid = db.parent.name
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
        con.row_factory = sqlite3.Row
        try:
            rows = con.execute(
                "SELECT video_id, camera_id, path, filename, file_size_bytes, "
                "total_frames, content_hash, content_hash_method FROM videos").fetchall()
        except sqlite3.OperationalError:
            rows = []
        finally:
            con.close()
        for r in rows:
            out.append((pid, dict(r)))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="directory holding the retrieved videos")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_dir():
        raise SystemExit(f"not a directory: {src}")

    # every candidate file under src, by basename
    candidates: dict[str, Path] = {}
    for p in src.rglob("*.mp4"):
        candidates[p.name] = p

    rows = _video_rows()
    print(f"videos rows across projects : {len(rows)}")
    print(f"candidate files under src   : {len(candidates)}")
    print()

    installed = skipped = failed = absent = 0
    for pid, r in rows:
        fn = r["filename"] or os.path.basename(r["path"] or "")
        old = r["path"] or ""
        if old and os.path.exists(old):
            print(f"[ok-already ] {pid[:8]} cam{r['camera_id']}  {fn} — current path exists")
            skipped += 1
            continue
        cand = candidates.get(fn)
        if cand is None:
            print(f"[not found  ] {pid[:8]} cam{r['camera_id']}  {fn}")
            absent += 1
            continue

        size = cand.stat().st_size
        if r["file_size_bytes"] and size != r["file_size_bytes"]:
            print(f"[SIZE FAIL  ] {pid[:8]} cam{r['camera_id']}  {fn}: "
                  f"{size:,} vs recorded {r['file_size_bytes']:,} — NOT installed")
            failed += 1
            continue

        if r["content_hash"] and r["content_hash_method"] == "blake2b-128m-v1":
            got, _ = compute_video_content_hash(
                cand, file_size_bytes=size, total_frames=r["total_frames"])
            if got != r["content_hash"]:
                print(f"[HASH FAIL  ] {pid[:8]} cam{r['camera_id']}  {fn}: "
                      f"{got[:16]}... vs recorded {r['content_hash'][:16]}... — NOT installed")
                failed += 1
                continue
            verdict = "hash VERIFIED"
        else:
            verdict = "no recorded hash — size match only"

        folder = os.path.basename(os.path.dirname(old)) or pid
        dest = DEST_ROOT / folder / fn
        if args.dry_run:
            print(f"[would-place] {pid[:8]} cam{r['camera_id']}  {fn}  ({verdict})")
            print(f"              -> {dest}")
            installed += 1
            continue

        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.move(str(cand), str(dest))
        wcon = sqlite3.connect(str(PROJECTS / pid / "project.db"))
        with wcon:
            wcon.execute("UPDATE videos SET path=? WHERE video_id=?",
                         (str(dest.resolve()), r["video_id"]))
        wcon.close()
        print(f"[INSTALLED  ] {pid[:8]} cam{r['camera_id']}  {fn}  ({verdict})")
        print(f"              old: {old}")
        print(f"              new: {dest.resolve()}")
        installed += 1

    print()
    print(f"installed {installed} | already-ok {skipped} | not-found {absent} | FAILED {failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
