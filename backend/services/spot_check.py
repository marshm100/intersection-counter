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

from backend.database import flag_summary, get_connection, list_paths_for_camera
from backend.services.cardinals import bound_approach
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

# Spot-window STRATIFICATION (MASTER_PLAN §5 — "a single AM spot window passed
# while the PM was bad"). A uniform-random window can miss the run's hardest
# conditions entirely (the FM51 low-sun PM sag is a real, unfixable detection
# loss that ONLY a spot count of that window catches — coverage_qa is blind to a
# gradual sag). So the sample must COVER the run's range of conditions: we split
# the processed footage into segments and require a spot count in each. Blind —
# uses only the run's own coverage/time structure, never ground truth.
SEG_GAP_SECONDS = 20 * 60       # a >20-min hole splits blocks (e.g. AM vs PM trims)
SEG_TARGET_SECONDS = 3 * 3600   # subdivide a long continuous block into ~3h parts
SEG_MAX_PER_BLOCK = 4           # ...capped, so a 24h run needs 4 spot checks, not 8


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


def _trim_windows_video(project_id: str, camera_id: int) -> list[tuple[float, float]]:
    """The camera's DECLARED reporting windows (its intersection's trims) in
    video-seconds — the deliverable's claim scope (§3-B validation 2026-07-28,
    phase-0 finding 2: certification must cover what the deliverable claims,
    not all processed footage). Empty when no trims are declared — the claim
    is then the full footage and stratification stays footage-wide."""
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT t.start_wallclock, t.end_wallclock FROM trims t "
            "JOIN cameras c ON c.intersection_id = t.intersection_id "
            "WHERE c.camera_id = ? ORDER BY t.sort_order", (camera_id,)).fetchall()
    finally:
        conn.close()
    if not rows:
        return []
    offset = _rec_offset_seconds(project_id, camera_id)
    if offset is None:
        return []

    def _secs(hms: str) -> float:
        h, m, s = (list(map(int, hms.split(":"))) + [0, 0])[:3]
        return h * 3600 + m * 60 + s

    out = []
    for sw, ew in rows:
        try:
            vs, ve = _secs(sw) - offset, _secs(ew) - offset
        except (ValueError, AttributeError):
            continue
        if ve > 0:
            out.append((max(0.0, vs), ve))
    return out


def _processed_segments(project_id: str, camera_id: int,
                        bin_seconds: int = 300) -> list[tuple[float, float]]:
    """Partition the camera's processed footage into coverage SEGMENTS for spot
    stratification: contiguous event blocks (a >SEG_GAP_SECONDS hole splits them —
    e.g. an AM trim vs a PM trim), each long block subdivided into <=
    SEG_MAX_PER_BLOCK parts of ~SEG_TARGET_SECONDS. Returns [(start, end), ...] in
    video-seconds. Aggregated in SQL (active 5-min bins, <=288 rows) so it stays
    index-only on the OneDrive DB. Blind: uses only the run's own coverage —
    CLIPPED to the declared reporting windows (trims) when any exist, so the
    gate certifies the deliverable's claim scope and nothing else."""
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT DISTINCT CAST(timestamp_video / ? AS INTEGER) * ? AS b "
            "FROM vehicle_events WHERE camera_id = ? AND rejected = 0 "
            "AND timestamp_video IS NOT NULL ORDER BY b",
            (bin_seconds, bin_seconds, camera_id)).fetchall()
    finally:
        conn.close()
    bins = [int(r[0]) for r in rows]
    trims = _trim_windows_video(project_id, camera_id)
    if trims:
        bins = [b for b in bins
                if any(ts <= b < te for ts, te in trims)]
    if not bins:
        return []
    blocks: list[tuple[int, int]] = []
    start = prev = bins[0]
    for b in bins[1:]:
        if b - prev > SEG_GAP_SECONDS:
            blocks.append((start, prev + bin_seconds))
            start = b
        prev = b
    blocks.append((start, prev + bin_seconds))

    segs: list[tuple[float, float]] = []
    for s, e in blocks:
        dur = e - s
        n = min(SEG_MAX_PER_BLOCK, max(1, round(dur / SEG_TARGET_SECONDS)))
        if n <= 1:
            segs.append((float(s), float(e)))
        else:
            step = dur / n
            for k in range(n):
                segs.append((float(s + k * step),
                             float(e if k == n - 1 else s + (k + 1) * step)))
    return segs


