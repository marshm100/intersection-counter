"""Blind-QA flag feeders + rebuild orchestrator (MASTER_PLAN §3-B).

The review queue (review_flags table) is fed by TWO independent sources, because
a confidence queue alone is insufficient — it only catches what the system is
unsure about, never what it MISSED entirely (an undetected vehicle emits no
event, so it can raise no confidence flag; the FM51 −8% would be invisible):

  1. feed_uncertain_events  — event-anchored low-confidence / ambiguous flags.
                              "What the system is unsure about."  (Phase B2)
  2. feed_suspected_gaps    — interval+approach the run looks to UNDER-count,
                              from the blind coverage/conservation diagnostic.
                              "What it missed."  (Phase B3 — the blind-deployment
                              hardening; uses the run's OWN internal consistency,
                              never ground truth.)

Each feeder returns a list of plain dicts whose keys are keyword arguments of
database.insert_flag(...) — minus project_id and intersection_id, which the
orchestrator supplies — so it just does
insert_flag(project_id, intersection_id=..., **f). This contract is frozen in
B1; B2/B3 are pure fill-ins of the two feeder functions below.

Rebuild is idempotent: it clears the intersection's OPEN flags and re-derives,
leaving worked (accepted/dismissed/resolved) flags as history.
"""
from __future__ import annotations

import json
import sqlite3

from backend.database import (
    clear_open_flags, flag_summary, get_connection, insert_flags,
)
from backend.services import coverage_qa
from backend.services.cardinals import bound_approach

# --- Feeder 1 (uncertain events) thresholds --------------------------------
# Global failure-mode floors — NOT per-site knobs — set from the confidence
# histograms of real runs (corridor 97a7849a ≈90k events; rehearsal 0acb12c0).
# Each STANDALONE trigger flags a small, high-value slice:
#   detection_confidence < 0.35   -> ~0.7–3.5% (the marginal / possible-phantom band)
#   posterior margin     < 0.20   -> <1%       (90%+ of posteriors are peaked, margin=1.0)
DET_CONF_FLOOR = 0.35
DEST_MARGIN_FLOOR = 0.20
# CORROBORATING ONLY — never a standalone trigger. trajectory_confidence is
# poorly calibrated (a huge mass sits at 0.10, so a <0.5 floor flags 40–63% of
# events — pure busywork). A low traj-conf merely RAISES the severity of an
# event already flagged by a standalone trigger; it cannot create a flag alone.
TRAJ_CONF_CORROB = 0.5
# NOTE: destination_confidence is always high in practice (median ~0.86, never
# <0.5) so it is no signal — the posterior MARGIN carries destination ambiguity.
# vehicle_class is never 'unknown' and the event row stores no bbox geometry, so
# the medium/articulated class signal needs the FHWA work (MASTER_PLAN §3-D) and
# is intentionally NOT emitted here.


def _posterior_top2(posterior_json: str | None) -> tuple[float, list[tuple[int, float]]]:
    """(margin, [(leg_id, prob), ...] up to 2) from a {str(leg_id): prob} JSON.

    margin = p1 - p2, and is 1.0 for a single-candidate / peaked polyline
    assignment (the common case) — i.e. not ambiguous."""
    if not posterior_json:
        return 1.0, []
    try:
        p = json.loads(posterior_json)
    except (TypeError, ValueError):
        return 1.0, []
    items = sorted(((int(k), float(v)) for k, v in p.items()), key=lambda kv: -kv[1])
    if not items:
        return 1.0, []
    if len(items) == 1:
        return 1.0, items[:1]
    return items[0][1] - items[1][1], items[:2]


