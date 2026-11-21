"""THE GLOBAL TRACKLET LINKER (config.TRACKLET_LINKER, 2026-09-30,
docs/research_tracking_2026-09-29.md phase 2).

Recorded video lets pass 2 use hindsight. This stage joins the pieces a
vehicle's track broke into (occlusion, detector flicker) BEFORE the journey
logic runs, so a vehicle reaches _finalize_vehicle_data as ONE track. It
replaces the patchwork of greedy fragment rules (chain_tracks, the fracture
rule, the bound-chain guard, the continuation rule, the turn merge).

How it decides, per level (<= 0.5 s gaps, <= 3 s gaps, stopped <= 60 s):
  * ENDPOINTS: each piece's tail and head position and velocity from a
    least-squares line over its last / first second, and its box scale
    s = sqrt(w * h). Every gate is in SECONDS and BOX UNITS, so the stage is
    frame-rate and zoom independent.
  * CANDIDATES: gap inside the level's window; limited temporal overlap;
    two-way prediction residual (where A would be at B's birth, where B
    would have been at A's death) within LINKER_RESID_BASE +
    LINKER_RESID_PER_S * gap box units; bearings agreeing.
  * THE FOLLOWER TEST: a continuation is born where the leader WOULD BE; the
    next car in the queue is born where the leader WAS. A moving leader
    whose head candidate sits much nearer its death point than its
    prediction is refused.
  * BIRTH / DEATH COSTS from the operator's gate lines: a piece that ends
    after a witnessed exit (or at the image edge) dies cheaply, one that
    dies mid-box expensively; births mirror that. A full journey therefore
    has no reason to link, which replaces the old "only incomplete journeys
    may chain" veto with a cost.
  * GLOBAL ASSIGNMENT: tails x heads plus dummy death / birth, solved with
    scipy's linear_sum_assignment per connected component (no greedy
    first-come pairing).
Linked families take the id min(member); stopped links longer than the
replay's finalize grace are bridged with held rows so the replay keeps the
one id. Movement still comes only from what the video shows for the vehicle.
"""
from __future__ import annotations

import bisect
import math
from collections import defaultdict

import numpy as np

RULE_REV = 1


class _Cfg:
    """config.py's LINKER_* constants plus the frozen chain-rule constants the
    linker reuses from track_chains (they are not in config.py)."""
    def __init__(self):
        from backend import config as c
        from backend.services import track_chains as tc
        self._c = c
        self.STITCH_STAT_SPEED_PXS = tc.STITCH_STAT_SPEED_PXS
        self.CHAIN_DIR_TOL_DEG = tc.CHAIN_DIR_TOL_DEG
        self.CHAIN_BEARING_END_S = tc.CHAIN_BEARING_END_S

    def __getattr__(self, name):
        return getattr(self._c, name)


def _cfg():
    return _Cfg()


def _tags(rows_by_tid: dict, fps: float, gates) -> dict:
    """Gate tag per track, exactly as the counting default tags it (bottom
    corners through the journey state machine)."""
    from backend.services.entry_gates import classify_pair
    out = {}
    for tid, sel in rows_by_tid.items():
        if len(sel) < 2:
            out[tid] = "no_crossing"
            continue
        yb = sel[:, 3] + sel[:, 5] / 2.0
        left = list(zip(sel[:, 1].tolist(), (sel[:, 2] - sel[:, 4] / 2.0).tolist(), yb.tolist()))
        right = list(zip(sel[:, 1].tolist(), (sel[:, 2] + sel[:, 4] / 2.0).tolist(), yb.tolist()))
        out[tid] = classify_pair(left, right, gates, fps)[6]
    return out


def _end_state(sel: np.ndarray, fps: float, tail: bool, window_s: float):
    """(frame, x, y, vx, vy [px/s], scale) at the tail or head of a piece."""
    f = sel[:, 1]
    if tail:
        m = f >= f[-1] - window_s * fps
    else:
        m = f <= f[0] + window_s * fps
    s = sel[m]
    t = (s[:, 1] - s[0, 1]) / fps
    if len(s) >= 2 and t[-1] > 0:
        vx, x0 = np.polyfit(t, s[:, 2], 1)
        vy, y0 = np.polyfit(t, s[:, 3], 1)
        te = t[-1] if tail else 0.0
        x, y = x0 + vx * te, y0 + vy * te
    else:
        vx = vy = 0.0
        x, y = float(s[-1 if tail else 0, 2]), float(s[-1 if tail else 0, 3])
    scale = float(np.median(np.sqrt(np.maximum(s[:, 4] * s[:, 5], 1.0))))
    fr = float(f[-1] if tail else f[0])
    return fr, float(x), float(y), float(vx), float(vy), scale


