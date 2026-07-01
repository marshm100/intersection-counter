"""Interval coverage QA — the blind "suspected gap" signals (MASTER_PLAN §3-B,
Feeder 2). Bins a run into wall-clock intervals and flags time-localized
under-counts the run reveals about ITSELF — no ground truth:

  S1 interval_corridor — per-bin corridor consistency. When two adjacent
     intersections disagree on the same vehicle stream within a 15-min bin, the
     smaller end is the suspected under-counter. The STRONG signal, for
     multi-intersection studies. (Whole-window form validated in Phase 3.)
  S2 interval_anomaly  — per-approach ABRUPT asymmetric drop vs a LOCAL rolling
     baseline, when the reverse partner held. Catches dropouts / tracking
     collapses; the local baseline keeps it quiet on smooth diurnal traffic.
     The single-intersection safety net.

DELIBERATE LIMIT — validated on FM51 (project 0acb12c0): a SMOOTH UNIFORM
detection sag (low-sun PM) is NOT visible here. Volume stays plausible (the sag
looks like ordinary traffic), event detection-confidence stays flat (missed
vehicles produced no box, not low-confidence ones), and the reverse imbalance
stays sub-threshold. That case is covered by spot-count coverage of the hardest
conditions (the gate / spot-window layer), never by this module. We do not
fabricate a catch we cannot make.
"""
from __future__ import annotations

import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime

from backend.database import get_connection
from backend.services.cardinals import OPPOSITE, bound_approach
from backend.services.conservation_qa import CORRIDOR_WARN, MIN_LINK_VOLUME

BIN_SECONDS = 900   # 15 min — the TMC/Miovision reporting interval

# S2 (abrupt-anomaly) thresholds — global failure-mode floors, NOT per-site knobs.
# A LOCAL rolling baseline (median of neighbouring bins) is what separates a
# glitch (sharp local dip) from ordinary slow variation, so these can stay tight.
ANOM_DROP_FRAC = 0.60        # bin must fall >=60% below its local baseline
ANOM_MIN_DEFICIT = 15        # ...and the absolute deficit must exceed this
ANOM_PARTNER_HELD = 0.70     # reverse partner stayed >=70% of ITS local baseline
ANOM_APPROACH_MIN = 60       # only check approaches with this many vehicles total
ANOM_ROLL_HALF = 2           # local baseline = median of +/- this many neighbour bins

# Fixed naive reference for wall-clock alignment across cameras (both parsed the
# same way, so the offset cancels — only relative alignment matters).
_REF = datetime(2000, 1, 1)


def _wall(rec_iso: str, tsv: float) -> float | None:
    """Absolute wall-clock seconds for an event: recording_start + video time."""
    try:
        return (datetime.fromisoformat(rec_iso) - _REF).total_seconds() + float(tsv)
    except (TypeError, ValueError):
        return None


