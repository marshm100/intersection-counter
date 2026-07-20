"""PHASE 3 corridor blind sweep — resumable, interleaved (OFF+ON per camera).

Order [1,2,5,4,3]: cam1 quick-validate, cam2/cam5 the decisive recovery
targets (phase-1 -467 / -416), cam4 wash, the 24h cam3 wash LAST. Existing
OFF DBs are reused (byte-identical when off); ON DBs always fresh. Writes
runs/origin_veto/corridor_sweep_phase3.json incrementally after each camera
and prints a '### CAM n COMPLETE' marker for the monitor.

ACCEPTANCE: cam2/cam5 total_on recover toward total_off; cam1/3/4 flat.
"""
from __future__ import annotations
import sys, json, sqlite3, time
from pathlib import Path
from collections import defaultdict

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")
from backend.services.pass2_replay import replay_camera
import backend.services.pipeline as PL

PROJECT = "97a7849a"
SCRATCH = Path(r"C:\Users\onkar\AppData\Local\Temp\ic_scratch_97a7849a")
CAMS = {
    1: ["study_0700"],
    2: ["study_0700", "study_1100", "study_1600"],
    3: ["study_0000"],
    4: ["study_0700", "study_1100", "study_1600"],
    5: ["study_0700", "study_1100", "study_1600"],
}
ORDER = [1, 2, 5, 4, 3]
OUT = Path("runs/origin_veto/corridor_sweep_phase3.json")
committed = json.loads(Path("runs/origin_veto/corridor_sweep.json").read_text())


def cells_of(db, cam):
    c = sqlite3.connect(str(db))
    cell = defaultdict(int)
    for o, d in c.execute(
            "SELECT origin_leg_id, destination_leg_id FROM vehicle_events "
            "WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)):
        cell[(o, d)] += 1
    c.close()
    return cell


result = {}
if OUT.exists():
    try:
        result = json.loads(OUT.read_text())
    except Exception:
        result = {}
t_all = time.time()

for cam in ORDER:
    windows = CAMS[cam]
    r = {}
    for tag, flag in (("off", False), ("on", True)):
        PL.ORIGIN_CLAIM_VETO_ENABLED = flag
        agg = defaultdict(int); rescued = rew = vetoed = 0
        for w in windows:
            out = SCRATCH / f"sweep_p3_{tag}_{cam}_{w}.db"
            if tag == "off" and out.exists():
                print(f"[{tag}] cam{cam} {w}: reuse existing DB", flush=True)
            else:
                t0 = time.time()
                st = replay_camera(PROJECT, cam, variant=w, out_db=out)
                rescued += st.get("origin_rescued", 0)
                rew += st.get("origin_rewrite_vetoed", 0)
                vetoed += st.get("origin_vetoed", 0)
                print(f"[{tag}] cam{cam} {w}: events={st['events']} "
                      f"vetoed={st.get('origin_vetoed')} rescued={st.get('origin_rescued')} "
                      f"rew={st.get('origin_rewrite_vetoed')} ({time.time()-t0:.0f}s)",
                      flush=True)
            for k, v in cells_of(out, cam).items():
                agg[k] += v
        r[f"total_{tag}"] = sum(agg.values())
        r[f"cells_{tag}"] = {f"{o}>{d}": v for (o, d), v in agg.items()}
        if flag:
            r["counters_on"] = {"vetoed": vetoed, "rescued": rescued,
                                "rewrite_vetoed": rew}
    changed = {}
    for k in set(r["cells_off"]) | set(r["cells_on"]):
        a, b = r["cells_off"].get(k, 0), r["cells_on"].get(k, 0)
        if a != b:
            changed[k] = [a, b]
    r["changed"] = changed
    result[str(cam)] = r
    OUT.write_text(json.dumps(result, indent=1))

    o, n = r["total_off"], r["total_on"]
    c1 = committed.get(str(cam), {})
    p1 = c1.get("total_on", 0) - c1.get("total_off", 0)
    print(f"### CAM {cam} COMPLETE off={o} on={n} delta={n-o:+d} "
          f"(phase1 delta={p1:+d}) rescued={r['counters_on']['rescued']} "
          f"changed_cells={len(changed)} ###", flush=True)

print(f"\nwrote {OUT}  ({time.time()-t_all:.0f}s total)", flush=True)
print("DONE", flush=True)