def _near_edge(x, y, scale, frame_size) -> bool:
    if not frame_size:
        return False
    w, h = frame_size
    m = max(3.0, 0.5 * scale)
    return x <= m or y <= m or x >= w - m or y >= h - m


def _angle_deg(ax, ay, bx, by) -> float:
    na, nb = math.hypot(ax, ay), math.hypot(bx, by)
    if na == 0 or nb == 0:
        return 0.0
    c = max(-1.0, min(1.0, (ax * bx + ay * by) / (na * nb)))
    return math.degrees(math.acos(c))


def _link_cost(A, B, fps, moving_level: bool, c):
    """Cost of joining tail A to head B, or None when a gate refuses it."""
    fa, xa, ya, vxa, vya, sa = A
    fb, xb, yb, vxb, vyb, sb = B
    g = (fb - fa) / fps
    s = max(1.0, (sa + sb) / 2.0)
    speed_a = math.hypot(vxa, vya)
    if moving_level:
        px, py = xa + vxa * g, ya + vya * g            # where A would be
        qx, qy = xb - vxb * g, yb - vyb * g            # where B would have been
        rf = math.hypot(xb - px, yb - py) / s
        rb = math.hypot(xa - qx, ya - qy) / s
        r = max(rf, rb)
        if r > c.LINKER_RESID_BASE + c.LINKER_RESID_PER_S * max(g, 0.0):
            return None
        if (speed_a >= c.STITCH_STAT_SPEED_PXS and math.hypot(vxb, vyb) >= c.STITCH_STAT_SPEED_PXS
                and _angle_deg(vxa, vya, vxb, vyb) > c.CHAIN_DIR_TOL_DEG):
            return None
        d_was = math.hypot(xb - xa, yb - ya) / s        # distance to where A WAS
        if speed_a * max(g, 0.0) / s >= 1.0 and d_was < c.LINKER_FOLLOWER_RATIO * rf:
            return None                                  # the next car, not A
        sig = c.LINKER_SIGMA_BASE + c.LINKER_SIGMA_PER_S * max(g, 0.0)
        return 0.5 * (rf / sig) ** 2 + 0.5 * (rb / sig) ** 2
    d = math.hypot(xb - xa, yb - ya) / s                 # stopped: same spot
    if d > c.LINKER_STOP_DIST_BOXES:
        return None
    return 0.5 * (d / c.LINKER_SIGMA_BASE) ** 2


def _assign(tails, heads, cands, death, birth):
    """Global assignment over one connected component. cands: {(i, j): cost}."""
    from scipy.optimize import linear_sum_assignment
    nT, nH = len(tails), len(heads)
    BIG = 1e9
    M = np.full((nT + nH, nH + nT), BIG)
    for (i, j), cst in cands.items():
        M[i, j] = cst
    for i in range(nT):
        M[i, nH + i] = death[i]
    for j in range(nH):
        M[nT + j, j] = birth[j]
    M[nT:, nH:] = 0.0
    r, cidx = linear_sum_assignment(M)
    return [(tails[i], heads[j]) for i, j in zip(r, cidx)
            if i < nT and j < nH and M[i, j] < BIG]


