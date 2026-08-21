"""Phase-1 APPLY GATE (plan_v2_apply_gate_2026-08-07).

Per-window candidate-vs-incumbent adjudication under the blind guards —
the G-A3 applicability law made mechanical: the V2 bundle (and any future
mechanism) wins where journeys are MISSING from the incumbent and loses
where it MANUFACTURES events beyond the window's own gate evidence, so an
apply may replace the incumbent table only when

  headroom   the incumbent under-claims vs the gate-evidence census,
  envelope   the candidate's per-cell excess mass stays inside it,
  contrast   the confusion channel is not saturated (oblique geometry —
             the census cannot be trusted to adjudicate there), and
  recovery   the candidate adds evidence-COVERED mass, not just excess.

No Miovision anywhere: the census comes from the window's own dump through
the pinned operator gates (census_expecteds / strict_full_census — the
same machinery the demotion selector ships). Ground-truth validation of
this rule: 12/12 on the v2_week1 pairs (the plan doc's evidence table).

Operator dispositions outrank the gate ('hold' blocks, 'force_once'
bypasses once) — the 07-31 blind product test's root cause 1 (uniform
apply overrode curated judgment) closes HERE, in product state.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from backend.config import (
    APPLY_GATE_FAIL_OPEN,
    APPLY_GATE_FLOOD_MAX,
    APPLY_GATE_HEADROOM,
    APPLY_GATE_MAX_OVERCLAIM,
    APPLY_GATE_REATTR_CONC_MASS_MIN,
    APPLY_GATE_REATTR_CONC_MAX,
    APPLY_GATE_REATTR_MOVED_MAX,
    APPLY_GATE_SATURATION,
)
from backend.database import (
    get_disposition,
    record_adjudication,
    set_disposition,
)

logger = logging.getLogger(__name__)


def window_cell_counts(db: str | Path, camera_id: int,
                       t_lo: float, t_hi: float) -> dict[tuple[int, int], int]:
    """Counted events per (origin, destination) cell for one camera window —
    the same scoping _apply_window_events swaps (crossing-timestamp
    convention), counted = rejected=0 with a destination."""
    conn = sqlite3.connect(db)
    try:
        return {(int(o), int(d)): n for o, d, n in conn.execute(
            "SELECT origin_leg_id, destination_leg_id, COUNT(*) "
            "FROM vehicle_events WHERE camera_id = ? "
            "AND COALESCE(rejected, 0) = 0 AND origin_leg_id IS NOT NULL "
            "AND destination_leg_id IS NOT NULL "
            "AND timestamp_video >= ? AND timestamp_video < ? "
            "GROUP BY 1, 2", (camera_id, t_lo, t_hi))}
    finally:
        conn.close()


def saturation_from_confusion(confusion: dict) -> float:
    """Lower-median per-origin confusion — the demotion contrast guard's
    exact computation (cam1 transfer verdict 2026-08-05: the measure's
    ceiling reads 0.73-1.0 on oblique geometry; cam2's true signature is
    one origin 0.98 vs median 0.08). Fewer than two measured origins =
    contrast unmeasurable = 1.0 (fail closed, the shipped convention)."""
    vals = sorted(confusion.values())
    return vals[len(vals) // 2 - 1] if len(vals) >= 2 else 1.0


def adjudicate_counts(inc: dict, cand: dict, census: dict,
                      saturation: float) -> tuple[str, list, dict]:
    """The pure decision rule. Returns (decision, reasons, metrics);
    decision 'apply' | 'stand_down'; reasons carries EVERY failed guard
    (or the single pass/abstain reason) for the audit trail."""
    t = float(sum(census.values()))
    n_inc = sum(inc.values())
    n_cand = sum(cand.values())
    metrics: dict = {"census_total": round(t), "inc_total": n_inc,
                     "cand_total": n_cand, "saturation": round(saturation, 3)}
    if n_inc == 0:
        # nothing to defend: first processing keeps its legacy behavior
        return "apply", ["fresh_window"], metrics
    # CENSUS ADEQUACY precondition (FM51 held-out finding): every guard
    # below reads the census as this window's volume envelope. Absent, or
    # accounting for so little of the counted traffic that it cannot be
    # one, there is nothing to adjudicate against — and "apply anyway"
    # would ship exactly the unverified overwrite the gate exists to stop
    # (FM51's own AM candidate was -18.9 points).
    if t > 0:
        metrics["R_inc"] = round(n_inc / t - 1, 4)
    if t <= 0 or n_inc / t - 1 > APPLY_GATE_MAX_OVERCLAIM:
        if APPLY_GATE_FAIL_OPEN:
            return "apply", ["not_adjudicable"], metrics
        return "stand_down", ["census_degenerate"], metrics

    cells = set(inc) | set(cand) | set(census)
    exc_i = sum(max(0.0, inc.get(c, 0) - census.get(c, 0.0)) for c in cells)
    exc_c = sum(max(0.0, cand.get(c, 0) - census.get(c, 0.0)) for c in cells)
    d_cov = (n_cand - exc_c) - (n_inc - exc_i)
    metrics.update({
        "R_cand": round(n_cand / t - 1, 4),
        "flood_share_inc": round(exc_i / t, 4),
        "flood_share_cand": round(exc_c / t, 4), "d_cov": round(d_cov)})

    reasons = []
    if saturation >= APPLY_GATE_SATURATION:
        reasons.append("saturated_geometry")
    if n_inc / t - 1 > -APPLY_GATE_HEADROOM:
        reasons.append("no_headroom")
    if exc_c / t > APPLY_GATE_FLOOD_MAX:
        reasons.append("event_flood")
    if d_cov <= 0:
        reasons.append("no_recovery")
    if reasons:
        return "stand_down", reasons, metrics
    return "apply", ["gate_pass"], metrics


def _event_cells(db: str | Path, camera_id: int,
                 t_lo: float, t_hi: float) -> dict[int, tuple]:
    """{event_id: (origin, dest, vehicle_track_id)} for kept events in the
    window — the reattribution mode's per-event join basis."""
    conn = sqlite3.connect(db)
    try:
        return {int(e): (o, d, int(t)) for e, o, d, t in conn.execute(
            "SELECT event_id, origin_leg_id, destination_leg_id, "
            "vehicle_track_id FROM vehicle_events WHERE camera_id = ? "
            "AND COALESCE(rejected, 0) = 0 AND origin_leg_id IS NOT NULL "
            "AND destination_leg_id IS NOT NULL "
            "AND timestamp_video >= ? AND timestamp_video < ?",
            (camera_id, t_lo, t_hi))}
    finally:
        conn.close()


