"""Stage-3 footage star rating — the blind censuses as an ingest-time
quality verdict (docs/plan_stage3_star_rating_2026-07-29.md).

The rating answers ONE operator question in child language: does this
footage support the 5/95 per-movement guarantee? It is computed from
blind signals only (§0: no ground truth, no per-site knobs) and REFINES
as inputs land, in tiers:

  A  video metadata (at add): resolution class, fps, night share.
     Sub-1080p footage CAPS the rating at 4 stars — the measured
     source-resolution wall (three mechanism families dead at 640x480;
     ReID twin AUC 0.399) and Miovision's own 5-star precondition.
  B  pass-1 dump + calibration: the chain/track census — journey tag
     mix (full / entry_only / exit_only / no_crossing) via the pinned
     entry gates, fragment-chain multiplicity (frozen STITCH machinery),
     and tag-based entry coverage.
  C  production events joined to the dump's chains (validated by id
     overlap — a legacy live-pipeline table that does not join is
     DETECTED and reported, never silently miscounted): excess-event
     rate and its KIND. Composition, not rate, is the signal
     (lane_echo phase-0): flip-pairs (A>B + B>A on one chain) are
     direction-gate-covered and benign — FM51 runs 81% flips and is
     the cleanest site; SAME-CELL echoes (one cell counted >=2x on one
     chain) are the real double-count/phantom risk — cam4's 35>33 pool
     produced its SB-right 20-vs-0 phantom bin.

Thresholds are FROZEN corpus-anchored constants (the gate table in the
plan doc; runs/stage3_star/rating_gate.json is the anchor evidence).
KNOWN LIMIT (pre-registered): concurrent occlusion ID-splits (cam2's
EB scrambling class) are invisible to these censuses at SD resolution —
cam2 rates with the corridor pack, not below it, and the statement
never pretends otherwise. The concurrent-twin census is the named v2
candidate.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import numpy as np

from backend.database import get_connection, list_paths_for_camera
from backend.services.detection_cache import (
    cache_dir, compute_video_content_hash)
from backend.services.entry_gates import build_gates, classify
from backend.services.pass2_replay import load_dump, tracks_dir
from backend.services.track_chains import build_chain_map

# --- frozen thresholds (corpus-anchored; see plan doc + rating_gate.json) ---
QUALIFYING_MIN_HEIGHT = 1080     # the 5-star resolution precondition
LOW_FPS = 8.0                    # below this, a reason line (corpus is 10-25)
DAYLIGHT_SECONDS = (6 * 3600, 20 * 3600)
NIGHT_DOMINANT = 0.90            # video almost entirely night -> 1 star
# Tier-C composition: same-cell echo excess per counted event — the ONE
# census axis the corpus defends as a star gate (plan doc, amended gate
# table). Replay-basis anchors (phase-0 censuses): cam4 ~10.7% (the
# phantom-producing 35>33 pool) and cam5 ~5.7% (the 39>37 stub class)
# vs everyone else <=2.5% (FM51 1.6%, cam3 2.1%, cam1 2.5%, cam2 0.6%).
# The threshold sits in that measured gap; the gate script confirms the
# ordering holds on the production basis before this ships.
ECHO_SHARE_FAIR = 0.04
# Tag coverage (full + entry_only share) and fragmentation are
# GEOMETRY-CONFOUNDED corpus-wide (FM51, the cleanest site, scores
# worst on both) -> reason lines only, never a star gate, in v1.
JOIN_VALID_MAX_UNMAPPED = 0.20   # event-id join validity for tier C
MIN_TRACK_POINTS = 5
# Bump when the census computation changes — invalidates sidecar caches.
CENSUS_VERSION = 2

STATEMENTS = {
    5: "Guarantee-ready: the 5/95 per-movement guarantee applies after review.",
    4: "Strong: totals certifiable and movements reviewable. The full "
       "per-movement guarantee needs qualifying (1080p-class) footage.",
    3: "Fair: totals + flag-queue surveillance. Some movement cells cannot "
       "be guaranteed on this footage.",
    2: "Weak: totals only on this footage.",
    1: "Not ratable for the guarantee (night or unusable footage dominates).",
}
LABELS = {5: "Guarantee-ready", 4: "Strong", 3: "Fair", 2: "Weak",
          1: "Not ratable"}


def _video_rows(conn: sqlite3.Connection, camera_id: int) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(
        "SELECT * FROM videos WHERE camera_id = ? ORDER BY sort_order",
        (camera_id,))]


def video_tier(conn: sqlite3.Connection, camera_id: int) -> dict | None:
    """Tier A — metadata only. None when the camera has no videos yet."""
    vids = _video_rows(conn, camera_id)
    if not vids:
        return None
    height = min(int(v["height"] or 0) for v in vids)
    width = min(int(v["width"] or 0) for v in vids)
    fps = min(float(v["fps"] or 0) for v in vids)
    total = 0.0
    night = 0.0
    for v in vids:
        dur = float(v["duration_seconds"] or 0)
        total += dur
        start = None
        if v["recording_start_datetime"]:
            try:
                dt = datetime.fromisoformat(v["recording_start_datetime"])
                start = dt.hour * 3600 + dt.minute * 60 + dt.second
            except ValueError:
                start = None
        if start is None:
            continue                      # unknown clock: no night attribution
        lo, hi = DAYLIGHT_SECONDS
        for s in range(int(start), int(start + dur), 60):
            if not (lo <= (s % 86400) < hi):
                night += 60.0
    return {"height": height, "width": width, "fps": fps,
            "duration_seconds": total,
            "night_share": round(night / total, 3) if total else None,
            "qualifying_resolution": height >= QUALIFYING_MIN_HEIGHT}


def _gates(conn: sqlite3.Connection, project_id: str, camera_id: int):
    """The pinned entry gates (same geometry as the evidence gate).
    None when calibration isn't there yet (no legs with origin zones)."""
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id = ?", (camera_id,)):
        if oz:
            z = json.loads(oz)
            p = z[0] if isinstance(z[0], (list, tuple)) else z
            mouths[lid] = (p[0], p[1])
            heads[lid] = rh
    if not mouths:
        return None
    return build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                       heads)


