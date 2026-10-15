"""THE CELL RISK SCORE, MEASURED (2026-10-15; plan C:\\Users\\marsh\\.claude\\plans\\proud-wiggling-swan.md phase 1a).
Can the app tell, WITHOUT Miovision, which 15-min cell-bins fail the 5/95 rule - so a reviewer goes there?
Per (camera, 15-min bin, movement) and per (camera, bin, approach), from runtime data only:
  ENC   counts on an encounter flag (two counted tracks meeting where a count can change; encounter flags)
  PART  counts decided from a partial journey (track_fates.gate_tag != 'full'), not already in ENC
  MISS  tracked-but-uncounted candidates in the bin + approach (gap_items.candidate_items - the gap cards' filter)
  LINK  the lagged corridor residual on the receiving approach (sent by the neighbour - received here; lag 0-5 min
        from the cross-correlation of the two per-minute series; corridor only, 0 elsewhere)
est (expected ours - truth) = a*ENC + b*PART - c*MISS - d*LINK, a..d >= 0, ONE set for every camera, fit by least
squares on the cell-bins of the OTHER cameras (leave-one-camera-out; Miovision used only to fit and score).
risk = |est| / tolerance(our count).  GATE R (declared before running): the top 20% of cell-bins by risk hold >= 80%
of the failing cell-bins' excess vehicles on the fleet, no camera < 60%, and on FM 51 (constants from all 5 cameras).
Baselines shown: rank by our count (traffic) and by ENC alone.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_cell_risk.py [STEM]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime
from pathlib import Path

import numpy as np
from scipy.optimize import nnls

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.database import leg_geometry_for_camera, list_paths_for_camera  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.entry_gates import build_gates  # noqa: E402
from backend.services.gap_items import PAD_SECONDS, candidate_items  # noqa: E402
from backend.services.mouth_from_motion import _load  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from backend.services.rule595 import score_cells, tolerance  # noqa: E402
from research_near_twins import WINDOWS  # noqa: E402
from research_review_queue import flags as encounter_flags  # noqa: E402
from v2_score_dev import CORRIDOR, FM51, NORM, SITES, leg_dir_for, load_miovision  # noqa: E402

CORR_BASE = Path("data/projects/97a7849a/_replay_scratch/fleet_20260908")
FM51_BASE = Path("data/projects/0acb12c0/_replay_scratch/blank_20260911")
FM51_CAM, FM51_VARIANTS = 2, ("vl3_l1_study_0700", "vl3_l1_study_1600")
MAX_LAG_MIN = 5
TOPS = (0.1, 0.2, 0.3)


def rows_for(proj, cam, chash, base, db):
    """The dump whose ids cover the working DB's counted events (eval_journeys.locate, any project)."""
    d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ev = {int(t) for (t,) in d.execute("SELECT DISTINCT vehicle_track_id FROM vehicle_events WHERE camera_id=? "
                                       "AND COALESCE(rejected,0)=0", (cam,))}
    d.close()
    root = tracks_dir(parquet_path(proj, cam, chash, base)).parent
    best, cov_best = None, -1.0
    for v in (*sorted(p.name[:-len(".tracks")] for p in root.glob(f"lk*_{base}.tracks")), base):
        td = tracks_dir(parquet_path(proj, cam, chash, v))
        if not (td / "count.txt").exists():
            continue
        rows = np.asarray(load_dump(td))
        cov = len(ev & set(np.unique(rows[:, 0]).astype(int).tolist())) / max(len(ev), 1)
        if cov > cov_best:
            best, cov_best = rows, cov
    return best


def window_events(db, cam, site):
    rec = site["rec_start"]
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    tag = {e["tid"]: e["tag"] for e in _load(c, cam)}
    out = []
    for tid, o, de, mv, tv, tr in c.execute(
            "SELECT vehicle_track_id, origin_leg_id, destination_leg_id, movement, timestamp_video, timestamp_real "
            "FROM vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0", (cam,)):
        wall = (rec + timedelta(seconds=float(tv))) if rec else (datetime.fromisoformat(tr) if tr else None)
        if wall is None:
            continue
        out.append({"tid": int(tid) if tid is not None else -1, "o": o, "d": de, "mv": NORM.get(mv, mv),
                    "tv": float(tv), "wall": wall, "tag": tag.get(int(tid)) if tid is not None else None})
    c.close()
    return out


def bin_key(t):
    return f"{t.hour:02d}:{(t.minute // 15) * 15:02d}"


