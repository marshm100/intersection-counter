"""LANE+ECHO phase 0 — the blind chain census (plan_cam5_lane_echo_2026-07-27).

Per window: pinned gates + fragment-chain map over the FULL dump
(track_chains.build_chain_map — STITCH_* frozen, zero new constants),
joined against the window's BASE replay events. Censuses:

  - chain multiplicity (tracks/chain) and tag mix (full / entry_only /
    exit_only / no_crossing);
  - the E prize: chains carrying >=2 counted events (excess events =
    what one-event-per-chain would remove), per co-occurring cell pair;
  - the NB-left split: multi-event-chain events (E-recoverable) vs
    singleton-chain orphans by tag (C's population);
  - the SB compose at vehicle level: real-geometry 37>39 tracks with no
    event of their own — how many sit in a chain that DID count (echo
    covered) vs truly uncounted.

GT-free by construction (events + geometry only — Mio appears nowhere).
Usage: py scripts/lane_echo_phase0.py [--windows study_0700,study_1100,study_1600]
Evidence -> runs/cam5_wall/chain_census.json. Basis: replayed-minutes
BASE replays (the OFF-parity DBs).
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np

from backend.database import get_connection, list_paths_for_camera
from backend.services.detection_cache import (
    compute_video_content_hash, parquet_path)
from backend.services.entry_gates import build_gates, classify
from backend.services.pass2_replay import load_dump, tracks_dir
from backend.services.track_chains import build_chain_map

PROJECT = "97a7849a"
CAM = 5
SCRATCH = Path("data/projects/97a7849a/_replay_scratch")  # see cam5_wall_phase0
OUT = Path("runs/cam5_wall/chain_census.json")


def load_rows(cam, variant):
    conn = sqlite3.connect(f"data/projects/{PROJECT}/project.db")
    conn.row_factory = sqlite3.Row
    v = dict(conn.execute(
        "SELECT * FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (cam,)).fetchone())
    conn.close()
    chash, _ = compute_video_content_hash(
        v["path"], file_size_bytes=v["file_size_bytes"],
        total_frames=v["total_frames"])
    rows = load_dump(tracks_dir(Path(parquet_path(PROJECT, cam, chash, variant))))
    return rows, float(v["fps"])


def pinned_gates(cam):
    conn = get_connection(PROJECT)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id=?", (cam,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = z
            heads[lid] = rh
    anchors = {lid: (z[0][0], z[0][1]) if isinstance(z[0], (list, tuple))
               else (z[0], z[1]) for lid, z in mouths.items()}
    conn.close()
    return build_gates(anchors, list_paths_for_camera(PROJECT, cam), heads), anchors


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows",
                    default="study_0700,study_1100,study_1600")
    args = ap.parse_args()
    windows = args.windows.split(",")

    gates, anchors = pinned_gates(CAM)
    result = {}
    for w in windows:
        rows, fps = load_rows(CAM, w)
        tracks: dict[int, list] = {}
        for r in rows:
            tracks.setdefault(int(r[0]), []).append(
                (float(r[1]), float(r[2]), float(r[3])))
        chain_map = build_chain_map(tracks, gates, fps)

        tags = {}
        for tid, pts in tracks.items():
            if len(pts) < 5:
                continue
            pts_s = sorted(pts)
            _o, _d, *_rest, tag = classify(pts_s, gates, fps)
            tags[tid] = tag

        chains: dict[int, list[int]] = defaultdict(list)
        for tid, ci in chain_map.items():
            chains[ci].append(tid)
        mult = Counter(len(v) for v in chains.values())

        db = SCRATCH / f"cam5wall_stock_{w}.db"
        ev_by_tid: dict[int, list] = defaultdict(list)
        c = sqlite3.connect(str(db))
        for tid, o, d in c.execute(
                "SELECT vehicle_track_id, origin_leg_id, destination_leg_id "
                "FROM vehicle_events WHERE camera_id=? AND "
                "COALESCE(rejected,0)=0", (CAM,)):
            ev_by_tid[tid].append((o, d))
        c.close()

        ev_chain: dict[int, list] = defaultdict(list)   # chain -> [(o,d)]
        unmapped_ev = 0
        for tid, evs in ev_by_tid.items():
            ci = chain_map.get(tid)
            if ci is None:
                unmapped_ev += len(evs)
                continue
            ev_chain[ci].extend(evs)
        n_events = sum(len(v) for v in ev_by_tid.values())
        multi_ev = {ci: evs for ci, evs in ev_chain.items() if len(evs) >= 2}
        excess = sum(len(evs) - 1 for evs in multi_ev.values())
        pair_cells = Counter()
        for evs in multi_ev.values():
            cells = sorted({f"{o}>{d}" for (o, d) in evs})
            pair_cells["+".join(cells)] += len(evs) - 1

        # NB-left split
        nbl_tids = [tid for tid, evs in ev_by_tid.items()
                    if any((o, d) == (39, 38) for (o, d) in evs)]
        nbl = {"n_events": sum(1 for tid in nbl_tids
                               for e in ev_by_tid[tid] if e == (39, 38)),
               "in_multi_event_chain": 0, "singleton_by_tag": Counter()}
        for tid in nbl_tids:
            ci = chain_map.get(tid)
            if ci is not None and len(ev_chain.get(ci, [])) >= 2:
                nbl["in_multi_event_chain"] += 1
            else:
                nbl["singleton_by_tag"][tags.get(tid, "unmapped")] += 1
        nbl["singleton_by_tag"] = dict(nbl["singleton_by_tag"])

        # SB compose at vehicle level: real-geometry 37>39 tracks w/o events
        def nearest(pt):
            return min(anchors, key=lambda l: math.hypot(
                pt[0] - anchors[l][0], pt[1] - anchors[l][1]))
        sb_noev = echo_covered = 0
        for tid, pts in tracks.items():
            if len(pts) < 4 or tid in ev_by_tid:
                continue
            pts_s = sorted(pts)
            if (nearest((pts_s[0][1], pts_s[0][2])) == 37
                    and nearest((pts_s[-1][1], pts_s[-1][2])) == 39):
                sb_noev += 1
                ci = chain_map.get(tid)
                if ci is not None and ev_chain.get(ci):
                    echo_covered += 1

        res_w = {
            "n_tracks_mapped": len(chain_map),
            "n_chains": len(chains),
            "multiplicity": {str(k): v for k, v in sorted(mult.items())},
            "tags": dict(Counter(tags.values())),
            "n_events": n_events,
            "events_unmapped_track": unmapped_ev,
            "chains_with_2plus_events": len(multi_ev),
            "excess_events": excess,
            "excess_by_cellpair_top": dict(pair_cells.most_common(8)),
            "nb_left": nbl,
            "sb_geo_no_event": sb_noev,
            "sb_geo_no_event_echo_covered": echo_covered,
        }
        result[w] = res_w
        print(f"[0] {w}: chains={len(chains)} mult={res_w['multiplicity']} "
              f"tags={res_w['tags']}", flush=True)
        print(f"[0] {w}: events={n_events} excess_in_chains={excess} "
              f"(chains2+={len(multi_ev)}) top_pairs="
              f"{json.dumps(res_w['excess_by_cellpair_top'])}", flush=True)
        print(f"[0] {w}: NB-left {json.dumps(nbl)}", flush=True)
        print(f"[0] {w}: SB geo-no-event={sb_noev} echo_covered={echo_covered}",
              flush=True)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=1))
    print(f"wrote {OUT}", flush=True)
    print("CENSUS DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