def _dump_variants(project_id: str, camera_id: int,
                   vids: list[dict]) -> list[dict]:
    """Available pass-1 dumps for the camera's first video: [{name, tdir,
    mtime}]. Empty when pass 1 hasn't run (tier B unavailable)."""
    if not vids:
        return []
    v = vids[0]
    try:
        chash, _ = compute_video_content_hash(
            v["path"], file_size_bytes=v["file_size_bytes"],
            total_frames=v["total_frames"])
    except (OSError, TypeError, ValueError):
        return []
    d = cache_dir(project_id, camera_id, chash)
    out = []
    if d.exists():
        for t in sorted(d.glob("*.tracks")):
            if (t / "count.txt").exists():
                out.append({"name": t.name[:-len(".tracks")], "tdir": t,
                            "mtime": (t / "count.txt").stat().st_mtime})
    return out


def chain_census(project_id: str, camera_id: int) -> dict | None:
    """Tier B (+C where the event join validates). None when the dump or
    the calibration is missing. Aggregates over the best-joining dump
    variant per window span."""
    conn = get_connection(project_id)
    try:
        vids = _video_rows(conn, camera_id)
        variants = _dump_variants(project_id, camera_id, vids)
        gates = _gates(conn, project_id, camera_id)
        if not variants or gates is None or not vids:
            return None
        fps = float(vids[0]["fps"] or 10.0)
        events = [(int(t), o, d, float(ts)) for t, o, d, ts in conn.execute(
            "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, "
            "timestamp_video FROM vehicle_events WHERE camera_id = ? AND "
            "COALESCE(rejected, 0) = 0 AND vehicle_track_id IS NOT NULL "
            "AND timestamp_video IS NOT NULL", (camera_id,))]
    finally:
        conn.close()

    loaded = []
    for va in variants:
        rows = load_dump(va["tdir"])
        tids = set(int(t) for t in np.unique(rows[:, 0]))
        f_lo, f_hi = float(rows[:, 1].min()), float(rows[:, 1].max())
        loaded.append({**va, "rows": rows, "tids": tids,
                       "span": (f_lo / fps, f_hi / fps)})

    # Events are assigned to a dump variant by TIME (their timestamp must
    # lie in the dump's span) and only then joined by track id. Joining by
    # id membership alone is WRONG: track ids restart per window and per
    # era, so an event from an un-dumped window numerically collides with
    # another window's ids and manufactures phantom same-cell echoes (the
    # 2026-07-29 gate run caught exactly this at cam1/cam2 — plan doc
    # verdict). Events covered by no chosen span are counted uncovered:
    # the census then rates the covered windows, which is what it has.
    groups: list[list[dict]] = []
    for va in sorted(loaded, key=lambda v: v["span"]):
        for g in groups:
            lo, hi = g[0]["span"]
            if va["span"][0] <= hi and va["span"][1] >= lo:
                g.append(va)
                break
        else:
            groups.append([va])

    def _covered(va, ts: float) -> bool:
        lo, hi = va["span"]
        return lo <= ts <= hi

    # per span group: the family whose ids best match ITS OWN covered events
    chosen = []
    for g in groups:
        def _join_score(va):
            return sum(1 for t, _o, _d, ts in events
                       if _covered(va, ts) and t in va["tids"])
        chosen.append(max(g, key=_join_score))

    agg = {"variants": [v["name"] for v in chosen], "tracks_mapped": 0,
           "chains": 0, "multi_chains": 0,
           "tags": Counter(), "events_joined": 0, "events_unmapped": 0,
           "events_uncovered": 0,
           "excess_events": 0, "excess_flip": 0, "excess_same_cell": 0,
           "excess_cross": 0}
    agg["events_uncovered"] = sum(
        1 for _t, _o, _d, ts in events
        if not any(_covered(va, ts) for va in chosen))
    for va in chosen:
        tracks: dict[int, list] = defaultdict(list)
        for r in va["rows"]:
            tracks[int(r[0])].append((float(r[1]), float(r[2]), float(r[3])))
        chain_map = build_chain_map(tracks, gates, fps)
        chains: dict[int, list[int]] = defaultdict(list)
        for tid, ci in chain_map.items():
            chains[ci].append(tid)
        for tid, pts in tracks.items():
            if len(pts) < MIN_TRACK_POINTS:
                continue
            agg["tracks_mapped"] += 1
            *_x, tag = classify(sorted(pts), gates, fps)
            agg["tags"][tag] += 1
        agg["chains"] += len(chains)
        agg["multi_chains"] += sum(1 for m in chains.values() if len(m) > 1)

        ev_chain: dict[int, list] = defaultdict(list)
        for t, o, d, ts in events:
            if not _covered(va, ts):
                continue                  # other window / uncovered
            if t not in va["tids"]:
                agg["events_unmapped"] += 1
                continue
            ci = chain_map.get(t)
            if ci is None:
                agg["events_unmapped"] += 1
                continue
            agg["events_joined"] += 1
            ev_chain[ci].append((o, d))
        for evs in ev_chain.values():
            if len(evs) < 2:
                continue
            agg["excess_events"] += len(evs) - 1
            cells = {(o, d) for o, d in evs}
            flips = {(o, d) for o, d in cells if (d, o) in cells}
            if len(cells) == 1:
                agg["excess_same_cell"] += len(evs) - 1
            elif flips:
                agg["excess_flip"] += len(evs) - 1
            else:
                agg["excess_cross"] += len(evs) - 1

    tags = agg.pop("tags")
    n = agg["tracks_mapped"]
    ev_n = agg["events_joined"] + agg["events_unmapped"]
    joined = agg["events_joined"]
    agg["tag_mix"] = {k: round(v / n, 3) for k, v in sorted(tags.items())} \
        if n else {}
    agg["entry_coverage"] = round(
        (tags.get("full", 0) + tags.get("entry_only", 0)) / n, 3) if n else None
    agg["multi_chain_share"] = round(agg["multi_chains"] / agg["chains"], 3) \
        if agg["chains"] else None
    agg["event_join_unmapped_share"] = round(
        agg["events_unmapped"] / ev_n, 3) if ev_n else None
    agg["event_join_valid"] = bool(
        ev_n and agg["events_unmapped"] / ev_n <= JOIN_VALID_MAX_UNMAPPED)
    if agg["event_join_valid"] and joined:
        agg["echo_share"] = round(agg["excess_same_cell"] / joined, 4)
        agg["flip_share"] = round(agg["excess_flip"] / joined, 4)
    else:
        agg["echo_share"] = agg["flip_share"] = None
    return agg