def window_cells(proj, cam, base, db, rows, site, fps, lo, hi, link=None):
    """Feature rows per movement and per approach cell-bin, with the truth from Miovision."""
    ld = leg_dir_for(proj, cam, site)
    evs = window_events(db, cam, site)
    flagged = {t for f in encounter_flags(db, rows, cam, fps) for t in (f["a"], f["b"])}
    minutes = [dtime(h, m) for h in range(lo, hi) for m in range(60)]
    mio = load_miovision(cam, site)
    mm = [m for m in minutes if m in mio]
    ours = {"mov": defaultdict(lambda: defaultdict(int)), "appr": defaultdict(lambda: defaultdict(int))}
    F = {"mov": defaultdict(lambda: np.zeros(4)), "appr": defaultdict(lambda: np.zeros(4))}
    first_wall = None
    for e in evs:
        dr = ld.get(e["o"])
        if not dr:
            continue
        tm = e["wall"].time().replace(second=0, microsecond=0)
        ours["mov"][tm][(dr, e["mv"])] += 1
        ours["appr"][tm][dr] += 1
        b = bin_key(tm)
        if e["tid"] in flagged:
            k = 0
        elif e["tag"] not in (None, "full"):
            k = 1
        else:
            continue
        F["mov"][(b, f"{dr} {e['mv']}")][k] += 1
        F["appr"][(b, dr)][k] += 1
    # video seconds of a wall bin: from any event (wall - tv is the recording start)
    e0 = evs[0]
    rec0 = e0["wall"] - timedelta(seconds=e0["tv"])
    # MISS: candidates per bin (gap card filter), over the dump
    geom = leg_geometry_for_camera(proj, cam)
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    legs_full = {int(r["leg_id"]): dict(r) for r in con.execute("SELECT * FROM legs WHERE camera_id=?", (cam,))}
    con.close()
    gates = build_gates({l: g["mouth"] for l, g in geom.items() if g.get("mouth")},
                        list_paths_for_camera(proj, cam), {l: g.get("heading") for l, g in geom.items()},
                        leg_gates={l: g["gate"] for l, g in geom.items() if g.get("gate")} or None)
    kept = {e["tid"] for e in evs}
    order = np.argsort(rows[:, 1], kind="stable")
    rf = rows[order, 1]
    day0 = datetime.combine(rec0.date(), dtime(0, 0))
    for h in range(lo, hi):
        for q in range(4):
            wall_lo = day0 + timedelta(hours=h, minutes=15 * q)
            t_lo = (wall_lo - rec0).total_seconds()
            t_hi = t_lo + 900
            a = np.searchsorted(rf, (t_lo - PAD_SECONDS) * fps)
            z = np.searchsorted(rf, (t_hi + PAD_SECONDS) * fps, side="right")
            if z <= a:
                continue
            sl = rows[order[a:z]]
            items, _ = candidate_items(sl, kept, set(), gates, legs_full, fps)
            b = f"{h:02d}:{15 * q:02d}"
            for it in items:
                if not (t_lo <= it["t_cross"] < t_hi):
                    continue
                dr = ld.get(it["origin_leg_id"])
                if not dr:
                    continue
                F["appr"][(b, dr)][2] += 1
                if it["movement"]:
                    F["mov"][(b, f"{dr} {NORM.get(it['movement'], it['movement'])}")][2] += 1
                else:   # unseen exit: spread over the approach's cells by OUR counts in the bin (risk only)
                    tot = defaultdict(int)
                    for tm, cc in ours["mov"].items():
                        if bin_key(tm) == b:
                            for k, v in cc.items():
                                if k[0] == dr:
                                    tot[k] += v
                    s = sum(tot.values())
                    for k, v in tot.items():
                        F["mov"][(b, f"{k[0]} {k[1]}")][2] += v / s if s else 0
    if link:
        for (b, dr), r in link.items():
            F["appr"][(b, dr)][3] += r
            tot = defaultdict(int)
            for tm, cc in ours["mov"].items():
                if bin_key(tm) == b:
                    for k, v in cc.items():
                        if k[0] == dr:
                            tot[k] += v
            s = sum(tot.values())
            for k, v in tot.items():
                F["mov"][(b, f"{k[0]} {k[1]}")][3] += r * v / s if s else 0
    refa = defaultdict(lambda: defaultdict(int))
    for m, cc in mio.items():
        for k, v in cc.items():
            refa[m][k[0]] += v
    out = {}
    for lvl, ref in (("mov", mio), ("appr", refa)):
        rr = []
        for r in score_cells(ours[lvl], ref, mm):
            rr.append({"cam": cam, "w": base, "bin": r["bin"], "cell": r["cell"], "ours": r["ours"], "ref": r["ref"],
                       "ok": r["ok"], "err": r["ours"] - r["ref"],
                       "ex": max(0.0, abs(r["ours"] - r["ref"]) - tolerance(r["ref"])),
                       "tol": tolerance(max(r["ours"], 1)), "f": F[lvl][(r["bin"], r["cell"])].copy()})
        out[lvl] = rr
    return out, evs