def feed_uncertain_events(project_id: str, intersection_id: int) -> list[dict]:
    """Feeder 1 — flag events the system is genuinely UNSURE about, anchored to
    the event so the operator can confirm/fix/reject from one clip.

    Two standalone triggers (low detection confidence = possible phantom;
    small destination posterior margin = movement near-tie). A low trajectory
    confidence corroborates (raises severity) but never fires alone. One flag
    per event (primary subtype = existence-first: low_det_conf > ambiguous_dest);
    all tripped signals go in `evidence`. Worst-first so the queue surfaces the
    most uncertain events earliest (impact is 1 each, so order is by severity).

    Skips events already rejected/edited by the operator, or already worked
    (a terminal-status flag) — keeping rebuild idempotent w.r.t. human effort.
    """
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        cams = [r[0] for r in conn.execute(
            "SELECT camera_id FROM cameras WHERE intersection_id = ?",
            (intersection_id,)).fetchall()]
        if not cams:
            return []
        ph = ",".join("?" * len(cams))
        legs = {r["leg_id"]: ((r["cardinal_direction"] or "").upper(), r["label"])
                for r in conn.execute(
                    f"SELECT leg_id, cardinal_direction, label FROM legs "
                    f"WHERE camera_id IN ({ph})", cams).fetchall()}
        # Only events that could trip a STANDALONE trigger — low detection
        # confidence OR a small destination margin — can produce a flag, so seek
        # just those via idx_events_uncertain instead of materialising every
        # event and parsing its posterior in Python (30k rows -> a few hundred on
        # the OneDrive DB). destination_margin is precomputed at write time from
        # the same JSON _posterior_top2 parses, so the pre-filter is exact; the
        # IS NULL branch is a correctness net for any un-backfilled/legacy row.
        rows = conn.execute(
            f"SELECT event_id, camera_id, origin_leg_id, movement, detection_confidence, "
            f"trajectory_confidence, destination_confidence, destination_posterior_json, "
            f"vehicle_class, timestamp_video FROM vehicle_events "
            f"WHERE camera_id IN ({ph}) AND rejected = 0 AND manually_edited = 0 "
            f"AND (detection_confidence < ? OR destination_margin < ? "
            f"     OR destination_margin IS NULL) "
            f"AND event_id NOT IN (SELECT event_id FROM review_flags "
            f"  WHERE event_id IS NOT NULL AND status IN ('accepted','dismissed','resolved'))",
            (*cams, DET_CONF_FLOOR, DEST_MARGIN_FLOOR)).fetchall()
    finally:
        conn.close()

    candidates: list[tuple[float, dict]] = []
    for r in rows:
        det = r["detection_confidence"]
        traj = r["trajectory_confidence"]
        margin, top2 = _posterior_top2(r["destination_posterior_json"])

        signals: list[str] = []
        severity = 0.0
        if det is not None and det < DET_CONF_FLOOR:
            signals.append("low_det_conf")
            severity += (DET_CONF_FLOOR - det) / DET_CONF_FLOOR
        if margin < DEST_MARGIN_FLOOR:
            signals.append("ambiguous_dest")
            severity += (DEST_MARGIN_FLOOR - margin) / DEST_MARGIN_FLOOR
        if not signals:
            continue  # nothing standalone tripped -> no flag

        traj_low = traj is not None and traj < TRAJ_CONF_CORROB
        if traj_low:
            severity += 0.25  # corroborating bump only

        primary = "low_det_conf" if "low_det_conf" in signals else "ambiguous_dest"
        ocard, _olabel = legs.get(r["origin_leg_id"], ("", ""))
        approach = bound_approach(ocard)
        top2_ev = [{"leg_id": lid, "label": legs.get(lid, ("", ""))[1],
                    "cardinal": legs.get(lid, ("", ""))[0], "p": round(p, 3)}
                   for lid, p in top2]
        evidence = {
            "detection_confidence": det,
            "trajectory_confidence": traj,
            "destination_confidence": r["destination_confidence"],
            "destination_margin": round(margin, 3),
            "top2": top2_ev,
            "vehicle_class": r["vehicle_class"],
            "signals": signals,
            "traj_corroborates": traj_low,
            "severity": round(severity, 3),
        }

        if primary == "low_det_conf":
            reason = (f"detection confidence {det:.2f} < {DET_CONF_FLOOR:.2f} "
                      f"— possible phantom")
            if "ambiguous_dest" in signals:
                reason += "; destination also uncertain"
            batch_key = None
        else:
            if len(top2_ev) == 2:
                reason = (f"destination near-tie ({top2_ev[0]['label']} "
                          f"{top2_ev[0]['p']:.2f} vs {top2_ev[1]['label']} "
                          f"{top2_ev[1]['p']:.2f}) — movement uncertain")
                c1, c2 = sorted([top2_ev[0]["cardinal"], top2_ev[1]["cardinal"]])
                batch_key = f"dest|{approach}|{c1}-{c2}"
            else:
                reason = "destination uncertain"
                batch_key = f"dest|{approach}|?"
        if traj_low:
            reason += f"; weak track (traj {traj:.2f})"

        candidates.append((severity, {
            "kind": "uncertain_event", "subtype": primary,
            "camera_id": r["camera_id"], "event_id": r["event_id"],
            "approach": approach, "movement": r["movement"], "impact": 1.0,
            "reason": reason, "evidence": evidence, "batch_key": batch_key,
        }))

    candidates.sort(key=lambda sc: -sc[0])   # worst-first -> earlier created_at -> sorts first
    return [f for _sev, f in candidates]


