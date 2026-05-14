"""Hook fired on UserPromptSubmit. Stashes the start of a task entry.

The entry is finalized by log_end.py when the assistant turn completes.
Failures here must be silent so they never block the user's prompt.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CURRENT_TASK_FILE = PROJECT_ROOT / ".claude" / "current-task.json"


def _git_head() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip()
    except Exception:
        return ""


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except Exception:
        payload = {}

    record = {
        "started_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "prompt": payload.get("prompt", ""),
        "session_id": payload.get("session_id", ""),
        "start_sha": _git_head(),
    }

    try:
        CURRENT_TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
        CURRENT_TASK_FILE.write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