def classify_metrics(meta: dict | None, census: dict | None) -> dict:
    """The frozen mapping: metrics -> stars/label/statement/reasons.
    Pure; the gate script and the service both call this."""
    reasons: list[str] = []
    if meta is None:
        return {"stars": None, "tier": None, "label": "No footage",
                "statement": "Add video to rate this camera.", "reasons": []}
    tier = "A"
    stars = 5
    if not meta["qualifying_resolution"]:
        stars = min(stars, 4)
        reasons.append(
            f"{meta['width']}x{meta['height']} is below qualifying "
            f"(1080p-class) resolution — the full per-movement guarantee "
            f"needs better footage (measured wall, not a policy choice)")
    if meta["fps"] and meta["fps"] < LOW_FPS:
        reasons.append(f"low frame rate ({meta['fps']:.0f} fps)")
    if meta["night_share"] is not None and meta["night_share"] > 0:
        if meta["night_share"] >= NIGHT_DOMINANT:
            stars = 1
            reasons.append("footage is almost entirely night — excluded "
                           "from the guarantee")
        else:
            reasons.append(
                f"{meta['night_share']:.0%} of the footage is night — "
                f"those hours are excluded from the guarantee")

    if census is None:
        reasons.append("processing/calibration pending — this is the "
                       "footage-metadata rating only")
    else:
        tier = "C" if census["event_join_valid"] else "B"
        if census["entry_coverage"] is not None:
            reasons.append(
                f"{census['entry_coverage']:.0%} of tracked vehicles show "
                f"their approach entry (camera angle/depth)")
        if census["multi_chain_share"]:
            reasons.append(
                f"{census['multi_chain_share']:.0%} of vehicles fragment "
                f"into multiple tracks")
        if tier == "B":
            reasons.append("count-echo census unavailable on this table "
                           "(legacy basis — will compute on next pass-2)")
        elif census["echo_share"] is not None:
            if census["echo_share"] > ECHO_SHARE_FAIR and stars > 3:
                stars = 3
                reasons.append(
                    f"double-count echo risk: {census['echo_share']:.1%} of "
                    f"counts repeat a cell on one vehicle chain (threshold "
                    f"{ECHO_SHARE_FAIR:.0%})")
            elif census["echo_share"] > ECHO_SHARE_FAIR:
                reasons.append(
                    f"double-count echo risk {census['echo_share']:.1%}")
            if census["flip_share"] and census["flip_share"] > 0.05:
                reasons.append(
                    f"{census['flip_share']:.1%} opposing-pair flips — "
                    f"benign (the direction gate absorbs these)")
    return {"stars": stars, "tier": tier, "label": LABELS[stars],
            "statement": STATEMENTS[stars], "reasons": reasons}