def reattribution_integrity(project_id: str, camera_id: int, variant: str,
                            incumbent_db: str | Path,
                            candidate_db: str | Path,
                            t_lo: float, t_hi: float, fps: float) -> dict:
    """GATE-SIDE recomputation (plan_gate_ag2_2026-08-13): join both tables
    by event_id, classify every MOVED event's track from the window's own
    dump through the pinned gates, and verify the candidate never touched
    a proven endpoint (entry_only origin / exit_only destination) and
    never moved a gate-verified full. Blind, mechanism-independent."""
    import json as _json

    from backend.database import get_connection, list_paths_for_camera
    from backend.services.entry_gates import build_gates, classify
    from backend.services.pass2_replay import load_dump, tracks_dir
    from backend.services.two_pass import (_camera_parquet,
                                           _tracks_from_rows, gate_axes_for)

    inc = _event_cells(incumbent_db, camera_id, t_lo, t_hi)
    cand = _event_cells(candidate_db, camera_id, t_lo, t_hi)
    out = {"ids_mismatch": set(inc) != set(cand),
           "n_events": len(inc), "moved": 0, "violations": 0,
           "fulls_moved": 0, "unclassifiable_moved": 0}
    if out["ids_mismatch"]:
        return out
    moved = [(e, inc[e], cand[e]) for e in inc
             if (inc[e][0], inc[e][1]) != (cand[e][0], cand[e][1])]
    out["moved"] = len(moved)
    if not moved:
        return out

    from backend.database import leg_geometry_for_camera
    geom = leg_geometry_for_camera(project_id, camera_id)
    mouths = {lid: g["mouth"] for lid, g in geom.items()}
    heads = {lid: g["heading"] for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}
    rows = load_dump(tracks_dir(_camera_parquet(project_id, camera_id,
                                                variant)))
    tracks = {tid: sorted(p) for tid, p in _tracks_from_rows(rows).items()}
    gates = build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                        heads, leg_axes=gate_axes_for(mouths,
                                                      tracks.values()),
                        leg_gates=drawn or None)
    cache: dict = {}
    for _e, (io, idd, tid), (co, cd, _t2) in moved:
        if tid not in cache:
            pts = tracks.get(tid)
            cache[tid] = (classify(pts, gates, fps)
                          if pts and len(pts) >= 5 else None)
        c = cache[tid]
        if c is None:
            out["unclassifiable_moved"] += 1
            out["violations"] += 1
            continue
        o, d, _of, _df, _op, _dp, tag = c
        if tag == "full":
            out["fulls_moved"] += 1
            out["violations"] += 1
        elif tag == "entry_only":
            if o is None or int(o) != co:
                out["violations"] += 1
        elif tag == "exit_only":
            if d is None or int(d) != cd:
                out["violations"] += 1
        # no_crossing: nothing proven, any re-decision permitted
    return out


