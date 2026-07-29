"""Stage-2 queue auto-resolution + 5/95 bin re-key
(docs/plan_stage2_labor_levers_2026-07-29.md, steps 2.2 + 2.3).

Blind-computable rules only (§0: no ground truth, no per-site fitting),
frozen corridor-wide by the 2.2 ablation (runs/stage2_labor/
ablation.json — recall and BIG recall byte-flat at baseline):

  R5_scope — an event flag whose wall-clock time falls outside the
             claim scope (declared trims where present, else the
             daylight envelope) resolves as out-of-claimed-windows.
             Time-only test; certification never covered that footage
             (spot_check claim structure item 3).
  R_cap    — the flags of one (approach, movement, 15-min bin) cluster
             keep the K=1 most-severe EXEMPLAR; the rest resolve as
             redundant-for-the-bin. >=1 member survives per cluster, so
             every cell-bin the queue caught stays caught — recall is
             invariant BY CONSTRUCTION (and was measured flat).
  R2_hole  — a bank_coverage_hole whose live fallback-event impact is
             <= 5 over the whole processed day cannot exceed the +/-5
             per-bin grace even if every event is misattributed.

Re-key (2.3): every in-scope event flag — exemplar and capped members
alike — gets batch_key `bin|{cam}|{approach}-{movement}|{HH:MM}`, so
one worklist card = one suspect cell-bin ("fix this bin") with its
events grouped under it. The exemplar carries impact = cluster size
(the bin's suspected max delta — the worklist orders by how much a bin
can move); capped members keep impact 1 and stay visible in the card's
drill-in as machine-closed (child-test: visible, reopenable, verifiable).

auto_resolved is MACHINE state: cleared and re-derived on every rebuild
(self-healing — unlike operator statuses, which persist and exclude the
event from re-flagging). Reopening one hands it back to the operator;
a later rebuild may re-resolve it unless they work it to a terminal
status.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone

from backend.database import get_connection

AUTO_STATUS = "auto_resolved"
CAP_K = 1                       # exemplars kept per cell-bin cluster
HOLE_MAX_EVENTS = 5.0           # R2: <= grace even if all misattributed
DAYLIGHT_SECONDS = (6 * 3600, 20 * 3600)   # guarantee's night exclusion
BIN_SECONDS = 900

_NOTES = {
    "R5_scope": ("outside the claimed windows (declared trims / daylight) — "
                 "not covered by the deliverable's certification scope"),
    "R_cap": ("redundant for this bin — the bin stays surfaced by its "
              "exemplar card"),
    "R2_hole": ("drawn-channel hole with <=5 fallback events all day — "
                "inside the +/-5 per-bin grace even if every one is wrong"),
}


def claim_windows(conn: sqlite3.Connection, intersection_id: int,
                  ) -> list[tuple[int, int]]:
    """The claim scope in wall-clock seconds: the intersection's declared
    trims, else the daylight envelope (the blind R5 scope)."""
    rows = conn.execute(
        "SELECT start_wallclock, end_wallclock FROM trims WHERE "
        "intersection_id = ? ORDER BY sort_order", (intersection_id,)).fetchall()

    def secs(hms: str) -> int:
        h, m, s = (int(x) for x in str(hms).split(":"))
        return h * 3600 + m * 60 + s
    if rows:
        return [(secs(a), secs(b)) for a, b in rows]
    return [DAYLIGHT_SECONDS]


def rec_offsets(conn: sqlite3.Connection) -> dict[int, int | None]:
    """{camera_id: seconds-since-midnight of recording start} (None when
    unknown — such cameras are left untouched by the time rules)."""
    out: dict[int, int | None] = {}
    for cam, start in conn.execute(
            "SELECT camera_id, MIN(recording_start_datetime) FROM videos "
            "GROUP BY camera_id"):
        if not start:
            out[cam] = None
            continue
        try:
            dt = datetime.fromisoformat(start)
            out[cam] = dt.hour * 3600 + dt.minute * 60 + dt.second
        except ValueError:
            out[cam] = None
    return out


def bin_batch_key(camera_id: int, approach: str | None, movement: str | None,
                  wall_bin: int) -> str:
    hh, mm = wall_bin // 3600, (wall_bin % 3600) // 60
    return f"bin|{camera_id}|{approach or '?'}-{movement or '?'}|{hh:02d}:{mm:02d}"


def decide(records: list[dict], windows: list[tuple[int, int]],
           rec_by_cam: dict[int, int | None]) -> list[dict]:
    """The rule core, pure. Each record: {subtype, camera_id, has_event,
    ev_ts (video secs | None), approach, movement, impact, severity}.
    Returns one decision per record (same order): {status, rule, note,
    batch_key, impact, cluster_n} — batch_key/impact/cluster_n are None
    when unchanged."""
    decisions: list[dict] = [
        {"status": "open", "rule": None, "note": None, "batch_key": None,
         "impact": None, "cluster_n": None} for _ in records]

    clusters: dict[tuple, list[int]] = defaultdict(list)
    for i, r in enumerate(records):
        if r["subtype"] == "bank_coverage_hole" and \
                float(r.get("impact") or 0) <= HOLE_MAX_EVENTS:
            decisions[i].update(status=AUTO_STATUS, rule="R2_hole",
                                note=_NOTES["R2_hole"])
            continue
        rec = rec_by_cam.get(r["camera_id"])
        if not r.get("has_event") or r.get("ev_ts") is None or rec is None:
            continue                     # broad/interval or unclockable: keep
        wall = r["ev_ts"] + rec
        if not any(lo <= wall < hi for lo, hi in windows):
            decisions[i].update(status=AUTO_STATUS, rule="R5_scope",
                                note=_NOTES["R5_scope"])
            continue
        wall_bin = int(wall // BIN_SECONDS) * BIN_SECONDS
        key = (r["camera_id"], r.get("approach") or "?",
               r.get("movement") or "?", wall_bin)
        clusters[key].append(i)

    for (cam, appr, mv, wall_bin), members in clusters.items():
        bkey = bin_batch_key(cam, appr, mv, wall_bin)
        members.sort(key=lambda i: (-float(records[i].get("severity") or 0.0), i))
        n = len(members)
        for rank, i in enumerate(members):
            decisions[i]["batch_key"] = bkey
            decisions[i]["cluster_n"] = n
            if rank < CAP_K:
                decisions[i]["impact"] = float(n)     # suspected max delta
            else:
                decisions[i].update(status=AUTO_STATUS, rule="R_cap",
                                    note=_NOTES["R_cap"])
    return decisions


def apply_to_feeder_dicts(conn: sqlite3.Connection, intersection_id: int,
                          flags: list[dict]) -> dict:
    """Rebuild-path adapter: annotate the pre-insert feeder dicts in
    place (status / evidence['auto_resolved'] / batch_key / impact).
    Consumes the feeder's `_ev_ts` helper key. Returns counts by rule."""
    windows = claim_windows(conn, intersection_id)
    recs = rec_offsets(conn)
    missing = [f["event_id"] for f in flags
               if f.get("event_id") is not None and "_ev_ts" not in f]
    ts_by_event: dict[int, float | None] = {}
    for chunk_start in range(0, len(missing), 500):
        chunk = missing[chunk_start:chunk_start + 500]
        ph = ",".join("?" * len(chunk))
        ts_by_event.update(dict(conn.execute(
            f"SELECT event_id, timestamp_video FROM vehicle_events "
            f"WHERE event_id IN ({ph})", chunk)))

    records = []
    for f in flags:
        ev_ts = f.pop("_ev_ts", None)
        if ev_ts is None and f.get("event_id") is not None:
            ev_ts = ts_by_event.get(f["event_id"])
        records.append({
            "subtype": f.get("subtype"), "camera_id": f.get("camera_id"),
            "has_event": f.get("event_id") is not None, "ev_ts": ev_ts,
            "approach": f.get("approach"), "movement": f.get("movement"),
            "impact": f.get("impact", 1.0),
            "severity": (f.get("evidence") or {}).get("severity", 0.0),
        })
    counts: dict[str, int] = defaultdict(int)
    for f, d in zip(flags, decide(records, windows, recs)):
        if d["batch_key"] is not None:
            f["batch_key"] = d["batch_key"]
        if d["impact"] is not None:
            f["impact"] = d["impact"]
        if d["cluster_n"] is not None:
            f.setdefault("evidence", {})
            f["evidence"]["bin_cluster_n"] = d["cluster_n"]
        if d["status"] == AUTO_STATUS:
            f["status"] = AUTO_STATUS
            f.setdefault("evidence", {})
            f["evidence"]["auto_resolved"] = {"rule": d["rule"], "note": d["note"]}
            counts[d["rule"]] += 1
    return dict(counts)


