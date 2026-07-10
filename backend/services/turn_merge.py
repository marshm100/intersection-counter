"""Production turn-fragment merge + S5 borderline signal (A4a,
docs/plan_A4_stage3_2026-07-10.md).

BoT/ByteTrack fragment one turning vehicle into several same-cell events (the
tracker coasts the sharp curve, the pipeline finalizes the stub, the exit
re-tracks). `merge_turn_fragments` collapses same-(origin,dest,movement)
events that start within merge_px of each other within merge_gap frames —
guarded by the VOLUME GATE: only cells whose raw count clearly exceeds
expectation merge at all, so sparse well-counted cells can't lose distinct
vehicles. Mechanism and constants ported VERBATIM from scripts/hybrid_ocbot.py
(the validated offline recipe; scripts re-import from here).

The expecteds are GT-FREE: the applied bank's supporting_count per (origin,
dest), scaled to the counting window via sample_window_seconds (blind gate,
validated 2026-07-08 — the honest cam1 cost was 10.0% vs 6.7% GT-gated, and
Miovision appears nowhere).

`borderline_merge_cells` is the S5 flag-queue signal: a cell whose raw count
sits within ±band of the gate threshold is one noise-vehicle from the merge
decision flipping (cam1 NB-left blind: 134 raw vs threshold 143 → no merge →
+38 shipped). Only computable HERE, where raw pre-merge counts exist.
"""
from __future__ import annotations

import json
import logging
import math
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

TURNS = ("left", "right", "u_turn")
# Frozen constants (hybrid_ocbot defaults; cam2-validated, blind-swept).
MERGE_PX = 30.0
MERGE_GAP = 40.0
VOL_FACTOR = 1.3
FALLBACK_SAMPLE_SECONDS = 1800.0   # corridor banks were 30-min samples


def merge_turn_fragments(turns, merge_px, merge_gap, expected_by_cell=None,
                         vol_factor=1.3):
    """Ported verbatim from scripts/hybrid_ocbot.py (see its docstring for the
    A2 volume-gate rationale). `turns` = dicts with id/ol/dl/mv/s/e/start.
    Returns the kept event ids."""
    by = defaultdict(list)
    for ev in turns:
        by[(ev["ol"], ev["dl"], ev["mv"])].append(ev)
    keep = []
    for cell, evs in by.items():
        evs.sort(key=lambda e: e["s"])
        if expected_by_cell is not None:
            exp = expected_by_cell.get((cell[0], cell[1]), 0)
            if len(evs) <= vol_factor * max(exp, 1):
                keep.extend(e["id"] for e in evs)
                continue
        used = [False] * len(evs)
        for i, ei in enumerate(evs):
            if used[i]:
                continue
            used[i] = True
            keep.append(ei["id"])
            if ei["start"] is None:
                continue
            for j in range(i + 1, len(evs)):
                ej = evs[j]
                if used[j] or ej["start"] is None:
                    continue
                if (ej["s"] - ei["e"]) <= merge_gap and math.hypot(
                        ei["start"][0] - ej["start"][0],
                        ei["start"][1] - ej["start"][1]) <= merge_px:
                    used[j] = True   # fragment of the same turning vehicle
    return set(keep)


def borderline_merge_cells(turns, expected_by_cell, vol_factor=1.3,
                           band=0.2) -> list[dict]:
    """S5 — cells whose raw fragment count sits within ±band of the volume-gate
    threshold (the noise-sensitive merge decisions). Ported verbatim."""
    raw = Counter((ev["ol"], ev["dl"]) for ev in turns)
    out = []
    for cell, n in raw.items():
        exp = (expected_by_cell or {}).get(cell)
        if not exp:
            continue
        thr = vol_factor * max(exp, 1)
        if thr * (1 - band) <= n <= thr * (1 + band):
            out.append({"cell": cell, "raw": n, "expected": exp,
                        "threshold": round(thr, 1),
                        "merges": n > thr})
    return out