def split_reversals(rows: np.ndarray, fps: float, c) -> tuple[np.ndarray, int]:
    """THE THEFT SPLIT (config.THEFT_SPLIT): cut each track where it moves one
    way, slows, and moves back the other way at a smaller box than either run
    (a far-field hand-off between an outgoing and an oncoming car). The part
    after each cut gets a new track id. Returns (rows', number of cuts)."""
    rows = np.array(rows, dtype=np.float64, copy=True)
    if not len(rows):
        return rows, 0
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows = rows[order]
    tids, starts = np.unique(rows[:, 0], return_index=True)
    ends = np.append(starts[1:], len(rows))
    next_tid = float(rows[:, 0].max()) + 1
    step = max(1, int(round(c.THEFT_SAMPLE_S * fps)))
    min_run = max(2, int(round(c.THEFT_RUN_S / c.THEFT_SAMPLE_S)))
    cuts = 0
    for a, b in zip(starts, ends):
        tr = rows[a:b]
        if len(tr) < 2 * min_run * step:
            continue
        idx = np.arange(0, len(tr), step)
        smp = tr[idx]
        if len(smp) < 2 * min_run + 1:
            continue
        d = np.diff(smp[:, 2:4], axis=0)
        dt = np.maximum(np.diff(smp[:, 1]), 1) / fps
        w = np.maximum(smp[:-1, 4], 1.0)
        spd = np.hypot(d[:, 0], d[:, 1]) / dt / w
        mov = spd >= c.THEFT_MOVE_WPS
        # maximal runs of moving samples
        runs, k = [], 0
        while k < len(mov):
            if mov[k]:
                j = k
                while j + 1 < len(mov) and mov[j + 1]:
                    j += 1
                runs.append((k, j))
                k = j + 1
            else:
                k += 1
        cut_rows = []
        for (a1, b1), (a2, b2) in zip(runs, runs[1:]):
            if b1 - a1 + 1 < min_run or b2 - a2 + 1 < min_run:
                continue
            v1, v2 = d[a1:b1 + 1].sum(axis=0), d[a2:b2 + 1].sum(axis=0)
            w1, w2 = float(np.median(w[a1:b1 + 1])), float(np.median(w[a2:b2 + 1]))
            if (np.hypot(*v1) < c.THEFT_RUN_BOXES * w1
                    or np.hypot(*v2) < c.THEFT_RUN_BOXES * w2):
                continue
            cosang = float(np.dot(v1, v2) / (np.hypot(*v1) * np.hypot(*v2)))
            if np.degrees(np.arccos(np.clip(cosang, -1, 1))) <= c.THEFT_REVERSE_DEG:
                continue
            between = range(b1 + 1, a2 + 1)          # sample indices of the turn
            if not len(between):
                continue
            k_turn = min(between, key=lambda q: smp[q, 4])
            if smp[k_turn, 4] > c.THEFT_TURN_SIZE_FRAC * min(w1, w2):
                continue
            cut_rows.append(int(idx[k_turn]))
        for r0 in sorted(cut_rows):                  # ascending: each cut relabels the rest
            tr[r0:, 0] = next_tid                    # view into rows: in place
            next_tid += 1
            cuts += 1
    return rows, cuts


