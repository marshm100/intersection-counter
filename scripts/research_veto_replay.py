"""Replay rv1 (2026-10-10, operator: "go for it"): the same-car check, offline, over the PRODUCTION dumps.

Arm av1 refused a contested match on ONE bad look and broke ~26 cars per switch it stopped (9.88). This
replays the decision rule - no re-track - to ask whether a longer memory (MEM) and "K bad looks in a row"
fix that. Declared in docs/plan_basis_2026-09-11.md "REPLAY rv1 DECLARED".

Per track (dump rows in frame order), each row joined to its detector box (IoU >= JOIN_IOU) and that
box's car-verifier embedding (<variant>.ver1/emb.npy). A row is CONTESTED when >= 2 detector boxes
(conf > 0.1, the tracker's own box included - as live) have their centre within NEAR_W box widths of the
row's centre. At a contested row with an embedding, the box is compared with the normalised mean of the
track's last MEM valid embeddings (>= 2 needed): cosine distance > THRESH fails. K consecutive failed
checks CUT the track at the first of them; memory restarts there.
Truth = the theft census of the same dump (runs/v2_week1/thefts_<proj>_<cam>_<variant>.json): a cut is
TRUE within [f_last_A - TOL, f_first_B + MEM + TOL] of a THEFT / EMERGENCE / A ENDS switch on that track,
NEUTRAL near a CHAIN SEAM, else FALSE. One-track lost = yardstick vehicles covered by exactly one id
that receive a FALSE cut on a row labelled to them.
Read-only. Usage:
  .venv/Scripts/python.exe -X utf8 scripts/research_veto_replay.py PROJ CAM VARIANT [VARIANT ...]
The operating point is chosen on the FIRST variant and applied unchanged to the rest.
Writes runs/v2_week1/veto_replay_<proj>_<cam>_<variant>.json
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir  # noqa: E402
from research_thefts import LABEL_IOU, iou_mat  # noqa: E402
from research_tracker_break import base_variant  # noqa: E402

JOIN_IOU = 0.7
NEAR_W = 2.0          # TRACKER_APPEARANCE_NEAR_W
THRESH = 0.482        # TRACKER_APPEARANCE_THRESH (verifier_v1_all's 1%-of-same-car point) - not swept
LOW_CONF = 0.1        # the tracker's inds_low: boxes that count as contestants
TOL_S = 0.5
MEMS = (0.5, 1.0, 2.0)
KS = (1, 3, 5)
WRONG = ("THEFT", "EMERGENCE", "A ENDS")


def _boxes(r: np.ndarray) -> np.ndarray:
    return np.stack([r[:, 2] - r[:, 4] / 2, r[:, 3] - r[:, 5] / 2,
                     r[:, 2] + r[:, 4] / 2, r[:, 3] + r[:, 5] / 2], axis=1)


def window(proj: str, cam: int, variant: str) -> dict:
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    pqp = parquet_path(proj, cam, chash, variant)
    rows = np.array(load_dump(tracks_dir(pqp)), dtype=np.float64, copy=True)
    rows = rows[np.argsort(rows[:, 1], kind="stable")]
    t = pq.read_table(pqp, columns=["frame_idx", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"])
    pfr = t.column("frame_idx").to_numpy().astype(np.int64)
    pbb = np.stack([t.column(c).to_numpy() for c in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2")],
                   axis=1).astype(np.float64)
    pcf = t.column("confidence").to_numpy()
    emb_mm = np.load(pqp.with_name(pqp.stem + ".ver1") / "emb.npy", mmap_mode="r")
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    ev = json.loads(Path(f"runs/v2_week1/thefts_{proj}_{cam}_{variant}.json").read_text())

    cf = defaultdict(list)
    for vi, v in enumerate(veh):
        for h in v:
            cf[int(h[0])].append((vi, h[1], h[2], h[3], h[4]))

    n = len(rows)
    join = np.full(n, -1, dtype=np.int64)
    contested = np.zeros(n, dtype=bool)
    lab = np.full(n, -1, dtype=np.int64)
    B = _boxes(rows)
    pf, ps = np.unique(pfr, return_index=True)
    pe = np.append(ps[1:], len(pfr))
    uf, s_ = np.unique(rows[:, 1].astype(np.int64), return_index=True)
    e_ = np.append(s_[1:], n)
    pos = np.searchsorted(pf, uf)
    for f, a, b, p in zip(uf, s_, e_, pos):
        R = B[a:b]
        if p < len(pf) and pf[p] == f:
            D = pbb[ps[p]:pe[p]]
            m = iou_mat(R, D)
            k = m.argmax(axis=1)
            ok = m[np.arange(len(k)), k] >= JOIN_IOU
            join[a:b][ok] = ps[p] + k[ok]
            low = pcf[ps[p]:pe[p]] > LOW_CONF
            if low.any():
                dc = (D[low, :2] + D[low, 2:]) / 2
                rc = rows[a:b, 2:4]
                w = np.maximum(rows[a:b, 4], 1.0)
                near = (np.hypot(rc[:, None, 0] - dc[None, :, 0], rc[:, None, 1] - dc[None, :, 1])
                        <= NEAR_W * w[:, None]).sum(axis=1)
                contested[a:b] = near >= 2
        c = cf.get(int(f))
        if c:
            C = np.asarray([x[1:] for x in c], dtype=np.float64)
            m = iou_mat(R, C)
            k = m.argmax(axis=1)
            ok = m[np.arange(len(k)), k] >= LABEL_IOU
            lab[a:b][ok] = np.asarray([c[j][0] for j in k[ok]])

    # one-track vehicles: every labelled row of the chain carries the same id
    ids_of = defaultdict(set)
    for tid, l in zip(rows[:, 0].astype(np.int64), lab):
        if l >= 0:
            ids_of[int(l)].add(int(tid))
    one_track = {c for c, s in ids_of.items() if len(s) == 1}

    order = np.lexsort((rows[:, 1], rows[:, 0]))
    rows, join, contested, lab = rows[order], join[order], contested[order], lab[order]
    ut, st_ = np.unique(rows[:, 0].astype(np.int64), return_index=True)
    en_ = np.append(st_[1:], n)
    tracks = []
    for tid, a, b in zip(ut, st_, en_):
        j = join[a:b]
        valid = j >= 0
        if valid.sum() < 3 or not (contested[a:b] & valid).any():
            continue
        tracks.append((int(tid), rows[a:b, 1].astype(np.int64), j, valid, contested[a:b], lab[a:b]))
    by_track = defaultdict(list)
    for e in ev:
        by_track[int(e["track"])].append(e)
    print(f"{variant}: {n} dump rows joined {np.mean(join >= 0):.3f}, contested {contested.mean():.3f}; "
          f"{len(tracks)} tracks checked; yardstick {len(veh)} vehicles, one-track {len(one_track)}; "
          f"census switches {len(ev)}", flush=True)
    return {"variant": variant, "fps": fps, "tracks": tracks, "emb": emb_mm, "events": by_track, "one_track": one_track,
            "n_wrong": sum(1 for e in ev if e["kind"] in WRONG),
            "n_swap": sum(1 for e in ev if e["kind"] == "THEFT" and e["swap_with"])}


def _cuts(E: np.ndarray, valid: np.ndarray, cont: np.ndarray, N: int, k: int, tally: list) -> list[int]:
    """Rows where K consecutive failed contested checks cut the track (at the first of them)."""
    cs = np.concatenate([np.zeros((1, E.shape[1])), np.cumsum(E, 0, dtype=np.float64)])
    vc = np.concatenate([[0], np.cumsum(valid)])        # valid embeddings strictly before row i
    vidx = np.flatnonzero(valid)
    start, run, first = 0, 0, -1
    cuts = []
    for i in np.flatnonzero(cont & valid):
        hi = vc[i]
        lo = max(hi - N, vc[start])
        if hi - lo < 2:
            continue
        m = cs[vidx[hi - 1] + 1] - cs[vidx[lo]]           # invalid rows are zero in E
        m /= max(float(np.linalg.norm(m)), 1e-9)
        tally[0] += 1
        if 1.0 - float(m @ E[i]) > THRESH:
            tally[1] += 1
            run += 1
            if run == 1:
                first = i
            if run == k:
                cuts.append(first)
                start, run = first, 0
        else:
            run = 0
    return cuts


def simulate(W: dict) -> list[dict]:
    fps = W["fps"]
    tol = TOL_S * fps
    cfgs = [(m, k) for m in MEMS for k in KS]
    acc = {c: {"tally": [0, 0], "tp": 0, "fp": 0, "nt": 0, "caught": set(), "lost": set()} for c in cfgs}
    emb_mm = W["emb"]
    for tid, fr, j, valid, cont, lab in W["tracks"]:
        E = np.zeros((len(fr), emb_mm.shape[1]), dtype=np.float32)
        E[valid] = np.asarray(emb_mm[j[valid]], dtype=np.float32)
        nrm = np.linalg.norm(E, axis=1)
        valid = valid & (nrm > 0)                         # zero row = box too small to embed
        E[valid] /= nrm[valid, None]
        E[~valid] = 0.0
        evs = W["events"].get(tid, [])
        for (mem_s, k) in cfgs:
            N = max(2, int(round(mem_s * fps)))
            a = acc[(mem_s, k)]
            for c in _cuts(E, valid, cont, N, k, a["tally"]):
                f = fr[c]
                near = [x for x, e in enumerate(evs) if e["f_last_A"] - tol <= f <= e["f_first_B"] + N + tol]
                hit = [x for x in near if evs[x]["kind"] in WRONG]
                if hit:
                    a["tp"] += 1
                    a["caught"].update((tid, x) for x in hit)
                elif near:
                    a["nt"] += 1
                else:
                    a["fp"] += 1
                    if lab[c] in W["one_track"]:
                        a["lost"].add(int(lab[c]))
    out = []
    for (mem_s, k), a in acc.items():
        n_swap = sum(1 for t_, x in a["caught"] if W["events"][t_][x]["kind"] == "THEFT"
                     and W["events"][t_][x]["swap_with"])
        out.append({"mem_s": mem_s, "k": k, "checks": a["tally"][0], "fails": a["tally"][1], "true": a["tp"],
                    "false": a["fp"], "neutral": a["nt"], "precision": a["tp"] / max(a["tp"] + a["fp"], 1),
                    "caught": len(a["caught"]), "caught_swaps": n_swap, "one_track_lost": len(a["lost"]),
                    "net": len(a["caught"]) - len(a["lost"])})
    return out


def fmt(r: dict, W: dict) -> str:
    return (f"MEM {r['mem_s']:.1f}s K {r['k']}: checks {r['checks']:>8} fail {r['fails']:>6}  cuts TRUE {r['true']:>4} "
            f"FALSE {r['false']:>5} nt {r['neutral']:>4}  P {r['precision']:.2f}  caught {r['caught']:>4}/{W['n_wrong']} "
            f"(swaps {r['caught_swaps']}/{W['n_swap']})  one-track lost {r['one_track_lost']:>4}  net {r['net']:+d}")


def main() -> int:
    proj, cam, variants = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
    results = {}
    chosen = None
    verdict = []
    for vi, v in enumerate(variants):
        W = window(proj, cam, v)
        grid = simulate(W)
        for r in grid:
            print("  " + fmt(r, W), flush=True)
        if vi == 0:
            chosen = max(grid, key=lambda r: r["net"])
            print(f"  OPERATING POINT (max caught - one-track lost on {v}): MEM {chosen['mem_s']} s, K {chosen['k']}")
        op = next(r for r in grid if r["mem_s"] == chosen["mem_s"] and r["k"] == chosen["k"])
        cal = next(r for r in grid if r["mem_s"] == 0.5 and r["k"] == 1)
        ok = op["precision"] >= 0.5 and op["caught"] > op["one_track_lost"]
        cal_ok = cal["precision"] >= 0.5 and cal["caught"] > cal["one_track_lost"]
        verdict.append(ok)
        print(f"  {v}: operating point {'PASS' if ok else 'FAIL'}; calibration (av1's rule MEM 0.5 K 1) "
              f"{'PASSES - the replay does NOT see what the re-track saw' if cal_ok else 'fails, as the re-track did'}\n",
              flush=True)
        results[v] = grid
        Path(f"runs/v2_week1/veto_replay_{proj}_{cam}_{v}.json").write_text(
            json.dumps({"grid": grid, "chosen_on": variants[0], "operating_point": op}, indent=1))
    print(f"GATE (precision >= 0.50 AND caught > one-track lost, every window): "
          f"{'PASS' if all(verdict) else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
