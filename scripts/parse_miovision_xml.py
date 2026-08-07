"""Parse the Miovision per-minute OD XML (the detailed export, richer than the
15-min summary CSV). Returns per-minute origin->destination movement counts.

The XML (docs/historic data/*.xml, BinSize=1) holds, per 1-minute bin and per
vehicle-class Group (Lights/Mediums/Articulated), 16 volumes — one per Movement,
each a (Name T/R/L, InApproachIndex, OutApproachIndex) over the 4 approaches:
  0=SB N Belt Line Rd, 1=WB Private Driveway, 2=EB Northwest Dr, 3=NB N Belt Line.
Through-pairs {0,3} (arterial) and {1,2} (cross street). This is per-minute and
carries the full OD matrix (origin AND destination), vs the CSV's 15-min coarse
movement counts. Verify-mode aggregates to 15-min and compares to the CSV.

Usage:  py scripts/parse_miovision_xml.py            # verify vs 15-min CSV
"""
from __future__ import annotations

import re
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime
from pathlib import Path

_HIST = Path("docs/historic data/Sunnyvale, TX")


def camera_xml(camera_id: int) -> Path:
    """Resolve a camera's Miovision per-minute OD XML (subfolder 'camN ...')."""
    folder = next(_HIST.glob(f"cam{camera_id} *"))
    return next(folder.glob("*.xml"))


XML = camera_xml(1)  # cam1 default (per-camera approach maps differ — see camera_xml)


def _root(camera_id: int | None, xml_path: Path | None = None):
    """Parse a camera's Miovision XML to an ElementTree root.
    camera_id None -> the module-default XML (cam1), for legacy callers.
    xml_path wins outright — how a HELD-OUT site (outside the Sunnyvale
    corridor folder this module's resolver knows) supplies its own export."""
    xml = xml_path or (XML if camera_id is None else camera_xml(camera_id))
    txt = xml.read_text(encoding="utf-8-sig")
    txt = re.sub(r"<\?xml[^>]*\?>", "", txt, count=1).lstrip()
    return ET.fromstring(txt)


def approaches(camera_id: int | None = None,
               xml_path: Path | None = None) -> dict[int, str]:
    """{approach_idx: approach Name} read straight from the camera's XML
    <Approaches> (e.g. {0:'SB N Belt Line Rd', ...}). Data-driven — the per-
    camera approach order and count (3 for a T, 4 for a 4-way) come from the
    file, not a hardcoded table."""
    root = _root(camera_id, xml_path)
    return {i: a.findtext("Name")
            for i, a in enumerate(root.find("Approaches").findall("Approach"))}


# cam1 approach map kept as a module constant for legacy callers (verify(), etc.)
APPROACH = approaches(None)


def parse(camera_id: int | None = None,
          xml_path: Path | None = None) -> dict:
    """Return {minute_iso: [count per slot]} summed over vehicle classes, plus
    .movements = [(name, in_idx, out_idx)] for each slot. Slot count follows the
    camera's movement count (9 for a T-intersection, 16 for a 4-way).
    xml_path: an explicit export (held-out sites outside the corridor)."""
    root = _root(camera_id, xml_path)
    s = lambda t: t.split("}")[-1]

    movements = []
    for m in (x for x in root.iter() if s(x.tag) == "Movement"):
        movements.append((m.findtext("Name"),
                          int(m.findtext("InApproachIndex")),
                          int(m.findtext("OutApproachIndex"))))
    n = len(movements)

    per_min: dict[str, list[int]] = defaultdict(lambda: [0] * n)
    for g in (x for x in root.iter() if s(x.tag) == "Group"):
        for b in (x for x in g.iter() if s(x.tag) == "Bin"):
            tm = b.findtext("Time")
            vols = [int(v.text) for v in b.find("volumes")]
            acc = per_min[tm]
            for i, v in enumerate(vols):
                acc[i] += v

    return {"per_min": dict(per_min), "movements": movements}