def _binned_io(conn: sqlite3.Connection, intersection_id: int,
               bin_seconds: int) -> dict | None:
    """Per-wall-clock-bin directional IN/OUT totals for an intersection.

    Returns {"bins": {bin_start: {"in": {card:n}, "out": {card:n}}},
             "cam_id": <primary camera>, "rec_offset": <wall offset of that cam>}
    or None when no event carries a recording_start_datetime (S1 cannot align
    two intersections in wall-clock without it — we degrade by skipping).

    Aggregated IN SQL: the project DB lives on a OneDrive-synced path where a
    per-event Python materialize of ~30k rows/intersection is pathologically slow
    (~28s/17k rows), which made a single flag rebuild fetch the whole corridor and
    hang for minutes. A GROUP BY returns a few hundred (bin, origin, dest) rows
    and stays index-only via idx_events_cardinal_v (which includes video_id). The
    900s wall-clock bin is computed in SQL — julianday reproduces Python's
    datetime binning exactly (validated: 0 bin mismatches on the corridor)."""
    cams = [r[0] for r in conn.execute(
        "SELECT camera_id FROM cameras WHERE intersection_id = ? ORDER BY sort_order, camera_id",
        (intersection_id,)).fetchall()]
    if not cams:
        return None
    ph = ",".join("?" * len(cams))
    card = {lid: (cd or "").upper() for lid, cd in conn.execute(
        f"SELECT leg_id, cardinal_direction FROM legs WHERE camera_id IN ({ph})",
        cams).fetchall()}
    # wall bin = floor((recording_start - _REF + timestamp_video) / bin) * bin,
    # computed in SQL; for positive wall times CAST(...AS INTEGER) == floor.
    # strftime('%s') gives INTEGER Unix seconds, matching Python's exact
    # (datetime - _REF).total_seconds() — julianday()*86400 carries ~1e-5s of
    # float error that would flip boundary-exact events into the adjacent bin.
    rows = conn.execute(
        f"SELECT e.origin_leg_id, e.destination_leg_id, "
        f"CAST(((CAST(strftime('%s', v.recording_start_datetime) AS INTEGER) "
        f"      - CAST(strftime('%s', '2000-01-01') AS INTEGER)) "
        f"      + e.timestamp_video) / ? AS INTEGER) * ? AS wbin, "
        f"COUNT(*) "
        f"FROM vehicle_events e JOIN videos v ON v.video_id = e.video_id "
        f"WHERE e.camera_id IN ({ph}) AND e.rejected = 0 "
        f"AND e.destination_leg_id IS NOT NULL "
        f"AND e.timestamp_video IS NOT NULL "
        f"AND v.recording_start_datetime IS NOT NULL "
        f"GROUP BY e.origin_leg_id, e.destination_leg_id, wbin",
        (bin_seconds, bin_seconds, *cams)).fetchall()

    bins: dict[int, dict] = {}
    for ol, dl, wbin, n in rows:
        if wbin is None:                          # unparseable recording_start
            continue
        slot = bins.setdefault(int(wbin), {"in": defaultdict(int), "out": defaultdict(int)})
        a, d = card.get(ol), card.get(dl)
        if a:
            slot["in"][a] += n
        if d:
            slot["out"][d] += n
    if not bins:
        return None
    # Per-camera wall offset (of the earliest video), for cams that have events —
    # used only to point the review clip at the flagged interval.
    ev_cams = {r[0] for r in conn.execute(
        f"SELECT DISTINCT camera_id FROM vehicle_events "
        f"WHERE camera_id IN ({ph}) AND rejected = 0 "
        f"AND destination_leg_id IS NOT NULL", cams).fetchall()}
    min_rec = {cam: rec for cam, rec in conn.execute(
        f"SELECT camera_id, MIN(recording_start_datetime) FROM videos "
        f"WHERE camera_id IN ({ph}) AND recording_start_datetime IS NOT NULL "
        f"GROUP BY camera_id", cams).fetchall()}
    cam_offset: dict[int, float] = {}
    for cam in cams:                              # sort_order -> deterministic primary
        if cam in ev_cams and cam in min_rec:
            off = _wall(min_rec[cam], 0.0)
            if off is not None:
                cam_offset[cam] = off
    if not cam_offset:
        return None
    primary = cams[0] if cams[0] in cam_offset else next(iter(cam_offset))
    return {"iid": intersection_id, "bins": bins, "cam_id": primary,
            "rec_offset": cam_offset[primary]}


CORRIDOR_BIN_DEFICIT_FLOOR = 15   # ignore per-bin deficits below this (alignment noise)


