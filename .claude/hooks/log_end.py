"""Hook fired on Stop. Finalizes the current task entry and appends to the log.

Pulls the start record left by log_start.py, adds end timestamp, duration,
files changed, and any commits made during the turn, then appends one JSON
line to logs/task-log.jsonl. All failures are silent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURRENT_TASK_FILE = PROJECT_ROOT / ".claude" / "current-task.json"
LOG_FILE = PROJECT_ROOT / "logs" / "task-log.jsonl"


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except Exception:
        return ""


def main() -> None:
    if not CURRENT_TASK_FILE.exists():
        return

    try:
        record = json.loads(CURRENT_TASK_FILE.read_text(encoding="utf-8"))
    except Exception:
        try:
            CURRENT_TASK_FILE.unlink()
        except Exception:
            pass
        return

    end_dt = datetime.now().astimezone()
    record["ended_at"] = end_dt.isoformat(timespec="seconds")

    try:
        start_dt = datetime.fromisoformat(record.get("started_at", ""))
        record["duration_seconds"] = max(0, int((end_dt - start_dt).total_seconds()))
    except Exception:
        record["duration_seconds"] = None

    start_sha = record.get("start_sha", "")
    end_sha = _git("rev-parse", "HEAD")
    record["end_sha"] = end_sha

    files: list[str] = []

    def _add(paths: list[str]) -> None:
        for p in paths:
            p = p.strip().strip('"')
            if p and p not in files:
                files.append(p)

    if start_sha and end_sha and start_sha != end_sha:
        _add(_git("diff", "--name-only", start_sha, end_sha).splitlines())

    # Tracked changes since HEAD (staged + unstaged)
    _add(_git("diff", "--name-only", "HEAD").splitlines())
    # Untracked files
    _add(_git("ls-files", "--others", "--exclude-standard").splitlines())
    record["files_changed"] = files

    commits: list[str] = []
    if start_sha and end_sha and start_sha != end_sha:
        log = _git("log", "--pretty=format:%H %s", f"{start_sha}..{end_sha}")
        commits = [line for line in log.splitlines() if line]
    record["commits"] = commits

    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass

    try:
        CURRENT_TASK_FILE.unlink()
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
