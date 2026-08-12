"""Pipeline-V2 shared utilities (plan_v2_week1_derisk).

- load_table: the D1 npz -> dict (rows, per-track slices, features, meta).
- fit_motion_residual: per-window self-calibration of extrapolation error
  (residual ~ alpha + beta * gap_seconds) from the window's OWN confident
  tracklets — the anti-frozen-constant mechanism; every consumer derives
  its gates/costs from (alpha, beta), never from hand constants.
- candidate_links: time-gated end->start candidate pairs with
  constant-velocity AND zero-velocity (stopped/queue) hypothesis costs.
- chain scoring helpers shared by the instrument and the scorers.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

T_MAX_S = 120.0          # max stitch gap — max red phase + margin (§2e S4)
CAL_GAPS = (0.5, 1.0, 2.0, 5.0, 10.0)   # calibration gap buckets (seconds)
KIN_PTS = 8


def load_table(path: str | Path) -> dict:
    z = np.load(path, allow_pickle=False)
    t = {k: z[k] for k in z.files if k not in ("meta",)}
    t["meta"] = json.loads(str(z["meta"]))
    t["fps"] = float(t["meta"]["fps"])
    t["n"] = len(t["track_id"])
    return t


def track_points(t: dict, i: int) -> np.ndarray:
    """(k,8) rows slice of tracklet i (sorted by frame)."""
    return t["rows"][int(t["starts"][i]):int(t["ends"][i])]


def window_speed_floor(t: dict, sample: int = 300, seed: int = 7) -> float:
    """v_stop (px/s): the window's own moving/queued speed separator — the
    20th percentile of per-step speeds inside long tracks, floored at 8."""
    rng = np.random.default_rng(seed)
    ok = np.where(t["n_pts"] >= 30)[0]
    if len(ok) == 0:
        return 8.0
    picks = rng.choice(ok, size=min(sample, len(ok)), replace=False)
    sp = []
    for i in picks:
        tr = track_points(t, int(i))
        d = np.hypot(*np.diff(tr[:, 2:4], axis=0).T)
        df = np.diff(tr[:, 1]) / t["fps"]
        sp.append(d / np.maximum(df, 1e-9))
    sp = np.concatenate(sp)
    return float(max(8.0, np.percentile(sp, 20)))


def fit_motion_residual(t: dict, max_samples: int = 500, seed: int = 42):
    """(alpha, beta, zv_radius, v_stop, table) — self-calibrated per window:

    - CV cone: median |extrapolation residual| vs gap, measured ONLY at
      MOVING anchors (speed >= v_stop) — queued anchors flatten the slope
      and poisoned the first fit (day-1 finding, on the record).
    - Monotone allowance: bucket medians made non-decreasing before the
      n-weighted line fit; alpha floored at 3 px.
    - zv_radius: measured reappearance radius across STOPPED segments
      (entry-to-stop vs exit-from-stop drift), p90 + 10 px slack.
    """
    rng = np.random.default_rng(seed)
    fps = t["fps"]
    v_stop = window_speed_floor(t)
    ok = np.where((t["n_pts"] >= 50)
                  & (t["mean_conf"] >= np.median(t["mean_conf"])))[0]
    if len(ok) == 0:
        ok = np.where(t["n_pts"] >= 20)[0]
    picks = rng.choice(ok, size=min(max_samples, len(ok)), replace=False)
    buckets: dict[float, list[float]] = {g: [] for g in CAL_GAPS}
    stop_drift: list[float] = []
    for i in picks:
        tr = track_points(t, int(i))
        fr, xy = tr[:, 1], tr[:, 2:4]
        step_v = np.hypot(*np.diff(xy, axis=0).T) / np.maximum(
            np.diff(fr) / fps, 1e-9)
        # stopped-segment drift (zero-velocity reappearance radius)
        slow = step_v < v_stop
        if slow.any():
            runs = np.flatnonzero(np.diff(np.concatenate(
                [[0], slow.view(np.int8), [0]])))
            for s0, s1 in zip(runs[::2], runs[1::2]):
                if (fr[min(s1, len(fr) - 1)] - fr[s0]) / fps >= 3.0:
                    stop_drift.append(float(np.hypot(
                        *(xy[min(s1, len(fr) - 1)] - xy[s0]))))
        for g in CAL_GAPS:
            gf = g * fps
            a = int(rng.integers(KIN_PTS, max(KIN_PTS + 1, len(fr) - 1)))
            target = fr[a] + gf
            j = int(np.searchsorted(fr, target))
            if j >= len(fr) or abs(fr[j] - target) > 0.4 * gf + 2:
                continue
            k = min(KIN_PTS, a)
            f_fit, p_fit = fr[a - k:a + 1], xy[a - k:a + 1]
            tt = (f_fit - f_fit[0]) / fps
            den = ((tt - tt.mean()) ** 2).sum() or 1e-9
            vx = ((tt - tt.mean()) * (p_fit[:, 0] - p_fit[:, 0].mean())).sum() / den
            vy = ((tt - tt.mean()) * (p_fit[:, 1] - p_fit[:, 1].mean())).sum() / den
            if np.hypot(vx, vy) < v_stop:        # moving anchors only
                continue
            dt = (fr[j] - fr[a]) / fps
            pred = xy[a] + np.array([vx, vy]) * dt
            buckets[g].append(float(np.hypot(*(xy[j] - pred))))
    gaps = [g for g in CAL_GAPS if len(buckets[g]) >= 10]
    table = {str(g): {"n": len(buckets[g]),
                      "median_px": float(np.median(buckets[g])) if buckets[g] else None}
             for g in CAL_GAPS}
    if len(gaps) >= 2:
        med = np.maximum.accumulate(
            np.array([np.median(buckets[g]) for g in gaps]))
        w = np.sqrt([len(buckets[g]) for g in gaps])
        A = np.vstack([np.ones(len(gaps)), np.array(gaps)]).T * w[:, None]
        (alpha, beta), *_ = np.linalg.lstsq(A, med * w, rcond=None)
        alpha, beta = float(max(alpha, 3.0)), float(max(beta, 1.0))
    else:
        alpha, beta = 8.0, 12.0    # degenerate window fallback — logged
    zv_radius = (float(np.percentile(stop_drift, 90) + 10.0)
                 if len(stop_drift) >= 10 else alpha + beta * 2.0)

    # velocity-fit noise + typical accel (for the velocity-continuity term):
    # v_noise = |v fitted over [a-k,a] vs [a,a+k]| at moving anchors (mostly
    # fit noise + sub-second accel); a_allow = median |dv|/dt over ~2 s.
    rng2 = np.random.default_rng(seed + 1)
    vn, aa = [], []
    for i in rng2.choice(ok, size=min(200, len(ok)), replace=False):
        tr = track_points(t, int(i))
        fr, xy = tr[:, 1], tr[:, 2:4]
        if len(fr) < 3 * KIN_PTS:
            continue
        def _v(a0, a1):
            f, p = fr[a0:a1], xy[a0:a1]
            if len(f) < 2 or f[-1] == f[0]:
                return None
            tt = (f - f[0]) / fps
            den = ((tt - tt.mean()) ** 2).sum() or 1e-9
            return np.array([
                ((tt - tt.mean()) * (p[:, 0] - p[:, 0].mean())).sum() / den,
                ((tt - tt.mean()) * (p[:, 1] - p[:, 1].mean())).sum() / den])
        a = int(rng2.integers(KIN_PTS, len(fr) - KIN_PTS))
        v1, v2 = _v(a - KIN_PTS, a + 1), _v(a, a + KIN_PTS + 1)
        if v1 is None or v2 is None or np.hypot(*v1) < v_stop:
            continue
        vn.append(float(np.hypot(*(v2 - v1))))
        j = int(np.searchsorted(fr, fr[a] + 2.0 * fps))
        if j + KIN_PTS < len(fr):
            v3 = _v(j, j + KIN_PTS + 1)
            if v3 is not None:
                aa.append(float(np.hypot(*(v3 - v1)) / 2.0))
    v_noise = float(np.median(vn)) if len(vn) >= 20 else 2.0 * beta / 3.0
    a_allow = float(np.median(aa)) if len(aa) >= 20 else v_noise
    return {"alpha": alpha, "beta": beta, "zv_radius": zv_radius,
            "v_stop": v_stop, "v_noise": v_noise, "a_allow": a_allow,
            "table": table}


def candidate_links(t: dict, cal: dict,
                    k_sigma: float = 3.0, t_max_s: float = T_MAX_S,
                    cv_cone_cap_s: float = 12.0,
                    pos_mode: str = "mean", vel_mode: str = "off"):
    # Defaults FROZEN by the day-2 cost sweep (v2_cost_sweep, cam2+cam1
    # transfer): bidirectional-mean position, velocity term OFF (dead at
    # this resolution — joins ReID in the pairwise-channel graveyard).
    """For every tracklet end -> plausible successor starts, physics-gated.

    Hypotheses per pair (i ends, j starts, dt = gap seconds):
    - CV (constant velocity): BIDIRECTIONAL position residual — mean of
      forward (i's end extrapolated to j's start time) and backward (j's
      start extrapolated back) — inside the calibrated cone
      alpha + beta*min(dt, cap); PLUS a velocity-continuity term
      |v_start_j - v_end_i| / (2*v_noise + a_allow*dt): a platoon follower
      matches position but sits in a different velocity phase (day-1
      diagnosis). Combined quadratically.
    - ZV (zero velocity / queue wait): |start_j - end_i| <= zv_radius;
      eligible when the end is slow OR when the gap outlives the CV cone
      and the reappearance is nearby (a long-gap nearby reappearance IS
      queue-like — the 60 s red-light class). No velocity term (restart
      velocity is uninformative).
    Physics gates: no backward motion when both endpoints are moving;
    dt in (0, t_max_s].

    Returns (i, j, dt_s, cost, hyp); keep cost <= k_sigma; hyp 1 = ZV.
    """
    fps = t["fps"]
    alpha, beta = cal["alpha"], cal["beta"]
    zv_radius, v_stop = cal["zv_radius"], cal["v_stop"]
    v_noise, a_allow = cal["v_noise"], cal["a_allow"]
    f1, f0 = t["f1"], t["f0"]
    end_xy = np.stack([t["x1"], t["y1"]], 1)
    start_xy = np.stack([t["x0"], t["y0"]], 1)
    end_v = np.stack([t["vx1"], t["vy1"]], 1)
    start_v = np.stack([t["vx0"], t["vy0"]], 1)
    end_speed = np.hypot(end_v[:, 0], end_v[:, 1])
    start_speed = np.hypot(start_v[:, 0], start_v[:, 1])
    order = np.argsort(f0)
    f0s = f0[order]
    out = ([], [], [], [], [])
    for i in range(t["n"]):
        lo = np.searchsorted(f0s, f1[i] + 1)
        hi = np.searchsorted(f0s, f1[i] + t_max_s * fps)
        cand = order[lo:hi]
        cand = cand[cand != i]
        if len(cand) == 0:
            continue
        dt = (f0[cand] - f1[i]) / fps
        disp = start_xy[cand] - end_xy[i]
        dist = np.hypot(disp[:, 0], disp[:, 1])
        # CV hypothesis — position residual per pos_mode, optional gated
        # velocity-continuity term per vel_mode (variant sweep decides;
        # frozen by v2_cost_sweep verdict, see week-1 verdict doc).
        fwd = np.hypot(*(start_xy[cand] - (end_xy[i] + end_v[i] * dt[:, None])).T)
        if pos_mode == "fwd":
            pos_res = fwd
        else:
            bwd = np.hypot(*((start_xy[cand] - start_v[cand] * dt[:, None])
                             - end_xy[i]).T)
            pos_res = (np.minimum(fwd, bwd) if pos_mode == "min"
                       else 0.5 * (fwd + bwd))
        pos_allow = alpha + beta * np.minimum(dt, cv_cone_cap_s)
        cv_cost = pos_res / pos_allow
        if vel_mode == "gated":
            vel_ok = ((dt <= 2.0) & (t["n_pts"][cand] >= 2 * KIN_PTS)
                      & (t["n_pts"][i] >= 2 * KIN_PTS))
            dv = np.hypot(*(start_v[cand] - end_v[i]).T)
            vel_allow = 2.0 * v_noise + a_allow * dt
            vel_cost = dv / np.maximum(vel_allow, 1e-9)
            cv_cost = np.where(vel_ok,
                               np.sqrt((cv_cost ** 2 + 0.5 * vel_cost ** 2) / 1.5),
                               cv_cost)
        cv_cost = np.where(dt <= cv_cone_cap_s, cv_cost, np.inf)
        # ZV hypothesis — slow end, OR beyond-cone nearby reappearance
        zv_ok = (end_speed[i] < v_stop) | ((dt > cv_cone_cap_s)
                                           & (dist <= zv_radius))
        zv_cost = np.where(zv_ok, dist / max(zv_radius, 1e-6), np.inf)
        cost = np.minimum(cv_cost, zv_cost)
        hyp = (zv_cost < cv_cost).astype(np.int8)
        # no-backward gate, turn-aware: heading may legitimately rotate
        # through the box (a left turn is ~90-140 deg over a few seconds) —
        # allowed rotation grows with dt (day-2 finding: a hard cos<0 gate
        # pruned mid-turn true links = the miss-10 class in the sweep).
        both_moving = (end_speed[i] >= v_stop) & (start_speed[cand] >= v_stop)
        if end_speed[i] >= v_stop:
            ev = end_v[i] / (end_speed[i] or 1.0)
            far = dist > max(zv_radius, alpha)
            cos_disp = (disp[:, 0] * ev[0] + disp[:, 1] * ev[1]) / np.maximum(dist, 1e-9)
            sv = start_v[cand] / np.maximum(start_speed[cand], 1e-9)[:, None]
            cos_v = sv[:, 0] * ev[0] + sv[:, 1] * ev[1]
            max_turn_deg = np.clip(30.0 + 35.0 * dt, 90.0, 150.0)
            cos_lim = np.cos(np.radians(max_turn_deg))
            bad = both_moving & ((far & (cos_disp < cos_lim)) | (cos_v < cos_lim))
            cost = np.where(bad, np.inf, cost)
        keep = cost <= k_sigma
        out[0].append(np.full(int(keep.sum()), i))
        out[1].append(cand[keep])
        out[2].append(dt[keep])
        out[3].append(cost[keep])
        out[4].append(hyp[keep])
    if not out[0]:
        return (np.array([], int),) * 2 + (np.array([]),) * 2 + (np.array([], np.int8),)
    return (np.concatenate(out[0]), np.concatenate(out[1]),
            np.concatenate(out[2]), np.concatenate(out[3]),
            np.concatenate(out[4]))


def premerge_concurrent(rows: np.ndarray, starts, ends, fps: float,
                        iou_min: float = 0.30, overlap_frac: float = 0.5):
    """Stage-3 structural pre-merge of CONCURRENT near-duplicate tracklets
    (one vehicle, simultaneous IDs — the occlusion-split class; sequential
    links with dt>0 cannot reach it by construction).

    Rule: two tracklets whose co-life covers >= overlap_frac of the
    shorter's life AND whose mean IoU over common frames >= iou_min merge
    (union-find groups; per-frame duplicates resolved by higher conf).
    Pairwise geometry/appearance channels stay dead — this is TIME-OVERLAP
    STRUCTURE, the one channel the three dead families never used.

    Returns (pieces, groups): merged per-track row arrays + the id groups.
    """
    n = len(starts)
    f0 = np.array([rows[int(s), 1] for s in starts])
    f1 = np.array([rows[int(e) - 1, 1] for e in ends])
    order = np.argsort(f0)
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    f0s = f0[order]
    for oi, i in enumerate(order):
        hi = np.searchsorted(f0s, f1[i], side="right")
        for j in order[oi + 1:hi]:
            lo, hi_f = max(f0[i], f0[j]), min(f1[i], f1[j])
            shorter = min(f1[i] - f0[i], f1[j] - f0[j]) or 1.0
            if (hi_f - lo) < overlap_frac * shorter or (hi_f - lo) < fps:
                continue
            ri = rows[int(starts[i]):int(ends[i])]
            rj = rows[int(starts[j]):int(ends[j])]
            ri = ri[(ri[:, 1] >= lo) & (ri[:, 1] <= hi_f)]
            rj = rj[(rj[:, 1] >= lo) & (rj[:, 1] <= hi_f)]
            fi = {int(r[1]): r for r in ri}
            ious = []
            for r2 in rj:
                r1 = fi.get(int(r2[1]))
                if r1 is None:
                    continue
                ax1, ay1 = r1[2] - r1[4] / 2, r1[3] - r1[5] / 2
                ax2, ay2 = r1[2] + r1[4] / 2, r1[3] + r1[5] / 2
                bx1, by1 = r2[2] - r2[4] / 2, r2[3] - r2[5] / 2
                bx2, by2 = r2[2] + r2[4] / 2, r2[3] + r2[5] / 2
                iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
                ih = max(0.0, min(ay2, by2) - max(ay1, by1))
                inter = iw * ih
                union_a = r1[4] * r1[5] + r2[4] * r2[5] - inter
                ious.append(inter / union_a if union_a > 0 else 0.0)
            if len(ious) >= 3 and float(np.mean(ious)) >= iou_min:
                union(int(i), int(j))

    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    pieces = []
    for root, members in groups.items():
        seg = np.concatenate([rows[int(starts[i]):int(ends[i])]
                              for i in members])
        if len(members) > 1:
            # one row per frame: keep the higher-confidence box
            seg = seg[np.lexsort((-seg[:, 6], seg[:, 1]))]
            _, first = np.unique(seg[:, 1], return_index=True)
            seg = seg[np.sort(first)]
        else:
            seg = seg[np.argsort(seg[:, 1])]
        pieces.append(seg)
    return pieces, [g for g in groups.values() if len(g) > 1]


def twin_pairs_structural(t: dict, cal: dict,
                          min_colife_s: float = 1.0,
                          dist_mult: float = 1.5):
    """The one untried twin channel (week-1 verdict item 1): two
    CO-TEMPORAL tracklets are one vehicle iff they COMPETE for the same
    continuation — best successor collision (join signature: the split
    rejoins into one downstream track) or best predecessor collision
    (fork signature: one upstream track splits into both). Structure on
    the existing candidate graph; the only knobs are a minimum co-life
    and the common-frame distance bound (dist_mult * zv_radius; 1.5 =
    the CD-test <20 px precedent — was a dead parameter defaulting 4.0
    while the body hardcoded 1.5*, fixed 2026-08-12, behavior-preserving).

    MEASURED DEAD 2026-08-12 (G-B1i, plan_b1_twin_isolation_2026-08-12):
    synthetic double-box twins are recovered at only 0.07-0.15 across four
    tables/two cameras — a mid-life duplicate has no fork/join topology,
    so the signature is structurally blind to the class — while queued
    FOLLOWERS false-flag at 0.08-0.16 (the same weld class that killed
    co-life IoU). Fifth and last twin channel at event level.

    Returns list of (i, j) twin pairs.
    """
    fps = t["fps"]
    ii, jj, dts, costs, hyps = candidate_links(t, cal)
    best_succ: dict[int, tuple] = {}
    best_pred: dict[int, tuple] = {}
    for k in range(len(ii)):
        i, j, c = int(ii[k]), int(jj[k]), float(costs[k])
        if i not in best_succ or c < best_succ[i][0]:
            best_succ[i] = (c, j)
        if j not in best_pred or c < best_pred[j][0]:
            best_pred[j] = (c, i)
    succ_of = {i: v[1] for i, v in best_succ.items()}
    pred_of = {j: v[1] for j, v in best_pred.items()}

    by_succ: dict[int, list[int]] = {}
    for i, z in succ_of.items():
        by_succ.setdefault(z, []).append(i)
    by_pred: dict[int, list[int]] = {}
    for j, w in pred_of.items():
        by_pred.setdefault(w, []).append(j)

    f0, f1 = t["f0"], t["f1"]
    # twins ride ON TOP of each other during co-life; followers hold
    # headway — gate on mean COMMON-FRAME distance at the same-vehicle
    # scale, not on midpoints (day-4: midpoint gate admitted half the
    # window)
    max_d = dist_mult * cal["zv_radius"]
    pairs = set()
    for group in list(by_succ.values()) + list(by_pred.values()):
        if len(group) < 2:
            continue
        for a in range(len(group)):
            for b in range(a + 1, len(group)):
                x, y = group[a], group[b]
                colife = min(f1[x], f1[y]) - max(f0[x], f0[y])
                if colife < min_colife_s * fps:
                    continue
                rx = track_points(t, x)
                ry = track_points(t, y)
                fy = {int(r[1]): r for r in ry}
                ds = [float(np.hypot(r[2] - fy[int(r[1])][2],
                                     r[3] - fy[int(r[1])][3]))
                      for r in rx if int(r[1]) in fy]
                if len(ds) < 3 or float(np.mean(ds)) > max_d:
                    continue
                pairs.add((min(x, y), max(x, y)))
    return sorted(pairs)


def table_from_pieces(pieces: list, fps: float, meta: dict) -> dict:
    """Minimal tracklet table (stitching features) from per-track row arrays
    — shared by the instrument's rebuild and the pre-merge path."""
    rows = np.concatenate(pieces)
    starts, ends = [], []
    off = 0
    for p in pieces:
        starts.append(off)
        off += len(p)
        ends.append(off)
    t = {"rows": rows, "starts": np.array(starts), "ends": np.array(ends),
         "fps": fps, "meta": meta, "n": len(pieces)}
    for k in ("track_id", "n_pts", "f0", "f1", "x0", "y0", "x1", "y1",
              "vx0", "vy0", "vx1", "vy1", "mean_conf", "mean_area"):
        t[k] = np.zeros(t["n"])
    for i, p in enumerate(pieces):
        fr, xy = p[:, 1], p[:, 2:4]
        t["track_id"][i] = p[0, 0]
        t["n_pts"][i] = len(p)
        t["f0"][i], t["f1"][i] = fr[0], fr[-1]
        t["x0"][i], t["y0"][i] = xy[0]
        t["x1"][i], t["y1"][i] = xy[-1]
        for head, (kx, ky) in ((True, ("vx0", "vy0")), (False, ("vx1", "vy1"))):
            k = min(KIN_PTS, len(fr))
            sl = slice(0, k) if head else slice(len(fr) - k, len(fr))
            f, q = fr[sl], xy[sl]
            if k >= 2 and f[-1] > f[0]:
                tt = (f - f[0]) / fps
                den = ((tt - tt.mean()) ** 2).sum() or 1e-9
                t[kx][i] = ((tt - tt.mean()) * (q[:, 0] - q[:, 0].mean())).sum() / den
                t[ky][i] = ((tt - tt.mean()) * (q[:, 1] - q[:, 1].mean())).sum() / den
        t["mean_conf"][i] = p[:, 6].mean()
        t["mean_area"][i] = (p[:, 4] * p[:, 5]).mean()
    return t


