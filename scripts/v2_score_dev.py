"""Pipeline-V2 D5 — dev scorer (plan_v2_week1_derisk §D5).

THE ONLY V2 MODULE THAT READS MIOVISION (dev-validation basis; never a
runtime input). Scores, on one window's Miovision-covered minutes:
  (a) V2 events (any events_*.json from D4, or a pass-2 working DB),
  (b) the PRODUCTION vehicle_events table (same minutes, for reference),
against per-cell per-15-min 5/95 + the named wall signatures.

Multi-site since the apply-gate block (2026-08-07): --project selects a
SITE entry carrying the window hours, the Miovision export, the leg->
approach direction map, and how wallclock is derived. The corridor entry
is the original behavior verbatim (byte-identical score JSONs — the
apply-gate validation depends on those committed artifacts).

Usage:
  py -X utf8 scripts/v2_score_dev.py runs/v2_week1/events_cam2_study_0700_greedy.json
  py -X utf8 scripts/v2_score_dev.py --project 0acb12c0 <working.db> ...
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, time as dtime, timedelta
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import parse_miovision_xml as MIO                       # noqa: E402
import triangulate_manual as T                          # noqa: E402
from backend.services.rule595 import compliance, score_cells  # noqa: E402

NORM = {"through": "thru", "u_turn": "uturn"}

CORRIDOR = "97a7849a"
FM51 = "0acb12c0"

# FM51-CORD4699 (held-out site, Wise County) leg -> Miovision approach
# DIRECTION. Derived and verified, NOT assumed: the site's Mio export is a
# T with approaches SB FM 51 (north arm), NB FM 51 (south arm), WB Co Rd
# 4699 (east arm), while the operator's compass at this camera is rotated
# a uniform +90 degrees (labels W/E/S sit on the true S/N/E arms — all
# three rotate by the same amount, which is what makes it a compass
# calibration offset rather than mislabeling). The mapping is pinned by
# TURN HANDEDNESS plus magnitude, independently in both windows:
#   ours S->E is a RIGHT   == Mio 'WB Co Rd 4699 R -> SB FM 51'  (51/46 AM, 16/13 PM)
#   ours E->S is a LEFT    == Mio 'SB FM 51 L -> WB Co Rd 4699'  ( 9/11 AM, 23/30 PM)
#   ours S->W is a LEFT    == Mio 'WB Co Rd 4699 L -> NB FM 51'  ( 1/1  PM)
# Leg 4 (label SE) is a driveway the Miovision export has no approach for
# -> unscoreable, dropped (identically for candidate and incumbent).
FM51_LEG_DIR = {1: "NB", 2: "SB", 3: "WB", 4: None}
FM51_XML = Path("docs/historic data/26097 TIA for Wise County, TX/"
                "Cam 1 FM51-CORD4699/"
                "405051_0029_20260430_000003_FM51-CORD4699_1398466_"
                "04-30-2026.xml")

SITES = {
    CORRIDOR: {
        "windows": {"study_0700": (7, 9), "study_1100": (11, 13),
                    "study_1600": (16, 18), "study_0600": (6, 20)},
        "xml": None,            # resolved per camera inside the Mio module
        "leg_dir": None,        # from each leg's cardinal (bound approach)
        "rec_start": None,      # events carry timestamp_real
    },
    FM51: {
        "windows": {"ftv2n_am": (7, 9), "ftv2n_pm": (16, 18)},
        "xml": FM51_XML,
        "leg_dir": FM51_LEG_DIR,
        # this site's events predate timestamp_real being written, so
        # wallclock comes from timestamp_video + the recording start
        "rec_start": datetime(2026, 4, 30, 0, 0, 3),
    },
}


def per_min_from_events(events: list[dict], leg_dir: dict[int, str]):
    out = defaultdict(lambda: defaultdict(int))
    for e in events:
        d = leg_dir.get(e["origin_leg"])
        if not d:
            continue
        tm = datetime.fromisoformat(e["wallclock"]).time().replace(
            second=0, microsecond=0)
        out[tm][(d, NORM.get(e["movement"], e["movement"]))] += 1
    return out


def cell_totals(pm, minutes):
    tot = defaultdict(int)
    mset = set(minutes)
    for tm, cells in pm.items():
        if tm in mset:
            for k, n in cells.items():
                tot[k] += n
    return tot


def leg_dir_for(project: str, cam: int, site: dict) -> dict:
    """Our leg_id -> bound-approach direction. Sites with a pinned map use
    it (the corridor derives it from each leg's cardinal, as before)."""
    if site["leg_dir"] is not None:
        return dict(site["leg_dir"])
    conn = sqlite3.connect(f"file:data/projects/{project}/project.db?mode=ro",
                           uri=True)
    leg_dir = {lid: T._CARD_TO_DIR.get((card or "").strip().upper())
               for lid, card in conn.execute(
                   "SELECT leg_id, cardinal_direction FROM legs "
                   "WHERE camera_id=?", (cam,))}
    conn.close()
    return leg_dir


def events_from_db(path: str, cam: int, site: dict) -> list[dict]:
    """Counted events out of a pass-2 working DB, with wallclock."""
    rec_start = site["rec_start"]
    col = "timestamp_video" if rec_start else "timestamp_real"
    c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    evs = []
    for olid, mv, ts in c.execute(
            f"SELECT origin_leg_id, movement, {col} FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)):
        if ts is None:
            continue
        wall = ((rec_start + timedelta(seconds=float(ts))).isoformat()
                if rec_start else ts)
        evs.append({"origin_leg": olid, "movement": mv, "wallclock": wall})
    c.close()
    return evs


def load_miovision(cam: int, site: dict):
    """Per-minute Mio counts keyed (bound direction, movement)."""
    xml = site["xml"]
    if xml is None:
        return T.load_miovision(cam)
    data = MIO.parse(cam, xml_path=xml)
    labels = MIO.slot_labels(data["movements"], cam, xml_path=xml)
    out = defaultdict(lambda: defaultdict(int))
    for tm, vols in data["per_min"].items():
        t = datetime.fromisoformat(tm).time()
        for i, v in enumerate(vols):
            d = labels[i][0].strip().split()[0].upper()
            out[t][(d, labels[i][1])] += int(v)
    return out


def load_production(project: str, cam: int, site: dict, leg_dir: dict):
    """The site's applied table, same keying (the reference column)."""
    if site["rec_start"] is None and project == CORRIDOR:
        return T.load_ours(cam)
    evs = events_from_db(f"data/projects/{project}/project.db", cam, site)
    return per_min_from_events(evs, leg_dir)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=CORRIDOR,
                    help="site id (default: the Sunnyvale corridor)")
    ap.add_argument("events_json", nargs="+",
                    help="D4 events_*.json OR a pass-2 working twopass_*.db")
    args = ap.parse_args()
    site = SITES[args.project]
    for path in args.events_json:
        stem = Path(path).stem
        if path.endswith(".db"):
            # twopass_cam{c}_{variant}.db from v2_run_pass2 (scratch)
            cam = int(stem.split("_")[1].replace("cam", ""))
            variant = stem.split("_", 2)[2]
            for pref in ("v2a_", "v2b_", "v2c_", "v2d_"):
                variant = variant.replace(pref, "")
            blob = {"camera": cam,
                    "events": events_from_db(path, cam, site)}
        else:
            blob = json.loads(Path(path).read_text())
            cam = blob["camera"]
            variant = "_".join(stem.split("_")[2:4])
        lo, hi = site["windows"][variant]
        minutes = [dtime(h, m) for h in range(lo, hi) for m in range(60)]

        leg_dir = leg_dir_for(args.project, cam, site)
        mio = load_miovision(cam, site)
        mio_minutes = [m for m in minutes if m in mio]
        ours_v2 = per_min_from_events(blob["events"], leg_dir)
        ours_prod = load_production(args.project, cam, site, leg_dir)

        rows_v2 = score_cells(ours_v2, mio, mio_minutes)
        rows_prod = score_cells(ours_prod, mio, mio_minutes)
        c_v2, c_prod = compliance(rows_v2), compliance(rows_prod)

        t_mio = cell_totals(mio, mio_minutes)
        t_v2 = cell_totals(ours_v2, mio_minutes)
        t_prod = cell_totals(ours_prod, mio_minutes)

        print(f"\n=== {stem} (cam{cam} {variant}, "
              f"{len(mio_minutes)} Mio minutes) ===")
        print(f"5/95 cell-bins: V2 {c_v2['pct']}% "
              f"({c_v2['compliant']}/{c_v2['cells_scored']})  |  "
              f"PRODUCTION {c_prod['pct']}% "
              f"({c_prod['compliant']}/{c_prod['cells_scored']})")
        print(f"{'cell':>12} {'Mio':>6} {'V2':>6} {'prod':>6}")
        for k in sorted(set(t_mio) | set(t_v2) | set(t_prod)):
            print(f"{k[0]+' '+k[1]:>12} {t_mio.get(k,0):>6} "
                  f"{t_v2.get(k,0):>6} {t_prod.get(k,0):>6}")
        out = Path("runs/v2_week1") / f"score_{stem}.json"
        out.write_text(json.dumps(
            {"v2": c_v2, "production": c_prod,
             "totals": {f"{k[0]}_{k[1]}": [t_mio.get(k, 0), t_v2.get(k, 0),
                                           t_prod.get(k, 0)]
                        for k in sorted(set(t_mio) | set(t_v2) | set(t_prod))}},
            indent=1))
        print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