def link_rows(rows: np.ndarray, fps: float, gates, frame_size=None):
    """Link a dump's pieces. Returns (rows', families {root: [members]}, stats)."""
    c = _cfg()
    rows = np.asarray(rows, dtype=np.float64)
    theft_cuts = 0
    if getattr(c, "THEFT_SPLIT", False):
        rows, theft_cuts = split_reversals(rows, fps, c)
    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rs = rows[order]
    tids, starts = np.unique(rs[:, 0], return_index=True)
    ends = np.append(starts[1:], len(rs))
    pieces = {int(t): rs[a:b] for t, a, b in zip(tids, starts, ends)}
    parent = {t: t for t in pieces}

    def root(t):
        while parent[t] != t:
            parent[t] = parent[parent[t]]
            t = parent[t]
        return t

    grace = c.fps_frames(c.TRACK_FINALIZE_GAP_FRAMES, fps)
    stats = defaultdict(int)
    stats["theft_cuts"] = theft_cuts
    bridges = []
    levels = [("move", c.LINKER_MOVE_GAP_MIN_S, c.LINKER_LEVEL1_GAP_S, True),
              ("move", c.LINKER_MOVE_GAP_MIN_S, c.LINKER_MOVE_GAP_MAX_S, True)]
    tags = _tags(pieces, fps, gates)
    for lvl, (_name, g_lo, g_hi, moving) in enumerate(levels, 1):
        live = {t: p for t, p in pieces.items() if root(t) == t and len(p) >= 2}
        ends_ = {t: _end_state(p, fps, True, c.CHAIN_BEARING_END_S) for t, p in live.items()}
        heads_ = {t: _end_state(p, fps, False, c.CHAIN_BEARING_END_S) for t, p in live.items()}
        hs = sorted(live, key=lambda t: heads_[t][0])
        hf = [heads_[t][0] for t in hs]
        cands = {}
        for ta in live:
            A = ends_[ta]
            stopped = math.hypot(A[3], A[4]) < c.STITCH_STAT_SPEED_PXS
            if moving == stopped:
                continue                                   # each tail in its own level
            lo = bisect.bisect_left(hf, A[0] + g_lo * fps)
            hi = bisect.bisect_right(hf, A[0] + g_hi * fps)
            pa = live[ta]
            for tb in hs[lo:hi]:
                if tb == ta:
                    continue
                pb = live[tb]
                if pb[-1, 1] <= pa[-1, 1] or pb[0, 1] <= pa[0, 1]:
                    continue                               # must extend in time
                ov = (min(pa[-1, 1], pb[-1, 1]) - max(pa[0, 1], pb[0, 1])) / fps
                shorter = min(pa[-1, 1] - pa[0, 1], pb[-1, 1] - pb[0, 1]) / fps
                if ov > min(c.LINKER_OVERLAP_MAX_S, c.LINKER_OVERLAP_MAX_FRAC * max(shorter, 1e-9)):
                    continue
                cst = _link_cost(A, heads_[tb], fps, moving, c)
                if cst is not None:
                    cands[(ta, tb)] = cst
        stats[f"level{lvl}_candidates"] = len(cands)
        if not cands:
            continue
        # connected components of the candidate graph (tails and heads)
        adj = defaultdict(set)
        for ta, tb in cands:
            adj[("T", ta)].add(("H", tb))
            adj[("H", tb)].add(("T", ta))
        seen, links = set(), []
        for node in list(adj):
            if node in seen:
                continue
            comp, stack = [], [node]
            seen.add(node)
            while stack:
                n = stack.pop()
                comp.append(n)
                for m in adj[n]:
                    if m not in seen:
                        seen.add(m)
                        stack.append(m)
            T = [n[1] for n in comp if n[0] == "T"]
            H = [n[1] for n in comp if n[0] == "H"]
            ti, hj = {t: i for i, t in enumerate(T)}, {t: j for j, t in enumerate(H)}
            death = []
            for t in T:
                A = ends_[t]
                cheap = tags.get(t) in ("full", "exit_only") or _near_edge(A[1], A[2], A[5], frame_size)
                death.append(0.0 if cheap else c.LINKER_MIDBOX_COST)
            birth = []
            for t in H:
                B = heads_[t]
                cheap = tags.get(t) in ("full", "entry_only") or _near_edge(B[1], B[2], B[5], frame_size)
                birth.append(0.0 if cheap else c.LINKER_MIDBOX_COST)
            sub = {(ti[a], hj[b]): v for (a, b), v in cands.items() if a in ti and b in hj}
            links += _assign(T, H, sub, death, birth)
        merged_roots = set()
        for ta, tb in links:
            # merge B's piece into A's family (following A back to its root:
            # A may itself have been merged earlier in this level); drop B's
            # frames that overlap A
            ra = root(ta)
            pa, pb = pieces[ra], pieces[tb]
            pb = pb[pb[:, 1] > pa[-1, 1]]
            gap = pb[0, 1] - pa[-1, 1] if len(pb) else 0
            if len(pb) and gap > grace:
                step = max(1, int(round(fps)))            # held rows, one per second
                hold = []
                for f in range(int(pa[-1, 1]) + step, int(pb[0, 1]), step):
                    r = pa[-1].copy()
                    r[1] = f
                    hold.append(r)
                if hold:
                    bridges.append(len(hold))
                    pb = np.vstack([np.array(hold), pb])
            merged = np.vstack([pa, pb]) if len(pb) else pa
            pieces[ra] = merged
            pieces[tb] = pieces[tb][:0]
            parent[tb] = ra
            merged_roots.add(ra)
            stats[f"level{lvl}_links"] += 1
        # tags of merged pieces change (a head + tail can now be one journey)
        tags.update(_tags({r: pieces[r] for r in merged_roots if root(r) == r}, fps, gates))
    families = defaultdict(list)
    for t in parent:
        families[root(t)].append(t)
    fam_min = {r: min(m) for r, m in families.items()}
    out = []
    for r, members in families.items():
        p = pieces[r]
        if len(p):
            q = p.copy()
            q[:, 0] = fam_min[r]
            out.append(q)
    # pieces with < 2 rows never took part; keep them verbatim
    out_rows = np.vstack(out) if out else rows[:0]
    out_rows = out_rows[np.lexsort((out_rows[:, 0], out_rows[:, 1]))]
    fams = {int(fam_min[r]): sorted(int(m) for m in members)
            for r, members in families.items() if len(members) > 1}
    stats["families"] = len(fams)
    stats["absorbed"] = sum(len(m) - 1 for m in fams.values())
    stats["bridged_links"] = len(bridges)
    stats["pieces_in"] = len(pieces)
    return out_rows.astype(np.float32), fams, dict(stats)