# Miovision Group names -> the deliverable's L/M/A buckets (mirrors
# audit_fm51's mapping; unknown groups fold into Lights).
MIO_GROUP_TO_LMA = {
    "Lights": "Lights", "Light": "Lights", "Cars": "Lights",
    "Mediums": "Mediums", "Medium": "Mediums",
    "Single-Unit Trucks": "Mediums", "Buses": "Mediums",
    "Articulated Trucks": "Articulated", "Articulated": "Articulated",
}


def parse_by_class(camera_id: int | None = None) -> dict:
    """Like parse() but keeps the vehicle-class dimension
    (plan_595_standard step 1.1 — the customer standard is per
    'classification'): {"per_min": {minute_iso: {lma_class: [vols per
    slot]}}, "movements": [...]}. Groups map to L/M/A via
    MIO_GROUP_TO_LMA."""
    root = _root(camera_id)
    s = lambda t: t.split("}")[-1]
    movements = []
    for m in (x for x in root.iter() if s(x.tag) == "Movement"):
        movements.append((m.findtext("Name"),
                          int(m.findtext("InApproachIndex")),
                          int(m.findtext("OutApproachIndex"))))
    n = len(movements)
    per_min: dict[str, dict[str, list[int]]] = defaultdict(
        lambda: defaultdict(lambda: [0] * n))
    for g in (x for x in root.iter() if s(x.tag) == "Group"):
        gname = g.findtext("Name") or g.get("Name") or "Lights"
        cls = MIO_GROUP_TO_LMA.get(gname, "Lights")
        for b in (x for x in g.iter() if s(x.tag) == "Bin"):
            tm = b.findtext("Time")
            vols = [int(v.text) for v in b.find("volumes")]
            acc = per_min[tm][cls]
            for i, v in enumerate(vols):
                acc[i] += v
    return {"per_min": {k: dict(v) for k, v in per_min.items()},
            "movements": movements}


# slot -> (approach_name, movement_label) using Name T/R/L + InApproachIndex
def slot_labels(movements, camera_id: int | None = None,
                xml_path: Path | None = None):
    appr = (approaches(camera_id, xml_path) if xml_path is not None
            else APPROACH if camera_id is None else approaches(camera_id))
    NAME = {"T": "thru", "R": "right", "L": "left", "U": "uturn"}
    labels = []
    for name, i_in, i_out in movements:
        mv = NAME.get(name, "uturn" if i_in == i_out else name)
        labels.append((appr[i_in], mv, appr.get(i_out)))
    return labels


def verify():
    """Aggregate per-minute -> 15-min and compare to the summary CSV."""
    import groundtruth
    data = parse()
    labels = slot_labels(data["movements"])
    # sum per-minute into 15-min buckets, by (approach, movement)
    buckets: dict[str, dict] = defaultdict(lambda: defaultdict(int))
    for tm, vols in data["per_min"].items():
        dt = datetime.fromisoformat(tm)
        b15 = dt.replace(minute=(dt.minute // 15) * 15, second=0)
        key = b15.strftime("%-I:%M %p") if sys.platform != "win32" else b15.strftime("%#I:%M %p")
        for i, v in enumerate(vols):
            appr, mv, _ = labels[i]
            buckets[key][(appr, mv)] += v
    manual = groundtruth.parse_manual_csv()
    print("Verify XML per-min -> 15min  vs  summary CSV (7:00, 7:15 buckets):")
    print(f"{'bucket':<9}{'approach':<22}{'mvt':<6}{'XML':>5}{'CSV':>5}{'ok':>4}")
    for bk in ("7:00 AM", "7:15 AM"):
        for appr in ("SB N Belt Line Rd", "NB N Belt Line Rd", "EB Northwest Dr", "WB Private Driveway"):
            for mv in ("thru", "left", "right", "uturn"):
                x = buckets.get(bk, {}).get((appr, mv), 0)
                c = manual.get(bk, {}).get(appr, {}).get(mv, 0)
                if x == 0 and c == 0:
                    continue
                print(f"{bk:<9}{appr[:20]:<22}{mv:<6}{x:>5}{c:>5}{'  ok' if x==c else ' XX':>4}")


if __name__ == "__main__":
    verify()
