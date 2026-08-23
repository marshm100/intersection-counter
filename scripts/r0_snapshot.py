"""R0 snapshot + diff — the audit substrate for the measured review pass.

There is no review-action audit trail in the schema (manually_edited is a bare
boolean; flag rebuilds destroy open-flag history; worklist undo is session-only
JS). R0's audit record is therefore a pair of verified snapshots and this diff:

  py scripts/r0_snapshot.py snapshot --label pre_r0
  ... operator works the queue ...
  py scripts/r0_snapshot.py snapshot --label post_r0
  py scripts/r0_snapshot.py diff <pre.db> <post.db> [--window 1600-1800]

Snapshot = the house pattern (apply_recal_updates._backup_db): checkpoint the
WAL, VACUUM INTO, then open the copy and assert integrity_check == ok and the
event count matches the live DB. Diff = per-event comparison keyed by event_id:
ADDED / REJECTED / UNREJECTED / MOVEMENT / CLASS changes, with per-movement
breakdowns, optionally scoped to a wallclock window.

Read-only with respect to the live DB (VACUUM INTO writes only the new file).
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, ".")

from backend.database import get_connection, get_db_path  # noqa: E402

DEFAULT_PROJECT = "97a7849a"


def snapshot(project_id: str, label: str) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    bak_dir = get_db_path(project_id).parent / "backups"
    bak_dir.mkdir(parents=True, exist_ok=True)
    bak = bak_dir / f"project_{stamp}_{label}.db"
    if bak.exists():
        raise SystemExit(f"target already exists: {bak}")

    src = get_connection(project_id)
    try:
        src.execute("PRAGMA busy_timeout = 10000")
        src.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        expected = src.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0]
        src.execute("VACUUM INTO ?", (str(bak),))
    finally:
        src.close()

    chk = sqlite3.connect(str(bak))
    try:
        integ = chk.execute("PRAGMA integrity_check").fetchone()[0]
        got = chk.execute("SELECT COUNT(*) FROM vehicle_events").fetchone()[0]
    finally:
        chk.close()
    if integ != "ok":
        bak.unlink()
        raise SystemExit(f"snapshot failed integrity_check: {integ}")
    if got != expected:
        bak.unlink()
        raise SystemExit(f"snapshot events {got} != live {expected} — WAL not captured")

    print(f"SNAPSHOT {bak}")
    print(f"  integrity ok | vehicle_events {got:,}")
    return bak


def _load_events(db: str, window: str | None):
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro&immutable=1", uri=True)
    con.row_factory = sqlite3.Row
    sql = ("SELECT event_id, camera_id, origin_leg_id, movement, vehicle_class, "
           "rejected, manually_edited, vehicle_track_id, timestamp_real "
           "FROM vehicle_events")
    rows = {r["event_id"]: dict(r) for r in con.execute(sql)}
    con.close()
    if window:
        a, b = window.split("-")
        lo = f"{a[:2]}:{a[2:]}"
        hi = f"{b[:2]}:{b[2:]}"
        rows = {k: v for k, v in rows.items()
                if v["timestamp_real"] and lo <= v["timestamp_real"][11:16] < hi}
    return rows


def diff(pre_db: str, post_db: str, window: str | None) -> None:
    pre = _load_events(pre_db, window)
    post = _load_events(post_db, window)
    scope = f" (window {window})" if window else ""

    added = [post[k] for k in post.keys() - pre.keys()]
    removed = pre.keys() - post.keys()          # should never happen (no hard delete)
    changed = {"movement": [], "class": [], "rejected": [], "unrejected": []}
    for k in pre.keys() & post.keys():
        a, b = pre[k], post[k]
        if a["movement"] != b["movement"]:
            changed["movement"].append((a, b))
        if a["vehicle_class"] != b["vehicle_class"]:
            changed["class"].append((a, b))
        ra, rb = a["rejected"] or 0, b["rejected"] or 0
        if ra != rb:
            changed["rejected" if rb else "unrejected"].append((a, b))

    print(f"R0 DIFF{scope}")
    print(f"  pre  : {pre_db}  ({len(pre):,} events in scope)")
    print(f"  post : {post_db}  ({len(post):,} events in scope)")
    print()
    print(f"  ADDED (add-missed)   : {len(added)}")
    for mv, n in Counter(e["movement"] for e in added).most_common():
        print(f"      {mv:<10} {n}")
    print(f"  REJECTED             : {len(changed['rejected'])}")
    for mv, n in Counter(a["movement"] for a, _ in changed["rejected"]).most_common():
        print(f"      {mv:<10} {n}")
    print(f"  UNREJECTED           : {len(changed['unrejected'])}")
    print(f"  MOVEMENT edited      : {len(changed['movement'])}")
    for pair, n in Counter((a["movement"], b["movement"])
                           for a, b in changed["movement"]).most_common():
        print(f"      {pair[0]} -> {pair[1]}   {n}")
    print(f"  CLASS edited         : {len(changed['class'])}")
    if removed:
        print(f"  !! REMOVED (unexpected — no hard delete exists): {len(removed)}")
    net = len(post) - len(pre)
    print()
    print(f"  NET event delta in scope: {net:+d}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("snapshot")
    s.add_argument("--project", default=DEFAULT_PROJECT)
    s.add_argument("--label", required=True)
    d = sub.add_parser("diff")
    d.add_argument("pre_db")
    d.add_argument("post_db")
    d.add_argument("--window", default=None, help="HHMM-HHMM wallclock scope")
    args = ap.parse_args()
    if args.cmd == "snapshot":
        snapshot(args.project, args.label)
    else:
        diff(args.pre_db, args.post_db, args.window)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