def corridor_links(per_cam_events, legs_card, ld_by_cam):
    """Lagged per-bin residual on each receiving approach: {cam: {(bin, dir): sent - received}}."""
    out = defaultdict(dict)
    lags = {}
    for a, b in ((1, 2), (2, 3), (3, 4), (4, 5)):
        for snd, rcv, exit_card, entry_card in ((a, b, "N", "S"), (b, a, "S", "N")):
            if snd not in per_cam_events or rcv not in per_cam_events:
                continue
            sent, recv = defaultdict(int), defaultdict(int)
            for e in per_cam_events[snd]:
                if legs_card[snd].get(e["d"]) == exit_card:
                    sent[e["wall"].replace(second=0, microsecond=0)] += 1
            dr = None
            for e in per_cam_events[rcv]:
                if legs_card[rcv].get(e["o"]) == entry_card:
                    recv[e["wall"].replace(second=0, microsecond=0)] += 1
                    dr = ld_by_cam[rcv].get(e["o"])
            common = sorted(set(recv))
            if not common or dr is None:
                continue
            best = (-2, 0)
            for lag in range(MAX_LAG_MIN + 1):
                xs = np.array([sent.get(m - timedelta(minutes=lag), 0) for m in common], dtype=float)
                ys = np.array([recv[m] for m in common], dtype=float)
                if xs.std() > 0 and ys.std() > 0:
                    cc = float(np.corrcoef(xs, ys)[0, 1])
                    if cc > best[0]:
                        best = (cc, lag)
            lag = best[1]
            lags[(snd, rcv)] = best
            res = defaultdict(int)
            have = set()
            for m in common:
                k = bin_key(m.time())
                have.add(k)
                res[k] += sent.get(m - timedelta(minutes=lag), 0) - recv[m]
            # only bins where the sender was recording too
            snd_bins = {bin_key(e["wall"].time()) for e in per_cam_events[snd]}
            for k, v in res.items():
                if k in snd_bins:
                    out[rcv][(k, dr)] = out[rcv].get((k, dr), 0) + v
    return out, lags


def design(rows):
    X = np.array([[r["f"][0], r["f"][1], -r["f"][2], -r["f"][3]] for r in rows], dtype=float)
    y = np.array([r["err"] for r in rows], dtype=float)
    return X, y


def fit(rows):
    X, y = design(rows)
    # nonneg on a, b, c, d: est = X @ w with the signs folded into X
    w, _ = nnls(X, y)
    return w


def rank_report(rows, score, label):
    fail = [r for r in rows if not r["ok"]]
    tex = sum(r["ex"] for r in fail)
    order = np.argsort(-np.asarray(score), kind="stable")
    out = []
    for top in TOPS:
        k = int(round(top * len(rows)))
        sel = [rows[i] for i in order[:k]]
        got = sum(r["ex"] for r in sel if not r["ok"])
        nf = sum(not r["ok"] for r in sel)
        out.append((top, nf, len(fail), got, tex))
    print(f"    {label:26} " + "  ".join(f"top{int(t * 100)}%: {nf}/{n} fail, {100 * g / max(tx, 1):3.0f}% excess"
                                         for t, nf, n, g, tx in out))
    return out


def risk(rows, w):
    X, _ = design(rows)
    est = X @ w
    return [abs(e) / r["tol"] for e, r in zip(est, rows)], est