def _load_turns(conn: sqlite3.Connection, camera_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT event_id, movement, origin_leg_id, destination_leg_id, "
        "start_frame, frame_number, trajectory_data FROM vehicle_events "
        "WHERE camera_id = ? AND rejected = 0 AND movement IN (?,?,?)",
        (camera_id, *TURNS)).fetchall()
    out = []
    for eid, mv, ol, dl, sf, ef, tj in rows:
        try:
            traj = json.loads(tj) if tj else []
        except Exception:
            traj = []
        s = sf if sf is not None else ef
        e = ef if ef is not None else sf
        out.append({"id": eid, "mv": mv, "ol": ol, "dl": dl, "s": s, "e": e,
                    "start": traj[0] if traj else None})
    return out


def bank_expecteds(conn: sqlite3.Connection, camera_id: int,
                   window_seconds: float) -> dict[tuple, float]:
    """{(origin,dest): expected count over window_seconds} from the applied
    bank's supporting_count, time-scaled by each path's sample window."""
    out: dict[tuple, float] = {}
    for o, d, sc, sw in conn.execute(
            "SELECT origin_leg_id, destination_leg_id, supporting_count, "
            "sample_window_seconds FROM intersection_paths WHERE camera_id = ?",
            (camera_id,)):
        if sw is None:
            logger.warning(
                "intersection_paths cam%s (%s->%s): sample_window_seconds is "
                "NULL — assuming %ss (legacy 30-min sample bank)",
                camera_id, o, d, FALLBACK_SAMPLE_SECONDS)
            sw = FALLBACK_SAMPLE_SECONDS
        out[(o, d)] = float(sc) * (window_seconds / float(sw))
    return out


def merge_replay_turns(db: str | Path, camera_id: int, *,
                       window_seconds: float,
                       expected_by_cell: dict | None = None) -> dict:
    """A4a post-pass on a pass-2 replay DB: volume-gated same-cell turn-fragment
    merge. Merged-away fragments are marked rejected=1 (non-destructive,
    reviewable in the worklist) — never deleted. THROUGH events are untouched
    by construction (the loader selects turns only).

    expected_by_cell overrides the bank expecteds (tests); default = the
    replay DB's own applied bank, time-scaled. Returns stats incl. the S5
    borderline cells for the caller to emit as review_flags."""
    db = str(db)
    conn = sqlite3.connect(db)
    try:
        turns = _load_turns(conn, camera_id)
        expected = (expected_by_cell if expected_by_cell is not None
                    else bank_expecteds(conn, camera_id, window_seconds))
        keep = merge_turn_fragments(turns, MERGE_PX, MERGE_GAP,
                                    expected_by_cell=expected,
                                    vol_factor=VOL_FACTOR)
        drop = [ev["id"] for ev in turns if ev["id"] not in keep]
        with conn:
            conn.executemany(
                "UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
                [(i,) for i in drop])
        borderline = borderline_merge_cells(turns, expected, VOL_FACTOR)
    finally:
        conn.close()
    return {"camera_id": camera_id, "turns": len(turns), "kept": len(keep),
            "merged_away": len(drop), "borderline": borderline,
            "window_seconds": window_seconds}


def s5_flags(camera_id: int, borderline: list[dict],
             leg_cardinals: dict[int, str], bound_approach) -> list[dict]:
    """Turn `borderline_merge_cells` output into insert_flags(**f) dicts
    (kind suspected_gap, subtype merge_borderline) — the S5 feeder
    (plan_flagqueue_B_2026-07-09). Called inside the rebuild path so the
    flags survive clear_open_flags."""
    flags = []
    for b in borderline:
        o, d = b["cell"]
        ap = bound_approach(leg_cardinals.get(o, ""))
        flags.append({
            "kind": "suspected_gap", "subtype": "merge_borderline",
            "camera_id": camera_id, "approach": ap, "movement": None,
            "impact": float(abs(b["raw"] - b["expected"])),
            "reason": (f"{ap}B turn cell {o}->{d}: {b['raw']} raw fragments vs "
                       f"merge threshold {b['threshold']} (expected "
                       f"{round(b['expected'])}) — the merge decision is one "
                       f"noise-vehicle from flipping; spot-check this cell."),
            "evidence": {"origin_leg_id": o, "destination_leg_id": d,
                         "raw": b["raw"], "expected": round(b["expected"], 1),
                         "threshold": b["threshold"], "merges": b["merges"]},
            "batch_key": None,
        })
    return flags
