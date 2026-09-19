"""Two-pass counting orchestration (stage 3, plan_A4_stage3_2026-07-10).

Pass 2 = ALL semantics, minutes from cache, re-runnable:
  1. corpus discovery — the bank builder runs over the camera's pass-1
     raw-track dump, giving per-cell volumes observed over the SAME window
     that gets counted (scale-1 merge expecteds; A4a retired extrapolation)
     plus the missing-movement QA. **The corpus bank does NOT replace the
     camera's APPLIED bank for attribution**: the 2026-07-09 bank audit
     measured that swap as catastrophic (cam5 drawn-direct arm: 38.9% MAE,
     +161 phantom NB-rights; cam2 §2c: −18.5%) — attribution stays on the
     operator-applied bank; the corpus result feeds expecteds + QA only.
  2. replay-classify through the production chain (A2 parity: exact);
  3. volume-gated turn-fragment merge, corpus expecteds (A4a: cam5 beat its
     live baseline with exactly this split);
  4. QA: rebuild_flags with the S5 merge-borderline rows (B4/A4b).

Everything lands in a WORKING DB first; `apply=True` swaps the camera's
events + bank into project.db atomically with a backup — the established
apply pattern. Gated by config.TWO_PASS_ENABLED (default OFF): the legacy
live pipeline path is untouched until the stage-3 gate + operator dry-run.

GT-free throughout (prime directive): raw video + operator calibration only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

_CELL_RE = re.compile(r"L(\d+)->L(\d+)")

from backend.config import (
    EVIDENCE_ACTIVATION_COVERAGE,
    EVIDENCE_ACTIVATION_ENABLED,
    ORIGIN_POSTERIOR_ENABLED,
)
from backend.database import get_connection, get_db_path
from backend.services.detection_cache import (
    compute_video_content_hash, parquet_path, resolve_content_hash)
from backend.services.flag_feeders import rebuild_flags
from backend.services.cardinals import bound_approach
from backend.services.pass2_replay import (
    JobCancelled, load_dump, replay_camera, tracks_dir,
)
from backend.services.turn_merge import merge_replay_turns, s5_flags

logger = logging.getLogger(__name__)

# Trim→window contract (stage 3.4 plan doc). A dump "satisfies" a derived
# window on coverage within this slack, not equality — a few-second trim edit
# (or the clamped-vs-unclamped start difference) must not orphan a multi-hour
# dump. Time-based, converted per camera fps (corridor cams are 10–25 fps).
WINDOW_SLACK_SECONDS = 5.0
# Legacy dumps (pre-"complete" marker) count as complete when the last dumped
# row is within this of the window end — cam3's gated study_0000 has a 118 s
# empty-midnight tail gap, so the tolerance must comfortably exceed that.
LEGACY_COMPLETE_TAIL_SECONDS = 300.0
# Every pass-1 resume restarts the tracker COLD, truncating tracks alive at
# the seam (the §2c edge-padding problem, at seams). Warm the tracker over
# this much preceding footage before the write boundary — long enough for a
# signal cycle + queue discharge. Time-based; converted per camera fps.
PASS1_SEAM_WARMUP_SECONDS = 90.0
# Detect-at-ingest writes the cache in closed per-chunk parquet parts so a
# crash resumes at chunk granularity instead of re-detecting hours.
PASS1_INGEST_CHUNK_SECONDS = 900.0


def _first_video(conn: sqlite3.Connection, camera_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM videos WHERE camera_id = ? ORDER BY sort_order LIMIT 1",
        (camera_id,)).fetchone()


def calib_fingerprint(project_id: str, camera_id: int) -> str:
    """Digest of every piece of OPERATOR state pass 2 consumes: calibration
    params, legs, the applied bank (attribution authority), and drawn channels
    (feed corpus-bank builds — standing rule 1 keeps them out of attribution).
    The pass-2 reuse sidecar keys on this + the dump meta, so a calibration
    edit invalidates a stale working DB (the stage-3.3 known limitation)."""
    from backend.database import get_camera_calibration_params
    calib = get_camera_calibration_params(project_id, camera_id)
    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    try:
        state = {"calib": calib}
        for name, table, order in (("legs", "legs", "leg_id"),
                                   ("paths", "intersection_paths", "path_id"),
                                   ("channels", "channels", "channel_id")):
            state[name] = [dict(r) for r in conn.execute(
                f"SELECT * FROM {table} WHERE camera_id = ? ORDER BY {order}",
                (camera_id,))]
    finally:
        conn.close()
    blob = json.dumps(state, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


def schema_fingerprint(project_id: str) -> str:
    """Digest of the vehicle_events schema pass 2 writes through (ordered
    PRAGMA column names). The reuse sidecar keys on this alongside the calib
    fingerprint: a working DB computed before a schema migration must be
    RECOMPUTED, never re-applied — _apply_window_events INSERT-SELECTs
    project.db's live column list against the attached working DB, so a
    pre-migration one dies with "no such column ..." (int2's Error card,
    blind product test 2026-07-31)."""
    conn = get_connection(project_id)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(vehicle_events)")]
    finally:
        conn.close()
    return hashlib.sha256(",".join(cols).encode()).hexdigest()


def flags_fingerprint() -> str:
    """Digest of the COUNTING FLAGS pass 2 obeys. The reuse sidecar keys
    on this alongside calib/schema: measured 2026-09-08, an apply with
    GATE_EVIDENCE_EITHER_CORNER newly on silently REUSED the working DB
    computed without it (same dump, same calibration) and re-applied the
    stale counts. A flag change must force a recompute, exactly as the
    pass-1 dump meta carries emergence_guard."""
    from backend import config as _c
    # SELF-MAINTAINING (2026-09-08): fingerprint EVERY module-level
    # boolean switch in backend.config rather than a hand-kept list.
    # The hand-kept version bit immediately — JOURNEY_FIRST_EXIT was
    # added and not listed, so an arm silently reused cached working
    # DBs and "measured" the old rule. Any future flag is covered
    # automatically; a spurious recompute is the safe failure.
    names = [n for n in dir(_c)
             if n.isupper() and isinstance(getattr(_c, n, None), bool)]
    flags = {n: bool(getattr(_c, n)) for n in sorted(names)}
    # 2026-09-09 (iteration 3): the law's frozen NUMBERS are part of
    # what pass 2 obeys too (GATE_EXTENSION_MARGIN, CORNER_PAIR_WINDOW_S
    # ...) — every module-level int/float constant is fingerprinted.
    nums = {n: getattr(_c, n) for n in dir(_c)
            if n.isupper() and type(getattr(_c, n, None)) in (int, float)}
    flags["__numeric__"] = {k: nums[k] for k in sorted(nums)}
    # BIT AGAIN 2026-09-09: G-SM-1 iteration 2 changed the crossing law
    # in entry_gates.py without moving any flag, and every arm "ran" in
    # 1 s on the iteration-1 working DBs. The law's SOURCE is part of
    # what pass 2 obeys, so its digest is part of the fingerprint. A
    # spurious recompute after an unrelated edit is the safe failure.
    law = Path(__file__).with_name("entry_gates.py").read_bytes()
    blob = json.dumps({"flags": flags,
                       "entry_gates_sha": hashlib.sha256(law).hexdigest()},
                      sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def sidecar_reusable(prior: dict, meta: dict, calib_fp: str,
                     schema_fp: str, flags_fp: str | None = None) -> bool:
    """One source of truth for 'this pass-2 sidecar still describes reality':
    same dump, same operator state, same vehicle_events schema, same
    counting flags. Legacy sidecars missing a key fail closed (recompute
    once, then carry it)."""
    return (prior.get("dump_meta") == meta
            and prior.get("calib_fingerprint") == calib_fp
            and prior.get("schema_fingerprint") == schema_fp
            and prior.get("flags_fingerprint")
            == (flags_fp if flags_fp is not None else flags_fingerprint()))


def _trim_datetimes(trim: dict, rec_start: datetime) -> tuple[datetime, datetime]:
    """Trim wallclock HH:MM:SS → datetimes on the recording's date. '24:00:00'
    and end-before-start both mean 'past midnight' (next day)."""
    date = rec_start.date().isoformat()

    def _parse(hms: str, *, bump_day: bool = False) -> datetime:
        if hms.startswith("24:"):
            dt = datetime.fromisoformat(f"{date}T00{hms[2:]}") + timedelta(days=1)
        else:
            dt = datetime.fromisoformat(f"{date}T{hms}")
        return dt + timedelta(days=1) if bump_day else dt

    t_start = _parse(trim["start_wallclock"])
    t_end = _parse(trim["end_wallclock"])
    if t_end <= t_start:
        t_end = _parse(trim["end_wallclock"], bump_day=True)
    return t_start, t_end


def derive_windows(project_id: str, intersection_id: int) -> list[dict]:
    """Map the card's trims to per-camera pass-1 dump windows — the naming
    contract the corridor dumps already follow, now written down:
      variant = 'study_' + trim start %H%M
      frames  = round((trim_wallclock − recording_start) × fps), UNCLAMPED
    (cam3's gated study_0000 starts at frame −20: a 00:00:00 trim against a
    00:00:02 recording start). Verified against all five corridor dump metas."""
    from backend.database import list_trims
    trims = list_trims(project_id, intersection_id)
    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    try:
        cams = conn.execute(
            "SELECT camera_id, label FROM cameras WHERE intersection_id = ? "
            "ORDER BY sort_order, camera_id", (intersection_id,)).fetchall()
        out: list[dict] = []
        for cam in cams:
            video = _first_video(conn, cam["camera_id"])
            if video is None:
                continue
            fps = float(video["fps"])
            rec_start = datetime.fromisoformat(video["recording_start_datetime"])
            for trim in trims:
                t_start, t_end = _trim_datetimes(trim, rec_start)
                out.append({
                    "camera_id": cam["camera_id"],
                    "camera_label": cam["label"],
                    "trim_id": trim["trim_id"],
                    "variant": f"study_{t_start.strftime('%H%M')}",
                    "start_frame": int(round((t_start - rec_start).total_seconds() * fps)),
                    "end_frame": int(round((t_end - rec_start).total_seconds() * fps)),
                    "start_wallclock": trim["start_wallclock"],
                    "end_wallclock": trim["end_wallclock"],
                    "fps": fps,
                })
        return out
    finally:
        conn.close()


def _camera_parquet(project_id: str, camera_id: int, variant: str) -> Path:
    from backend.services.detection_cache import HASH_METHOD
    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    try:
        video = _first_video(conn, camera_id)
    finally:
        conn.close()
    if video is None:
        raise ValueError(f"camera {camera_id}: no video row")
    # Prefer the persisted hash — plan_intersection runs on card open and a
    # fresh 128 MiB hash per camera per view would make the card feel stuck.
    if (video["content_hash"]
            and video["content_hash_method"] == HASH_METHOD):
        chash = video["content_hash"]
    else:
        chash, _ = compute_video_content_hash(
            video["path"], file_size_bytes=video["file_size_bytes"],
            total_frames=video["total_frames"])
    return parquet_path(project_id, camera_id, chash, variant)


def dump_status(pq: Path, start_frame: int, end_frame: int, fps: float) -> dict:
    """Classify a pass-1 dump against a derived window: ready | partial |
    missing | mismatch (coverage rule + completeness marker, plan doc §1)."""
    tdir = tracks_dir(pq)
    meta_p, count_p = tdir / "meta.json", tdir / "count.txt"
    if not (meta_p.exists() and count_p.exists() and (tdir / "rows.npy").exists()):
        return {"status": "missing"}
    meta = json.loads(meta_p.read_text())
    f_lo, f_hi = meta.get("frames", [None, None])
    slack = WINDOW_SLACK_SECONDS * fps
    if f_lo is None or f_lo > start_frame + slack or f_hi < end_frame - slack:
        return {"status": "mismatch", "frames": meta.get("frames")}
    if meta.get("complete"):
        return {"status": "ready", "frames": [f_lo, f_hi], "recipe": meta.get("backend")}
    # Legacy dump (pre-marker): complete iff the last dumped row is near the
    # window end. Empty-tail tolerance covers cam3's 118 s midnight gap.
    try:
        n = int(count_p.read_text())
        rows = np.load(tdir / "rows.npy", mmap_mode="r")
        last_frame = int(rows[n - 1, 1]) if n else f_lo
    except Exception:
        return {"status": "partial", "frames": [f_lo, f_hi]}
    if last_frame >= f_hi - LEGACY_COMPLETE_TAIL_SECONDS * fps:
        return {"status": "ready", "frames": [f_lo, f_hi], "recipe": meta.get("backend")}
    return {"status": "partial", "frames": [f_lo, f_hi], "last_frame": last_frame}


def plan_intersection(project_id: str, intersection_id: int,
                      workdir: str | Path) -> list[dict]:
    """The card's two-pass readiness view: each derived window + cache/dump/
    pass-2 status. pass2 'current' = a reuse sidecar that matches BOTH the
    dump meta and the live calibration fingerprint."""
    from backend.services.detection_cache import cache_exists
    workdir = Path(workdir)
    plan = derive_windows(project_id, intersection_id)
    fp_cache: dict[int, str] = {}
    schema_fp: str | None = None
    for w in plan:
        cid = w["camera_id"]
        try:
            pq = _camera_parquet(project_id, cid, w["variant"])
        except (ValueError, OSError):
            # no video row / video file unreadable — everything's missing
            w.update(cache="missing", dump={"status": "missing"}, pass2="missing")
            continue
        w["cache"] = "ready" if cache_exists(pq) else "missing"
        w["dump"] = dump_status(pq, w["start_frame"], w["end_frame"], w["fps"])
        stats_p = workdir / f"twopass_cam{cid}_{w['variant']}.stats.json"
        w["pass2"] = "missing"
        if stats_p.exists() and w["dump"]["status"] == "ready":
            try:
                prior = json.loads(stats_p.read_text())
                meta = json.loads((tracks_dir(pq) / "meta.json").read_text())
                if cid not in fp_cache:
                    fp_cache[cid] = calib_fingerprint(project_id, cid)
                if schema_fp is None:
                    schema_fp = schema_fingerprint(project_id)
                if sidecar_reusable(prior, meta, fp_cache[cid], schema_fp):
                    w["pass2"] = "current"
                else:
                    w["pass2"] = "stale"
                # Blind gate-evidence coverage from the last run's sidecar —
                # free here (the file is already open) and the ONLY place an
                # operator can see that a camera cannot produce gate evidence.
                # Below the bar, the evidence channel and the apply gate both
                # stand down; until now they did so silently (FM51 measured
                # 0.031 against 0.45, and nothing said so).
                w["evidence"] = (prior.get("result") or {}).get(
                    "evidence_activation")
            except Exception:
                w["pass2"] = "stale"
    return plan


def _dump_tracks_pointlists(rows: np.ndarray) -> list[list[tuple]]:
    """Group dump rows into per-track point lists (build_bank input shape)."""
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append((float(r[2]), float(r[3])))
    return list(tracks.values())


_ADDITIVE = ("branch1", "rescue_full", "rescue_supports")
_ADDITIVE_RANK = {"rescue_full": 0, "branch1": 1, "rescue_supports": 2}


def conserve_replay_additions(db: str | Path, camera_id: int,
                              chain_map: dict,
                              evidence: dict | None = None) -> dict:
    """The conservation pass (plan_conservation_pass_2026-07-15): at most one
    counted event per fragment CHAIN. Mixed-chain arbitration (legacy +
    additive): additive events (posterior_source branch1/rescue_*) always
    lose to legacy events by default; with config.CHAIN_ARBITRATION_EVIDENCE
    (C-1, plan_v2_c1_arbitration_2026-08-12) AND an evidence map from
    build_chain_map_ev ({tid: (origin_leg, dest_leg, tag)}), the chain keeps
    its best-evidenced event instead — ranked by agreement with the track's
    own gate crossings — and may reject a LEGACY event (reported as
    legacy_rejected). All-additive chains keep the proven _ADDITIVE_RANK path
    either way; legacy-only chains are never touched. Write-then-reject, the
    turn-merge pattern (rejected=1, non-destructive). Singleton/unmapped
    tracks are untouched. Returns counter stats."""
    from backend import config as _cfg
    ranked = (bool(getattr(_cfg, "CHAIN_ARBITRATION_EVIDENCE", False))
              and evidence is not None)
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT event_id, vehicle_track_id, posterior_source, "
        "COALESCE(classifier_num_points, 0), origin_leg_id, "
        "destination_leg_id FROM vehicle_events "
        "WHERE camera_id = ? AND COALESCE(rejected, 0) = 0",
        (camera_id,)).fetchall()
    groups: dict = {}
    for eid, tid, src, npts, o_leg, d_leg in rows:
        cid = chain_map.get(int(tid))
        if cid is None:
            continue
        groups.setdefault(cid, []).append((eid, src, npts, int(tid),
                                           o_leg, d_leg))

    def _ev_key(e):
        # C-1 rank, no new constants: class 0 = agrees with its track's gate
        # crossings on >=1 comparable component with no mismatch, 1 = nothing
        # comparable (vacuous agreement is NOT agreement), 2 = flip-suspect
        # (mismatches a comparable component — the D1-measured failure).
        # -matches subsumes tag strength (full track: both components
        # comparable; entry-only: one; blind: none). Components compare only
        # when BOTH the track evidence and the event column are non-NULL.
        o, d, _tag = evidence.get(e[3]) or (None, None, None)
        matches = mism = 0
        if o is not None and e[4] is not None:
            if e[4] == o:
                matches += 1
            else:
                mism += 1
        if d is not None and e[5] is not None:
            if e[5] == d:
                matches += 1
            else:
                mism += 1
        cls = 2 if mism else (0 if matches else 1)
        return (cls, -matches, -e[2], e[0])

    reject: list = []
    n_legacy_dupe = n_additive_dupe = n_legacy_rejected = 0
    for evs in groups.values():
        if len(evs) < 2:
            continue
        additive = [e for e in evs if e[1] in _ADDITIVE]
        if not additive:
            continue                      # legacy multi-counts pre-date us
        if len(additive) < len(evs):
            if ranked:
                # C-1: keep the chain's best-evidenced event, legacy or not
                evs_sorted = sorted(evs, key=_ev_key)
                keep_legacy = evs_sorted[0][1] not in _ADDITIVE
                for e in evs_sorted[1:]:
                    reject.append(e[0])
                    if e[1] in _ADDITIVE:
                        if keep_legacy:
                            n_legacy_dupe += 1
                        else:
                            n_additive_dupe += 1
                    else:
                        n_legacy_rejected += 1
            else:
                # the chain already has a legacy event: every additive one is
                # a duplicate of a counted vehicle
                reject += [e[0] for e in additive]
                n_legacy_dupe += len(additive)
        else:
            # all additive: keep the single best-evidenced (longest breaks
            # ties), reject the rest
            additive.sort(key=lambda e: (_ADDITIVE_RANK.get(e[1], 9),
                                         -e[2], e[0]))
            reject += [e[0] for e in additive[1:]]
            n_additive_dupe += len(additive) - 1
    with conn:
        conn.executemany(
            "UPDATE vehicle_events SET rejected = 1 WHERE event_id = ?",
            [(eid,) for eid in reject])
    conn.close()
    return {"chains_with_events": len(groups), "rejected": len(reject),
            "rejected_vs_legacy": n_legacy_dupe,
            "rejected_vs_additive": n_additive_dupe,
            "legacy_rejected": n_legacy_rejected}


def posterior_extras_enabled(activation: dict | None) -> bool:
    """Do the posterior EXTRAS — census_expecteds + conserve_pass — run?

    Block D1. Those two were retired as blind five-camera defaults per the
    two-iteration budget for ONE stated reason: not blind-deployable where
    evidence coverage is low (plan_conservation_pass_2026-07-15: "the
    mechanism family is REAL: cam2 9.1 -> 3.3-3.5% ... NOT blind-deployable
    where evidence coverage is low (36-60%)"). The ACTIVATION PRECONDITION is
    the decider for exactly that question, and it shipped 2026-07-27 — but it
    governs the REPLAY only, so the extras kept their own always-off flag and
    conserve_pass has never actually run in the campaign.

    CONSERVE_ON_ACTIVATION ON: the extras follow the per-window activation
    decision. OFF (default): this is exactly ORIGIN_POSTERIOR_ENABLED, so the
    shipped path is byte-identical. `activation` is None when
    EVIDENCE_ACTIVATION_ENABLED is off — then there is no decision to follow
    and the extras stay off unless the posterior flag forces them.
    """
    if ORIGIN_POSTERIOR_ENABLED:
        return True
    from backend import config as _cfg
    if not getattr(_cfg, "CONSERVE_ON_ACTIVATION", False):
        return False
    return bool(activation and activation.get("activated"))


def gate_axes_for(mouths: dict, tracks) -> dict | None:
    """Track-derived road axes for gate orientation, or None when the
    V2_GATE_AXIS flag is off (then build_gates keeps its channel-tangent
    behavior byte-identically). One place so every offline consumer —
    conserve_pass, census_expecteds, strict_full_census and the pass-2
    replay injection — derives gates the same way from the same dump."""
    from backend import config as _cfg
    if not getattr(_cfg, "V2_GATE_AXIS", False):
        return None
    from backend.services.entry_gates import derive_gate_axes
    return derive_gate_axes(mouths, tracks)


def _cfg_emergence_guard():
    from backend.config import EMERGENCE_GUARD
    return EMERGENCE_GUARD


def _cfg_fuse_score():
    from backend.config import TRACKER_FUSE_SCORE
    return TRACKER_FUSE_SCORE


def _cfg_position_recovery():
    from backend.config import TRACKER_POSITION_RECOVERY
    return TRACKER_POSITION_RECOVERY


def _cfg_recovery_min_iou():
    from backend.config import TRACKER_RECOVERY_MIN_IOU
    return TRACKER_RECOVERY_MIN_IOU


def _cfg_kf_vel_std():
    from backend import config as c
    return float(getattr(c, "TRACKER_KF_VEL_STD", 1.0 / 20))


def _cfg_recovery_guard():
    """The stage-2.5 guards as a recipe value (None when both are off)."""
    from backend import config as c
    held = float(getattr(c, "TRACKER_RECOVERY_HELD_IOU", 0.6))
    deg = float(getattr(c, "TRACKER_RECOVERY_REVERSE_DEG", 0.0))
    if held <= 0 and deg <= 0:
        return None
    return {"held_iou": held, "reverse_deg": deg,
            "reverse_jump": float(getattr(c, "TRACKER_RECOVERY_REVERSE_JUMP", 0.15))}


def _cfg_confirm_by_position():
    from backend.config import TRACKER_CONFIRM_BY_POSITION
    return TRACKER_CONFIRM_BY_POSITION


def _cfg_edge_exit():
    from backend.config import TRACKER_EDGE_EXIT
    return TRACKER_EDGE_EXIT


def _cfg_dup_box_iou():
    from backend.config import TRACKER_DUP_BOX_IOU
    return TRACKER_DUP_BOX_IOU


def _cfg_stack_iou():
    from backend.config import TRACKER_STACK_IOU
    return TRACKER_STACK_IOU


def _cfg_weak_birth():
    """The weak-box birth recipe (None when the stage is off)."""
    from backend import config as c
    if not (getattr(c, "TRACKER_POSITION_RECOVERY", False)
            and getattr(c, "TRACKER_WEAK_BIRTH", False)):
        return None
    return {"persist_s": float(c.TRACKER_WEAK_BIRTH_PERSIST_S),
            "gap_s": float(c.TRACKER_WEAK_BIRTH_GAP_S),
            "min_move": float(c.TRACKER_WEAK_BIRTH_MIN_MOVE),
            "max_cover": float(c.TRACKER_WEAK_BIRTH_MAX_COVER),
            "history_s": float(c.TRACKER_WEAK_BIRTH_HISTORY_S),
            "promote": bool(c.TRACKER_WEAK_BIRTH_PROMOTE)}


# Dump meta keys that define the pass-1 recipe: a resume whose existing dump
# differs on any of them is a hard error (delete the dump to start over).
PASS1_RESUME_KEYS = ("format", "frames", "backend", "nms_iou",
                     "activation", "match", "bbox_buffer",
                     "lost_buffer", "emergence_guard",
                     "fuse_score", "position_recovery", "recovery_min_iou",
                     "recovery_guard", "kf_vel_std", "confirm_by_position", "edge_exit",
                     "dup_box_iou", "stack_iou", "weak_birth")


def _tracks_from_rows(rows: np.ndarray) -> dict:
    """{track_id: [(frame, x, y), ...]} — the shape the gate/census helpers
    consume."""
    tracks: dict[int, list] = {}
    for r in rows:
        tracks.setdefault(int(r[0]), []).append(
            (float(r[1]), float(r[2]), float(r[3])))
    return tracks


def fracture_pass(project_id: str, camera_id: int, rows: np.ndarray,
                  fps: float, out_db: str | Path) -> dict:
    """THE FRACTURE RULE over a dump: pinned gates from the project
    geometry (the conserve_pass construction), then
    turn_merge.fracture_track_dedup."""
    from backend.database import (leg_geometry_for_camera,
                                  list_paths_for_camera)
    from backend.services.entry_gates import build_gates
    from backend.services.turn_merge import fracture_track_dedup
    geom = leg_geometry_for_camera(project_id, camera_id)
    mouths = {lid: g["mouth"] for lid, g in geom.items()}
    heads = {lid: g["heading"] for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}
    if not mouths:
        return {"skipped": "no leg mouths"}
    tracks = _tracks_from_rows(rows)
    gates = build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                        heads, leg_axes=gate_axes_for(mouths, tracks.values()),
                        leg_gates=drawn or None)
    if not gates:
        return {"skipped": "no gates"}
    return fracture_track_dedup(out_db, camera_id, rows, fps, gates)


def conserve_pass(project_id: str, camera_id: int, rows: np.ndarray,
                  fps: float, out_db: str | Path) -> dict:
    """Convenience wrapper for run_pass2 + the ablation harness: build the
    pinned gates + fragment-chain map from the dump, then conserve."""
    from backend.database import (leg_geometry_for_camera,
                                  list_paths_for_camera)
    from backend.services.entry_gates import build_gates
    from backend.services.track_chains import build_chain_map_ev
    geom = leg_geometry_for_camera(project_id, camera_id)
    mouths = {lid: g["mouth"] for lid, g in geom.items()}
    heads = {lid: g["heading"] for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}
    if not mouths:
        return {"skipped": "no leg mouths"}
    tracks = _tracks_from_rows(rows)
    gates = build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                        heads, leg_axes=gate_axes_for(mouths, tracks.values()),
                        leg_gates=drawn or None)
    if not gates:
        return {"skipped": "no gates"}
    chain_map, ev = build_chain_map_ev(tracks, gates, fps)
    return conserve_replay_additions(out_db, camera_id, chain_map, ev)


def census_expecteds(project_id: str, camera_id: int, rows: np.ndarray,
                     fps: float) -> dict:
    """Gate-evidence merge expecteds (posterior half stage 3,
    plan_posterior_half_2026-07-15): per-cell observed n from the dump's own
    entry/exit-gate crossings instead of the bank builder's flip-prone shape
    assignment. Gates = operator mouths + the APPLIED bank's tangents — the
    same pinned geometry the pipeline's evidence gate uses. Shared by
    run_pass2 and the ablation harness (one source of truth)."""
    from backend.database import (leg_geometry_for_camera,
                                  list_paths_for_camera)
    from backend.services.entry_gates import build_gates, cell_census
    geom = leg_geometry_for_camera(project_id, camera_id)
    mouths = {lid: g["mouth"] for lid, g in geom.items()}
    heads = {lid: g["heading"] for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}
    if not mouths:
        return {}
    tracks = _tracks_from_rows(rows)
    gates = build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                        heads, leg_axes=gate_axes_for(mouths, tracks.values()),
                        leg_gates=drawn or None)
    if not gates:
        return {}
    return cell_census(tracks.values(), gates, fps)


def strict_full_census(project_id: str, camera_id: int, rows: np.ndarray,
                       fps: float) -> dict:
    """FULL gate-to-gate journeys per cell (classify tag=='full') — the
    V2-demotion selector's census. cell_census's partial-evidence credits
    are too loose for flood detection (day-6b: cam2 28->29 loose census
    >=110 vs 54 strict fulls masked the 4.1x flood ratio)."""
    from backend.database import (leg_geometry_for_camera,
                                  list_paths_for_camera)
    from backend.services.entry_gates import build_gates, classify
    geom = leg_geometry_for_camera(project_id, camera_id)
    mouths = {lid: g["mouth"] for lid, g in geom.items()}
    heads = {lid: g["heading"] for lid, g in geom.items()}
    drawn = {lid: g["gate"] for lid, g in geom.items() if g["gate"]}
    if not mouths:
        return {}
    tracks = _tracks_from_rows(rows)
    gates = build_gates(mouths, list_paths_for_camera(project_id, camera_id),
                        heads, leg_axes=gate_axes_for(mouths, tracks.values()),
                        leg_gates=drawn or None)
    if not gates:
        return {}
    # channel families by origin, for the entanglement measure
    paths = list_paths_for_camera(project_id, camera_id)
    chans: dict[int, list] = {}
    for p in paths:
        if p.get("polyline"):
            chans.setdefault(int(p["origin_leg_id"]), []).append(p["polyline"])

    def _mean_dist(poly, pts):
        best = [float("inf")] * len(pts)
        for i in range(len(poly) - 1):
            ax, ay = poly[i]
            bx, by = poly[i + 1]
            vx, vy = bx - ax, by - ay
            L2 = vx * vx + vy * vy
            if L2 < 1e-9:
                continue
            for k, (px, py) in enumerate(pts):
                t = max(0.0, min(1.0, ((px - ax) * vx + (py - ay) * vy) / L2))
                d = ((px - (ax + t * vx)) ** 2 + (py - (ay + t * vy)) ** 2) ** 0.5
                if d < best[k]:
                    best[k] = d
        return sum(best) / len(best) if best else float("inf")

    out: dict[tuple, int] = {}
    conf_n: dict[int, int] = {}
    conf_r: dict[int, int] = {}
    full_by_tid: dict[int, tuple] = {}
    for tid, tr in tracks.items():
        o, d, _of, _df, _op, _dp, tag = classify(tr, gates, fps)
        if tag != "full":
            continue
        o, d = int(o), int(d)
        out[(o, d)] = out.get((o, d), 0) + 1
        full_by_tid[int(tid)] = (o, d, float(_of) if _of is not None else None)
        early = [(x, y) for _f, x, y in tr[:12]]
        d_own = min((_mean_dist(p, early) for p in chans.get(o, [])),
                    default=float("inf"))
        d_riv = min((_mean_dist(p, early) for ol, ps in chans.items()
                     if ol != o for p in ps), default=float("inf"))
        conf_n[o] = conf_n.get(o, 0) + 1
        if d_riv < d_own:
            conf_r[o] = conf_r.get(o, 0) + 1
    confusion = {o: conf_r.get(o, 0) / n for o, n in conf_n.items() if n}
    return out, confusion, full_by_tid



def _collapse_stop_fractures(arr, drawn, fps):
    """Counted-path C (operator mechanism 2026-08-27,
    docs/diag_waste_reel_2026-08-27.md): the red-light stop-fracture
    cycle — motion stops, track A goes lost, twin B births at the rest
    position, on green A re-activates and B dies; BOTH counted. The
    signature, every constant frozen (track_chains STITCH_STAT_*):

    - A has an intra-track gap [f1, f2] and was STOPPED at the loss
      (displacement over its last ~1 s < STITCH_STAT_SPEED_PXS px/s);
    - B's ENTIRE life sits strictly inside (f1, f2) — zero frame
      collision with A by construction;
    - B is pinned to the rest position at BOTH ends: birth within
      STITCH_STAT_DIST of A's last pre-gap point AND death within
      STITCH_STAT_DIST of A's first post-gap point. (One-end proximity
      is the ledgered CHAIN_GLUE caterpillar predicate — forbidden.
      Queue neighbors fail an end; the twin fails neither.)
    - Neither sub-chord (A_end -> B_birth, B_death -> A_resume) may
      cross a drawn gate (the A2 physical-crossing law).

    Collapse = B's rows re-stamped to A's tid: one track carries A's
    entry AND the journey's exit — the dup dies and the attribution
    heals in the same move. Operates IN PLACE; returns
    (n_collapsed, pairs)."""
    import math

    import numpy as np

    from backend.services.entry_gates import _seg_cross
    from backend.services.track_chains import (
        STITCH_STAT_DIST, STITCH_STAT_SPEED_PXS,
    )

    if not len(arr):
        return 0, []
    order = np.lexsort((arr[:, 1], arr[:, 0]))
    tids = arr[order, 0]
    frames = arr[order, 1]
    xs = arr[order, 2]
    ys = arr[order, 3]
    bnd = np.flatnonzero(np.diff(tids)) + 1
    starts = np.concatenate(([0], bnd))
    ends = np.concatenate((bnd, [len(tids)]))
    # per-track birth/death index for the candidate search
    info = {}
    for s0, s1 in zip(starts, ends):
        t = float(tids[s0])
        info[t] = (float(frames[s0]), float(frames[s1 - 1]),
                   (float(xs[s0]), float(ys[s0])),
                   (float(xs[s1 - 1]), float(ys[s1 - 1])), s1 - s0)
    cand = sorted(info.items(), key=lambda kv: kv[1][0])
    births = np.array([kv[1][0] for kv in cand])
    grace = 0.5 * fps
    consumed = set()
    n_col = 0
    pairs = []
    for s0, s1 in zip(starts, ends):
        a_tid = float(tids[s0])
        fr = frames[s0:s1]
        gaps = np.flatnonzero(np.diff(fr) > grace)
        for gi in gaps:
            f1, f2 = float(fr[gi]), float(fr[gi + 1])
            ax1, ay1 = float(xs[s0 + gi]), float(ys[s0 + gi])
            ax2, ay2 = float(xs[s0 + gi + 1]), float(ys[s0 + gi + 1])
            # stopped at loss: displacement over A's trailing ~1 s
            k = s0 + gi
            back = k
            while back > s0 and (frames[k] - frames[back - 1]) < fps:
                back -= 1
            if math.hypot(xs[k] - xs[back], ys[k] - ys[back])                     > STITCH_STAT_SPEED_PXS:
                continue
            lo = np.searchsorted(births, f1, side="right")
            best = None
            for bi in range(lo, len(cand)):
                b_tid, (bf0, bf1, bp0, bp1, n_pts) = cand[bi]
                if bf0 >= f2:
                    break
                if b_tid == a_tid or b_tid in consumed:
                    continue
                if not (bf0 > f1 and bf1 < f2):
                    continue
                if math.hypot(bp0[0] - ax1, bp0[1] - ay1) > STITCH_STAT_DIST:
                    continue
                if math.hypot(bp1[0] - ax2, bp1[1] - ay2) > STITCH_STAT_DIST:
                    continue
                if drawn and any(
                        _seg_cross(c1, c2, (g[0][0], g[0][1]),
                                   (g[1][0], g[1][1])) is not None
                        for c1, c2 in (((ax1, ay1), bp0), (bp1, (ax2, ay2)))
                        for g in drawn):
                    continue
                if best is None or n_pts > best[1]:
                    best = (b_tid, n_pts)
            if best is not None:
                b_tid = best[0]
                arr[:, 0][arr[:, 0] == b_tid] = a_tid
                consumed.add(b_tid)
                n_col += 1
                pairs.append([int(a_tid), int(b_tid), int(f1), int(f2)])
    return n_col, pairs


def _split_gate_straddles(arr, drawn, fps):
    """Amendment A2 (operator ruling 2026-08-24,
    docs/diag_lock_demo_review_2026-08-24.md): a join may not span a gate.
    A gate crossing that falls inside an UNOBSERVED stretch of a track is
    synthetic evidence — the same physical-crossing law the cutter carries
    (rev 6), enforced at the dump. Any intra-track gap longer than the
    re-association grace whose chord (last observed point -> first after)
    crosses a drawn gate segment is SPLIT: post-gap rows move to a fresh
    id. Joined tracks that classify full therefore have BOTH crossings
    observed; straddling joins become entry_only + exit_only partials,
    counted like today's fragments.

    Operates IN PLACE on arr (rows [tid, frame, ...]); returns n_split."""
    import numpy as np

    from backend.services.entry_gates import _seg_cross

    if not len(arr) or not drawn:
        return 0
    grace = 0.5 * fps
    order = np.lexsort((arr[:, 1], arr[:, 0]))
    tids = arr[order, 0].copy()
    frames = arr[order, 1].copy()
    xs = arr[order, 2].copy()
    ys = arr[order, 3].copy()
    next_id = float(np.max(arr[:, 0])) + 1.0
    n_split = 0
    bnd = np.flatnonzero(np.diff(tids)) + 1
    starts = np.concatenate(([0], bnd))
    ends = np.concatenate((bnd, [len(tids)]))
    for s0, s1 in zip(starts, ends):
        fr = frames[s0:s1]
        gaps = np.flatnonzero(np.diff(fr) > grace)
        if not len(gaps):
            continue
        tid = tids[s0]
        for gi in gaps:
            a = (float(xs[s0 + gi]), float(ys[s0 + gi]))
            b = (float(xs[s0 + gi + 1]), float(ys[s0 + gi + 1]))
            if any(_seg_cross(a, b, (g[0][0], g[0][1]), (g[1][0], g[1][1]))
                   is not None for g in drawn):
                f_split = float(fr[gi + 1])
                sel = (arr[:, 0] == tid) & (arr[:, 1] >= f_split)
                arr[:, 0][sel] = next_id
                tid = next_id          # later gaps belong to the new id
                next_id += 1.0
                n_split += 1
    return n_split


# ---- weak-box birth back-fill (2026-09-12) --------------------------------
# The recovery tracker emits BACK-FILL rows: past-frame observations of a
# track born from a car's weak boxes. They cannot go into rows.npy mid-run
# (resume assumes a frame-ordered tail), so they collect in a sidecar saved
# just before every count.txt write, and join the dump at the end of the run.
BACKFILL_FILE = "backfill.npy"      # (K, 9) float64: the 8 dump columns + promoted_at


def _save_backfill(out: Path, rows: list) -> None:
    import os
    arr = np.asarray(rows, dtype=np.float64).reshape(-1, 9)
    tmp = out / "backfill.tmp.npy"
    np.save(tmp, arr)
    os.replace(tmp, out / BACKFILL_FILE)


def _load_backfill(out: Path, resume_from: int) -> list:
    """Sidecar rows of tracks promoted BEFORE the resume frame (the rest are
    produced again by the resumed run)."""
    p = out / BACKFILL_FILE
    if not p.exists():
        return []
    arr = np.load(p).reshape(-1, 9)
    return [tuple(r) for r in arr[arr[:, 8] < float(resume_from)].tolist()]


def _reset_backfill(out: Path) -> None:
    for name in (BACKFILL_FILE, "backfill.tmp.npy", "rows_ordered.tmp.npy"):
        (out / name).unlink(missing_ok=True)


def _resume_count(out: Path, old_meta: dict | None) -> int:
    """count.txt, clamped to the main rows when a back-fill merge had begun
    (rows past it are a partly written tail). The clamp is written back at
    once: the start-of-run meta write erases the marker."""
    w = int((out / "count.txt").read_text())
    mk = (old_meta or {}).get("backfill_merge")
    if mk and "main_rows" in mk and w > int(mk["main_rows"]):
        w = int(mk["main_rows"])
        (out / "count.txt").write_text(str(w))
    return w


def _backfill_keep_mask(main: np.ndarray, bf: np.ndarray) -> np.ndarray:
    """Keep back-fill rows whose (id, frame) the main rows do NOT have, and
    the first of any duplicates within the back-fill: pass 2 must never see
    two rows for one (id, frame)."""
    if len(bf) == 0:
        return np.zeros(0, dtype=bool)
    bk = bf[:, 0].astype(np.int64) * 10_000_000 + bf[:, 1].astype(np.int64)
    keep = np.ones(len(bf), dtype=bool)
    if len(main):
        mk = main[:, 0].astype(np.int64) * 10_000_000 + main[:, 1].astype(np.int64)
        keep &= ~np.isin(bk, mk)
    _, first = np.unique(bk, return_index=True)
    uniq = np.zeros(len(bf), dtype=bool)
    uniq[first] = True
    return keep & uniq


def _append_backfill_tail(out: Path, meta: dict, state: dict, grow_rows) -> int:
    """Append the (deduplicated, frame-sorted) back-fill after the main rows.
    The marker goes to meta.json FIRST, so a crash mid-append resumes clamped
    to the main rows."""
    bf = np.asarray(state.get("bf") or [], dtype=np.float64).reshape(-1, 9)
    w = int(state["w"])
    if len(bf) == 0:
        meta["backfill_rows"] = 0
        meta["backfill_dup_dropped"] = 0
        return 0
    keep = _backfill_keep_mask(np.asarray(state["mm"][:w]), bf)
    dup = int((~keep).sum())
    bf = bf[keep]
    bf = bf[np.argsort(bf[:, 1], kind="stable")]
    k = len(bf)
    meta["backfill_merge"] = {"main_rows": w, "rows": int(k)}
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    if k:
        grow_rows(k)
        state["mm"][w:w + k] = bf[:, :8].astype(np.float32)
        state["w"] = w + k
    meta["backfill_rows"] = int(k)
    meta["backfill_dup_dropped"] = dup
    return k


def _frame_order_rewrite(out: Path, n: int) -> bool:
    """Rewrite rows.npy (its first n rows) in frame order, main rows before
    back-fill within a frame (stable). Runs after the dump is marked complete;
    on failure the tail layout stays, which load_dump re-sorts."""
    import os
    from numpy.lib.format import open_memmap
    try:
        rows = np.array(np.load(out / "rows.npy", mmap_mode="r")[:n])
        order = np.argsort(rows[:, 1], kind="stable")
        tmp = out / "rows_ordered.tmp.npy"
        mm = open_memmap(tmp, mode="w+", dtype=np.float32, shape=(max(n, 1), 8))
        if n:
            mm[:n] = rows[order]
        mm.flush()
        del mm
        os.replace(tmp, out / "rows.npy")
        return True
    except OSError:
        (out / "rows_ordered.tmp.npy").unlink(missing_ok=True)
        return False


def _floor_bytetrack_ids(out: Path) -> None:
    """On resume the tracker is new but supervision's id counter is process-
    global: floor it at the dump's (and sidecar's) max id so a resumed run
    never reuses an id — reuse plus back-fill would give two rows for one
    (id, frame)."""
    try:
        from supervision.tracker.byte_tracker.basetrack import BaseTrack
        n = int((out / "count.txt").read_text()) if (out / "count.txt").exists() else 0
        mx = 0
        if n and (out / "rows.npy").exists():
            mx = int(np.load(out / "rows.npy", mmap_mode="r")[:n, 0].max())
        if (out / BACKFILL_FILE).exists():
            a = np.load(out / BACKFILL_FILE).reshape(-1, 9)
            if len(a):
                mx = max(mx, int(a[:, 0].max()))
        if BaseTrack._count < mx:
            BaseTrack._count = mx
    except Exception:
        pass


def run_pass1(project_id: str, camera_id: int, *, variant: str,
              start_frame: int, end_frame: int, backend: str | None = None,
              resume: bool = True, progress=None, should_cancel=None) -> dict:
    """Pass 1: raw-track dump for one camera window — the productized core of
    scripts/dump_raw_tracks.py (the CLI wraps this). Semantics-free: no legs,
    channels, or classification; live-parity tracking input (per-camera
    pre-track NMS -> bbox buffer -> tracker, full frame schedule incl. empty
    updates — the A2 tier-1 lessons).

    Detection source (stage 3.4): the variant's detection cache when it
    exists; otherwise DETECT-AT-INGEST — decode the window once, detect with
    the project's processing-mode config, write-through the cache in closed
    ~15-min parquet chunks (crash-resumable; a ParquetWriter file without its
    footer is unreadable), and merge to the variant parquet at completion.
    First run = detect+cache+dump; re-runs = pass 2 only.

    backend: None -> the camera's calib_pass1_backend (default bytetrack).
    'botsort+reid' loads the pre-built ReID sidecar (build_reid_cache);
    missing sidecar is an actionable error, not an implicit hours-long build.
    resume: continue from the high-water mark when the existing dump's recipe
    matches (recipe mismatch = hard error). Every resume warms the tracker
    over the preceding ~PASS1_SEAM_WARMUP_SECONDS so the seam doesn't
    truncate tracks mid-intersection (the §2c edge-padding problem, at seams;
    ID reuse across the seam is handled downstream by the finalize-gap)."""
    import numpy as _np
    from numpy.lib.format import open_memmap

    from backend.config import PRE_TRACK_NMS_IOU
    from backend.database import get_camera_calibration_params
    from backend.services.detection_cache import cache_exists
    from backend.services.pipeline import _class_agnostic_nms
    from backend.services.tracker import create_tracker_backend

    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    video = conn.execute(
        "SELECT * FROM videos WHERE camera_id = ? ORDER BY sort_order LIMIT 1",
        (camera_id,)).fetchone()
    conn.close()
    if video is None:
        raise ValueError(f"camera {camera_id}: no video row")
    fps = float(video["fps"])
    chash, hash_method = compute_video_content_hash(
        video["path"], file_size_bytes=video["file_size_bytes"],
        total_frames=video["total_frames"])
    pq = parquet_path(project_id, camera_id, chash, variant)
    out = tracks_dir(pq)

    calib = get_camera_calibration_params(project_id, camera_id)
    recipe = (backend or calib.get("pass1_backend") or "bytetrack").lower()
    with_reid = recipe.endswith("+reid")
    tracker_backend = recipe.replace("+reid", "")
    activation = float(calib.get("tracker_activation_threshold") or 0.25)
    match = float(calib.get("tracker_match_threshold") or 0.8)
    buf = float(calib.get("bbox_buffer_scale") or 1.0)
    nms_iou = calib.get("pre_track_nms_iou")
    if nms_iou is None:
        nms_iou = PRE_TRACK_NMS_IOU
    ntt = calib.get("new_track_thresh")
    # Stage-4a hygiene (2026-08-24): the lost buffer was honored live
    # (pipeline.py tracker property) but silently ignored here — every
    # dump ever built ran at the library default. Pass it through, record
    # it, and guard it in the resume-drift check.
    lb = calib.get("tracker_lost_buffer")
    tracker_kwargs: dict = {}
    if lb is not None:
        tracker_kwargs["lost_track_buffer"] = int(lb)
    if ntt is not None and tracker_backend == "botsort":
        tracker_kwargs["new_track_thresh"] = float(ntt)
    if tracker_backend == "bytetrack" and video["width"] and video["height"]:
        tracker_kwargs["frame_size"] = (int(video["width"]), int(video["height"]))
    if tracker_backend == "bytetrack":
        tracker_kwargs["collect_backfill"] = True
    if with_reid:
        side = pq.with_name(pq.stem + ".reid")
        if not side.exists():
            side_npz = pq.with_name(pq.stem + ".reid.npz")
            if side_npz.exists():
                side = side_npz
            else:
                raise FileNotFoundError(
                    f"recipe '{recipe}' needs the ReID sidecar at {side} — "
                    f"build it first: py scripts/build_reid_cache.py "
                    f"--camera {camera_id} --variant {variant}")
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "scripts"))
        from reid_embedding_cache import ReidEmbeddingCache
        tracker_kwargs["with_reid"] = True
        tracker_kwargs["reid_embeddings"] = ReidEmbeddingCache(side)
    be = create_tracker_backend(
        tracker_backend, track_activation_threshold=activation,
        minimum_matching_threshold=match, frame_rate=int(fps), **tracker_kwargs)

    meta = {
        "format": 2,
        "cols": ["track_id", "frame", "cx", "cy", "bw", "bh", "conf", "class_id"],
        "backend": recipe, "camera": camera_id, "variant": variant,
        "frames": [start_frame, end_frame],
        "nms_iou": nms_iou, "new_track_thresh": ntt,
        "activation": activation, "match": match, "bbox_buffer": buf,
        "lost_buffer": (int(lb) if lb is not None else None),
        "emergence_guard": bool(_cfg_emergence_guard()),
        "fuse_score": bool(_cfg_fuse_score()),
        "position_recovery": bool(_cfg_position_recovery()),
        "recovery_min_iou": (float(_cfg_recovery_min_iou()) if _cfg_position_recovery() else None),
        "recovery_guard": (_cfg_recovery_guard() if _cfg_position_recovery() else None),
        "kf_vel_std": (float(_cfg_kf_vel_std()) if tracker_backend == "bytetrack" else None),
        "confirm_by_position": (bool(_cfg_confirm_by_position()) if _cfg_position_recovery() else None),
        "edge_exit": (bool(_cfg_edge_exit()) if _cfg_position_recovery() else None),
        "dup_box_iou": (float(_cfg_dup_box_iou()) if _cfg_position_recovery() else None),
        "stack_iou": (float(_cfg_stack_iou()) if _cfg_position_recovery() else None),
        "weak_birth": (_cfg_weak_birth() if tracker_backend == "bytetrack" else None),
    }
    out.mkdir(parents=True, exist_ok=True)
    warm_frames = int(PASS1_SEAM_WARMUP_SECONDS * fps)

    def _check_resume_meta():
        old_meta = json.loads((out / "meta.json").read_text())
        mismatches = [k for k in PASS1_RESUME_KEYS
                      if old_meta.get(k) != meta.get(k)]
        if mismatches:
            raise ValueError(
                f"pass-1 resume: existing dump differs on {mismatches} — "
                f"delete {out} to start over")
        return old_meta

    # A COMPLETE dump is not re-stepped on resume (it may already carry a
    # merged back-fill tail; re-stepping its last frame would mint new ids).
    if resume and (out / "meta.json").exists() and (out / "count.txt").exists():
        try:
            _old = json.loads((out / "meta.json").read_text())
        except (OSError, ValueError):
            _old = {}
        if _old.get("complete"):
            _check_resume_meta()
            return {"camera_id": camera_id, "variant": variant, "recipe": recipe,
                    "rows": int((out / "count.txt").read_text()),
                    "frames": [start_frame, end_frame], "tracks_dir": str(out),
                    "status": "complete"}
    if resume and tracker_backend == "bytetrack":
        _floor_bytetrack_ids(out)

    # Shared per-frame step: NMS -> bbox buffer -> tracker -> dump rows.
    # write=False = warm-up (tracker state only, nothing persisted).
    pop_bf = getattr(be, "pop_backfill", None)
    state = {"mm": None, "w": 0, "bf": [], "bf_on": pop_bf is not None}

    def _grow_rows(extra: int) -> None:
        """rows.npy capacity is an estimate; grow by copy when it falls short
        (the ingest path has no detection count to estimate from)."""
        import os
        mm = state["mm"]
        if state["w"] + extra <= mm.shape[0]:
            return
        new_cap = max(mm.shape[0] * 2, state["w"] + extra + 1000)
        mm.flush(); del mm
        state["mm"] = None
        tmp = out / "rows_grow.npy"
        new = open_memmap(tmp, mode="w+", dtype=_np.float32, shape=(new_cap, 8))
        old = open_memmap(out / "rows.npy", mode="r")
        new[:state["w"]] = old[:state["w"]]
        del old
        new.flush(); del new
        os.replace(tmp, out / "rows.npy")
        state["mm"] = open_memmap(out / "rows.npy", mode="r+")

    def _step(fidx: int, dets: list, write: bool = True) -> None:
        if nms_iou is not None and len(dets) > 1:
            dets = _class_agnostic_nms(dets, float(nms_iou))
        if buf != 1.0 and dets:
            inflated = []
            for d in dets:
                x1, y1, x2, y2 = d["bbox"]
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                hw, hh = (x2 - x1) * buf / 2, (y2 - y1) * buf / 2
                d = dict(d); d["bbox"] = [cx - hw, cy - hh, cx + hw, cy + hh]
                inflated.append(d)
            dets = inflated
        tracks = be.update(dets, fidx)
        bf_rows = pop_bf() if pop_bf is not None else []
        if not write:
            return          # warm-up: the run that wrote these frames kept their back-fill
        _grow_rows(len(tracks))
        mm = state["mm"]
        for t in tracks:
            cx, cy = t["center"]
            mm[state["w"]] = (
                float(t["track_id"]), float(fidx), float(cx), float(cy),
                float(t.get("bbox_width", 0.0)), float(t.get("bbox_height", 0.0)),
                float(t.get("confidence", 0.0)), float(t.get("class_id", -1)))
            state["w"] += 1
        for r in bf_rows:
            bx, by = r["center"]
            state["bf"].append((float(r["track_id"]), float(r["frame"]), float(bx), float(by),
                                float(r["bbox_width"]), float(r["bbox_height"]),
                                float(r["confidence"]), float(r["class_id"]),
                                float(r["promoted_at"])))

    if cache_exists(pq):
        _pass1_from_cache(
            pq, out, meta, start_frame, end_frame, warm_frames, resume,
            progress, state, _step, _check_resume_meta, open_memmap, _np,
            should_cancel)
    else:
        _pass1_ingest(
            project_id, video, chash, hash_method, pq, out, meta, fps,
            start_frame, end_frame, warm_frames, resume, progress, state,
            _step, _check_resume_meta, open_memmap, _np, should_cancel)

    fin = getattr(be, "finalize", None)
    if fin is not None:
        fin()          # end-of-run flip flush: late thefts still re-stamp
    # Gate-break re-stamp (Stage 4b): each probation break recorded
    # (old_id, new_id, resume_frame) — rows the thief contaminated between
    # re-acquisition and judgment move to the thief's id, so the old track
    # ends at its loss. Must run before the final flush.
    breaks = getattr(getattr(be, "bot", None), "gate_breaks", None)
    if breaks and state["mm"] is not None:
        mm = state["mm"]
        w = state["w"]
        n_moved = 0
        for old_id, new_id, resume_f in breaks:
            sel = (mm[:w, 0] == float(old_id)) & (mm[:w, 1] >= float(resume_f))
            n_moved += int(sel.sum())
            mm[:w, 0][sel] = float(new_id)
        meta["gate_breaks"] = len(breaks)
        meta["gate_break_rows_moved"] = n_moved
        (out / "gate_breaks.json").write_text(json.dumps(breaks))
    ev = getattr(getattr(be, "bot", None), "emergence_vetoes", None)
    if ev is not None:
        meta["emergence_vetoes"] = int(ev)
    # Weak-box birth back-fill joins the dump BEFORE the stop-fracture
    # collapse (which must relabel back-filled rows too, and judge a
    # fragment's true first frame).
    if state.get("bf_on") and state["mm"] is not None:
        _save_backfill(out, state["bf"])
        _append_backfill_tail(out, meta, state, _grow_rows)
        bt = getattr(be, "byte_track", None)
        meta["weak_births"] = int(getattr(bt, "n_weak_births", 0))
        meta["weak_inherited"] = int(getattr(bt, "n_weak_inherited", 0))
    # Counted-path C (flag-gated, default off): collapse red-light
    # stop-fracture twin pairs before anything reads the dump.
    from backend.config import STOP_FRACTURE_COLLAPSE
    if STOP_FRACTURE_COLLAPSE and state["mm"] is not None:
        try:
            from backend.database import leg_geometry_for_camera as _lgc
            _drawn = [g["gate"] for g in
                      _lgc(project_id, camera_id).values() if g.get("gate")]
        except Exception:
            _drawn = []
        n_col, sf_pairs = _collapse_stop_fractures(
            state["mm"][:state["w"]], _drawn, fps)
        meta["stop_fracture_collapsed"] = n_col
        if sf_pairs:
            (out / "stop_fracture_pairs.json").write_text(
                json.dumps(sf_pairs))
    # Amendment A2: locked-recipe dumps only (applying it to the stock
    # recipe would silently change the production basis).
    if tracker_backend == "botsort_locked" and state["mm"] is not None:
        try:
            from backend.database import leg_geometry_for_camera
            drawn = [g["gate"] for g in
                     leg_geometry_for_camera(project_id, camera_id).values()
                     if g.get("gate")]
        except Exception:
            drawn = []
        if drawn:
            n_split = _split_gate_straddles(
                state["mm"][:state["w"]], drawn, fps)
            if n_split:
                meta["gate_straddle_splits"] = n_split
    mm = state["mm"]
    mm.flush(); del mm
    state["mm"] = None
    (out / "count.txt").write_text(str(state["w"]))
    # Positive completeness marker (plan doc §1): nothing else distinguishes a
    # finished dump from an interrupted one (count.txt updates mid-run). The
    # start-of-run meta write deliberately omits it, so a resumed dump reads
    # incomplete until this line runs.
    meta["complete"] = True
    (out / "meta.json").write_text(json.dumps(meta, indent=2))
    if meta.get("backfill_rows"):
        meta["frame_ordered"] = _frame_order_rewrite(out, state["w"])
        (out / "meta.json").write_text(json.dumps(meta, indent=2))
    return {"camera_id": camera_id, "variant": variant, "recipe": recipe,
            "rows": state["w"], "frames": [start_frame, end_frame],
            "tracks_dir": str(out)}


def _pass1_from_cache(pq, out, meta, start_frame, end_frame, warm_frames,
                      resume, progress, state, step, check_resume_meta,
                      open_memmap, _np, should_cancel=None) -> None:
    """Pass-1 tracking over an existing detection-cache parquet (the original
    stage-3.3 path, plus the resume seam warm-up)."""
    from backend.services.detection_cache import DetectionCacheReader

    reader = DetectionCacheReader(pq)
    n_dets = sum(len(d) for f, d in reader.iter_frames()
                 if start_frame <= f < end_frame)
    cap_rows = int(n_dets * 1.2) + 1000

    resume_from = start_frame
    if resume and (out / "rows.npy").exists() and (out / "count.txt").exists():
        old_meta = check_resume_meta()
        mm = open_memmap(out / "rows.npy", mode="r+")
        w0 = _resume_count(out, old_meta)
        if w0 > 0:
            f_last = int(mm[w0 - 1, 1])
            w = w0
            while w > 0 and int(mm[w - 1, 1]) == f_last:
                w -= 1
            state["w"] = w
            resume_from = f_last
        state["mm"] = mm
        state["bf"] = _load_backfill(out, resume_from)
    if state["mm"] is None:
        _reset_backfill(out)
        state["mm"] = open_memmap(out / "rows.npy", mode="w+",
                                  dtype=_np.float32, shape=(cap_rows, 8))
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    # Warm the tracker over the seam so resumed tracks aren't born cold at
    # the boundary (rows before resume_from are already in the dump).
    loop_start = resume_from
    if resume_from > start_frame:
        loop_start = max(start_frame, resume_from - warm_frames)

    reader_iter = DetectionCacheReader(pq).iter_frames()
    nxt = next(reader_iter, None)
    done = 0
    for fidx in range(loop_start, end_frame):
        if should_cancel is not None and should_cancel():
            # flush so the resume high-water mark reflects everything written
            state["mm"].flush()
            if state.get("bf_on"):
                _save_backfill(out, state["bf"])     # never behind count.txt
            (out / "count.txt").write_text(str(state["w"]))
            raise JobCancelled(f"pass-1 cancelled at frame {fidx} (resumable)")
        while nxt is not None and nxt[0] < fidx:
            nxt = next(reader_iter, None)
        if nxt is not None and nxt[0] == fidx:
            dets = nxt[1]
            nxt = next(reader_iter, None)
        else:
            dets = []
        step(fidx, dets, write=(fidx >= resume_from))
        done += 1
        if done % 5000 == 0:
            state["mm"].flush()
            if state.get("bf_on"):
                _save_backfill(out, state["bf"])     # never behind count.txt
            (out / "count.txt").write_text(str(state["w"]))
            if progress:
                progress(done, end_frame - loop_start, state["w"])


def _pass1_ingest(project_id, video, chash, hash_method, pq, out, meta, fps,
                  start_frame, end_frame, warm_frames, resume, progress,
                  state, step, check_resume_meta, open_memmap, _np,
                  should_cancel=None) -> None:
    """Detect-at-ingest: no cache for this variant — decode the window ONCE,
    detect with the project's processing-mode config, write-through the cache
    in closed per-chunk parquet parts (resume at chunk granularity; a crashed
    ParquetWriter file has no footer and is unreadable), track+dump in the
    same pass, merge parts -> the variant parquet at completion."""
    import cv2

    from backend.config import DEFAULT_PROCESSING_MODE, get_processing_mode_config
    from backend.database import get_project_info
    from backend.services.detection_cache import (
        DetectionCacheReader, DetectionCacheWriter)

    mode_name = (get_project_info(project_id, "processing_mode")
                 or DEFAULT_PROCESSING_MODE)
    cfg = get_processing_mode_config(mode_name)
    skip = int(cfg.get("detection_skip") or 1)
    chunk_frames = max(1, int(PASS1_INGEST_CHUNK_SECONDS * fps))
    n_chunks = max(1, -(-(end_frame - start_frame) // chunk_frames))

    def part_path(k: int) -> Path:
        return pq.with_name(f"{pq.stem}.part{k:05d}.parquet")

    # Resume point = the first chunk whose part is missing or unreadable.
    k0 = 0
    for k in range(n_chunks):
        p = part_path(k)
        if not p.exists():
            break
        try:
            DetectionCacheReader(p)
        except Exception:
            break
        k0 = k + 1
    resume_from = start_frame + k0 * chunk_frames
    if (k0 and resume and (out / "rows.npy").exists()
            and (out / "count.txt").exists()):
        old_meta = check_resume_meta()
        mm = open_memmap(out / "rows.npy", mode="r+")
        # Truncate to rows strictly before the resume chunk: count.txt is
        # written after the part closes, so a crash between the two leaves
        # either stale count (no-op here) or rows past the last closed part
        # (dropped here) — both orders reconverge.
        w = _resume_count(out, old_meta)
        while w > 0 and int(mm[w - 1, 1]) >= resume_from:
            w -= 1
        state["mm"], state["w"] = mm, w
        state["bf"] = _load_backfill(out, resume_from)
    else:
        k0 = 0
        resume_from = start_frame
        _reset_backfill(out)
        for k in range(n_chunks):
            part_path(k).unlink(missing_ok=True)
        cap_rows = (end_frame - start_frame) * 8 + 1000
        state["mm"] = open_memmap(out / "rows.npy", mode="w+",
                                  dtype=_np.float32, shape=(cap_rows, 8))
        state["w"] = 0
    (out / "meta.json").write_text(json.dumps(meta, indent=2))

    # Seam warm-up from the tail of the last closed part.
    if k0 > 0:
        warm_from = max(start_frame, resume_from - warm_frames)
        rd = DetectionCacheReader(part_path(k0 - 1)).iter_frames()
        nxt = next(rd, None)
        for fidx in range(warm_from, resume_from):
            while nxt is not None and nxt[0] < fidx:
                nxt = next(rd, None)
            if nxt is not None and nxt[0] == fidx:
                dets = nxt[1]
                nxt = next(rd, None)
            else:
                dets = []
            step(fidx, dets, write=False)

    from backend.services.detector import VehicleDetector
    detector = VehicleDetector(model_path=cfg["yolo_model"],
                               imgsz=cfg["yolo_imgsz"],
                               confidence=cfg["yolo_confidence"],
                               class_scheme=cfg.get("yolo_class_scheme",
                                                    "coco"))
    cap = cv2.VideoCapture(video["path"])
    try:
        decode_from = max(0, resume_from)
        if decode_from:
            cap.set(cv2.CAP_PROP_POS_FRAMES, decode_from)
        done, total = 0, end_frame - resume_from
        for k in range(k0, n_chunks):
            c_lo = start_frame + k * chunk_frames
            c_hi = min(end_frame, c_lo + chunk_frames)
            writer = DetectionCacheWriter(pq_path=part_path(k), metadata={})
            for fidx in range(c_lo, c_hi):
                if should_cancel is not None and should_cancel():
                    # mid-chunk cancel = the crash-resume path: the open part
                    # has no footer, so resume re-enters at this chunk's start
                    raise JobCancelled(
                        f"pass-1 ingest cancelled in chunk {k} (resumable)")
                dets = []
                if fidx >= 0:                      # pre-recording frames (cam3
                    ok, frame = cap.read()         # -20 case) don't exist
                    if ok and fidx % skip == 0:
                        dets = detector.detect(frame)
                        writer.add(fidx, dets)     # cache stays raw, pre-NMS
                step(fidx, dets)
                done += 1
                if progress and done % 200 == 0:
                    progress(done, total, state["w"])
            state["mm"].flush()
            if state.get("bf_on"):
                _save_backfill(out, state["bf"])     # never behind count.txt
            (out / "count.txt").write_text(str(state["w"]))
            writer.close()
    finally:
        cap.release()

    # Merge closed parts -> the variant parquet + provenance sidecar (the
    # same shape the live pipeline's write-through produces, plus windows).
    merged = DetectionCacheWriter(pq_path=pq, metadata={
        "camera_id": int(video["camera_id"]), "content_hash": chash,
        "method": hash_method, "model": cfg["yolo_model"],
        "imgsz": cfg["yolo_imgsz"], "confidence": cfg["yolo_confidence"],
        "detection_skip": skip,
        "windows": [[start_frame, end_frame]]})
    for k in range(n_chunks):
        for fidx, dets in DetectionCacheReader(part_path(k)).iter_frames():
            merged.add(fidx, dets)
    merged.close()
    for k in range(n_chunks):
        p = part_path(k)
        p.unlink(missing_ok=True)
        p.with_suffix(".meta.json").unlink(missing_ok=True)


def _apply_window_events(proj_db: Path, out_db: Path, camera_id: int,
                         t_lo: float, t_hi: float) -> None:
    """Swap ONE trim window's events into project.db, scoped by the event's
    crossing timestamp (the two-pass binning convention) — applying a study
    day's three windows must not wipe each other. The applied bank is never
    touched here."""
    c = sqlite3.connect(proj_db)
    cols = [r[1] for r in c.execute("PRAGMA table_info(vehicle_events)")
            if r[1] != "event_id"]
    collist = ",".join(cols)
    with c:
        c.execute("ATTACH DATABASE ? AS w", (str(out_db),))
        c.execute("DELETE FROM vehicle_events WHERE camera_id = ? AND "
                  "timestamp_video >= ? AND timestamp_video < ?",
                  (camera_id, t_lo, t_hi))
        c.execute(f"INSERT INTO vehicle_events ({collist}) "
                  f"SELECT {collist} FROM w.vehicle_events WHERE camera_id = ? "
                  f"AND timestamp_video >= ? AND timestamp_video < ?",
                  (camera_id, t_lo, t_hi))
    c.execute("DETACH DATABASE w")
    c.close()


def run_pass2(project_id: str, camera_id: int, *, variant: str,
              workdir: str | Path, apply: bool = False,
              should_cancel=None) -> dict:
    """Pass 2 for one camera from its pass-1 dump. Returns stats incl. the
    working DB path; apply=True additionally swaps events+bank into project.db
    (backup first) and rebuilds the intersection's flag queue with S5 rows.

    should_cancel: polled at stage boundaries and inside the replay frame
    loop (JobCancelled). The corpus-bank build is not interruptible (scripts
    function), and _finish_apply never is — apply stays atomic."""
    # scripts/ is on the path for build_bank_gtfree (Phase-2 productized entry
    # point that still lives there; the CLI and this service share it).
    scripts = str(Path(__file__).resolve().parent.parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from build_bank_gtfree import build_gtfree_bank as build_bank

    conn = get_connection(project_id)
    conn.row_factory = sqlite3.Row
    video = conn.execute(
        "SELECT * FROM videos WHERE camera_id = ? ORDER BY sort_order LIMIT 1",
        (camera_id,)).fetchone()
    cam_row = conn.execute(
        "SELECT intersection_id FROM cameras WHERE camera_id = ?",
        (camera_id,)).fetchone()
    conn.close()
    if video is None or cam_row is None:
        raise ValueError(f"camera {camera_id}: missing video/camera row")
    intersection_id = cam_row["intersection_id"]
    fps = float(video["fps"])

    # resolve_content_hash, not compute_video_content_hash: pass-2 replays a
    # pass-1 dump and never opens the video, so a missing source file must not
    # stop it (2026-08-22 — the corridor's videos stayed on the company
    # OneDrive). Identical result when the video is present.
    chash, _ = resolve_content_hash(
        project_id, camera_id, video["path"],
        file_size_bytes=video["file_size_bytes"],
        total_frames=video["total_frames"],
        persisted_hash=video["content_hash"],
        persisted_method=video["content_hash_method"])
    tdir = tracks_dir(parquet_path(project_id, camera_id, chash, variant))
    if not (tdir / "count.txt").exists():
        raise FileNotFoundError(
            f"pass-1 dump missing/incomplete at {tdir} — run pass 1 first")
    meta = json.loads((tdir / "meta.json").read_text())
    f_lo, f_hi = meta["frames"]
    window_seconds = (f_hi - f_lo) / fps
    rows = load_dump(tdir)

    # --- Track Repair Stage 1 (operator ruling 2026-08-24): resolve base
    # study_* windows to the a3_-CUT derived dump before anything reads the
    # rows. Every cut ends a vehicle identity — segments are separate
    # vehicles, classified by their own gate crossings; classify() and every
    # census/threshold downstream see the same cut tid space. Fail-safe:
    # resolution errors fall back to the base dump (processing never breaks
    # on the repair layer).
    from backend.config import A3_CUT_DUMPS
    if A3_CUT_DUMPS and variant.startswith("study_"):
        try:
            from backend.services.track_cut import ensure_cut_dump
            variant, tdir, meta, rows = ensure_cut_dump(
                project_id, camera_id, variant, chash, fps, tdir, rows, meta)
            f_lo, f_hi = meta["frames"]
            window_seconds = (f_hi - f_lo) / fps
        except Exception as e:                      # pragma: no cover
            logger.warning("a3 cut-dump resolution failed for cam%s %s: %s "
                           "— falling back to the base dump",
                           camera_id, variant, e)

    # --- 0. reuse: a prior compute of THIS dump is still valid ----------------
    # (apply=True used to recompute the whole pass-2 — 2x wall time for
    # nothing when the working DB was just measured. The stats sidecar records
    # the dump meta AND the calibration fingerprint; matching both = identical
    # inputs = reuse. The fingerprint closes the stage-3.3 known limitation:
    # an operator calibration/bank/channel edit now invalidates the sidecar.
    # Legacy sidecars lack the key -> recompute once, then carry it.)
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    fingerprint = calib_fingerprint(project_id, camera_id)
    schema_fp = schema_fingerprint(project_id)
    flags_fp = flags_fingerprint()
    out_db = workdir / f"twopass_cam{camera_id}_{variant}.db"
    stats_p = workdir / f"twopass_cam{camera_id}_{variant}.stats.json"
    if out_db.exists() and stats_p.exists():
        prior = json.loads(stats_p.read_text())
        if sidecar_reusable(prior, meta, fingerprint, schema_fp, flags_fp):
            logger.info("two-pass cam%s %s: reusing computed working DB", camera_id, variant)
            result = prior["result"]
            result["reused"] = True
            if not apply:
                return result
            return _gated_finish_apply(project_id, camera_id, intersection_id,
                                       variant, out_db, f_lo, f_hi, fps,
                                       result, chash)

    # --- 1. corpus bank: discovery over the dump's own tracks ---------------
    if should_cancel is not None and should_cancel():
        raise JobCancelled(f"pass-2 cancelled before corpus bank (cam {camera_id})")
    from datetime import timedelta
    rec_start = datetime.fromisoformat(video["recording_start_datetime"])
    start_hms = (rec_start + timedelta(seconds=f_lo / fps)).strftime("%H:%M:%S")
    bank_res = build_bank(
        camera=camera_id, project=project_id,
        out=str(workdir / f"twopass_bank_cam{camera_id}_{variant}.json"),
        start_hms=start_hms, minutes=window_seconds / 60.0,
        tracks=_dump_tracks_pointlists(rows))
    # (Merge expecteds are computed AFTER the replay — they now depend on the
    # activation decision. Nothing between here and there consumes them: the
    # only readers are the demotion block and merge_replay_turns, both below.)

    # --- 2+3. replay-classify (APPLIED bank), then the turn merge ------------
    # Variant in the name: a study day runs one pass-2 per trim window and the
    # working DBs must coexist (measure-then-apply per window).
    if should_cancel is not None and should_cancel():
        raise JobCancelled(f"pass-2 cancelled after corpus bank (cam {camera_id})")
    # Evidence-gate activation precondition (plan_evidence_activation
    # PHASE-1 VERDICT): PROBE replay first — evidence counted, zero
    # attribution effect, so this replay IS the legacy result — then only a
    # camera whose own blind coverage clears the bar re-replays with the
    # proven pair (gate + posterior, replay-level only). Flag OFF: plain
    # legacy replay, byte-identical.
    activation = None
    if EVIDENCE_ACTIVATION_ENABLED:
        stats = replay_camera(project_id, camera_id, variant=variant,
                              out_db=out_db, should_cancel=should_cancel,
                              evidence_mode="probe")
        n_tracks = int(stats.get("tracks") or 0)
        coverage = (stats.get("origin_evidenced", 0) / n_tracks
                    if n_tracks else 0.0)
        activation = {"coverage": round(coverage, 3),
                      "threshold": EVIDENCE_ACTIVATION_COVERAGE,
                      "activated": coverage >= EVIDENCE_ACTIVATION_COVERAGE}
        logger.info("two-pass cam%s %s: evidence coverage %.3f -> %s",
                    camera_id, variant, coverage,
                    "ACTIVATE" if activation["activated"] else "stand down")
        if activation["activated"]:
            stats = replay_camera(project_id, camera_id, variant=variant,
                                  out_db=out_db, should_cancel=should_cancel,
                                  evidence_mode="on")
    else:
        stats = replay_camera(project_id, camera_id, variant=variant,
                              out_db=out_db, should_cancel=should_cancel)

    # POSTERIOR EXTRAS gate (block D1). census_expecteds + conserve_pass were
    # retired for ONE reason — not blind-deployable at low evidence coverage —
    # and the activation precondition is the decider for exactly that. With
    # CONSERVE_ON_ACTIVATION the extras follow the per-window activation
    # decision; with it OFF this reduces to ORIGIN_POSTERIOR_ENABLED and the
    # shipped path is byte-identical.
    posterior_extras = posterior_extras_enabled(activation)

    # Scale-1 merge expecteds. Posterior half ON: per-cell observed n from
    # GATE EVIDENCE over the dump (census_expecteds — the bank builder's own
    # shape assignment is flip-prone and starved stolen cells; measured 17/14
    # genuine box-full EB-lefts merge-rejected per held-out window). Flag
    # OFF: the legacy corpus-QA derivation, byte-identical (any admission
    # status — a rejected path's traffic still counts toward the gate's
    # expectation — falling back to admitted-path supports; the A4a recipe).
    expected: dict[tuple, float] = {}
    if posterior_extras:
        expected = census_expecteds(project_id, camera_id, rows, fps)
    if not expected:
        for cell in bank_res.get("qa", {}).get("cells", []):
            m = _CELL_RE.match(cell.get("cell", ""))
            if m and "n" in cell:
                key = (int(m.group(1)), int(m.group(2)))
                expected[key] = max(expected.get(key, 0.0), float(cell["n"]))
        for p in bank_res["paths"]:
            key = (p["origin_leg_id"], p["destination_leg_id"])
            expected.setdefault(key, float(p.get("supporting_count", 0)))

    # V2 census-ratio demotion (config flag, default OFF): measure per-cell
    # DIRECT-attributed mass from the first replay against the gate-evidence
    # census; flooded cells re-replay with their direct claims demoted to
    # the branch1 posterior. GT-free throughout (census = gate evidence).
    demotion = None
    from backend import config as _cfg
    if getattr(_cfg, "V2_DEMOTION_ENABLED", False) and expected:
        _c = sqlite3.connect(out_db)
        direct = {(int(o), int(d)): int(n) for o, d, n in _c.execute(
            "SELECT origin_leg_id, destination_leg_id, COUNT(*) "
            "FROM vehicle_events WHERE camera_id=? AND "
            "COALESCE(rejected,0)=0 AND posterior_source IS NULL "
            "AND origin_leg_id IS NOT NULL AND destination_leg_id IS NOT NULL "
            "GROUP BY 1,2", (camera_id,))}
        _c.close()
        ratio = getattr(_cfg, "V2_DEMOTION_RATIO", 2.0)
        # Census from the UNEXTENDED base dump when replaying a derived
        # variant (stack verdict 2026-08-05: extension COMPLETES the
        # flood's false-origin tracks into legitimate-looking fulls and
        # poisons the flooded cell's census -> dose under-fires; the base
        # dump is extension-proof; r_clean absorbs extension's global
        # direct-count inflation on the clean cells).
        census_rows = rows
        base_variant = variant
        for _pref in ("v2c_", "v2a_", "v2b_", "v2d_"):
            if variant.startswith(_pref):
                base_variant = variant[len(_pref):]
                break
        if base_variant != variant:
            _btdir = tracks_dir(parquet_path(project_id, camera_id, chash,
                                             base_variant))
            if (_btdir / "count.txt").exists():
                census_rows = load_dump(_btdir)
        strict, confusion, _full_map = strict_full_census(
            project_id, camera_id, census_rows, fps)
        # ENTANGLEMENT CONDITION (day-6b selector fix): only origins whose
        # own genuine fulls MAJORITY-read as a rival's lanes are demotable —
        # a ratio flag on a clean-geometry origin is recall STARVATION, and
        # demoting starved cells smears real events (SB-right -34 lesson).
        # CONTRAST GUARD (cam1 transfer verdict 2026-08-05): the confusion
        # measure SATURATES on oblique geometry (cam1: 3 of 4 origins read
        # 0.73-1.0 — that is the measure's ceiling, not selectivity; cam2's
        # true signature is ONE origin 0.98 vs median 0.08). Demotion needs
        # an entangled origin against OTHERWISE-CLEAN geometry; saturated
        # cameras stand down entirely.
        conf_vals = sorted(confusion.values())
        others_med = (conf_vals[len(conf_vals) // 2 - 1]
                      if len(conf_vals) >= 2 else 1.0)
        # Shared constant with the apply gate (one contrast ceiling,
        # plan_v2_apply_gate_2026-08-07); value unchanged (0.25).
        contrast_ok = others_med < getattr(_cfg, "APPLY_GATE_SATURATION", 0.25)
        flooded = {cell for cell, nd in direct.items()
                   if contrast_ok and confusion.get(cell[0], 0.0) > 0.5
                   and nd > ratio * max(float(strict.get(cell, 0)), 1.0)}
        # DOSE (held-out verdict 2026-08-05: binary demotion overshoots
        # small-excess windows — PM EB-right +85 -> -177): the CLEAN
        # origins' own direct/strict ratio is the window's recall-inflation
        # factor; a flooded cell keeps that many directs per strict full
        # and demotes only the EXCESS, sampled deterministically per track.
        clean_ratios = [nd / max(float(strict.get(c, 0)), 1.0)
                        for c, nd in direct.items()
                        if confusion.get(c[0], 0.0) <= 0.5
                        and strict.get(c, 0) >= 20 and nd >= 20]
        import statistics as _st
        r_clean = (_st.median(clean_ratios) if clean_ratios else 1.0)
        demote_frac = {
            cell: max(0.0, 1.0 - (r_clean * max(float(strict.get(cell, 0)), 1.0)
                                  / direct[cell]))
            for cell in flooded}
        if flooded:
            # TIME-LOCAL allocation mix (block-2 item 4): per-15-min-segment
            # origin proportions from the BASE dump's strict-census fulls
            # (scale-1 per segment by construction; add-one smoothed;
            # sampler falls back to window-global bank supports when a
            # segment is thin). Bins-only change by design.
            seg_frames = 900.0 * fps
            seg_supports: dict = {}
            for _tid, g in _full_map.items():
                if g[2] is None:
                    continue
                seg = int((g[2] - f_lo) / seg_frames)
                key = (int(g[1]), seg)
                seg_supports.setdefault(key, {})
                seg_supports[key][int(g[0])] = \
                    seg_supports[key].get(int(g[0]), 0) + 1
            timelocal = ({"f_lo": float(f_lo), "seg_frames": seg_frames,
                          "supports": seg_supports}
                         if getattr(_cfg, "V2_TIMELOCAL", False) else None)
            ev_final = ("on" if (activation and activation.get("activated"))
                        else ("probe" if activation is not None else None))
            logger.info("two-pass cam%s %s: demotion re-replay, cells=%s",
                        camera_id, variant, sorted(flooded))
            stats = replay_camera(project_id, camera_id, variant=variant,
                                  out_db=out_db, should_cancel=should_cancel,
                                  evidence_mode=ev_final,
                                  demoted_cells=demote_frac,
                                  demotion_timelocal=timelocal)
        demotion = {"cells": sorted(list(c) for c in flooded),
                    "dose": {f"{k[0]}->{k[1]}": round(v, 3)
                             for k, v in sorted(demote_frac.items())},
                    "r_clean": round(r_clean, 3),
                    "direct": {f"{k[0]}->{k[1]}": v for k, v in
                               sorted(direct.items())},
                    "census_strict": {f"{k[0]}->{k[1]}": v for k, v in
                                      sorted(strict.items())},
                    "confusion": {str(k): round(v, 3)
                                  for k, v in sorted(confusion.items())},
                    "ratio": ratio}
    # Conservation pass (posterior half iteration 3): at most one counted
    # event per fragment chain, additive loses to legacy — BEFORE the merge
    # so the volume gate polices turns over de-duplicated counts.
    if posterior_extras:
        conserve = conserve_pass(project_id, camera_id, rows, fps, out_db)
        stats["conservation"] = conserve
        logger.info("two-pass cam%s %s: conservation %s", camera_id, variant,
                    conserve)
    # Counted-path C2 (flag-gated): coexisting-twin dedup BEFORE the
    # volume-gated merge, so the merge polices de-duplicated counts.
    from backend.config import COEXISTING_TWIN_DEDUP as _twin_on
    if _twin_on:
        from backend.services.turn_merge import twin_track_dedup
        stats["twin_dedup"] = twin_track_dedup(out_db, camera_id, rows, fps)
        logger.info("two-pass cam%s %s: twin dedup %s", camera_id, variant,
                    stats["twin_dedup"])
    # THE FRACTURE RULE (flag-gated, 2026-09-11): drop-and-recapture pairs
    # de-duplicated BEFORE the merge, same reason as the twin dedup.
    from backend.config import FRACTURE_DEDUP as _frac_on
    if _frac_on:
        stats["fracture_dedup"] = fracture_pass(project_id, camera_id, rows,
                                                fps, out_db)
        logger.info("two-pass cam%s %s: fracture dedup %s", camera_id,
                    variant, stats["fracture_dedup"])
    merge = merge_replay_turns(out_db, camera_id, window_seconds=window_seconds,
                               expected_by_cell=expected)
    # V2 MERGE RESCUE (block-2 item 1, diagnosis 2026-08-06): a merged-away
    # turn whose track is a GATE-VERIFIED FULL JOURNEY in a DIFFERENT cell
    # was a misclassified real vehicle (35 gate-verified SB-thrus deleted as
    # SB-right excess on the extended dev dump) — reclassify to the gate
    # cell instead of deleting. Same-cell rejects stay rejected (the volume
    # gate's genuine-excess semantics intact). Gate evidence outranks the
    # volume prior. Census from the REPLAYED variant's own rows here (the
    # journeys being rescued are this dump's).
    from backend import config as _cfg
    if getattr(_cfg, "V2_MERGE_RESCUE", False):
        _strict2, _conf2, full_map2 = strict_full_census(
            project_id, camera_id, rows, fps)
        conn_r = sqlite3.connect(out_db)
        conn_r.row_factory = sqlite3.Row
        legs_r = {r["leg_id"]: dict(r) for r in conn_r.execute(
            "SELECT * FROM legs WHERE camera_id=?", (camera_id,))}
        if getattr(_cfg, "MOUTH_FROM_GATE", False):
            from backend.services.entry_gates import mouth_from_gate
            legs_r = {d["leg_id"]: d for d in mouth_from_gate(list(legs_r.values()))}
        all_legs_r = list(legs_r.values())
        from backend.services.trajectory_classifier import derive_movement
        rescued = 0
        with conn_r:
            for ev in conn_r.execute(
                    "SELECT event_id, vehicle_track_id, origin_leg_id, "
                    "destination_leg_id FROM vehicle_events "
                    "WHERE camera_id=? AND COALESCE(rejected,0)=1",
                    (camera_id,)).fetchall():
                g = full_map2.get(int(ev["vehicle_track_id"]))
                if not g or g[:2] == (ev["origin_leg_id"],
                                      ev["destination_leg_id"]):
                    continue
                o_g, d_g = g[0], g[1]
                if o_g not in legs_r or d_g not in legs_r:
                    continue
                mv = derive_movement(legs_r[o_g], legs_r[d_g], all_legs_r)
                conn_r.execute(
                    "UPDATE vehicle_events SET rejected=0, origin_leg_id=?, "
                    "destination_leg_id=?, movement=? WHERE event_id=?",
                    (o_g, d_g, mv, ev["event_id"]))
                rescued += 1
        conn_r.close()
        merge["rescued_cross_cell"] = rescued
        logger.info("two-pass cam%s %s: merge-rescue reclassified %s "
                    "gate-verified cross-cell rejects", camera_id, variant,
                    rescued)

    result = {
        "camera_id": camera_id, "intersection_id": intersection_id,
        "variant": variant, "window_seconds": window_seconds,
        "corpus_bank_paths": len(bank_res["paths"]),
        "missing_movements": bank_res.get("missing_movements"),
        "replay": stats, "merge": {k: v for k, v in merge.items()
                                   if k != "borderline"},
        "borderline": merge["borderline"], "out_db": str(out_db),
        # The turn-merge volume-gate basis, recorded so control/arm
        # geometry pairs can diff WHY merges (de)activated (the W1a
        # coupling: paths move the corpus bank, which moves these).
        "merge_expecteds": {f"{o}->{d}": round(v, 1)
                            for (o, d), v in sorted(expected.items())},
        "applied": False,
        # Evidence-activation decision (None when the flag is off) — the
        # operator-visible record of the blind coverage census + outcome.
        "evidence_activation": activation,
        # Census-ratio demotion record (None when V2_DEMOTION off).
        "demotion": demotion,
    }
    stats_p.write_text(json.dumps({"dump_meta": meta,
                                   "calib_fingerprint": fingerprint,
                                   "schema_fingerprint": schema_fp,
                                   "flags_fingerprint": flags_fp,
                                   "result": result},
                                  default=str, indent=1))
    if not apply:
        return result
    return _gated_finish_apply(project_id, camera_id, intersection_id,
                               variant, out_db, f_lo, f_hi, fps, result,
                               chash)


def rebuild_s5_union(project_id: str, intersection_id: int,
                     results: list[dict]) -> dict:
    """One flag-queue rebuild carrying the UNION of S5 merge-borderline rows
    across every window a process run applied. A per-window _finish_apply
    rebuild only carries its own window's rows, so a multi-window apply used
    to leave the LAST window's S5 flags only (stage-3.4 dry-run finding).
    Dedup by (camera, cell) keeping the max-|raw−expected| instance; cells
    round-trip through JSON sidecars as lists, so normalize to tuples."""
    best: dict[tuple, dict] = {}
    for res in results:
        cam = res["camera_id"]
        for b in res.get("borderline") or []:
            b = dict(b, cell=tuple(b["cell"]))
            key = (cam, b["cell"])
            if (key not in best or abs(b["raw"] - b["expected"])
                    > abs(best[key]["raw"] - best[key]["expected"])):
                best[key] = b
    by_cam: dict[int, list[dict]] = {}
    for (cam, _), b in best.items():
        by_cam.setdefault(cam, []).append(b)
    extras: list[dict] = []
    conn = get_connection(project_id)
    try:
        for cam, borderline in by_cam.items():
            card = {lid: cd for lid, cd in conn.execute(
                "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id = ?",
                (cam,))}
            extras.extend(s5_flags(cam, borderline, card, bound_approach))
    finally:
        conn.close()
    return rebuild_flags(project_id, intersection_id, extra_flags=extras)


BACKUP_KEEP = 12   # pre-apply project.db copies kept per project (~380 MB
                   # each on the corridor — a full-corridor re-apply is
                   # 9 windows, so 12 keeps a whole campaign + margin while
                   # bounding the directory at ~5 GB; C-stage residual,
                   # closed 2026-07-28)


def _rotate_backups(bdir: Path, keep: int = BACKUP_KEEP) -> None:
    """Delete the oldest pre-apply backups beyond `keep`. Name-sorted =
    time-sorted (timestamp prefix). Deletion failures are non-fatal — a
    locked file just survives one more rotation."""
    try:
        backups = sorted(bdir.glob("*_pre_twopass_cam*.db"))
    except OSError:
        return
    for old in backups[:-keep] if keep > 0 else []:
        try:
            old.unlink()
            logger.info("backup rotation: removed %s", old.name)
        except OSError:
            pass


def gate_census_inputs(project_id: str, camera_id: int, chash: str,
                       variant: str, fps: float) -> tuple[dict, dict]:
    """The apply gate's blind inputs for one window: (gate-evidence census,
    per-origin confusion), computed on the BASE dump (the demotion
    selector's extension-proof principle: a derived variant's own extension
    rows must not vouch for the events they created). Falls back to the
    variant's own dump if no base exists; ({}, {}) when neither does —
    the gate then abstains (not_adjudicable). Shared by the product apply
    path and the offline validation harness (one source of truth)."""
    base_variant = variant
    for _pref in ("v2c_", "v2a_", "v2b_", "v2d_"):
        if variant.startswith(_pref):
            base_variant = variant[len(_pref):]
            break
    census_rows = None
    for cand_variant in dict.fromkeys((base_variant, variant)):
        _tdir = tracks_dir(parquet_path(project_id, camera_id, chash,
                                        cand_variant))
        if (_tdir / "count.txt").exists():
            census_rows = load_dump(_tdir)
            break
    if census_rows is None:
        return {}, {}
    census = census_expecteds(project_id, camera_id, census_rows, fps)
    _sf = strict_full_census(project_id, camera_id, census_rows, fps)
    confusion = _sf[1] if isinstance(_sf, tuple) else {}
    return census, confusion


def _gated_finish_apply(project_id: str, camera_id: int, intersection_id: int,
                        variant: str, out_db: Path, f_lo: int, f_hi: int,
                        fps: float, result: dict, chash: str) -> dict:
    """Adjudicate candidate (working DB) vs incumbent (project.db) for this
    window under the blind guards, then apply only on an 'apply' decision
    (plan_v2_apply_gate_2026-08-07 — every apply must win its window).
    Abstentions (fresh window, no census) keep the legacy apply behavior;
    stand-downs return the measured result with applied=False and the
    verdict in result['apply_gate'] + the apply_adjudications trail."""
    from backend import config as _cfg
    from backend.services.apply_gate import adjudicate_apply
    if not getattr(_cfg, "APPLY_GATE_ENABLED", True):
        return _finish_apply(project_id, camera_id, intersection_id,
                             out_db, f_lo, f_hi, fps, result)
    census, confusion = gate_census_inputs(project_id, camera_id, chash,
                                           variant, fps)
    verdict = adjudicate_apply(
        project_id, camera_id, variant,
        incumbent_db=get_db_path(project_id), candidate_db=out_db,
        t_lo=f_lo / fps, t_hi=f_hi / fps, census=census, confusion=confusion)
    result = dict(result)
    result["apply_gate"] = verdict
    if verdict["decision"] != "apply":
        result["applied"] = False
        logger.info("two-pass cam%s %s: apply gate STAND-DOWN (%s) — "
                    "incumbent table kept", camera_id, variant,
                    ",".join(verdict["reasons"]))
        return result
    return _finish_apply(project_id, camera_id, intersection_id,
                         out_db, f_lo, f_hi, fps, result)


def _finish_apply(project_id: str, camera_id: int, intersection_id: int,
                  out_db: Path, f_lo: int, f_hi: int, fps: float,
                  result: dict) -> dict:
    """The apply half of pass 2: swap this WINDOW's events into project.db
    (the applied bank stays — it is the operator's attribution authority;
    other windows' events stay), then rebuild the queue with the S5 rows."""
    proj_db = get_db_path(project_id)
    backup = proj_db.parent / "backups" / (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_pre_twopass_cam{camera_id}.db")
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(proj_db, backup)
    _rotate_backups(backup.parent)
    _apply_window_events(proj_db, out_db, camera_id, f_lo / fps, f_hi / fps)
    c = sqlite3.connect(proj_db)
    card = {lid: cd for lid, cd in c.execute(
        "SELECT leg_id, cardinal_direction FROM legs WHERE camera_id = ?",
        (camera_id,))}
    c.close()

    # borderline cells round-trip through the stats sidecar as lists
    borderline = [dict(b, cell=tuple(b["cell"])) for b in result["borderline"]]
    extra = s5_flags(camera_id, borderline, card, bound_approach)
    flag_summary = rebuild_flags(project_id, intersection_id, extra_flags=extra)
    result = dict(result)
    result.update({"applied": True, "backup": str(backup), "flags": flag_summary})
    logger.info("two-pass apply cam%s: %s events (applied bank kept), backup %s",
                camera_id, result["replay"]["events"], backup)
    return result