def main() -> int:
    stem = sys.argv[1] if len(sys.argv) > 1 else "mm1"
    site = SITES[CORRIDOR]
    con = sqlite3.connect(f"file:data/projects/{CORRIDOR}/project.db?mode=ro", uri=True)
    legs_card = defaultdict(dict)
    for lid, cam, card in con.execute("SELECT leg_id, camera_id, cardinal_direction FROM legs"):
        legs_card[cam][lid] = (card or "").strip().upper()
    ld_by_cam = {cam: leg_dir_for(CORRIDOR, cam, site) for cam in range(1, 6)}
    # pass 1: events of every window, for the corridor links (per camera, all its windows)
    per_cam = defaultdict(list)
    for cam, w in WINDOWS:
        per_cam[cam] += window_events(CORR_BASE / f"{stem}_cam{cam}_{w}.db", cam, site)
    link, lags = corridor_links(per_cam, legs_card, ld_by_cam)
    print("CORRIDOR LINKS (lag in minutes chosen by correlation):")
    for k, (cc, lag) in sorted(lags.items()):
        print(f"  cam{k[0]} -> cam{k[1]}: lag {lag} min  r {cc:.2f}")
    rows = {"mov": [], "appr": []}
    for cam, w in WINDOWS:
        chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
        db = CORR_BASE / f"{stem}_cam{cam}_{w}.db"
        dump = rows_for(CORRIDOR, cam, chash, w, db)
        lo, hi = site["windows"][w]
        cells, _ = window_cells(CORRIDOR, cam, w, db, dump, site, float(fps), lo, hi, link.get(cam))
        for lvl in rows:
            rows[lvl] += cells[lvl]
        f = np.array([r["f"] for r in cells["mov"]])
        print(f"cam{cam} {w}: {len(cells['mov'])} movement cell-bins; ENC {f[:, 0].sum():.0f} PART {f[:, 1].sum():.0f} "
              f"MISS {f[:, 2].sum():.0f} LINK {f[:, 3].sum():+.0f}", flush=True)
    # FM 51 (held-out site, single intersection: LINK = 0)
    fsite = SITES[FM51]
    fcon = sqlite3.connect(f"file:data/projects/{FM51}/project.db?mode=ro", uri=True)
    fchash, ffps = fcon.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (FM51_CAM,)).fetchone()
    fm = {"mov": [], "appr": []}
    for v in FM51_VARIANTS:
        db = FM51_BASE / f"{stem}_cam{FM51_CAM}_{v}.db"
        dump = rows_for(FM51, FM51_CAM, fchash, v, db)
        lo, hi = fsite["windows"][v.replace("vl3_l1_", "")]
        cells, _ = window_cells(FM51, FM51_CAM, v, db, dump, fsite, float(ffps), lo, hi, None)
        for lvl in fm:
            fm[lvl] += cells[lvl]
        print(f"FM51 {v}: {len(cells['mov'])} movement cell-bins", flush=True)

    verdict = {}
    for lvl, name in (("mov", "MOVEMENT"), ("appr", "APPROACH")):
        R = rows[lvl]
        print(f"\n=== {name} cell-bins: {len(R)}, failing {sum(not r['ok'] for r in R)}, "
              f"excess {sum(r['ex'] for r in R):.0f}")
        # leave one camera out
        loco = [None] * len(R)
        for cam in range(1, 6):
            tr = [r for r in R if r["cam"] != cam]
            w = fit(tr)
            idx = [i for i, r in enumerate(R) if r["cam"] == cam]
            sc, _ = risk([R[i] for i in idx], w)
            for i, s in zip(idx, sc):
                loco[i] = s
            print(f"  fold cam{cam}: weights ENC {w[0]:.3f} PART {w[1]:.3f} MISS {w[2]:.3f} LINK {w[3]:.3f}")
        print("  FLEET (each camera scored with weights fit on the other four):")
        rank_report(R, [r["ours"] for r in R], "baseline: our count")
        rank_report(R, [r["f"][0] / r["tol"] for r in R], "baseline: ENC / tolerance")
        fleet = rank_report(R, loco, "RISK (leave-one-camera-out)")
        per_cam_ok = True
        for cam in range(1, 6):
            idx = [i for i, r in enumerate(R) if r["cam"] == cam]
            res = rank_report([R[i] for i in idx], [loco[i] for i in idx], f"  cam{cam}")
            t20 = [x for x in res if x[0] == 0.2][0]
            if t20[4] and t20[3] / t20[4] < 0.6:
                per_cam_ok = False
        w_all = fit(R)
        print(f"  weights on all 5 cameras: ENC {w_all[0]:.3f} PART {w_all[1]:.3f} MISS {w_all[2]:.3f} LINK {w_all[3]:.3f}")
        F = fm[lvl]
        fsc, _ = risk(F, w_all)
        print(f"  FM 51 ({len(F)} cell-bins, failing {sum(not r['ok'] for r in F)}, excess {sum(r['ex'] for r in F):.0f}):")
        rank_report(F, [r["ours"] for r in F], "baseline: our count")
        fmr = rank_report(F, fsc, "RISK (corridor weights)")
        # direction on the failing ones (LOCO estimate sign vs truth)
        est_sign = []
        for cam in range(1, 6):
            w = fit([r for r in R if r["cam"] != cam])
            _, est = risk([r for r in R if r["cam"] == cam], w)
            est_sign += [(e, r) for e, r in zip(est, [r for r in R if r["cam"] == cam])]
        fails = [(e, r) for e, r in est_sign if not r["ok"]]
        right = sum((e > 0) == (r["err"] > 0) for e, r in fails)
        print(f"  direction on failing cell-bins (over vs under): {right}/{len(fails)} right")
        f20 = [x for x in fleet if x[0] == 0.2][0]
        m20 = [x for x in fmr if x[0] == 0.2][0]
        verdict[name] = (f20[3] / max(f20[4], 1) >= 0.8, per_cam_ok, (m20[4] == 0) or m20[3] / m20[4] >= 0.8)
    for name, (a, b, c) in verdict.items():
        print(f"GATE R {name}: fleet top-20% >= 80% excess {'PASS' if a else 'FAIL'}; every camera >= 60% "
              f"{'PASS' if b else 'FAIL'}; FM 51 >= 80% {'PASS' if c else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