def propose_windows(project_id: str, camera_id: int, minutes: float = 10.0,
                    seed: int | None = None) -> dict:
    """Stratified spot-count windows — ONE per processed segment (trim / time-of-
    day block) — so the sample covers the run's range of conditions, the hardest
    (low-sun) windows included, instead of a single uniform-random window that can
    miss them (MASTER_PLAN §5). A single short run yields one window (== the old
    behaviour)."""
    segs = _processed_segments(project_id, camera_id)
    if not segs:
        return {"camera_id": camera_id, "error": "no processed events for this camera yet",
                "windows": []}
    dur = minutes * 60.0
    rng = random.Random(seed)
    windows = []
    for i, (s, e) in enumerate(segs):
        seg_dur = e - s
        if seg_dur <= dur:
            w_start, w_dur = s, max(60.0, seg_dur)
        else:
            w_start, w_dur = s + rng.uniform(0.0, seg_dur - dur), dur
        windows.append({
            "segment_index": i, "segment": [round(s, 1), round(e, 1)],
            "start_seconds": round(w_start, 1), "duration_seconds": round(w_dur, 1),
        })
    return {"camera_id": camera_id, "n_segments": len(segs), "windows": windows,
            "processed_segments": [[round(s, 1), round(e, 1)] for s, e in segs]}


def _rec_offset_seconds(project_id: str, camera_id: int) -> int | None:
    """Time-of-day (seconds since midnight) of the camera's recording start, so
    spot segments can be labelled in wall-clock. None when unknown."""
    conn = get_connection(project_id)
    try:
        row = conn.execute(
            "SELECT MIN(recording_start_datetime) FROM videos WHERE camera_id = ?",
            (camera_id,)).fetchone()
    finally:
        conn.close()
    if not row or not row[0]:
        return None
    try:
        dt = datetime.fromisoformat(row[0])
    except ValueError:
        return None
    return dt.hour * 3600 + dt.minute * 60 + dt.second


def _clock_label(offset: int | None, secs: float) -> str:
    """HH:MM wall-clock for a video-second position (or '..into the run' when the
    recording start time is unknown)."""
    if offset is None:
        s = int(secs)
        return f"{s // 3600:02d}:{(s // 60) % 60:02d} into the run"
    t = int(offset + secs)
    return f"{(t // 3600) % 24:02d}:{(t // 60) % 60:02d}"


def _system_counts(project_id: str, camera_id: int,
                   start: float, duration: float) -> dict[str, int]:
    """System counts in the window, keyed 'APPROACH movement' where APPROACH is
    the bound direction (opposite of the origin leg's cardinal POSITION) — e.g.
    a south-arm leg (cardinal 'S') counts as 'N through' (the NB through). The
    operator's spot-count grid is labeled the same way (setup.js)."""
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
            out[f"{bound_approach(a)} {_movement(a, b)}"] += 1
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


APPROACH_MIN_MANUAL = 30   # per-approach binding needs at least this many
                           # manually counted vehicles (below it the CI always
                           # straddles the target band — self-limiting anyway)


