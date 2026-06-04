#!/usr/bin/env python
"""SEGREGATED offline replay: re-classify stored cam5 tracks against the
engineer's hand-drawn channels, writing ONLY to an isolated copy DB.

Touches:  READ-ONLY the source scratch DB + project.db;
          WRITES experiments/channel_replay/cam5_channels.db + results.json
Undo:     delete experiments/channel_replay/   (nothing else is modified)

Matcher (order-aware, partial-Frechet analog of the live score_path_joint):
  * subsequence DTW aligns the whole track, IN ORDER, to the best-fitting
    sub-curve of each channel centreline;
  * distances are normalised by the LOCAL corridor half-width (perspective ->
    lane-width units, not pixels);
  * a TAIL-DIRECTION gate requires the track's exit heading to agree with the
    channel's tangent at the matched end -- this is what structurally separates
    a straight through from a returning u-turn (a through can't align to a turn).
  Best channel clearing coverage + cost + tail gates assigns origin/dest/
  movement; otherwise the stored classification is kept (fallback).
"""
from __future__ import annotations
import json, shutil, sqlite3, sys
from collections import Counter
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent
SOURCE_DB = Path(r"C:/Users/onkar/AppData/Local/Temp/claude/ic_scratch_97a7849a/cam5_bot_pm.db")
WORK_DB = HERE / "cam5_channels.db"
CHANNELS = HERE / "channels_cam5.json"
RESULTS = HERE / "results.json"

CAMERA = 5
INCLUDE_UTURN = False   # wide self-returning u-turn corridors magnet via partial
                        # match; exclude until they're redrawn lane-tight
N_SAMPLES = 36          # channel centreline samples
N_TRACK = 28            # resample each track to this many points (bounds DTW cost)
COVERAGE_FLOOR = 0.30   # matched sub-curve must span >= this fraction of the channel
COST_CEIL = 1.20        # mean DTW deviation, in half-widths
TAIL_MIN = 0.20         # min cos(angle) between track tail dir & channel exit tangent
# --- selective override (supplementary, not wholesale): only replace the
#     baseline when the channel fit is STRONG and the baseline is WEAK. ---
STRONG_COST = 1.00      # channel cost must be at least this good to override
CONF_GATE = 0.45        # only override baselines below this trajectory_confidence


def quad_samples(ch, n=N_SAMPLES):
    e = np.array(ch["entry"], float); a = np.array(ch["apex"], float); x = np.array(ch["exit"], float)
    c = 2 * a - (e + x) / 2
    t = np.linspace(0, 1, n)
    pts = ((1 - t) ** 2)[:, None] * e + (2 * (1 - t) * t)[:, None] * c + (t ** 2)[:, None] * x
    hw = np.maximum((ch["width_in"] + (ch["width_out"] - ch["width_in"]) * t) / 2.0, 1.0)
    return pts, hw


def resample(P, n=N_TRACK):
    P = np.asarray(P, float)
    if len(P) < 2:
        return P
    seg = np.sqrt((np.diff(P, axis=0) ** 2).sum(1))
    s = np.concatenate([[0], np.cumsum(seg)])
    if s[-1] <= 0:
        return np.repeat(P[:1], n, axis=0)
    u = np.linspace(0, s[-1], n)
    return np.column_stack([np.interp(u, s, P[:, 0]), np.interp(u, s, P[:, 1])])


def _unit(v):
    nrm = float(np.hypot(v[0], v[1]))
    return v / nrm if nrm > 1e-9 else None


def subseq_dtw(track, qpts, qhw):
    """Full track vs a sub-curve of the channel (free start/end on channel side).
    Returns (mean lane-width deviation along the warp, coverage, end_idx)."""
    T, S = len(track), len(qpts)
    D = np.sqrt(((track[:, None, :] - qpts[None, :, :]) ** 2).sum(-1)) / qhw[None, :]
    A = np.full((T, S), np.inf)
    A[0] = D[0]                                  # free start: track[0] -> any channel pt
    bt = np.zeros((T, S), np.int8)               # 0 diag, 1 up(i-1,j), 2 left(i,j-1)
    for i in range(1, T):
        Ai, Ai1, Di = A[i], A[i - 1], D[i]
        Ai[0] = Di[0] + Ai1[0]; bt[i, 0] = 1
        for j in range(1, S):
            d = Ai1[j - 1]; mv = 0
            if Ai1[j] < d: d = Ai1[j]; mv = 1
            if Ai[j - 1] < d: d = Ai[j - 1]; mv = 2
            Ai[j] = Di[j] + d; bt[i, j] = mv
    end_j = int(np.argmin(A[T - 1]))
    i, j = T - 1, end_j
    dists = []
    while True:
        dists.append(D[i, j])
        if i == 0:
            break
        mv = bt[i, j]
        if mv == 0: i, j = i - 1, j - 1
        elif mv == 1: i = i - 1
        else: j = j - 1
    return float(np.mean(dists)), (end_j - j + 1) / S, end_j