def sweep(project_id: str, intersection_id: int) -> dict:
    """In-place application to an EXISTING open queue (the production
    path — never a rebuild, so pass-2-only flags like S5 survive).
    Idempotent. Returns per-camera before/after + counts by rule."""
    conn = get_connection(project_id)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT f.flag_id, f.camera_id, f.subtype, f.event_id, f.approach, "
            "f.movement, f.impact, f.evidence_json, e.timestamp_video AS ev_ts "
            "FROM review_flags f LEFT JOIN vehicle_events e "
            "ON e.event_id = f.event_id "
            "WHERE f.intersection_id = ? AND f.status = 'open'",
            (intersection_id,)).fetchall()
        if not rows:
            return {"open_before": 0, "open_after": 0, "by_rule": {}}
        windows = claim_windows(conn, intersection_id)
        recs = rec_offsets(conn)
        records = []
        for r in rows:
            try:
                sev = float((json.loads(r["evidence_json"] or "{}") or {})
                            .get("severity", 0.0))
            except (TypeError, ValueError):
                sev = 0.0
            records.append({
                "subtype": r["subtype"], "camera_id": r["camera_id"],
                "has_event": r["event_id"] is not None, "ev_ts": r["ev_ts"],
                "approach": r["approach"], "movement": r["movement"],
                "impact": r["impact"], "severity": sev,
            })
        decisions = decide(records, windows, recs)
        now = datetime.now(timezone.utc).isoformat()
        counts: dict[str, int] = defaultdict(int)
        with conn:
            for r, d in zip(rows, decisions):
                sets, params = [], []
                if d["batch_key"] is not None:
                    sets.append("batch_key = ?"); params.append(d["batch_key"])
                if d["impact"] is not None:
                    sets.append("impact = ?"); params.append(d["impact"])
                ev_extra = {}
                if d["cluster_n"] is not None:
                    ev_extra["bin_cluster_n"] = d["cluster_n"]
                if d["status"] == AUTO_STATUS:
                    sets += ["status = ?", "resolved_at = ?"]
                    params += [AUTO_STATUS, now]
                    ev_extra["auto_resolved"] = {"rule": d["rule"],
                                                 "note": d["note"]}
                    counts[d["rule"]] += 1
                if ev_extra:
                    try:
                        ev = json.loads(r["evidence_json"] or "{}") or {}
                    except (TypeError, ValueError):
                        ev = {}
                    ev.update(ev_extra)
                    sets.append("evidence_json = ?"); params.append(json.dumps(ev))
                if sets:
                    params.append(r["flag_id"])
                    conn.execute(
                        f"UPDATE review_flags SET {', '.join(sets)} "
                        f"WHERE flag_id = ?", params)
        open_after = conn.execute(
            "SELECT COUNT(*) FROM review_flags WHERE intersection_id = ? "
            "AND status = 'open'", (intersection_id,)).fetchone()[0]
        return {"open_before": len(rows), "open_after": open_after,
                "by_rule": dict(counts)}
    finally:
        conn.close()
