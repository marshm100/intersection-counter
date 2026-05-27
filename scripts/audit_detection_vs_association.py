"""Step 0 detection audit report (Attribution v2 P2.C).

Reads the per-track audit JSON produced by `reprocess_camera.py --audit` and
splits finalized tracks into:
  - "never emitted"      : YOLO produced no confident box for the track
                           (real_yolo_hits == 0)
  - "emitted, fragmented": YOLO DID emit boxes but the track died too short /
                           with a long coasted gap before it could be used
                           (real_yolo_hits >= 1 but final_points < min_points,
                            or max_coasted_gap > finalize_gap, or origin never
                            assigned)
  - "ok"                 : everything else (a usable track)

Reported per distance/size band (entry bbox area quartiles — smaller area =
farther vehicle). The split decides OC-SORT ROI: if a large share of the
short/fragmented tracks were "emitted but fragmented", OC-SORT's gap recovery
is worth it; if dominated by "never emitted" in the far band, the gap is
detector recall and OC-SORT won't help (pivot to detector work).

Usage:
  py scripts/audit_detection_vs_association.py
  py scripts/audit_detection_vs_association.py --audit-json <path>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import ORIGIN_ASSIGN_MIN_FRAMES, TRACK_FINALIZE_GAP_FRAMES


def classify(rec: dict) -> str:
    if rec["real_yolo_hits"] == 0:
        return "never_emitted"
    fragmented = (
        rec["final_points"] < ORIGIN_ASSIGN_MIN_FRAMES
        or rec["max_coasted_gap"] > TRACK_FINALIZE_GAP_FRAMES
        or not rec.get("origin_assigned", True)
    )
    return "emitted_fragmented" if fragmented else "ok"


def _quartile_bands(areas: list[float]) -> list[float]:
    s = sorted(a for a in areas if a is not None)
    if not s:
        return [0, 0, 0]
    def q(p):
        return s[min(len(s) - 1, int(p * len(s)))]
    return [q(0.25), q(0.50), q(0.75)]


def band_of(area, cuts) -> str:
    if area is None:
        return "unknown"
    if area <= cuts[0]:
        return "far (smallest 25%)"
    if area <= cuts[1]:
        return "mid-far"
    if area <= cuts[2]:
        return "mid-near"
    return "near (largest 25%)"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, default=1)
    ap.add_argument("--audit-json", default=None)
    args = ap.parse_args()

    path = Path(args.audit_json) if args.audit_json else (
        Path("data/projects") / args.project / "detections" / str(args.camera)
        / "track_audit.json")
    if not path.exists():
        raise SystemExit(
            f"No audit JSON at {path}. Run: py scripts/reprocess_camera.py --yes --audit")

    records = json.loads(path.read_text())
    print(f"Loaded {len(records)} track audit records from {path}")
    print(f"(min_points={ORIGIN_ASSIGN_MIN_FRAMES}, "
          f"finalize_gap={TRACK_FINALIZE_GAP_FRAMES})\n")

    cuts = _quartile_bands([r.get("entry_bbox_area") for r in records])
    print(f"entry-bbox-area quartile cuts (px^2): {[round(c) for c in cuts]}\n")

    # band -> class -> count
    table: dict[str, dict[str, int]] = {}
    totals = {"never_emitted": 0, "emitted_fragmented": 0, "ok": 0}
    for r in records:
        cls = classify(r)
        b = band_of(r.get("entry_bbox_area"), cuts)
        table.setdefault(b, {"never_emitted": 0, "emitted_fragmented": 0, "ok": 0})
        table[b][cls] += 1
        totals[cls] += 1

    order = ["far (smallest 25%)", "mid-far", "mid-near", "near (largest 25%)", "unknown"]
    print(f"{'band':<20} {'never_emit':>11} {'fragmented':>11} {'ok':>7} {'total':>7}")
    print("-" * 60)
    for b in order:
        if b not in table:
            continue
        row = table[b]
        tot = sum(row.values())
        print(f"{b:<20} {row['never_emitted']:>11} {row['emitted_fragmented']:>11} "
              f"{row['ok']:>7} {tot:>7}")
    print("-" * 60)
    grand = sum(totals.values()) or 1
    print(f"{'TOTAL':<20} {totals['never_emitted']:>11} {totals['emitted_fragmented']:>11} "
          f"{totals['ok']:>7} {grand:>7}")

    lost = totals["never_emitted"] + totals["emitted_fragmented"]
    print(f"\nOf the {lost} lost/short tracks: "
          f"{totals['emitted_fragmented']} ({totals['emitted_fragmented']/max(1,lost)*100:.0f}%) "
          f"were EMITTED-BUT-FRAGMENTED, "
          f"{totals['never_emitted']} ({totals['never_emitted']/max(1,lost)*100:.0f}%) "
          f"were NEVER EMITTED.")
    print("\nGo/no-go (P2.C): if fragmented share is high (>~35-40%), OC-SORT gap "
          "recovery is worth it. If dominated by never-emitted in the far band, "
          "the gap is detector recall -> pivot to detector work, OC-SORT is low-ROI.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