def classify(track, chans, samples):
    k = max(1, len(track) // 4)
    ttail = _unit(track[-1] - track[-1 - k])
    best = None
    for ch, (pts, hw) in zip(chans, samples):
        if not INCLUDE_UTURN and ch["movement"] == "u_turn":
            continue
        cost, cov, ej = subseq_dtw(track, pts, hw)
        if cov < COVERAGE_FLOOR or cost > COST_CEIL:
            continue
        if ttail is not None:
            a, b = max(0, ej - 2), min(len(pts) - 1, ej + 2)
            ctan = _unit(pts[b] - pts[a])
            if ctan is not None and float(np.dot(ttail, ctan)) < TAIL_MIN:
                continue
        if best is None or cost < best[1]:
            best = (ch, cost)
    return (best[0], best[1]) if best else (None, None)


def main() -> int:
    chans = json.loads(CHANNELS.read_text())["channels"]
    samples = [quad_samples(c) for c in chans]
    if not SOURCE_DB.exists():
        print(f"SOURCE_DB missing: {SOURCE_DB}", file=sys.stderr); return 1
    shutil.copyfile(SOURCE_DB, WORK_DB)
    con = sqlite3.connect(WORK_DB)
    rows = con.execute(
        "SELECT event_id, origin_leg_id, destination_leg_id, movement, trajectory_confidence, "
        "trajectory_data FROM vehicle_events WHERE camera_id=? AND trajectory_data IS NOT NULL",
        (CAMERA,)
    ).fetchall()

    updates = []
    short = no_channel = agree = overridden = protected_conf = protected_weakfit = 0
    moved = Counter()
    for ev, o0, d0, m0, conf, tj in rows:
        try:
            raw = np.array(json.loads(tj), float)
        except Exception:
            raw = None
        if raw is None or raw.ndim != 2 or len(raw) < 4:
            short += 1; continue
        track = resample(raw)
        ch, cost = classify(track, chans, samples)
        if ch is None:
            no_channel += 1; continue                      # no corridor fits -> keep baseline
        key = (ch["origin_leg"], ch["destination_leg"], ch["movement"])
        if key == (o0, d0, m0):
            agree += 1; continue                            # channel agrees -> nothing to do
        # --- disagreement: override ONLY if channel strong AND baseline weak ---
        weak = (conf is None) or (conf < CONF_GATE)
        if cost <= STRONG_COST and weak:
            overridden += 1
            moved[f"{m0} -> {ch['movement']}"] += 1
            updates.append((ch["origin_leg"], ch["destination_leg"], ch["movement"], ev))
        elif not weak:
            protected_conf += 1                             # baseline confident -> keep it
        else:
            protected_weakfit += 1                          # channel not strong enough -> keep baseline

    con.executemany(
        "UPDATE vehicle_events SET origin_leg_id=?, destination_leg_id=?, movement=? WHERE event_id=?",
        updates)
    con.commit(); con.close()

    summary = {
        "matcher": "subsequence-DTW + tail gate, SELECTIVE override",
        "tracks": len(rows), "too_short": short,
        "overridden": overridden, "channel_agreed": agree, "no_channel_fit": no_channel,
        "protected_confident_baseline": protected_conf,
        "protected_weak_channel_fit": protected_weakfit,
        "params": {"coverage_floor": COVERAGE_FLOOR, "cost_ceil": COST_CEIL, "tail_min": TAIL_MIN,
                   "strong_cost": STRONG_COST, "conf_gate": CONF_GATE,
                   "include_uturn": INCLUDE_UTURN, "n_samples": N_SAMPLES, "n_track": N_TRACK},
        "movement_changes": dict(moved.most_common()),
    }
    RESULTS.write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