def ensure_linked_dump(project_id: str, camera_id: int, variant: str,
                       fps: float, base_tdir, base_rows, base_meta: dict,
                       frame_size=None):
    """Materialise (or reuse) the linked dump lk{sig}_{variant}.tracks beside the
    base dump (the derived-dump pattern). Returns (variant',
    tdir', meta', rows'). The base dump is never touched."""
    import json
    from pathlib import Path

    from backend.services.track_cut import _geom_hash
    from backend.services.two_pass import _pinned_gates

    ghash = _geom_hash(project_id, camera_id)
    cfg_sig = linker_signature()
    # One directory per linker setting (2026-10-01): arms with different
    # linker settings no longer overwrite each other's derived dump (arm ts1
    # rewrote the dump a concurrent journey score of the default was reading).
    import hashlib
    sig_h = hashlib.sha1(json.dumps(cfg_sig, sort_keys=True).encode()).hexdigest()[:6]
    new_variant = f"lk{sig_h}_{variant}"
    dst = Path(str(base_tdir).replace(f"{variant}.tracks", f"{new_variant}.tracks"))
    meta_p = dst / "meta.json"
    if meta_p.exists():
        m = json.loads(meta_p.read_text())
        info = m.get("linker") or {}
        if (info.get("geom_hash") == ghash and info.get("rule_rev") == RULE_REV
                and info.get("base_rows") == int(len(base_rows))
                and info.get("config") == cfg_sig):
            return new_variant, dst, m, np.load(dst / "rows.npy")
    gates, skip = _pinned_gates(project_id, camera_id, np.asarray(base_rows))
    if skip is not None:
        raise RuntimeError(f"cam{camera_id}: {skip}")
    out_rows, fams, stats = link_rows(np.asarray(base_rows), fps, gates, frame_size)
    dst.mkdir(parents=True, exist_ok=True)
    np.save(dst / "rows.npy", np.ascontiguousarray(out_rows, dtype=np.float32))
    (dst / "count.txt").write_text(str(len(out_rows)))
    (dst / "families.json").write_text(json.dumps(fams))
    meta2 = dict(base_meta)
    meta2["variant"] = new_variant
    meta2["complete"] = True
    meta2["linker"] = {"geom_hash": ghash, "rule_rev": RULE_REV, "base_variant": variant,
                       "base_rows": int(len(base_rows)), "config": cfg_sig,
                       **{k: int(v) for k, v in stats.items()}}
    meta_p.write_text(json.dumps(meta2))
    return new_variant, dst, meta2, out_rows


def linker_signature() -> dict:
    c = _cfg()
    return {k: getattr(c, k) for k in (
        "LINKER_LEVEL1_GAP_S", "LINKER_MOVE_GAP_MIN_S", "LINKER_MOVE_GAP_MAX_S",
        "LINKER_OVERLAP_MAX_S", "LINKER_OVERLAP_MAX_FRAC", "LINKER_RESID_BASE",
        "LINKER_RESID_PER_S", "LINKER_SIGMA_BASE", "LINKER_SIGMA_PER_S",
        "LINKER_FOLLOWER_RATIO", "LINKER_STOP_DIST_BOXES", "LINKER_MIDBOX_COST",
        "STITCH_STAT_SPEED_PXS", "CHAIN_DIR_TOL_DEG", "CHAIN_BEARING_END_S",
        "THEFT_SPLIT", "THEFT_SAMPLE_S", "THEFT_MOVE_WPS", "THEFT_RUN_S",
        "THEFT_RUN_BOXES", "THEFT_REVERSE_DEG", "THEFT_TURN_SIZE_FRAC")}