def interval_corridor_gaps(project_id: str, ordered_ids: list[int] | None = None,
                           axis: str = "NS", bin_seconds: int = BIN_SECONDS,
                           target_id: int | None = None) -> list[dict]:
    """S1 — LOCALIZE confirmed corridor under-counts to their worst bins.

    Per-bin comparison alone cries wolf: at 15-min granularity, inter-camera
    clock/phase offset and link travel-time smear flagged dozens of bins even on
    links that conserve to ~2% over the whole window. So we GATE on the trusted
    whole-window check (Phase 3): a link/direction is only localized if its
    WHOLE-WINDOW gap clears CORRIDOR_WARN. For a confirmed-bad direction we then
    emit only the worst-deficit bins, stopping once their deficits sum to the
    whole-window deficit (the minimal set that explains the gap). A conserving
    link emits nothing — its per-bin wobble nets to zero over the window.

    Returns flag dicts tagged with `_intersection_id` (the under-counting end),
    which feed_suspected_gaps strips after filtering to its intersection.

    `target_id` restricts the scan to that intersection and its two corridor
    neighbours — the only pairs that can produce a flag FOR it — so a single-
    intersection rebuild never binned-IO-fetches the whole corridor (the caller
    filters to target_id anyway; the kept flags are identical)."""
    conn = get_connection(project_id)
    try:
        if ordered_ids is None:
            ordered_ids = [r[0] for r in conn.execute(
                "SELECT intersection_id FROM intersections "
                "ORDER BY sort_order, intersection_id").fetchall()]
        if target_id is not None and target_id in ordered_ids:
            i = ordered_ids.index(target_id)
            ordered_ids = ordered_ids[max(0, i - 1):i + 2]
        data = {iid: _binned_io(conn, iid, bin_seconds) for iid in ordered_ids}
    finally:
        conn.close()

    up, down = ("N", "S") if axis.upper() == "NS" else ("E", "W")
    flags: list[dict] = []
    for a, b in zip(ordered_ids, ordered_ids[1:]):
        da, db = data.get(a), data.get(b)
        if da is None or db is None:
            continue
        # CO-ACTIVE bins only: bins where BOTH intersections were recording (each
        # has some activity). Comparing a bin one end never processed is the
        # coverage-mismatch trap — adjacent intersections are often run over
        # different windows (e.g. a 24h count next to a peak-only one), which
        # would otherwise manufacture a 60% "gap" out of missing footage.
        bins = sorted(set(da["bins"]) & set(db["bins"]))
        # Two directional links: up-bound (a->b) and down-bound (b->a).
        for bound, send_d, recv_d in ((up, da, db), (down, db, da)):
            send_card = bound                        # sender's OUT cardinal
            recv_card = down if bound == up else up  # receiver's IN cardinal
            per_bin = []
            sent_total = recv_total = 0
            for w in bins:
                s = send_d["bins"].get(w, {"out": {}}).get("out", {}).get(send_card, 0)
                r = recv_d["bins"].get(w, {"in": {}}).get("in", {}).get(recv_card, 0)
                per_bin.append((w, s, r))
                sent_total += s
                recv_total += r
            big = max(sent_total, recv_total)
            if big < MIN_LINK_VOLUME:
                continue
            whole_gap = abs(sent_total - recv_total) / big
            if whole_gap < CORRIDOR_WARN:
                continue                              # link conserves -> not localized
            # Confirmed under-count: whichever end is smaller over the window.
            if sent_total >= recv_total:
                under, deficit_total = recv_d, sent_total - recv_total
                bin_deficit = [(w, s - r) for (w, s, r) in per_bin]
            else:
                under, deficit_total = send_d, recv_total - sent_total
                bin_deficit = [(w, r - s) for (w, s, r) in per_bin]
            origin_card = down if bound == up else up   # approach the stream enters from
            approach = bound_approach(origin_card)
            # Emit the worst-deficit bins until they explain the whole-window gap.
            acc = 0
            for w, dfc in sorted(bin_deficit, key=lambda x: -x[1]):
                if dfc < CORRIDOR_BIN_DEFICIT_FLOOR:
                    break
                vstart = max(0.0, w - under["rec_offset"])
                flags.append({
                    "_intersection_id": under["iid"],
                    "kind": "suspected_gap", "subtype": "interval_corridor",
                    "camera_id": under["cam_id"],
                    "interval_start_seconds": round(vstart, 1),
                    "interval_end_seconds": round(vstart + bin_seconds, 1),
                    "approach": approach, "movement": None,
                    "impact": float(dfc),
                    "reason": (f"{approach}B approach, {_hhmm(w, bin_seconds)}: corridor "
                               f"link {a}<->{b} {bound}bound short by {dfc} this bin "
                               f"(whole-window {bound}bound gap {round(whole_gap*100)}%) "
                               f"- likely undercount; review / add-missed here."),
                    "evidence": {"bin_deficit": dfc, "whole_window_gap": round(whole_gap, 3),
                                 "bound": bound, "link": f"{a}-{b}",
                                 "sent_total": sent_total, "recv_total": recv_total},
                    "batch_key": None,
                })
                acc += dfc
                if acc >= deficit_total:
                    break
    return flags


