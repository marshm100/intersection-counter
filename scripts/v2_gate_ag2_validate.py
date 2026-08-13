"""GATE-AG2 validation (docs/plan_gate_ag2_2026-08-13.md, G-AG2-v).

Six pre-declared verdicts through the reattribution mode (record=False;
NO Miovision reaches the gate — expectations were fixed in the plan doc
and yardstick checks happen afterward, the AG1 pattern):

  P1  ppt2_cam2_study_1600 vs live         -> APPLY
  N1  ppt2_cam2_study_0700 vs live         -> STAND_DOWN (mass_change)
  N2  ppt2_cam2_study_1100 vs live         -> STAND_DOWN (mass_change)
  N3  random re-attribution (seeded) of P1's moved events
                                           -> STAND_DOWN (endpoint_integrity)
  N4  same-proven-endpoint concentration into one cell
                                           -> STAND_DOWN (concentrated_movement)
  N5  P1 minus one event                   -> STAND_DOWN (mass_change)

Usage: py -X utf8 scripts/v2_gate_ag2_validate.py
Writes runs/v2_week1/gate_ag2_validation.json; exits 1 on any miss.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, ".")
sys.path.insert(0, "scripts")

import numpy as np                                              # noqa: E402

from backend.database import get_connection, get_db_path        # noqa: E402
from backend.services.apply_gate import adjudicate_apply        # noqa: E402
from backend.services.entry_gates import build_gates, classify  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.two_pass import (                         # noqa: E402
    _camera_parquet, _tracks_from_rows, gate_axes_for,
    gate_census_inputs)

PROJECT = "97a7849a"
CAM = 2
FPS = 25.0
S = Path("data/projects/97a7849a/_replay_scratch/ppt")
FR = {"study_0700": (629950, 809950), "study_1100": (989950, 1169950),
      "study_1600": (1439950, 1619950)}
SEED = 42


def wal_copy(src: Path, dst: Path):
    if dst.exists():
        dst.unlink()
    a = sqlite3.connect(src)
    b = sqlite3.connect(dst)
    a.backup(b)
    b.close()
    a.close()


def moved_events(inc_db, cand_db, t_lo, t_hi):
    def cells(db):
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        r = {int(e): (o, d) for e, o, d in conn.execute(
            "SELECT event_id, origin_leg_id, destination_leg_id "
            "FROM vehicle_events WHERE camera_id=? "
            "AND COALESCE(rejected,0)=0 AND origin_leg_id IS NOT NULL "
            "AND destination_leg_id IS NOT NULL "
            "AND timestamp_video >= ? AND timestamp_video < ?",
            (CAM, t_lo, t_hi))}
        conn.close()
        return r
    a, b = cells(inc_db), cells(cand_db)
    return [e for e in a if e in b and a[e] != b[e]]


def main() -> int:
    live = get_db_path(PROJECT)
    conn = get_connection(PROJECT)
    chash = conn.execute(
        "SELECT content_hash FROM videos WHERE camera_id=? "
        "ORDER BY sort_order LIMIT 1", (CAM,)).fetchone()[0]
    legs = [r[0] for r in conn.execute(
        "SELECT leg_id FROM legs WHERE camera_id=?", (CAM,))]
    conn.close()
    rng = np.random.default_rng(SEED)
    scratch = S / "ag2"
    scratch.mkdir(parents=True, exist_ok=True)
    f_lo, f_hi = FR["study_1600"]
    t_lo, t_hi = f_lo / FPS, f_hi / FPS

    # ---- N3: random re-attribution of P1's moved events --------------------
    p1 = S / "ag2" / "p1_live_cam2_study_1600.db"   # composed ON the live table (id-aligned)
    n3 = scratch / "n3_random.db"
    wal_copy(p1, n3)
    mv = moved_events(live, p1, t_lo, t_hi)
    conn = sqlite3.connect(n3)
    with conn:
        for e in mv:
            o, d = rng.choice(legs), rng.choice(legs)
            while d == o:
                d = rng.choice(legs)
            conn.execute("UPDATE vehicle_events SET origin_leg_id=?, "
                         "destination_leg_id=? WHERE event_id=?",
                         (int(o), int(d), int(e)))
    conn.close()

    # ---- N4: same-proven-endpoint concentration ----------------------------
    # move (27,29) events whose tracks are entry_only o=27 into (27,28):
    # proven origins preserved -> integrity passes; concentration must fire.
    n4 = scratch / "n4_concentrated.db"
    wal_copy(live, n4)
    conn = get_connection(PROJECT)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id=?", (CAM,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
    conn.close()
    from backend.database import list_paths_for_camera
    rows = load_dump(tracks_dir(_camera_parquet(PROJECT, CAM, "study_1600")))
    tracks = {tid: sorted(p) for tid, p in _tracks_from_rows(rows).items()}
    gates = build_gates(mouths, list_paths_for_camera(PROJECT, CAM), heads,
                        leg_axes=gate_axes_for(mouths, tracks.values()))
    conn = sqlite3.connect(n4)
    cur = conn.execute(
        "SELECT event_id, vehicle_track_id FROM vehicle_events "
        "WHERE camera_id=? AND COALESCE(rejected,0)=0 "
        "AND origin_leg_id=27 AND destination_leg_id=29 "
        "AND timestamp_video >= ? AND timestamp_video < ?",
        (CAM, t_lo, t_hi)).fetchall()
    hijack = []
    for e, tid in cur:
        pts = tracks.get(int(tid))
        if not pts or len(pts) < 5:
            continue
        o, _d, *_r, tag = classify(pts, gates, FPS)
        if tag == "entry_only" and o is not None and int(o) == 27:
            hijack.append(int(e))
        if len(hijack) >= 100:
            break
    with conn:
        for e in hijack:
            conn.execute("UPDATE vehicle_events SET destination_leg_id=28, "
                         "movement='right' WHERE event_id=?", (e,))
    conn.close()
    print(f"[ag2] N4 built: {len(hijack)} entry_27 events concentrated "
          f"into (27,28)")

    # ---- N5: mass impostor --------------------------------------------------
    n5 = scratch / "n5_massdrop.db"
    wal_copy(p1, n5)
    conn = sqlite3.connect(n5)
    with conn:
        eid = conn.execute(
            "SELECT event_id FROM vehicle_events WHERE camera_id=? "
            "AND COALESCE(rejected,0)=0 AND timestamp_video >= ? "
            "AND timestamp_video < ? LIMIT 1", (CAM, t_lo, t_hi)).fetchone()[0]
        conn.execute("DELETE FROM vehicle_events WHERE event_id=?", (eid,))
    conn.close()

    # ---- adjudicate all six -------------------------------------------------
    CASES = [
        ("P1 ppt2-on-live 1600", "study_1600", p1, "apply"),
        ("N1 ppt2_0700-on-base", "study_0700", S / "ppt2_cam2_study_0700.db",
         "stand_down"),
        ("N2 ppt2_1100-on-base", "study_1100", S / "ppt2_cam2_study_1100.db",
         "stand_down"),
        ("N3 random", "study_1600", n3, "stand_down"),
        ("N4 concentrated", "study_1600", n4, "stand_down"),
        ("N5 massdrop", "study_1600", n5, "stand_down"),
    ]
    out, ok_all = [], True
    for label, w, db, expected in CASES:
        wf_lo, wf_hi = FR[w]
        census, confusion = gate_census_inputs(PROJECT, CAM, chash, w, FPS)
        v = adjudicate_apply(PROJECT, CAM, w, incumbent_db=live,
                             candidate_db=db, t_lo=wf_lo / FPS,
                             t_hi=wf_hi / FPS, census=census,
                             confusion=confusion, record=False,
                             mode="reattribution", fps=FPS)
        correct = v["decision"] == expected
        ok_all &= correct
        out.append({"case": label, "window": w, "expected": expected,
                    **v, "correct": correct})
        print(f"{label:22s} {v['decision']:10s} expected={expected:10s} "
              f"{'OK' if correct else 'MISS'}  [{','.join(v['reasons'])}]")
    dst = Path("runs/v2_week1/gate_ag2_validation.json")
    dst.write_text(json.dumps(out, indent=1))
    print(f"\nG-AG2-v: {sum(1 for o in out if o['correct'])}/6"
          f"  -> {dst}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
