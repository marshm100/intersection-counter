"""PHASE 3 FM51 ablation — re-gate the veto's rescue half + rewrite-veto.

OFF baseline = the existing fullchain_ftv1_{am,pm}.db (flag-off, unchanged by
phase 3 — proven byte-identical by the flag-off unit test). ON = a fresh
replay of the SAME ftv1 detection caches through the phase-3 pipeline with
ORIGIN_CLAIM_VETO on. Reproduces runs/origin_veto/fm51_ablation.json's
metrics (per_leg / kills / totals / interval_mae) plus the (origin,movement)
cell table (the S-right 76->84 leak) and the new rescue/rewrite counters.

Compare to the committed phase-1 numbers to confirm: the redirect HOLDS
(leg 3 down, leg 1 up, kills low), the leak CLOSES (S-right back toward 76),
and drops RETURN as counts (rescued > 0, totals move toward Miovision 3469).
"""
from __future__ import annotations
import sys, json, sqlite3
from pathlib import Path
from collections import defaultdict
from datetime import timedelta

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")
import audit_fm51 as A
from backend.services.pass2_replay import replay_camera
from backend.services.through_gate import bank_turn_pairs
from backend.database import list_paths_for_camera
import backend.services.pipeline as PL

PROJECT, CAM, REC_START = A.PROJECT, A.CAM, A.REC_START
SCRATCH = Path(r"C:\Users\onkar\AppData\Local\Temp\ic_scratch_fm51")
VARIANTS = ["ftv1_am", "ftv1_pm"]
TURN_PAIRS = set(bank_turn_pairs(list_paths_for_camera(PROJECT, CAM), 3))
LEG = {1: "W", 2: "E", 3: "S", 4: "SE"}


def score(dbs):
    per_leg = defaultdict(int); cell = defaultdict(int); per_iv = defaultdict(int)
    kills = 0; total = 0
    for db in dbs:
        c = sqlite3.connect(str(db))
        for olid, dlid, mv, tsv in c.execute(
                "SELECT origin_leg_id, destination_leg_id, movement, "
                "timestamp_video FROM vehicle_events "
                "WHERE camera_id=? AND COALESCE(rejected,0)=0", (CAM,)):
            total += 1
            per_leg[olid] += 1
            cell[(olid, mv)] += 1
            if mv == "through" and (olid, dlid) in TURN_PAIRS:
                kills += 1
            if tsv is not None:
                iv = A._iv(REC_START + timedelta(seconds=float(tsv)))
                per_iv[iv] += 1
        c.close()
    return {"per_leg": dict(per_leg), "cell": cell, "kills": kills,
            "total": total, "per_iv": dict(per_iv)}


def imae(per_iv, mio_iv):
    errs = [abs(100.0 * (per_iv.get(iv, 0) - m) / m)
            for iv, m in mio_iv.items() if m]
    return round(sum(errs) / len(errs), 2) if errs else None


mio_iv = A.load_miovision()[0]
mio_total = sum(mio_iv.values())

# ---- OFF: score the existing baseline DBs (flag-off basis) ----------------
off_dbs = [SCRATCH / f"fullchain_{v}.db" for v in VARIANTS]
missing = [str(p) for p in off_dbs if not p.exists()]
if missing:
    raise SystemExit(f"OFF baseline DBs missing: {missing}")
off = score(off_dbs)

# ---- ON: fresh phase-3 replay with the veto flag on -----------------------
PL.ORIGIN_CLAIM_VETO_ENABLED = True
print(f"[replay] flag ON = {PL.ORIGIN_CLAIM_VETO_ENABLED}", flush=True)
on_dbs = []; rescued = rew = vetoed = 0
for v in VARIANTS:
    out = SCRATCH / f"fullchain_veto3_{v}.db"
    st = replay_camera(PROJECT, CAM, variant=v, out_db=out)
    rescued += st.get("origin_rescued", 0)
    rew += st.get("origin_rewrite_vetoed", 0)
    vetoed += st.get("origin_vetoed", 0)
    print(f"[replay] {v}: events={st['events']} vetoed={st.get('origin_vetoed')} "
          f"rescued={st.get('origin_rescued')} rewrite_vetoed="
          f"{st.get('origin_rewrite_vetoed')}", flush=True)
    on_dbs.append(out)
on = score(on_dbs)

# ---- report ---------------------------------------------------------------
committed = json.loads(Path("runs/origin_veto/fm51_ablation.json").read_text())


def legname(d):
    return {LEG.get(k, k): v for k, v in sorted(d.items())}


print("\n================= FM51 PHASE-3 ABLATION =================")
print(f"Miovision total: {mio_total}")
print(f"\nper_leg  OFF : {legname(off['per_leg'])}")
print(f"per_leg  ON3 : {legname(on['per_leg'])}")
print(f"per_leg  ON1 (committed phase-1): "
      f"{ {LEG.get(int(k), k): v for k, v in committed['per_leg']['on'].items()} }")
print(f"\nkills    OFF={off['kills']}  ON3={on['kills']}  "
      f"(committed ON1={committed['kills']['on']})")
print(f"totals   mio={mio_total}  OFF={off['total']}  ON3={on['total']}  "
      f"(committed ON1={committed['totals']['on']})")
print(f"intMAE   OFF={imae(off['per_iv'], mio_iv)}  ON3={imae(on['per_iv'], mio_iv)}  "
      f"(committed ON1={committed.get('interval_mae_on')})")
print(f"\ncounters ON3: vetoed={vetoed}  rescued={rescued}  rewrite_vetoed={rew}")

print("\n--- (origin,movement) cell table, S-leg (3) + main throughs ---")
keys = sorted(set(off['cell']) | set(on['cell']))
print(f"{'cell':<16}{'OFF':>6}{'ON3':>6}{'delta':>7}")
for (olid, mv) in keys:
    o = off['cell'].get((olid, mv), 0); n = on['cell'].get((olid, mv), 0)
    if o == 0 and n == 0:
        continue
    if olid == 3 or mv == "through":       # the stem cells + all throughs
        print(f"{LEG.get(olid, olid) + '-' + str(mv):<16}{o:>6}{n:>6}{n - o:>+7}")

out = {
    "per_leg": {"off": off['per_leg'], "on": on['per_leg']},
    "kills": {"off": off['kills'], "on": on['kills']},
    "totals": {"mio": mio_total, "off": off['total'], "on": on['total']},
    "interval_mae_off": imae(off['per_iv'], mio_iv),
    "interval_mae_on": imae(on['per_iv'], mio_iv),
    "counters_on": {"vetoed": vetoed, "rescued": rescued, "rewrite_vetoed": rew},
    "cell_S_and_throughs": {
        f"{LEG.get(o, o)}-{m}": {"off": off['cell'].get((o, m), 0),
                                 "on": on['cell'].get((o, m), 0)}
        for (o, m) in keys if (o == 3 or m == "through")
        and (off['cell'].get((o, m), 0) or on['cell'].get((o, m), 0))},
}
Path("runs/origin_veto/fm51_ablation_phase3.json").write_text(json.dumps(out, indent=1))
print("\nwrote runs/origin_veto/fm51_ablation_phase3.json")