def _hhmm(wall_bin: float, bin_seconds: int) -> str:
    """Time-of-day HH:MM for a wall-clock bin (wall = recording_start - _REF +
    video time, and _REF is midnight-aligned, so this reads off the clock time)."""
    secs = int(wall_bin)
    h = (secs // 3600) % 24
    m = (secs // 60) % 60
    return f"{h:02d}:{m:02d}"


def interval_anomalies(project_id: str, intersection_id: int,
                       bin_seconds: int = BIN_SECONDS) -> list[dict]:
    """S2 — per-approach abrupt asymmetric drops vs a LOCAL rolling baseline.

    Per camera (so clip references stay in that camera's video time), bin events
    by video time; for each approach with enough volume, flag a bin that falls
    sharply below the median of its neighbours WHILE its reverse partner held.
    Quiet on smooth traffic; fires on dropouts / collapses."""
    conn = get_connection(project_id)
    try:
        cams = [r[0] for r in conn.execute(
            "SELECT camera_id FROM cameras WHERE intersection_id = ?",
            (intersection_id,)).fetchall()]
        per_cam = {}
        for cam in cams:
            card = {lid: (cd or "").upper() for lid, cd in conn.execute(
                "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id = ?",
                (cam,)).fetchall()}
            # Aggregated in SQL (per-event materialize is slow on the OneDrive DB);
            # video-time bin = floor(timestamp_video / bin) * bin. Index-only via
            # idx_events_cardinal_v.
            rows = conn.execute(
                "SELECT origin_leg_id, CAST(timestamp_video / ? AS INTEGER) * ? AS vbin, "
                "COUNT(*) FROM vehicle_events "
                "WHERE camera_id = ? AND rejected = 0 AND timestamp_video IS NOT NULL "
                "GROUP BY origin_leg_id, vbin", (bin_seconds, bin_seconds, cam)).fetchall()
            per_cam[cam] = (card, rows)
    finally:
        conn.close()

    flags: list[dict] = []
    for cam, (card, rows) in per_cam.items():
        # active bins (camera was recording) and per-approach counts per bin
        counts: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        active: set[int] = set()
        for ol, b, n in rows:
            a = card.get(ol)
            if not a:
                continue
            counts[a][int(b)] += n
            active.add(int(b))
        active_sorted = sorted(active)
        for ap, series in counts.items():
            if sum(series.values()) < ANOM_APPROACH_MIN:
                continue
            partner = OPPOSITE.get(ap)
            pser = counts.get(partner, {})
            for b in active_sorted:
                v = series.get(b, 0)
                base = _local_median(series, b, active_sorted)
                if base is None or base < ANOM_MIN_DEFICIT:
                    continue
                if (base - v) < ANOM_MIN_DEFICIT or v > base * (1 - ANOM_DROP_FRAC):
                    continue
                # asymmetry guard: the reverse partner must have HELD locally
                pbase = _local_median(pser, b, active_sorted)
                pv = pser.get(b, 0)
                if pbase is None or pbase < ANOM_MIN_DEFICIT:
                    continue   # no partner reference -> cannot rule out a real lull
                if pv < pbase * ANOM_PARTNER_HELD:
                    continue   # partner dropped too -> looks like a real lull, skip
                missing = base - v
                hhmm = _hhmm_video(b)
                flags.append({
                    "_intersection_id": intersection_id,
                    "kind": "suspected_gap", "subtype": "interval_anomaly",
                    "camera_id": cam,
                    "interval_start_seconds": float(b),
                    "interval_end_seconds": float(b + bin_seconds),
                    "approach": bound_approach(ap), "movement": None,
                    "impact": float(missing),
                    "reason": (f"{bound_approach(ap)}B approach, ~{hhmm} into the run: "
                               f"{v} vehicles vs ~{round(base)} typical while the reverse "
                               f"approach held — likely a coverage gap (dropout/occlusion); "
                               f"review here."),
                    "evidence": {"observed": v, "local_baseline": round(base, 1),
                                 "partner_observed": pv,
                                 "partner_baseline": round(pbase, 1)},
                    "batch_key": None,
                })
    return flags


def _local_median(series: dict[int, int], b: int, active_sorted: list[int]) -> float | None:
    """Median of an approach's counts in the +/- ANOM_ROLL_HALF neighbouring
    ACTIVE bins around b (excluding b). None if too few neighbours."""
    try:
        i = active_sorted.index(b)
    except ValueError:
        return None
    lo = max(0, i - ANOM_ROLL_HALF)
    hi = min(len(active_sorted), i + ANOM_ROLL_HALF + 1)
    neigh = [series.get(active_sorted[j], 0) for j in range(lo, hi) if j != i]
    if len(neigh) < 2:
        return None
    return float(statistics.median(neigh))


def _hhmm_video(secs: int) -> str:
    h = secs // 3600
    m = (secs // 60) % 60
    return f"{h:02d}:{m:02d}"
