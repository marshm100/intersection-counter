"""Audit our FM51-CORD4699 pipeline output against the Miovision deliverable
(same 2026-04-30 footage, camera 405051). Localizes the ~8% miss: per 15-min
interval (find the worst), per vehicle class (Lights/Mediums/Articulated), and
per approach. Mapping-free for the total/interval/class cuts; per-approach maps
our legs to Miovision approaches by geometry+volume.

Usage:  py scripts/audit_fm51.py
"""
from __future__ import annotations
import re, sqlite3, sys
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

PROJECT = "0acb12c0"
CAM = 2
REC_START = datetime(2026, 4, 30, 0, 0, 3)
XML = Path("docs/historic data/26097 TIA for Wise County, TX/Cam 1 FM51-CORD4699/"
           "405051_0029_20260430_000003_FM51-CORD4699_1398466_04-30-2026.xml")
# FHWA class -> Miovision bucket
_FHWA_TO_MIO = {1: "Lights", 2: "Lights", 3: "Lights",
                4: "Mediums", 5: "Mediums", 6: "Mediums", 7: "Mediums",
                8: "Articulated", 9: "Articulated", 10: "Articulated",
                11: "Articulated", 12: "Articulated", 13: "Articulated"}
_MIO_GROUP = {"Lights": "Lights", "Mediums": "Mediums",
              "Articulated Trucks": "Articulated"}


def _iv(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)


def load_miovision():
    txt = re.sub(r"<\?xml[^>]*\?>", "", XML.read_text(encoding="utf-8-sig"), count=1).lstrip()
    root = ET.fromstring(txt)
    s = lambda t: t.split("}")[-1]
    appr = [a.findtext("Name") for a in root.find("Approaches").findall("Approach")]
    moves = [(m.findtext("Name"), int(m.findtext("InApproachIndex")),
              int(m.findtext("OutApproachIndex"))) for m in root.iter() if s(m.tag) == "Movement"]
    per_iv_total = defaultdict(int)
    per_appr = defaultdict(int)
    per_class = defaultdict(int)
    per_iv_appr = defaultdict(int)
    for g in (x for x in root.iter() if s(x.tag) == "Group"):
        cls = _MIO_GROUP.get(g.findtext("Name") or g.get("Name"), "Lights")
        for b in (x for x in g.iter() if s(x.tag) == "Bin"):
            t = datetime.fromisoformat(b.findtext("Time")); iv = _iv(t)
            vols = [int(v.text) for v in b.find("volumes")]
            for i, v in enumerate(vols):
                per_iv_total[iv] += v
                per_appr[appr[moves[i][1]]] += v
                per_class[cls] += v
                per_iv_appr[(iv, appr[moves[i][1]])] += v
    return dict(per_iv_total), dict(per_appr), dict(per_class), dict(per_iv_appr), appr


def load_ours():
    c = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    legs = {lid: lab for lid, lab in c.execute(
        "SELECT leg_id,label FROM legs WHERE camera_id=?", (CAM,))}
    per_iv_total = defaultdict(int); per_leg = defaultdict(int)
    per_class = defaultdict(int); per_iv_leg = defaultdict(int)
    for olid, tsv, fhwa in c.execute(
            "SELECT origin_leg_id, timestamp_video, fhwa_class FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0", (CAM,)):
        if tsv is None:
            continue
        iv = _iv(REC_START + timedelta(seconds=float(tsv)))
        per_iv_total[iv] += 1
        per_leg[legs.get(olid, f"leg{olid}")] += 1
        per_class[_FHWA_TO_MIO.get(fhwa, "Lights" if fhwa is None else "?")] += 1
        per_iv_leg[(iv, legs.get(olid, f"leg{olid}"))] += 1
    c.close()
    return dict(per_iv_total), dict(per_leg), dict(per_class), dict(per_iv_leg)


def main():
    m_iv, m_appr, m_cls, m_iv_appr, appr = load_miovision()
    o_iv, o_leg, o_cls, o_iv_leg = load_ours()
    tM, tO = sum(m_iv.values()), sum(o_iv.values())
    print(f"TOTAL  Miovision {tM}   ours {tO}   ours-Mio {tO-tM:+d} ({100*(tO-tM)/tM:+.1f}%)\n")

    print("=== per 15-min interval (total) ===")
    print(f"{'interval':<8}{'MIO':>6}{'OURS':>6}{'diff':>7}{'err%':>8}")
    worst = (0, None)
    for iv in sorted(set(m_iv) | set(o_iv)):
        mi, ou = m_iv.get(iv, 0), o_iv.get(iv, 0)
        err = 100 * (ou - mi) / mi if mi else 0.0
        if abs(err) > abs(worst[0]):
            worst = (err, iv)
        print(f"{iv.strftime('%H:%M'):<8}{mi:>6}{ou:>6}{ou-mi:>+7}{err:>+7.1f}%")
    print(f"  WORST interval: {worst[1].strftime('%H:%M')}  {worst[0]:+.1f}%")

    print("\n=== per vehicle class (Lights/Mediums/Articulated) ===")
    for k in ("Lights", "Mediums", "Articulated"):
        print(f"  {k:<12} Miovision {m_cls.get(k,0):>5}   ours {o_cls.get(k,0):>5}")

    print("\n=== per approach (Miovision) vs per leg (ours), by volume ===")
    print("  Miovision:", {k: m_appr[k] for k in sorted(m_appr, key=lambda x: -m_appr[x])})
    print("  ours legs:", {k: o_leg[k] for k in sorted(o_leg, key=lambda x: -o_leg[x])})


if __name__ == "__main__":
    main()
