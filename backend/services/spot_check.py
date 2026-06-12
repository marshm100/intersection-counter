"""Spot-count validation + acceptance gate (Phase 4 —
docs/implementation_plan_architecture_2026-06-11.md).

THE new-site accuracy story: with zero ground truth, an engineer hand-counts a
short randomly-chosen window from the raw video (count-only — much faster than
per-event review), and the system compares its own counts for the same window,
with honest confidence intervals.

Statistics: per cell, manual count M and system count S over the same window
are treated as Poisson. The relative error (S-M)/M gets a 95% CI from the Katz
log-ratio interval: log(S/M) +/- z*sqrt(1/S + 1/M). Small cells produce wide
CIs — that is the truth of a short window, and it is why the gate's binding
test is the TOTAL (tightest CI), with per-cell rows as review pointers.
A +0.5 continuity correction handles zero counts.

Acceptance gate (4.2) combines, per intersection:
  - corridor-consistency verdicts on links touching this intersection (Phase 3)
  - spot-count total error vs the +/-5% target
  - reverse-balance fails (long windows only; Phase 3)
Verdict: "ship" (all green), "review" (warns / CI too wide / no spot count
yet), "fail" (a hard red anywhere). The gate never auto-ships — it tells the
engineer what stands between this intersection-day and the Excel export.
"""
from __future__ import annotations

import json
import math
import random
from collections import defaultdict
from datetime import datetime, timezone

from backend.database import get_connection
from backend.services.conservation_qa import (
    _cardinal_volumes, _movement, corridor_consistency, reverse_balance,
)

Z95 = 1.959964

# Gate thresholds (4.2). Point error on the spot-window TOTAL must be within
# TARGET, and the CI must exclude errors beyond CI_LIMIT — a wide CI (tiny
# sample) keeps the verdict at "review", it can never pass by vagueness.
TARGET_REL_ERR = 0.05
CI_LIMIT_REL_ERR = 0.10

# Sample-size fact (the question the architecture research left open): under
# the conservative independent-Poisson model, certifying the CI within
# +/-CI_LIMIT needs n >= 2 * (z / ln(1 + CI_LIMIT))^2 total vehicles —
# ~850 for +/-10% at 95%. At this corridor's ~1300 veh / 30 min that is a
# 20-40 minute spot count; 10 minutes is structurally too short to certify.
NEEDED_TOTAL_FOR_CI = math.ceil(2 * (Z95 / math.log1p(CI_LIMIT_REL_ERR)) ** 2)


def katz_ci(system: int, manual: int, z: float = Z95) -> tuple[float, float, float]:
    """(point, lo, hi) for the relative error (S-M)/M with a Katz log-ratio CI.
    Continuity-corrected so zero counts stay finite."""
    s = system + 0.5
    m = manual + 0.5
    point = (system - manual) / manual if manual > 0 else float("inf")
    se = math.sqrt(1.0 / s + 1.0 / m)
    lo = math.exp(math.log(s / m) - z * se) - 1.0
    hi = math.exp(math.log(s / m) + z * se) - 1.0
    return point, lo, hi


def propose_window(project_id: str, camera_id: int, minutes: float = 10.0,
                   seed: int | None = None) -> dict:
    """Pick a random spot-count window inside the camera's PROCESSED range
    (where events exist), so manual and system are counting the same footage."""
    conn = get_connection(project_id)
    try:
        row = conn.execute(
            "SELECT MIN(timestamp_video), MAX(timestamp_video) FROM vehicle_events "
            "WHERE camera_id = ? AND rejected = 0", (camera_id,)).fetchone()
    finally:
        conn.close()
    if row is None or row[0] is None:
        return {"error": "no processed events for this camera yet"}
    t0, t1 = float(row[0]), float(row[1])
    dur = minutes * 60.0
    if t1 - t0 <= dur:
        start = t0
        dur = max(60.0, t1 - t0)
    else:
        rng = random.Random(seed)
        start = t0 + rng.uniform(0.0, (t1 - t0) - dur)
    return {"camera_id": camera_id, "start_seconds": round(start, 1),
            "duration_seconds": round(dur, 1),
            "processed_range": [round(t0, 1), round(t1, 1)]}


