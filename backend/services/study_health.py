"""Study health — the reference-free self-diagnosis battery.

Operator mandate (2026-08-28, docs/plan_study_health_2026-08-28.md):
"on new videos we will not know what is broken unless the machine can
identify it." Every disease diagnosed in the August campaigns leaves a
fingerprint computable WITHOUT ground truth; this module assembles
those fingerprints per camera-window and renders a verdict
(green/amber/red + reasons + suspect cells).

READ-ONLY over surfaces that already exist:
- the pass-2 stats sidecar (provenance counters, activation, merge,
  twin dedup) — two_pass workdir twopass_cam{cid}_{variant}.stats.json
- the dump meta (stop_fracture_collapsed)
- the events DB (counted events by posterior_source per cell)
- the bank flow priors (turn_merge.bank_expecteds)
- the per-window chain census (footage_rating.census_for_variant)

Thresholds: v1 DECLARED in the gate doc; replaced by the S2
corridor-calibrated set. classify_signals is pure (the
classify_metrics / spot_check verdict idiom).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from backend.config import EVIDENCE_ACTIVATION_COVERAGE, PROJECTS_DIR

# ---- v1 thresholds (gate doc plan_study_health_2026-08-28.md) ----------
GUESSED_AMBER = 0.35      # guessed share of counted events
GUESSED_RED = 0.55
# Divergence needs RATIO and MATERIALITY (S2 calibration 2026-08-28:
# ratio alone flagged the b145 winner at 2.02x/1.3% of events while a
# real flood ran 2.39x/3.9%): excess share = (counted-expected)/window
# events.
DIVERGENCE_RED_RATIO = 2.0
DIVERGENCE_RED_EXCESS = 0.035
DIVERGENCE_AMBER_RATIO = 1.5
DIVERGENCE_AMBER_EXCESS = 0.025
DIVERGENCE_MIN_N = 30
ENTRY_COV_AMBER = 0.50        # census entry coverage
ENTRY_COV_RED = 0.35
ECHO_SHARE_AMBER = 0.04       # footage_rating's frozen fair line
# twin_pairs is informational when the dedup ran (the pairs were
# CAUGHT); it fires no verdict (S2: cam3 at 83.7 carried 10% twin
# pressure, all handled).

# Operator-ruled cells the divergence signal must not flag: cam1's
# commercial-driveway leg (ruling 2026-08-28: a real 4th leg counted
# to reality; the bank predates it and Miovision under-counts it).
DIVERGENCE_EXCEPT = {(1, 25)}      # (camera_id, origin_leg_id)

GUESSED_SOURCES = ("branch1", "rescue_full", "rescue_supports",
                   "demoted", "dest_tie")


def _stats_sidecar(project_id: str, camera_id: int, variant: str,
                   workdir: Path | None):
    wd = workdir or (Path(PROJECTS_DIR) / project_id / "two_pass")
    p = Path(wd) / f"twopass_cam{camera_id}_{variant}.stats.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text())
    except Exception:
        return None


def collect_signals(project_id: str, camera_id: int, variant: str, *,
                    db_path: str | Path | None = None,
                    workdir: Path | None = None) -> dict | None:
    """Assemble the per-window signal dict. db_path defaults to the
    production project DB; pass a replay stem/working DB to health-check
    an experiment arm. Returns None when no dump exists."""
    import numpy as np

    from backend.database import get_connection
    from backend.services.detection_cache import parquet_path
    from backend.services.cardinals import bound_approach
    from backend.services.footage_rating import _gates, census_for_variant
    from backend.services.pass2_replay import load_dump, tracks_dir
    from backend.services.turn_merge import bank_expecteds

    conn = get_connection(project_id)
    try:
        vid = conn.execute(
            "SELECT content_hash, fps FROM videos WHERE camera_id = ? "
            "ORDER BY sort_order LIMIT 1", (camera_id,)).fetchone()
        if vid is None:
            return None
        chash, fps = vid[0], float(vid[1] or 10.0)
        gates = _gates(conn, project_id, camera_id)
        legs = {int(r[0]): r[1] for r in conn.execute(
            "SELECT leg_id, cardinal_direction FROM legs "
            "WHERE camera_id = ?", (camera_id,))}
    finally:
        conn.close()

    td = Path(tracks_dir(parquet_path(project_id, camera_id, chash,
                                      variant)))
    if not (td / "meta.json").exists():
        return None
    dmeta = json.loads((td / "meta.json").read_text())
    frames = dmeta.get("frames")
    win_s = (frames[1] - frames[0]) / fps if frames else None
    t_lo = frames[0] / fps if frames else None
    t_hi = frames[1] / fps if frames else None

    sig: dict = {"camera_id": camera_id, "variant": variant,
                 "window_seconds": win_s,
                 "stop_fracture_collapsed":
                     dmeta.get("stop_fracture_collapsed"),
                 "dump_backend": dmeta.get("backend")}

    # ---- stats sidecar: provenance counters + activation + twin ------
    sc = _stats_sidecar(project_id, camera_id, variant, workdir)
    if sc:
        res = sc.get("result", {})
        rep = res.get("replay", {})
        sig["activation"] = res.get("evidence_activation")
        sig["tracks"] = rep.get("tracks")
        sig["insufficient"] = rep.get("insufficient_data")
        sig["origin_flow_inferred"] = rep.get("origin_flow_inferred")
        sig["twin_pairs"] = (rep.get("twin_dedup") or {}).get("twin_pairs")
        sig["merged_away"] = (res.get("merge") or {}).get("merged_away")
        sig["borderline_cells"] = len(res.get("borderline") or [])

    # ---- DB: counted events by cell + provenance ---------------------
    dbp = str(db_path) if db_path else \
        str(Path(PROJECTS_DIR) / project_id / "project.db")
    con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    try:
        q = ("FROM vehicle_events WHERE camera_id = ? AND "
             "COALESCE(rejected,0) = 0")
        args: list = [camera_id]
        if t_lo is not None:
            q += " AND timestamp_video >= ? AND timestamp_video < ?"
            args += [t_lo, t_hi]
        counted = con.execute("SELECT COUNT(*) " + q, args).fetchone()[0]
        marks = ",".join("?" * len(GUESSED_SOURCES))
        guessed = con.execute(
            "SELECT COUNT(*) " + q + " AND posterior_source IN (" +
            marks + ")", args + list(GUESSED_SOURCES)).fetchone()[0]
        cells: dict = {}
        for o, d, mv, n in con.execute(
                "SELECT origin_leg_id, destination_leg_id, movement, "
                "COUNT(*) " + q + " GROUP BY 1,2,3", args):
            cells[(o, d, mv)] = n
    finally:
        con.close()
    con2 = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
    try:
        expected = bank_expecteds(con2, camera_id, win_s or 7200.0)
    finally:
        con2.close()
    sig["counted_events"] = counted
    sig["guessed_events"] = guessed
    sig["guessed_share"] = round(guessed / counted, 3) if counted else None
    sig["twin_rate"] = (round(sig["twin_pairs"] / counted, 4)
                        if counted and sig.get("twin_pairs") is not None
                        else None)

    # flow divergence per TURN cell (the lane-echo signature)
    diverging = []
    for (o, d, mv), n in cells.items():
        if mv not in ("left", "right", "u_turn") or n < DIVERGENCE_MIN_N:
            continue
        if (camera_id, o) in DIVERGENCE_EXCEPT:
            continue
        exp = expected.get((o, d))
        if not exp or exp <= 0:
            continue
        ratio = n / exp
        excess = (n - exp) / counted if counted else 0.0
        if ratio >= DIVERGENCE_AMBER_RATIO and                 excess >= DIVERGENCE_AMBER_EXCESS:
            diverging.append({
                "cell": str(bound_approach(legs.get(o, "")) or "?")
                        + "_" + str(mv),
                "origin_leg_id": o, "destination_leg_id": d,
                "movement": mv, "counted": n,
                "expected": round(exp, 1),
                "ratio": round(ratio, 2),
                "excess_share": round(excess, 3),
                "red": bool(ratio >= DIVERGENCE_RED_RATIO
                            and excess >= DIVERGENCE_RED_EXCESS)})
    sig["diverging_cells"] = sorted(diverging,
                                    key=lambda c: -c["excess_share"])[:8]

    # ---- per-window chain census (twin/echo/truncation anatomy) ------
    if gates is not None:
        rows = load_dump(td)
        tids = set(int(t) for t in np.unique(rows[:, 0]))
        va = {"rows": rows, "tids": tids,
              "span": (float(rows[:, 1].min()) / fps,
                       float(rows[:, 1].max()) / fps)}
        events = []
        con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
        try:
            for t, o, d, ts, mv in con.execute(
                    "SELECT vehicle_track_id, origin_leg_id, "
                    "destination_leg_id, timestamp_video, movement FROM "
                    "vehicle_events WHERE camera_id = ? AND "
                    "COALESCE(rejected,0) = 0 AND vehicle_track_id IS "
                    "NOT NULL AND timestamp_video IS NOT NULL",
                    (camera_id,)):
                events.append((int(t), o, d, float(ts), mv))
        finally:
            con.close()
        part, _echo = census_for_variant(va, events, gates, fps)
        n = part["tracks_mapped"]
        tags = part["tags"]
        sig["tag_mix"] = ({k: round(v / n, 3)
                           for k, v in sorted(tags.items())} if n else {})
        sig["entry_coverage"] = (round(
            (tags.get("full", 0) + tags.get("entry_only", 0)) / n, 3)
            if n else None)
        sig["multi_chain_share"] = (round(
            part["multi_chains"] / part["chains"], 3)
            if part["chains"] else None)
        joined = part["events_joined"]
        sig["echo_share"] = (round(part["excess_same_cell"] / joined, 4)
                             if joined else None)
    return sig


def classify_signals(sig: dict) -> dict:
    """Pure verdict: green/amber/red + reasons. v1 thresholds (gate
    doc); S2 replaces them with the corridor-calibrated set."""
    reasons: list[str] = []
    level = 0                     # 0 green, 1 amber, 2 red

    def worst(new, why):
        nonlocal level
        level = max(level, new)
        reasons.append(why)

    act = sig.get("activation") or {}
    if act and not act.get("activated"):
        worst(2, "evidence channel OFF (coverage {} < {}) - attribution "
                 "runs on guesses".format(
                     act.get("coverage"),
                     act.get("threshold", EVIDENCE_ACTIVATION_COVERAGE)))
    gs = sig.get("guessed_share")
    if gs is not None:
        if gs >= GUESSED_RED:
            worst(2, "{:.0%} of counts are guessed, not witnessed"
                  .format(gs))
        elif gs >= GUESSED_AMBER:
            worst(1, "{:.0%} of counts are guessed".format(gs))
    for c in sig.get("diverging_cells") or []:
        worst(2 if c.get("red") else 1,
              "turn cell {} counts {}x its historical flow "
              "({} vs ~{})".format(c["cell"], c["ratio"],
                                   c["counted"], c["expected"]))
    ec = sig.get("entry_coverage")
    if ec is not None:
        if ec < ENTRY_COV_RED:
            worst(2, "only {:.0%} of tracks have a witnessed entry"
                  .format(ec))
        elif ec < ENTRY_COV_AMBER:
            worst(1, "entry coverage {:.0%}".format(ec))
    es = sig.get("echo_share")
    if es is not None and es >= ECHO_SHARE_AMBER:
        worst(1, "same-cell echo share {:.1%}".format(es))
    return {"verdict": ("green", "amber", "red")[level],
            "reasons": reasons}


def window_health(project_id: str, camera_id: int, variant: str, *,
                  db_path=None, workdir=None, write=True) -> dict | None:
    """collect + classify + (optionally) persist the sidecar
    data/projects/{pid}/study_health_cam{cid}_{variant}.json."""
    sig = collect_signals(project_id, camera_id, variant,
                          db_path=db_path, workdir=workdir)
    if sig is None:
        return None
    out = {**sig, **classify_signals(sig)}
    if write:
        # JSON-safe: tuple keys never appear (cells are stringified)
        p = (Path(PROJECTS_DIR) / project_id /
             ("study_health_cam{}_{}.json".format(camera_id, variant)))
        p.write_text(json.dumps(out, indent=2, default=str))
    return out
