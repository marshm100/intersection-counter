"""Auto-trims proposal (Stage-4 4.3, plan_stage4_childtest_ux).

Blind-computable from footage METADATA alone (recording clocks +
durations — nothing processed, nothing detected): the covered
wall-clock span(s) of the intersection-day's cameras, and from them a
one-click trims proposal:

  - SHORT coverage (every span <= 4.5 h): the recording IS the study —
    propose the span(s) themselves.
  - LONG coverage (a full-day-class span): propose the STANDARD TMC
    peaks (07-09 / 11-13 / 16-18) clipped to coverage — the corridor's
    own declared trims are exactly these — plus a "count everything
    (daylight)" alternative, since the guarantee excludes night anyway.

Accepted rows land as ordinary trims (editable/deletable afterward);
declaring trims tightens the claim scope, the queue's R5 rule, the
star rating's night handling, and the spot-segment stratification.
"""
from __future__ import annotations

from datetime import datetime

from backend.database import get_connection

GAP_SPLIT_SECONDS = 20 * 60          # a >20-min hole splits coverage spans
LONG_SPAN_SECONDS = 4.5 * 3600       # beyond this, propose peaks not the span
STANDARD_PEAKS = [(7 * 3600, 9 * 3600), (11 * 3600, 13 * 3600),
                  (16 * 3600, 18 * 3600)]
DAYLIGHT = (6 * 3600, 20 * 3600)
MIN_WINDOW_SECONDS = 30 * 60         # a clipped piece below this isn't proposed


def _hms(secs: float) -> str:
    s = int(round(secs))
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def _coverage_spans(conn, intersection_id: int) -> list[list[float]]:
    spans = []
    for start, dur in conn.execute(
            "SELECT v.recording_start_datetime, v.duration_seconds "
            "FROM videos v JOIN cameras c ON c.camera_id = v.camera_id "
            "WHERE c.intersection_id = ?", (intersection_id,)):
        if not start or not dur:
            continue
        try:
            dt = datetime.fromisoformat(start)
        except ValueError:
            continue
        s = dt.hour * 3600 + dt.minute * 60 + dt.second
        spans.append([float(s), float(s) + float(dur)])
    spans.sort()
    merged: list[list[float]] = []
    for s, e in spans:
        if merged and s - merged[-1][1] <= GAP_SPLIT_SECONDS:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def _clip(windows, spans) -> list[list[float]]:
    out = []
    for ws, we in windows:
        for s, e in spans:
            lo, hi = max(ws, s), min(we, e)
            if hi - lo >= MIN_WINDOW_SECONDS:
                out.append([lo, hi])
    return out


def propose_trims(project_id: str, intersection_id: int) -> dict:
    conn = get_connection(project_id)
    try:
        spans = _coverage_spans(conn, intersection_id)
    finally:
        conn.close()
    if not spans:
        return {"covered": [], "proposals": [], "alternative_daylight": [],
                "note": "No clocked footage yet — add videos first."}
    covered = [{"start": _hms(s), "end": _hms(e)} for s, e in spans]
    long_run = any(e - s > LONG_SPAN_SECONDS for s, e in spans)
    if not long_run:
        props = [{"start_wallclock": _hms(s), "end_wallclock": _hms(e),
                  "kind": "footage"} for s, e in spans]
        alt = []
        note = ("Your footage covers "
                + ", ".join(f"{c['start'][:5]}–{c['end'][:5]}" for c in covered)
                + ". The recording looks like the study itself — count all "
                  "of it?")
    else:
        props = [{"start_wallclock": _hms(s), "end_wallclock": _hms(e),
                  "kind": "peak"} for s, e in _clip(STANDARD_PEAKS, spans)]
        alt = [{"start_wallclock": _hms(s), "end_wallclock": _hms(e),
                "kind": "daylight"} for s, e in _clip([DAYLIGHT], spans)]
        note = ("Your footage covers "
                + ", ".join(f"{c['start'][:5]}–{c['end'][:5]}" for c in covered)
                + ". Studies usually count the peak windows — accept these? "
                  "(Or count everything in daylight instead.)")
    return {"covered": covered, "proposals": props,
            "alternative_daylight": alt, "note": note}