def compare_spot_count(project_id: str, camera_id: int, start: float,
                       duration: float, manual_counts: dict[str, int]) -> dict:
    """Manual vs system over the window, per cell + total, with 95% CIs.

    PER-APPROACH BINDING (§3-B validation 2026-07-28, phase-0 finding 1):
    the TOTAL can pass while one approach is badly off — cancellation is
    exactly how cam5 false-passed (a −18.5% EB approach inside a passing
    total). So each approach (bound direction) gets its own Katz CI, and
    an approach whose CI lies WHOLLY outside ±TARGET (with ≥
    APPROACH_MIN_MANUAL manual vehicles) demotes a would-be pass to
    "review" — review-not-fail semantics: a small window cannot condemn a
    camera, but it can and must withhold certification."""
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

    approaches = []
    app_binding = []
    agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for c in cells:
        d = c["cell"].split()[0]
        agg[d][0] += c["manual"]
        agg[d][1] += c["system"]
    for d in sorted(agg):
        am, asys = agg[d]
        ap, alo, ahi = katz_ci(asys, am)
        outside = am >= APPROACH_MIN_MANUAL and (alo > TARGET_REL_ERR
                                                 or ahi < -TARGET_REL_ERR)
        approaches.append({"approach": d, "manual": am, "system": asys,
                           "rel_err": (round(ap, 3) if math.isfinite(ap) else None),
                           "ci95": [round(alo, 3), round(ahi, 3)],
                           "outside_target": outside})
        if outside:
            app_binding.append(f"{d} {ap*100:+.0f}%")

    point, lo, hi = katz_ci(s_tot, m_tot)
    if m_tot == 0:
        verdict = "review"
    elif abs(point) <= TARGET_REL_ERR and -CI_LIMIT_REL_ERR <= lo and hi <= CI_LIMIT_REL_ERR:
        verdict = "pass"
    elif abs(point) > 2 * TARGET_REL_ERR and (lo > TARGET_REL_ERR or hi < -TARGET_REL_ERR):
        verdict = "fail"
    else:
        verdict = "review"   # within reach but CI too wide, or marginal point error
    if verdict == "pass" and app_binding:
        verdict = "review"   # an approach's CI wholly outside ±target
    note = ("no manual counts entered" if not m_tot else
            f"total error {point*100:+.1f}% (95% CI {lo*100:+.1f}%..{hi*100:+.1f}%) "
            f"vs target +/-{TARGET_REL_ERR*100:.0f}%")
    if app_binding:
        note += ("; approach(es) outside the target band despite the total: "
                 + ", ".join(app_binding) + " — review those movements")
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
        "approaches": approaches,
        "total": {"manual": m_tot, "system": s_tot,
                  "rel_err": (round(point, 3) if math.isfinite(point) else None),
                  "ci95": [round(lo, 3), round(hi, 3)]},
        "verdict": verdict,
        "needed_total_for_ci": NEEDED_TOTAL_FOR_CI,
        "note": note,
    }


