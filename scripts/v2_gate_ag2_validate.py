"""GATE-AG2 validation (docs/plan_gate_ag2_2026-08-13.md, G-AG2-v).

Nine pre-declared verdicts through the reattribution mode (record=False;
NO Miovision reaches the gate — expectations were fixed in the plan docs
and yardstick checks happen afterward, the AG1 pattern). P3 added
2026-08-17 with the concentration mass qualifier (plan_ppt3):

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
# Per-camera frame windows for non-cam2 cases (same wall-clock seconds;
# cam4 runs at 10 fps).
FR_BY_CAM = {(4, "study_1100"): (395980, 467980, 10.0)}
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

    # ---- case-input guard (2026-08-17: sqlite3.connect on a missing path
    # CREATES a 0-byte ghost, and a prior cleanup + this behavior produced
    # a confusing "no such table" crash mid-run — fail loud up front) -----
    p1 = S / "ag2" / "p1_live_cam2_study_1600.db"   # composed ON the live table (id-aligned)
    required = [p1, S / "ag2" / "p2_live_cam2_study_1100.db",
                S / "ppt2_cam2_study_0700.db",
                S / "ppt2_cam2_study_1100.db",
                S / "ag2" / "n6_unfloored_1100.db",
                S / "corridor" / "p3c_cam4_study_1100.db"]
    missing = [str(p) for p in required
               if not p.exists() or p.stat().st_size == 0]
    if missing:
        raise SystemExit(
            "[ag2] case-input DBs missing/empty — rebuild before running "
            "(recipes: plan_gate_ag2 + plan_ppt3 verdicts; p1/p2 = legacy "
            "composes on the retained pre-apply backups; N1/N2 = legacy "
            "composes on re-derived v2c replay controls via v2_run_pass2 "
            "(~8.5 min each); n6 = legacy UNFROZEN --unfloored compose on "
            "live; p3c = capped compose on live):\n  " + "\n  ".join(missing))

    # ---- N3: random re-attribution of P1's moved events --------------------
    n3 = scratch / "n3_random.db"
    wal_copy(p1, n3)
    preapply_early = Path("data/projects/97a7849a/backups/"
                          "20260813_151203_pre_twopass_cam2.db")
    mv = moved_events(preapply_early, p1, t_lo, t_hi)
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

    # ---- adjudicate all nine ------------------------------------------------
    p2 = S / "ag2" / "p2_live_cam2_study_1100.db"
    n6 = S / "ag2" / "n6_unfloored_1100.db"
    p3c = S / "corridor" / "p3c_cam4_study_1100.db"
    # Cases carry (cam, window, VARIANT for the integrity dump, incumbent):
    # P1/N3/N5 were composed on the PRE-APPLY live table — their incumbent
    # is the retained pre-apply backup (the 2026-08-13 study_1600 apply
    # changed the live table's event_ids; pinning the incumbent keeps the
    # validation reproducible forever). P2 is pinned the same way to the
    # 2026-08-14 pre-1100-apply backup (that apply shipped P2's content —
    # vs today's live it would degenerate to a no-movement pass). N1/N2
    # ride the re-derived v2c replay controls (id-misaligned with live by
    # construction). P3 (2026-08-17): the cam4-1100 capped candidate
    # through the concentration mass qualifier — one-cell mass 28 <= 40
    # at a 3-cell T-junction must PASS; N4 (mass ~100) must still fail.
    preapply = Path("data/projects/97a7849a/backups/"
                    "20260813_151203_pre_twopass_cam2.db")
    preapply_1100 = Path("data/projects/97a7849a/backups/"
                         "20260814_085707_pre_twopass_cam2.db")
    CASES = [
        ("P1 ppt2 1600", 2, "study_1600", "study_1600", p1, preapply,
         "apply"),
        ("P2 ppt2 1100", 2, "study_1100", "v2c_study_1100", p2,
         preapply_1100, "apply"),
        ("N1 0700-on-base", 2, "study_0700", "v2c_study_0700",
         S / "ppt2_cam2_study_0700.db", live, "stand_down"),
        ("N2 1100-on-base", 2, "study_1100", "v2c_study_1100",
         S / "ppt2_cam2_study_1100.db", live, "stand_down"),
        ("N3 random", 2, "study_1600", "study_1600", n3, preapply,
         "stand_down"),
        ("N4 concentrated", 2, "study_1600", "study_1600", n4, live,
         "stand_down"),
        ("N5 massdrop", 2, "study_1600", "study_1600", n5, preapply,
         "stand_down"),
        ("N6 unfloored runaway", 2, "study_1100", "v2c_study_1100", n6,
         live, "stand_down"),
        ("P3 cam4-1100 conc-amend", 4, "study_1100", "study_1100", p3c,
         live, "apply"),
    ]
    chash_by_cam = {2: chash}
    out, ok_all = [], True
    for label, ccam, w, variant, db, inc_db, expected in CASES:
        if (ccam, w) in FR_BY_CAM:
            wf_lo, wf_hi, cfps = FR_BY_CAM[(ccam, w)]
        else:
            (wf_lo, wf_hi), cfps = FR[w], FPS
        if ccam not in chash_by_cam:
            cc = get_connection(PROJECT)
            chash_by_cam[ccam] = cc.execute(
                "SELECT content_hash FROM videos WHERE camera_id=? "
                "ORDER BY sort_order LIMIT 1", (ccam,)).fetchone()[0]
            cc.close()
        census, confusion = gate_census_inputs(PROJECT, ccam,
                                               chash_by_cam[ccam], variant,
                                               cfps)
        v = adjudicate_apply(PROJECT, ccam, variant, incumbent_db=inc_db,
                             candidate_db=db, t_lo=wf_lo / cfps,
                             t_hi=wf_hi / cfps, census=census,
                             confusion=confusion, record=False,
                             mode="reattribution", fps=cfps)
        correct = v["decision"] == expected
        ok_all &= correct
        out.append({"case": label, "window": w, "expected": expected,
                    **v, "correct": correct})
        print(f"{label:22s} {v['decision']:10s} expected={expected:10s} "
              f"{'OK' if correct else 'MISS'}  [{','.join(v['reasons'])}]")
    dst = Path("runs/v2_week1/gate_ag2_validation.json")
    dst.write_text(json.dumps(out, indent=1))
    print(f"\nG-AG2-v: {sum(1 for o in out if o['correct'])}/{len(CASES)}"
          f"  -> {dst}")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
