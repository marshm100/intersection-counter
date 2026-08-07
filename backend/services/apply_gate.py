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
    APPLY_GATE_FLOOD_MAX,
    APPLY_GATE_HEADROOM,
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
    if t <= 0:
        # no drawn gates/paths -> no census -> the gate abstains rather
        # than freezing re-processing; protection there = dispositions
        return "apply", ["not_adjudicable"], metrics

    cells = set(inc) | set(cand) | set(census)
    exc_i = sum(max(0.0, inc.get(c, 0) - census.get(c, 0.0)) for c in cells)
    exc_c = sum(max(0.0, cand.get(c, 0) - census.get(c, 0.0)) for c in cells)
    d_cov = (n_cand - exc_c) - (n_inc - exc_i)
    metrics.update({
        "R_inc": round(n_inc / t - 1, 4), "R_cand": round(n_cand / t - 1, 4),
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


def adjudicate_apply(project_id: str, camera_id: int, variant: str, *,
                     incumbent_db: str | Path, candidate_db: str | Path,
                     t_lo: float, t_hi: float, census: dict,
                     confusion: dict, record: bool = True) -> dict:
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