def _system_counts(project_id: str, camera_id: int,
                   start: float, duration: float) -> dict[str, int]:
    """System counts in the window, keyed 'ORIGIN_CARDINAL movement'
    (e.g. 'N through' = the NB through)."""
    conn = get_connection(project_id)
    try:
        card = {lid: (cd or "").upper() for lid, cd in conn.execute(
            "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id = ?",
            (camera_id,)).fetchall()}
        rows = conn.execute(
            "SELECT origin_leg_id, destination_leg_id FROM vehicle_events "
            "WHERE camera_id = ? AND rejected = 0 AND destination_leg_id IS NOT NULL "
            "AND timestamp_video >= ? AND timestamp_video < ?",
            (camera_id, start, start + duration)).fetchall()
    finally:
        conn.close()
    out: dict[str, int] = defaultdict(int)
    for ol, dl in rows:
        a, b = card.get(ol), card.get(dl)
        if a and b:
            out[f"{a} {_movement(a, b)}"] += 1
    return dict(out)


def save_spot_count(project_id: str, camera_id: int, start: float,
                    duration: float, manual_counts: dict[str, int],
                    notes: str = "") -> dict:
    """Persist a manual spot count and return the comparison report."""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection(project_id)
    try:
        with conn:
            conn.execute(
                "INSERT INTO spot_counts (camera_id, start_seconds, duration_seconds, "
                "manual_counts, notes, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (camera_id, start, duration, json.dumps(manual_counts), notes, now))
    finally:
        conn.close()
    return compare_spot_count(project_id, camera_id, start, duration, manual_counts)


def list_spot_counts(project_id: str, camera_id: int) -> list[dict]:
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT spot_id, start_seconds, duration_seconds, manual_counts, notes, "
            "created_at FROM spot_counts WHERE camera_id = ? ORDER BY created_at DESC",
            (camera_id,)).fetchall()
    finally:
        conn.close()
    return [{"spot_id": r[0], "start_seconds": r[1], "duration_seconds": r[2],
             "manual_counts": json.loads(r[3]), "notes": r[4], "created_at": r[5]}
            for r in rows]


def compare_spot_count(project_id: str, camera_id: int, start: float,
                       duration: float, manual_counts: dict[str, int]) -> dict:
    """Manual vs system over the window, per cell + total, with 95% CIs."""
    sys_counts = _system_counts(project_id, camera_id, start, duration)
    cells = []
    for key in sorted(set(manual_counts) | set(sys_counts)):
        m = int(manual_counts.get(key, 0))
        s = int(sys_counts.get(key, 0))
        point, lo, hi = katz_ci(s, m)
        cells.append({"cell": key, "manual": m, "system": s,
                      "rel_err": (round(point, 3) if math.isfinite(point) else None),
                      "ci95": [round(lo, 3), round(hi, 3)]})
    m_tot = sum(int(v) for v in manual_counts.values())
    s_tot = sum(sys_counts.values())
    point, lo, hi = katz_ci(s_tot, m_tot)
    if m_tot == 0:
        verdict = "review"
    elif abs(point) <= TARGET_REL_ERR and -CI_LIMIT_REL_ERR <= lo and hi <= CI_LIMIT_REL_ERR:
        verdict = "pass"
    elif abs(point) > 2 * TARGET_REL_ERR and (lo > TARGET_REL_ERR or hi < -TARGET_REL_ERR):
        verdict = "fail"
    else:
        verdict = "review"   # within reach but CI too wide, or marginal point error
    note = ("no manual counts entered" if not m_tot else
            f"total error {point*100:+.1f}% (95% CI {lo*100:+.1f}%..{hi*100:+.1f}%) "
            f"vs target +/-{TARGET_REL_ERR*100:.0f}%")
    if verdict == "review" and m_tot and abs(point) <= TARGET_REL_ERR:
        # How many total vehicles would certify, GIVEN the observed point
        # error: the CI half-width budget shrinks by |log-ratio| already spent.
        budget = math.log1p(CI_LIMIT_REL_ERR) - abs(math.log((s_tot + 0.5) / (m_tot + 0.5)))
        if budget > 0:
            needed = math.ceil(2 * (Z95 / budget) ** 2)
            if needed > m_tot:
                note += (f"; counts agree but the CI is too wide to certify — "
                         f"extend the count to ~{needed} total vehicles "
                         f"({m_tot} so far)")
    return {
        "camera_id": camera_id, "start_seconds": start, "duration_seconds": duration,
        "cells": cells,
        "total": {"manual": m_tot, "system": s_tot,
                  "rel_err": (round(point, 3) if math.isfinite(point) else None),
                  "ci95": [round(lo, 3), round(hi, 3)]},
        "verdict": verdict,
        "needed_total_for_ci": NEEDED_TOTAL_FOR_CI,
        "note": note,
    }


