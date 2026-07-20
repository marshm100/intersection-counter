"""PHASE 3 corridor per-approach scorer — reproduces corridor_scored.json's
AVG|err| structure on the phase-3 sweep DBs. Replicates triangulate_manual.
load_ours against arbitrary sweep DBs (leg cardinal -> bound approach via
_CARD_TO_DIR, timestamp_real binned per minute) and scores vs load_miovision
through interval_metric.per_interval(by_approach=True).

VALIDATION: the OFF column must reproduce the committed corridor_scored.json
'off' numbers (my code is byte-identical when off) — that proves the scorer
faithful; then the ON3 column is the phase-3 result. ACCEPTANCE: cam2
6.7->~<=4.1, cam5 approaches recover, cam1/3/4 flat.
"""
from __future__ import annotations
import sys, json, sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import datetime

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")
import triangulate_manual as T
import interval_metric as IM

SCRATCH = Path(r"C:\Users\onkar\AppData\Local\Temp\ic_scratch_97a7849a")
CAMS = {
    1: ["study_0700"],
    2: ["study_0700", "study_1100", "study_1600"],
    3: ["study_0000"],
    4: ["study_0700", "study_1100", "study_1600"],
    5: ["study_0700", "study_1100", "study_1600"],
}
NORM = {"through": "thru", "u_turn": "uturn", "left": "left", "right": "right"}


def load_ours_db(dbs, cam):
    out = defaultdict(lambda: defaultdict(int))
    c0 = sqlite3.connect(str(dbs[0]))
    leg_dir = {lid: T._CARD_TO_DIR.get((card or "").strip().upper())
               for lid, card in c0.execute(
                   "SELECT leg_id,cardinal_direction FROM legs WHERE camera_id=?",
                   (cam,))}
    c0.close()
    for db in dbs:
        c = sqlite3.connect(str(db))
        for olid, mv, ts in c.execute(
                "SELECT origin_leg_id, movement, timestamp_real FROM vehicle_events "
                "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)):
            d = leg_dir.get(olid)
            if ts and d:
                key = datetime.fromisoformat(ts).time().replace(second=0, microsecond=0)
                out[key][(d, NORM.get(mv, mv))] += 1
        c.close()
    return out


committed = json.loads(Path("runs/origin_veto/corridor_scored.json").read_text())
result = {}
for cam, windows in CAMS.items():
    try:
        mio = T.load_miovision(cam)
    except Exception as e:
        print(f"cam{cam}: no miovision reference ({e}) -- skipping scored", flush=True)
        continue
    row = {"per_approach": {}}
    ok = True
    for tag in ("off", "on"):
        dbs = [SCRATCH / f"sweep_p3_{tag}_{cam}_{w}.db" for w in windows]
        miss = [str(p) for p in dbs if not p.exists()]
        if miss:
            print(f"cam{cam} {tag}: MISSING {miss}", flush=True)
            ok = False
            break
        ours = load_ours_db(dbs, cam)
        # score only the minutes we actually replayed (the study windows)
        res = IM.per_interval(ours, mio, minutes=sorted(ours.keys()),
                              by_approach=True)
        row[f"total_{tag}"] = round(res["avg_abs_err_pct"], 1)
        for d, r in res["per_approach"].items():
            row["per_approach"].setdefault(d, {})[tag] = (
                round(r["avg_abs_err_pct"], 1) if r["n_bins"] else None)
    if ok:
        result[str(cam)] = row

# ---- report + validate OFF vs committed -----------------------------------
print("\n================ CORRIDOR PHASE-3 SCORED (AVG|err|%) ================")
print(f"{'cam':>4} {'OFF':>6} {'ON3':>6} | {'cOFF':>6} {'cON1':>6}  (committed)")
for cam in sorted(result, key=int):
    r = result[cam]
    c = committed.get(cam, {})
    off_match = "OK" if r.get("total_off") == c.get("total_off") else "DIFF"
    print(f"{cam:>4} {r.get('total_off'):>6} {r.get('total_on'):>6} | "
          f"{c.get('total_off'):>6} {c.get('total_on'):>6}  OFF-parity:{off_match}")
    capp = c.get("per_approach", {})
    for d in sorted(r["per_approach"]):
        on1 = capp.get(d, {}).get("on")
        print(f"       {d:<3} off={r['per_approach'][d].get('off')} "
              f"on3={r['per_approach'][d].get('on')}  (committed on1={on1})")

Path("runs/origin_veto/corridor_scored_phase3.json").write_text(json.dumps(result, indent=1))
print("\nwrote runs/origin_veto/corridor_scored_phase3.json")
