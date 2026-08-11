"""Does endpoint extension DESTROY the fragment chains that dedup relies on?

docs/plan_v2_confound_split_2026-08-11.md, Finding B.

track_chains.chain_tracks gates on gate tags — A_OK = (entry_only,
no_crossing), B_OK = (exit_only, no_crossing), "a full journey never
chains". Endpoint extension converts exactly those fragments into FULL
journeys (fulls 3459 -> 4162). So a queued vehicle that fragments into
A + B chains on the BASE dump and CANNOT chain on the extended dump, and
each half is then counted separately.

Track ids are identical between base and extended dumps (extension never
renumbers), so the base-dump chain map applies directly to the extended
run's events. That is what makes this measurable without re-running pass 2.

Reported per arm: counted events that share a BASE-dump chain, and the
EXCESS (sum over chains of n_events - 1) — the number of counted vehicles
that base-dump chaining says are the same vehicle.

NOTE this is a STRUCTURAL probe, not the conservation pass.
conserve_replay_additions only rejects events whose posterior_source is in
_ADDITIVE, so it is a no-op on all-direct arms; this probe counts the
duplicate population regardless of source, which is the quantity that
decides whether a direct-path dedup is worth building.

Usage:
  py -X utf8 scripts/v2_chain_dup_probe.py --camera 1 --variant study_1600
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

from backend.database import get_connection, list_paths_for_camera   # noqa: E402
from backend.services.entry_gates import build_gates                 # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir      # noqa: E402
from backend.services.track_chains import build_chain_map            # noqa: E402
from backend.services.two_pass import (_tracks_from_rows,            # noqa: E402
                                       parquet_path)

SCRATCH = Path("data/projects/97a7849a/_replay_scratch")


def gates_for(project: str, cam: int, tracks: dict):
    conn = get_connection(project)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id = ?", (cam,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
    conn.close()
    return build_gates(mouths, list_paths_for_camera(project, cam), heads)


def counted(db: Path, cam: int) -> list[tuple[int, int, str]]:
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    rows = c.execute(
        "SELECT event_id, vehicle_track_id, COALESCE(posterior_source,'direct'), "
        "origin_leg_id, destination_leg_id FROM vehicle_events "
        "WHERE camera_id=? AND COALESCE(rejected,0)=0 "
        "AND origin_leg_id IS NOT NULL AND destination_leg_id IS NOT NULL",
        (cam,)).fetchall()
    c.close()
    return rows


def dup_stats(evs, chain_map) -> dict:
    groups: dict = {}
    for eid, tid, src, o, d in evs:
        cid = chain_map.get(int(tid))
        if cid is None:
            continue
        groups.setdefault(cid, []).append((eid, src, o, d))
    multi = {k: v for k, v in groups.items() if len(v) > 1}
    excess = sum(len(v) - 1 for v in multi.values())
    same_cell = sum(1 for v in multi.values()
                    if len({(e[2], e[3]) for e in v}) == 1)
    all_direct = sum(1 for v in multi.values()
                     if all(e[1] == "direct" for e in v))
    return {"events": len(evs), "mapped": sum(len(v) for v in groups.values()),
            "chains": len(groups), "multi_chains": len(multi),
            "excess": excess, "same_cell_chains": same_cell,
            "all_direct_chains": all_direct}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    args = ap.parse_args()
    cam, var, proj = args.camera, args.variant, args.project

    # resolve dumps via the same helper run_pass2 uses
    from backend.services.two_pass import _camera_parquet
    base_rows = load_dump(tracks_dir(_camera_parquet(proj, cam, var)))
    ext_rows = load_dump(tracks_dir(_camera_parquet(proj, cam, f"v2c_{var}")))

    conn = get_connection(proj)
    fps = float(conn.execute(
        "SELECT fps FROM videos WHERE camera_id=? LIMIT 1", (cam,)).fetchone()[0])
    conn.close()

    base_tracks = _tracks_from_rows(base_rows)
    ext_tracks = _tracks_from_rows(ext_rows)
    gates = gates_for(proj, cam, base_tracks)
    cm_base = build_chain_map(base_tracks, gates, fps)
    cm_ext = build_chain_map(ext_tracks, gates, fps)

    n_chain_base = len({v for v in cm_base.values()})
    n_chain_ext = len({v for v in cm_ext.values()})
    multi_base = sum(1 for c in _sizes(cm_base) if c > 1)
    multi_ext = sum(1 for c in _sizes(cm_ext) if c > 1)
    print(f"=== cam{cam} {var} (fps {fps:g}) ===")
    print(f"  dump rows      base {len(base_rows):>9,d}   ext {len(ext_rows):>9,d}")
    print(f"  tracks         base {len(base_tracks):>9,d}   ext {len(ext_tracks):>9,d}")
    print(f"  MULTI-TRACK CHAINS  base {multi_base:>5d}   ext {multi_ext:>5d}"
          f"   ({multi_ext - multi_base:+d})")
    print("  ^ chains of >1 fragment. Extension converting fragments to FULL")
    print("    journeys should DESTROY these — that is Finding B.")
    print()

    arms = [("A control", SCRATCH / "v2_week1" / f"ga3ctrl_cam{cam}_{var}.db")]
    for sub in ("armC", "armC2"):
        p = SCRATCH / "v2_confound" / sub / f"armC_cam{cam}_v2c_{var}.db"
        if p.exists():
            arms.append(("C ext,pair off", p))
    pb = SCRATCH / "v2_week1" / f"twopass_cam{cam}_v2c_{var}.db"
    if pb.exists():
        arms.append(("B ext,pair on", pb))

    print(f"  {'arm':>15s} {'counted':>8s} {'chains':>7s} {'multi':>6s} "
          f"{'EXCESS':>7s} {'same-cell':>9s} {'all-direct':>10s}")
    for name, db in arms:
        if not db.exists():
            continue
        s = dup_stats(counted(db, cam), cm_base)
        print(f"  {name:>15s} {s['events']:>8d} {s['chains']:>7d} "
              f"{s['multi_chains']:>6d} {s['excess']:>7d} "
              f"{s['same_cell_chains']:>9d} {s['all_direct_chains']:>10d}")
    print()
    print("  EXCESS = counted events that BASE-dump chaining says are the same")
    print("  vehicle. same-cell = those duplicate chains whose events all land")
    print("  in ONE (origin,dest) cell — i.e. straight cell inflation.")
    return 0


def _sizes(cm: dict):
    n: dict = {}
    for v in cm.values():
        n[v] = n.get(v, 0) + 1
    return n.values()


if __name__ == "__main__":
    raise SystemExit(main())