def rate_camera(project_id: str, camera_id: int,
                use_cache: bool = True) -> dict:
    """The service entry: tiered rating + metrics, sidecar-cached (the
    census is the expensive part; the cache keys on dump variants,
    event count, and calibration rows)."""
    conn = get_connection(project_id)
    try:
        meta = video_tier(conn, camera_id)
        vids = _video_rows(conn, camera_id)
        n_events = conn.execute(
            "SELECT COUNT(*) FROM vehicle_events WHERE camera_id = ?",
            (camera_id,)).fetchone()[0]
        n_legs = conn.execute(
            "SELECT COUNT(*) FROM legs WHERE camera_id = ? AND "
            "origin_zone IS NOT NULL", (camera_id,)).fetchone()[0]
    finally:
        conn.close()
    variants = _dump_variants(project_id, camera_id, vids)
    cache_key = {"v": CENSUS_VERSION,
                 "variants": [(v["name"], v["mtime"]) for v in variants],
                 "n_events": n_events, "n_legs": n_legs}
    cache_path = Path(f"data/projects/{project_id}/footage_rating_cam"
                      f"{camera_id}.json")
    census = None
    if use_cache and cache_path.exists():
        try:
            stored = json.loads(cache_path.read_text())
            if stored.get("cache_key") == cache_key:
                census = stored.get("census")
        except (ValueError, OSError):
            pass
    if census is None and variants and n_legs:
        census = chain_census(project_id, camera_id)
        if census is not None:
            try:
                cache_path.write_text(json.dumps(
                    {"cache_key": cache_key, "census": census}))
            except OSError:
                pass
    out = classify_metrics(meta, census)
    out["camera_id"] = camera_id
    out["metrics"] = {"video": meta, "census": census}
    return out