def feed_suspected_gaps(project_id: str, intersection_id: int) -> list[dict]:
    """Feeder 2 — the blind coverage diagnostic (MASTER_PLAN §3-B). Flags
    intervals/approaches that look under-counted from the run's OWN internal
    consistency (no ground truth):
      S1 interval_corridor — per-bin corridor mismatch (multi-intersection).
      S2 interval_anomaly  — abrupt asymmetric drop vs a local baseline.
      S4 bank_coverage_hole — operator-drawn movement with no bank path.
    See backend/services/coverage_qa.py for S1/S2 and their documented limit
    (a smooth uniform detection sag is NOT visible here — that is the
    spot-count's job; the two-counter S3 idea is BLOCKED on a second counter
    of comparable accuracy — see docs/flagqueue_retrospective_2026-07-09.md).
    Returns insert_flag(**f) dicts for THIS intersection.
    """
    flags: list[dict] = []
    for f in coverage_qa.interval_corridor_gaps(project_id, target_id=intersection_id):
        if f.pop("_intersection_id", None) == intersection_id:
            flags.append(f)
    for f in coverage_qa.interval_anomalies(project_id, intersection_id):
        f.pop("_intersection_id", None)
        flags.append(f)
    flags += _bank_coverage_holes(project_id, intersection_id)
    return flags


def _bank_coverage_holes(project_id: str, intersection_id: int) -> list[dict]:
    """S4 — an operator-drawn movement with NO applied-bank path
    (docs/plan_flagqueue_B_2026-07-09.md; the cam2 EB-thru case: 31 real
    vehicles, 4 counted, no 28->26 path). A drawn channel is the operator
    declaring "this movement exists here"; when the applied bank has no path
    for that cell, its vehicles can only surface through fallback tiers, so
    the cell is structurally under-countable and a human should look.

    impact = the cell's LIVE event count (fallback-tier events are a lower
    bound of real traffic there). A zero-event hole still flags at impact 1 —
    it sinks to the bottom of the worklist and is one-keystroke dismissable
    (the 2026-07-09 bank audit: tiny holes are real but not worth templates).
    Drawn U-TURN channels are excluded: the calibration UI seeds one per leg,
    so a missing u-turn path is the default state, not a declaration."""
    conn = get_connection(project_id)
    try:
        flags: list[dict] = []
        for (cam,) in conn.execute(
                "SELECT camera_id FROM cameras WHERE intersection_id = ?",
                (intersection_id,)).fetchall():
            card = {lid: cd for lid, cd in conn.execute(
                "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id = ?", (cam,))}
            label = {lid: lb for lid, lb in conn.execute(
                "SELECT leg_id, label FROM legs WHERE camera_id = ?", (cam,))}
            banked = {(o, d) for o, d in conn.execute(
                "SELECT origin_leg_id, destination_leg_id FROM intersection_paths "
                "WHERE camera_id = ?", (cam,))}
            for o, d, mv in conn.execute(
                    "SELECT origin_leg_id, destination_leg_id, movement FROM channels "
                    "WHERE camera_id = ?", (cam,)).fetchall():
                if o == d or (o, d) in banked or o not in card or d not in card:
                    continue
                n_live = conn.execute(
                    "SELECT COUNT(*) FROM vehicle_events WHERE camera_id = ? AND "
                    "rejected = 0 AND origin_leg_id = ? AND destination_leg_id = ?",
                    (cam, o, d)).fetchone()[0]
                ap = bound_approach(card.get(o))
                flags.append({
                    "kind": "suspected_gap", "subtype": "bank_coverage_hole",
                    "camera_id": cam,
                    "approach": ap, "movement": mv,
                    "impact": float(max(1, n_live)),
                    "reason": (f"{ap}B {mv} ({label.get(o, o)} -> {label.get(d, d)}): "
                               f"channel drawn but the applied bank has NO path for this "
                               f"cell — its vehicles only surface via fallback tiers "
                               f"({n_live} events so far). Rebuild/re-apply the bank with "
                               f"drawn channels, or dismiss if the movement is negligible."),
                    "evidence": {"origin_leg_id": o, "destination_leg_id": d,
                                 "live_fallback_events": n_live},
                    "batch_key": None,
                })
        return flags
    finally:
        conn.close()


def rebuild_flags(project_id: str, intersection_id: int) -> dict:
    """Clear the intersection's open flags, run both feeders, insert the
    results, and return {created, ...flag_summary}."""
    clear_open_flags(project_id, intersection_id)
    flags: list[dict] = []
    flags += feed_uncertain_events(project_id, intersection_id)
    flags += feed_suspected_gaps(project_id, intersection_id)
    insert_flags(project_id, intersection_id, flags)   # one transaction, not N commits
    summary = flag_summary(project_id, intersection_id)
    return {"created": len(flags), **summary}