def acceptance(project_id: str, intersection_id: int,
               _cache: dict | None = None) -> dict:
    """4.2 — the gate: what stands between this intersection-day and export.

    `_cache`: optional per-call _cardinal_volumes memo (see conservation_qa).
    export_gate passes a shared cache so the corridor + reverse-balance volumes
    are computed once across all intersections instead of ~30 DB scans."""
    conn = get_connection(project_id)
    try:
        ids = [r[0] for r in conn.execute(
            "SELECT intersection_id FROM intersections "
            "ORDER BY sort_order, intersection_id").fetchall()]
        cams = [r[0] for r in conn.execute(
            "SELECT camera_id FROM cameras WHERE intersection_id = ?",
            (intersection_id,)).fetchall()]
        total_events = 0
        if cams:
            ph = ",".join("?" * len(cams))
            total_events = conn.execute(
                f"SELECT COUNT(*) FROM vehicle_events "
                f"WHERE rejected = 0 AND camera_id IN ({ph})", cams).fetchone()[0]
    finally:
        conn.close()

    items = []

    # corridor links touching this intersection (only when a corridor exists)
    if len(ids) >= 2:
        cc = corridor_consistency(project_id, ids, _cache=_cache)
        mine = [l for l in cc["links"]
                if l["link"].startswith(f"{intersection_id}->")
                or f"->{intersection_id} " in l["link"]]
        worst = ("fail" if any(l["verdict"] == "fail" for l in mine)
                 else "warn" if any(l["verdict"] == "warn" for l in mine)
                 else "ok" if mine else "info")
        items.append({"item": "corridor_consistency", "verdict": worst,
                      "detail": mine})

    rb = reverse_balance(project_id, intersection_id, _cache=_cache)
    rb_verdict = ("info" if not rb["applicable"]
                  else "fail" if any(p["verdict"] == "fail" for p in rb["pairs"])
                  else "warn" if any(p["verdict"] == "warn" for p in rb["pairs"])
                  else "ok")
    items.append({"item": "reverse_balance", "verdict": rb_verdict,
                  "detail": {"applicable": rb["applicable"], "note": rb["note"]}})

    # Spot-count coverage per camera. STRATIFIED (MASTER_PLAN §5): a camera only
    # reaches "pass" when a spot count lands in EVERY processed segment — so an
    # all-AM sample can no longer certify a run whose PM was bad. Uncovered
    # segments keep it at "review" and NAME the window to sample next.
    spot_verdict = "review"
    spot_detail = []
    any_spot = False
    for cid in cams:
        spots = list_spot_counts(project_id, cid)
        segs = _processed_segments(project_id, cid)
        if not spots:
            note = "no spot count recorded"
            if len(segs) > 1:
                note += f" — {len(segs)} coverage segments to sample (incl. the hardest)"
            spot_detail.append({"camera_id": cid, "verdict": "review", "note": note,
                                "segments": len(segs), "covered": 0})
            continue
        any_spot = True
        off = _rec_offset_seconds(project_id, cid)
        covered: set[int] = set()
        reps = []
        for s in spots:
            rep = compare_spot_count(project_id, cid, s["start_seconds"],
                                     s["duration_seconds"], s["manual_counts"])
            reps.append(rep)
            mid = s["start_seconds"] + s["duration_seconds"] / 2.0
            for i, (a, b) in enumerate(segs):
                if a <= mid < b:
                    covered.add(i)
        vs = [r["verdict"] for r in reps]
        uncovered = [segs[i] for i in range(len(segs)) if i not in covered]
        if "fail" in vs:
            cam_v = "fail"
            note = next(r["note"] for r in reps if r["verdict"] == "fail")
        elif uncovered:
            wins = ", ".join(f"{_clock_label(off, a)}-{_clock_label(off, b)}"
                             for a, b in uncovered)
            cam_v = "review"
            note = (f"{len(covered)}/{len(segs)} coverage segments spot-checked — also "
                    f"sample {wins} so the run's hardest conditions (e.g. low-sun) are "
                    f"validated, not just the easy windows")
        elif "review" in vs:
            cam_v = "review"
            note = next(r["note"] for r in reps if r["verdict"] == "review")
        else:
            cam_v = "pass"
            note = f"spot counts cover all {len(segs)} segment(s) and certify within target"
        spot_detail.append({"camera_id": cid, "verdict": cam_v, "note": note,
                            "segments": len(segs), "covered": len(covered)})
    if any_spot:
        vs = [d["verdict"] for d in spot_detail]
        spot_verdict = ("fail" if "fail" in vs
                        else "review" if "review" in vs else "pass")
    items.append({"item": "spot_count", "verdict": spot_verdict,
                  "detail": spot_detail})

    # Review-flag queue (Phase B). The two feeders measure different things, so
    # the gate does NOT sum their impacts: suspected_gap impact is an ESTIMATE of
    # missed vehicles (a real count error) and drives the verdict against the
    # +/-5% bar; uncertain_event flags are a per-vehicle REVIEW BACKLOG (phantoms
    # are already measured by the spot count; movement ambiguity is approach-
    # neutral) and are surfaced, never summed in. Flags are work-to-do, so this
    # item is only info/ok/review — never a hard fail.
    fs = flag_summary(project_id, intersection_id)
    total_flags = fs["open"] + fs["accepted"] + fs["dismissed"] + fs["resolved"]
    gap_impact = fs["open_impact_by_kind"].get("suspected_gap", 0.0)
    uncertain_open = fs["by_kind"].get("uncertain_event", 0)
    gap_frac = (gap_impact / total_events) if total_events else 0.0
    if total_events == 0 or total_flags == 0:
        flags_verdict = "info"
        flags_note = ("no events processed" if total_events == 0
                      else "flags not built yet — run a rebuild to populate the queue")
    elif gap_frac >= TARGET_REL_ERR:
        flags_verdict = "review"
        flags_note = (f"est. {round(gap_impact)} missed ({gap_frac*100:.1f}% of "
                      f"{total_events}) across flagged intervals — review/add-missed; "
                      f"{uncertain_open} uncertain events to confirm (optional polish)")
    else:
        flags_verdict = "ok"
        flags_note = (f"est. missed {gap_frac*100:.1f}% of {total_events} (within "
                      f"+/-{TARGET_REL_ERR*100:.0f}%); {uncertain_open} uncertain events "
                      f"to confirm (optional polish)")
    items.append({"item": "review_flags", "verdict": flags_verdict, "detail": {
        "open": fs["open"],
        "estimated_missed": round(gap_impact, 1),
        "estimated_missed_pct": round(gap_frac * 100, 1),
        "uncertain_to_confirm": uncertain_open,
        "note": flags_note,
    }})

    verdicts = [i["verdict"] for i in items]
    overall = ("fail" if "fail" in verdicts
               else "review" if ("warn" in verdicts or "review" in verdicts)
               else "ship")
    return {"intersection_id": intersection_id, "overall": overall, "items": items}