def adjudicate_reattribution_counts(inc: dict, cand: dict, census: dict,
                                    saturation: float,
                                    integ: dict) -> tuple[str, list, dict]:
    """The pure reattribution decision rule (GATE-AG2). Zero-mass
    candidates only; quality of the re-decided UNPROVEN endpoint is the
    mechanism's instrument-gate burden, recorded, not verified here."""
    n_inc = sum(inc.values())
    n_cand = sum(cand.values())
    cells = set(inc) | set(cand)
    moved_mass = sum(abs(cand.get(c, 0) - inc.get(c, 0)) for c in cells) / 2.0
    max_gain = max((cand.get(c, 0) - inc.get(c, 0) for c in cells),
                   default=0)
    t = float(sum(census.values()))
    metrics = {"inc_total": n_inc, "cand_total": n_cand,
               "moved_events": integ.get("moved", 0),
               "moved_cell_mass": round(moved_mass),
               "moved_share": round(moved_mass / n_inc, 4) if n_inc else 0.0,
               "max_cell_gain": int(max_gain),
               "concentration": round(max_gain / moved_mass, 4)
               if moved_mass else 0.0,
               "integrity_violations": integ.get("violations", 0),
               "fulls_moved": integ.get("fulls_moved", 0),
               "saturation": round(saturation, 3),
               "census_total": round(t)}
    reasons = []
    if integ.get("ids_mismatch") or n_inc != n_cand:
        reasons.append("mass_change")
    if integ.get("violations", 0) > 0:
        reasons.append("endpoint_integrity")
    if n_inc and moved_mass / n_inc > APPLY_GATE_REATTR_MOVED_MAX:
        reasons.append("excessive_movement")
    if moved_mass > APPLY_GATE_REATTR_CONC_MASS_MIN \
            and max_gain / moved_mass > APPLY_GATE_REATTR_CONC_MAX:
        reasons.append("concentrated_movement")
    if saturation >= APPLY_GATE_SATURATION:
        reasons.append("saturated_geometry")
    if reasons:
        return "stand_down", reasons, metrics
    return "apply", ["gate_pass_reattr"], metrics


def adjudicate_apply(project_id: str, camera_id: int, variant: str, *,
                     incumbent_db: str | Path, candidate_db: str | Path,
                     t_lo: float, t_hi: float, census: dict,
                     confusion: dict, record: bool = True,
                     mode: str = "recall",
                     fps: float | None = None) -> dict:
    """Full adjudication for one window: operator disposition ladder first,
    then the blind rule over the two tables. Records to the audit trail
    (and consumes 'force_once') unless record=False (offline validation)."""
    disposition = get_disposition(project_id, camera_id, variant)
    if disposition == "hold":
        decision, reasons, metrics = "stand_down", ["operator_hold"], {}
    elif disposition == "force_once":
        decision, reasons, metrics = "apply", ["operator_force"], {}
        if record:
            set_disposition(project_id, camera_id, variant, "auto")
    elif mode == "reattribution":
        # GATE-AG2 (plan_gate_ag2_2026-08-13): zero-mass candidates only.
        if fps is None:
            raise ValueError("reattribution mode requires fps")
        integ = reattribution_integrity(
            project_id, camera_id, variant, incumbent_db, candidate_db,
            t_lo, t_hi, fps)
        inc = window_cell_counts(incumbent_db, camera_id, t_lo, t_hi)
        cand = window_cell_counts(candidate_db, camera_id, t_lo, t_hi)
        decision, reasons, metrics = adjudicate_reattribution_counts(
            inc, cand, census, saturation_from_confusion(confusion), integ)
    else:
        inc = window_cell_counts(incumbent_db, camera_id, t_lo, t_hi)
        cand = window_cell_counts(candidate_db, camera_id, t_lo, t_hi)
        decision, reasons, metrics = adjudicate_counts(
            inc, cand, census, saturation_from_confusion(confusion))
    verdict = {"decision": decision, "reasons": reasons, "metrics": metrics,
               "disposition": disposition}
    if record:
        record_adjudication(project_id, camera_id, variant, decision,
                            reasons, metrics)
    logger.info("apply gate cam%s %s: %s (%s)", camera_id, variant,
                decision, ",".join(reasons))
    return verdict