def acceptance(project_id: str, intersection_id: int) -> dict:
    """4.2 — the gate: what stands between this intersection-day and export."""
    conn = get_connection(project_id)
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT intersection_id FROM intersections "
            "ORDER BY sort_order, intersection_id").fetchall()]
        cams = [r[0] for r in conn.execute(
            "SELECT camera_id FROM cameras WHERE intersection_id = ?",
            (intersection_id,)).fetchall()]
    finally:
        conn.close()

    items = []

    # corridor links touching this intersection (only when a corridor exists)
    if len(ids) >= 2:
        cc = corridor_consistency(project_id, ids)
        mine = [l for l in cc["links"]
                if l["link"].startswith(f"{intersection_id}->")
                or f"->{intersection_id} " in l["link"]]
        worst = ("fail" if any(l["verdict"] == "fail" for l in mine)
                 else "warn" if any(l["verdict"] == "warn" for l in mine)
                 else "ok" if mine else "info")
        items.append({"item": "corridor_consistency", "verdict": worst,
                      "detail": mine})

    rb = reverse_balance(project_id, intersection_id)
    rb_verdict = ("info" if not rb["applicable"]
                  else "fail" if any(p["verdict"] == "fail" for p in rb["pairs"])
                  else "warn" if any(p["verdict"] == "warn" for p in rb["pairs"])
                  else "ok")
    items.append({"item": "reverse_balance", "verdict": rb_verdict,
                  "detail": {"applicable": rb["applicable"], "note": rb["note"]}})

    # most recent spot count per camera
    spot_verdict = "review"
    spot_detail = []
    any_spot = False
    for cid in cams:
        spots = list_spot_counts(project_id, cid)
        if not spots:
            spot_detail.append({"camera_id": cid, "verdict": "review",
                                "note": "no spot count recorded"})
            continue
        any_spot = True
        s = spots[0]
        rep = compare_spot_count(project_id, cid, s["start_seconds"],
                                 s["duration_seconds"], s["manual_counts"])
        spot_detail.append({"camera_id": cid, "verdict": rep["verdict"],
                            "note": rep["note"]})
    if any_spot:
        vs = [d["verdict"] for d in spot_detail]
        spot_verdict = ("fail" if "fail" in vs
                        else "review" if "review" in vs else "pass")
    items.append({"item": "spot_count", "verdict": spot_verdict,
                  "detail": spot_detail})

    verdicts = [i["verdict"] for i in items]
    overall = ("fail" if "fail" in verdicts
               else "review" if ("warn" in verdicts or "review" in verdicts)
               else "ship")
    return {"intersection_id": intersection_id, "overall": overall, "items": items}
