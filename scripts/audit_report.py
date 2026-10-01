r"""Event-audit report (2026-10-01): the operator's verdicts on counted events, as precision
per camera x decision path (backend/services/event_audit.py, /static/audit.html).

precision = correct / answered (unsure left out). Also the share of each failure kind, so a
decision path that counts NON-intersection traffic reads differently from one that picks the
wrong movement or counts a vehicle twice.
Usage: .venv/Scripts/python.exe -X utf8 scripts/audit_report.py [BATCH]
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.services.event_audit import list_items  # noqa: E402

PROJ = "97a7849a"


def main() -> int:
    batch = sys.argv[1] if len(sys.argv) > 1 else "a1"
    items = list_items(PROJ, batch)
    done = [i for i in items if i["answer"]]
    print(f"batch {batch}: {len(done)} of {len(items)} answered\n")
    for key, label in ((lambda i: i["stratum"].split("|")[0], "GATE EVIDENCE (all cameras)"),
                       (lambda i: i["stratum"], "DECISION PATH (all cameras)"),
                       (lambda i: (i["camera_id"], i["stratum"].split("|")[0]), "CAMERA x GATE EVIDENCE")):
        groups = defaultdict(Counter)
        for i in done:
            groups[key(i)][i["answer"]["verdict"]] += 1
        print(label)
        for k, c in sorted(groups.items(), key=lambda kv: str(kv[0])):
            judged = sum(v for kk, v in c.items() if kk != "unsure")
            prec = c["correct"] / judged if judged else float("nan")
            print(f"  {str(k):34} n={sum(c.values()):3}  precision {prec:5.0%}   "
                  f"wrong mvmt {c['wrong_movement']:2}  not intersection {c['not_intersection']:2}  "
                  f"double {c['double']:2}  unsure {c['unsure']:2}")
        print()
    wrong = [i for i in done if i["answer"]["verdict"] == "wrong_movement"]
    if wrong:
        print("WRONG MOVEMENTS (claimed origin->dest => true origin->dest):")
        for i in wrong:
            a = i["answer"]
            print(f"  cam{i['camera_id']} {i['stratum']:28} {i['claimed_origin_leg_id']}->"
                  f"{i['claimed_dest_leg_id']} => {a['true_origin_leg_id']}->{a['true_dest_leg_id']}"
                  f"  {a['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
