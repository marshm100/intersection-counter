"""Hook fired on Stop. If uncommitted changes include backend methodology
files but no docs/walkthrough/ updates, prints a reminder via systemMessage.

Methodology = files whose behavior is described in the walkthrough:
  - backend/services/**   (pipeline, detector, tracker, classifiers, origin)
  - backend/config.py     (tunables/thresholds quoted on pages 2-4)
  - backend/database.py   (schema referenced on pages 0/5)

Passive reminder only — never blocks the stop, never modifies anything.
Silent on internal failure so it never disrupts the user's flow.
"""
import json
import re
import subprocess
import sys


METHODOLOGY = re.compile(r"^backend/(services/|config\.py$|database\.py$)")
WALKTHROUGH = re.compile(r"^docs/walkthrough/")


def changed_files() -> list[str]:
    """All paths git knows about with any pending change since HEAD:
    staged, unstaged, AND untracked. `git diff HEAD` misses untracked
    files; `git status --porcelain` catches them too, which matters when
    the walkthrough itself isn't committed yet."""
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=False, timeout=5,
        )
        # porcelain format: 2-char status + space + path (rename = " -> ").
        files = []
        for line in out.stdout.splitlines():
            if not line:
                continue
            path = line[3:].split(" -> ")[-1]
            files.append(path)
        return files
    except Exception:
        return []


def main() -> None:
    try:
        sys.stdin.read()
    except Exception:
        pass

    files = changed_files()
    methodology = [f for f in files if METHODOLOGY.match(f)]
    walkthrough = [f for f in files if WALKTHROUGH.match(f)]

    if methodology and not walkthrough:
        listing = "\n  ".join(methodology)
        msg = (
            "Walkthrough may be stale -- backend methodology changed "
            f"without docs/walkthrough/ updates:\n  {listing}\n"
            "Review whether the walkthrough needs updating."
        )
        print(json.dumps({"systemMessage": msg}))
    else:
        print("{}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        print("{}")