# Worst-wins ordering for rolling per-intersection verdicts up to the project.
_GATE_RANK = {"ship": 0, "review": 1, "fail": 2}


def export_gate(project_id: str) -> dict:
    """Project-level export readiness — the precondition for the whole-project TMC
    export (MASTER_PLAN §3-A).

    Aggregates the per-intersection `acceptance()` gate plus two HARD preconditions
    a deliverable cannot skip — a path bank must exist (else counts are
    unattributed) and classification must be populated (the L/M/A output) — into a
    single ship/review/fail verdict, worst-wins across intersections.

    `blocking` is True when export should be WITHHELD absent an explicit operator
    override: a hard QA `fail`, a missing bank, or empty classification. A `review`
    verdict is NOT blocking — it permits a DRAFT export (e.g. spot count still
    pending) per the §3-B draft-then-finalize model. Intersections with no cameras
    are listed but excluded from the verdict (nothing to export there yet).
    """
    conn = get_connection(project_id)
    try:
        rows = conn.execute(
            "SELECT intersection_id, name FROM intersections "
            "ORDER BY sort_order, intersection_id").fetchall()
        cams_by_int, classified = {}, {}
        for iid, _name in rows:
            cams = [r[0] for r in conn.execute(
                "SELECT camera_id FROM cameras WHERE intersection_id = ?",
                (iid,)).fetchall()]
            cams_by_int[iid] = cams
            if cams:
                ph = ",".join("?" * len(cams))
                classified[iid] = conn.execute(
                    f"SELECT COUNT(*) FROM vehicle_events WHERE fhwa_class IS NOT NULL "
                    f"AND rejected = 0 AND camera_id IN ({ph})", cams).fetchone()[0] > 0
            else:
                classified[iid] = False
    finally:
        conn.close()

    intersections, blocking_reasons, warnings = [], [], []
    worst = "ship"
    vol_cache: dict = {}   # shared _cardinal_volumes memo across all intersections
    for iid, name in rows:
        cams = cams_by_int[iid]
        acc = acceptance(project_id, iid, _cache=vol_cache)
        local = acc["overall"]
        bank = any(list_paths_for_camera(project_id, c) for c in cams)
        cls = classified[iid]
        notes, blocked = [], False
        if not cams:
            notes.append("no cameras — nothing to export yet")
        else:
            if not bank:
                blocked = True
                notes.append("no path bank — build/apply a bank first")
                blocking_reasons.append(f"{name}: no path bank")
            if not cls:
                blocked = True
                notes.append("classification not populated")
                blocking_reasons.append(f"{name}: classification not populated")
            if local == "fail":
                blocked = True
                blocking_reasons.append(f"{name}: QA gate FAIL")
            elif local == "review":
                warnings.append(f"{name}: QA review — draft only")
            eff = "fail" if blocked else local
            if _GATE_RANK[eff] > _GATE_RANK[worst]:
                worst = eff
        intersections.append({
            "intersection_id": iid, "name": name, "overall": local,
            "bank_exists": bank, "classified": cls, "blocked": blocked,
            "notes": notes, "items": acc["items"],
        })

    return {"project_id": project_id, "overall": worst,
            "blocking": worst == "fail",
            "blocking_reasons": blocking_reasons, "warnings": warnings,
            "intersections": intersections}