def fifo_links(t: dict, cal: dict, existing: list[tuple[int, int]],
               min_wait_s: float = 20.0, max_wait_s: float = 120.0):
    """Block-2 item 3 — QUEUE-ORDER (FIFO) links for the red-light class.

    The ZV cone cannot pick among co-located queue neighbors; ORDER can:
    within a stop zone and lane, vehicles leave in the order they arrived.
    Stop zones = spatial clusters of slow endpoints (grid hash, cell
    3*zv_radius); lanes = clusters of perpendicular offset along the
    zone's principal axis (merge distance 1.5*zv_radius); per lane,
    queue-entering ENDS (end speed < v_stop) pair with queue-leaving
    STARTS in strict arrival order within [min_wait, max_wait] seconds.
    Existing (motion-evidence) links take precedence; FIFO fills holes.
    """
    fps = t["fps"]
    v_stop, zr = cal["v_stop"], cal["zv_radius"]
    end_v = np.hypot(t["vx1"], t["vy1"])
    start_v = np.hypot(t["vx0"], t["vy0"])
    # enders: tracks vanishing SLOW (entering the queue). starters: tracks
    # BORN in the stop zone regardless of speed — re-acquisition happens at
    # green, moving (day-1 instrument finding of this item); membership in
    # the zone is the queue-exit evidence, not start speed.
    enders = np.where(end_v < v_stop)[0]
    starters = np.arange(t["n"])
    if not len(enders) or not len(starters):
        return []
    used_end = {i for i, _ in existing}
    used_start = {j for _, j in existing}

    # grid-hash clustering of all queue endpoints
    cell = 3.0 * zr
    pts = []
    for i in enders:
        pts.append((float(t["x1"][i]), float(t["y1"][i]), int(i), 0))
    for j in starters:
        pts.append((float(t["x0"][j]), float(t["y0"][j]), int(j), 1))
    grid: dict[tuple, list] = {}
    for x, y, idx, kind in pts:
        grid.setdefault((int(x // cell), int(y // cell)), []).append(
            (x, y, idx, kind))
    # union adjacent grid cells into zones
    parent: dict[tuple, tuple] = {k: k for k in grid}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    for gx, gy in list(grid):
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nb = (gx + dx, gy + dy)
                if nb in grid:
                    ra, rb = find((gx, gy)), find(nb)
                    if ra != rb:
                        parent[rb] = ra
    zones: dict[tuple, list] = {}
    for k, members in grid.items():
        zones.setdefault(find(k), []).extend(members)

    links = []
    for members in zones.values():
        if len(members) < 4:
            continue
        P = np.array([(m[0], m[1]) for m in members])
        mu = P.mean(0)
        C = np.cov((P - mu).T) if len(P) > 2 else np.eye(2)
        w, V = np.linalg.eigh(C)
        axis, perp = V[:, -1], V[:, 0]
        offs = (P - mu) @ perp
        order = np.argsort(offs)
        # lanes: split sorted perpendicular offsets at gaps > 1.5*zv_radius
        lanes: list[list[int]] = [[]]
        for oi, k in enumerate(order):
            if lanes[-1] and (offs[k] - offs[order[oi - 1]]) > 1.5 * zr:
                lanes.append([])
            lanes[-1].append(k)
        for lane in lanes:
            le = sorted((float(t["f1"][members[k][2]]), members[k][2])
                        for k in lane if members[k][3] == 0
                        and members[k][2] not in used_end)
            ls = sorted((float(t["f0"][members[k][2]]), members[k][2])
                        for k in lane if members[k][3] == 1
                        and members[k][2] not in used_start)
            # CYCLE-AWARE (iteration 3): order holds within ONE signal
            # cycle, not across the window — segment arrivals into bursts
            # (inter-end gap < 30 s) and departures into discharge bursts
            # (inter-start gap < 10 s); pair burst -> first discharge
            # burst after it, rank-to-rank.
            def bursts(seq, gap_s):
                out, cur = [], []
                for f, i in seq:
                    if cur and (f - cur[-1][0]) > gap_s * fps:
                        out.append(cur)
                        cur = []
                    cur.append((f, i))
                if cur:
                    out.append(cur)
                return out
            ab = bursts(le, 30.0)
            db = bursts(ls, 10.0)
            di = 0
            for burst in ab:
                last_end = burst[-1][0]
                while di < len(db) and db[di][0][0] <= last_end + min_wait_s * fps:
                    di += 1
                if di >= len(db):
                    break
                disc = db[di]
                if disc[0][0] - last_end > max_wait_s * fps:
                    continue
                for rank in range(min(len(burst), len(disc))):
                    ei, sj = burst[rank][1], disc[rank][1]
                    if ei != sj:
                        links.append((int(ei), int(sj)))
                di += 1
    return links


def chains_from_links(n: int, links: list[tuple[int, int]]):
    """links (i->j, each endpoint used once) -> list of ordered chains."""
    nxt = {i: j for i, j in links}
    prv = {j: i for i, j in links}
    chains = []
    for i in range(n):
        if i in prv:
            continue
        ch = [i]
        while ch[-1] in nxt:
            ch.append(nxt[ch[-1]])
        chains.append(ch)
    return chains
