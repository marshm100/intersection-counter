"""Step T1 (2026-10-10): appearance as a TIE-BREAKER, offline. Declared in docs/plan_basis_2026-09-11.md
"STEP T1 DECLARED"; plan C:\\Users\\marsh\\.claude\\plans\\yes-plan-all-of-quiet-pearl.md.

av1 / rv1 asked "does this box look like my car?" on every contested frame and failed on base rate. T1 asks the
relative question only where MOTION IS TORN. The dump's tracker is re-run in process (research_thefts.stage_run)
with the tracker's decision_log on: per s1 / s25 match, the chosen box and cost, the track's runner-up box and
cost, the rival track for the chosen box and its cost.
  row tie     runner-up cost - chosen cost <= M; FLIP when the track's memory is nearer the runner-up box
              than the chosen box by > D
  column tie  rival cost - chosen cost <= M; FLIP when the rival's memory is nearer the chosen box than the
              track's own memory is, by > D
Memory (v1 rule; --memory gallery is step 2): the normalised mean of the track's last 0.5 s of box embeddings
(.ver1 sidecar) before the decision frame, >= 2 needed. Truth = yardstick chains (vehicles_all_*.json): a box's
chain by IoU >= LABEL_IOU; a track's chain = its majority over the last 1 s (>= 80% of >= 3 labelled boxes).
FIX = motion picked the wrong car and the flip the right one; BREAK = the reverse; the rest NEUTRAL. Census
switches (thefts_<proj>_<cam>_<variant>.json; THEFT / EMERGENCE / A ENDS) are matched to a decision at
f_first_B whose chosen box overlaps box_B >= 0.95: CAUGHT = that decision is a FIX.
Operating point (M, D) = max FIX - BREAK on the FIRST variant, applied unchanged to the rest.
GATE T1 (every window): FIX >= 2 x BREAK AND CAUGHT >= 15% of the census's wrong switches.
Read-only. Usage:
  .venv/Scripts/python.exe -X utf8 scripts/research_tiebreak.py PROJ CAM VARIANT [VARIANT ...] [--memory gallery]
  [--smoke N  (first N frames only: a plumbing check, never a result)]
Writes runs/v2_week1/tiebreak_<proj>_<cam>_<variant>[_gallery].json and tiebreak_sheet_*.png
"""
from __future__ import annotations

import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.pass2_replay import tracks_dir  # noqa: E402
from research_thefts import LABEL_IOU, iou_mat, stage_run  # noqa: E402
from research_tracker_break import base_variant  # noqa: E402

MS = (0.05, 0.1, 0.2)
DS = (0.0, 0.05, 0.1)
MEM_S = 0.5
CHAIN_S = 1.0
CHAIN_SHARE = 0.8
JOIN_IOU = 0.7          # a history box to its detector row
DEC_IOU = 0.95          # a decision box (a detector box) to its row; a census box to a decision
WRONG = ("THEFT", "EMERGENCE", "A ENDS")
GALLERY_N = 5
GALLERY_SEP_S = 0.3
CLEAN_IOU = 0.05
SHEET_N = 40


class Frames:
    """Parquet rows by frame: boxes, conf, chain label; lookups by box."""

    def __init__(self, pqp: Path, veh: list):
        t = pq.read_table(pqp, columns=["frame_idx", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "confidence"])
        self.fr = t.column("frame_idx").to_numpy().astype(np.int64)
        self.bb = np.stack([t.column(c).to_numpy() for c in ("bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2")],
                           axis=1).astype(np.float64)
        self.conf = t.column("confidence").to_numpy().astype(np.float64)
        pf, ps = np.unique(self.fr, return_index=True)
        pe = np.append(ps[1:], len(self.fr))
        self.span = {int(f): (int(a), int(b)) for f, a, b in zip(pf, ps, pe)}
        cf = defaultdict(list)
        for vi, v in enumerate(veh):
            for h in v:
                cf[int(h[0])].append((vi, h[1], h[2], h[3], h[4]))
        # chain label + "clean" (no other box overlapping) for every parquet row
        self.chain = np.full(len(self.fr), -1, dtype=np.int64)
        self.clean = np.zeros(len(self.fr), dtype=bool)
        for f, (a, b) in self.span.items():
            D = self.bb[a:b]
            if b - a > 1:
                m = iou_mat(D, D)
                np.fill_diagonal(m, 0.0)
                self.clean[a:b] = m.max(axis=1) <= CLEAN_IOU
            else:
                self.clean[a:b] = True
            c = cf.get(f)
            if c:
                C = np.asarray([x[1:] for x in c], dtype=np.float64)
                m = iou_mat(D, C)
                k = m.argmax(axis=1)
                ok = m[np.arange(len(k)), k] >= LABEL_IOU
                self.chain[a:b][ok] = np.asarray([c[j][0] for j in k[ok]])

    def row(self, f: int, box, thr: float) -> int:
        s = self.span.get(int(f))
        if s is None or box is None:
            return -1
        m = iou_mat(np.asarray([box], dtype=np.float64), self.bb[s[0]:s[1]])[0]
        j = int(m.argmax())
        return s[0] + j if m[j] >= thr else -1


def window(proj: str, cam: int, variant: str, smoke: int = 0) -> dict:
    con = sqlite3.connect(f"file:data/projects/{proj}/project.db?mode=ro", uri=True)
    chash, fps, vw, vh, vpath = con.execute(
        "SELECT content_hash, fps, width, height, path FROM videos WHERE camera_id=?", (cam,)).fetchone()
    fps = float(fps)
    pqp = parquet_path(proj, cam, chash, variant)
    meta = json.loads((tracks_dir(pqp) / "meta.json").read_text())
    if smoke:
        meta["frames"] = [meta["frames"][0], meta["frames"][0] + smoke]
    veh = json.loads(Path(f"runs/v2_week1/vehicles_all_{proj}_{cam}_{base_variant(variant)}.json").read_text())
    ev = json.loads(Path(f"runs/v2_week1/thefts_{proj}_{cam}_{variant}.json").read_text())
    emb = np.load(pqp.with_name(pqp.stem + ".ver1") / "emb.npy", mmap_mode="r")
    t0 = time.time()
    P = Frames(pqp, veh)
    print(f"{variant}: parquet {len(P.fr)} rows, chain-labelled {np.mean(P.chain >= 0):.3f} "
          f"({time.time() - t0:.0f}s)", flush=True)
    t0 = time.time()
    extra = {"decision": []}
    by_box, _ = stage_run(proj, cam, variant, meta, (int(vw), int(vh)) if vw and vh else None, extra)
    dec = extra["decision"]
    print(f"  in-process tracker: {sum(len(v) for v in by_box.values())} boxes, {len(dec)} decisions with a "
          f"runner-up or rival ({time.time() - t0:.0f}s)", flush=True)

    # each track's history: frame, parquet row (or -1), chain
    t0 = time.time()
    hist = defaultdict(list)
    for f, lst in by_box.items():
        s = P.span.get(int(f))
        if s is None:
            for box, tid in lst:
                hist[int(tid)].append((int(f), -1))
            continue
        B = np.asarray([b for b, _ in lst], dtype=np.float64)
        m = iou_mat(B, P.bb[s[0]:s[1]])
        k = m.argmax(axis=1)
        ok = m[np.arange(len(k)), k] >= JOIN_IOU
        for (box, tid), kk, o in zip(lst, k, ok):
            hist[int(tid)].append((int(f), s[0] + int(kk) if o else -1))
    H = {}
    for tid, h in hist.items():
        h.sort()
        a = np.asarray(h, dtype=np.int64)
        H[tid] = (a[:, 0], a[:, 1])
    print(f"  histories for {len(H)} tracks ({time.time() - t0:.0f}s)", flush=True)
    return {"variant": variant, "fps": fps, "P": P, "emb": emb, "H": H, "dec": dec, "events": ev,
            "vpath": vpath}


def _unit(v: np.ndarray) -> np.ndarray | None:
    n = float(np.linalg.norm(v))
    return v / n if n > 0 else None


def track_chain(W: dict, tid: int, f: int) -> int:
    h = W["H"].get(tid)
    if h is None:
        return -1
    fr, rows = h
    a, b = np.searchsorted(fr, f - CHAIN_S * W["fps"]), np.searchsorted(fr, f)
    r = rows[a:b]
    lab = W["P"].chain[r[r >= 0]]
    lab = lab[lab >= 0]
    if len(lab) < 3:
        return -1
    c, n = Counter(lab.tolist()).most_common(1)[0]
    return int(c) if n >= CHAIN_SHARE * len(lab) else -1


def memory(W: dict, tid: int, f: int, mode: str):
    """('mean', unit vector) or ('gallery', [(width, unit vector)]) from the track's boxes before frame f."""
    h = W["H"].get(tid)
    if h is None:
        return None
    fr, rows = h
    b = np.searchsorted(fr, f)
    ok = rows[:b] >= 0
    r, rf = rows[:b][ok], fr[:b][ok]
    if mode == "mean":
        r = r[-max(2, int(round(MEM_S * W["fps"]))):]
        E = np.asarray(W["emb"][np.sort(r)], dtype=np.float32) if len(r) else np.zeros((0, 1))
        E = E[np.linalg.norm(E, axis=1) > 0] if len(E) else E
        return ("mean", _unit(E.mean(axis=0))) if len(E) >= 2 else None
    # gallery: the best views - clean boxes, by conf x width, at least GALLERY_SEP_S apart
    P = W["P"]
    cl = P.clean[r]
    r, rf = r[cl], rf[cl]
    if len(r) < 2:
        return None
    w = P.bb[r, 2] - P.bb[r, 0]
    q = P.conf[r] * w
    picked: list[int] = []
    for i in np.argsort(-q):
        if all(abs(rf[i] - rf[j]) >= GALLERY_SEP_S * W["fps"] for j in picked):
            picked.append(int(i))
            if len(picked) == GALLERY_N:
                break
    G = []
    for i in picked:
        e = _unit(np.asarray(W["emb"][r[i]], dtype=np.float32))
        if e is not None:
            G.append((float(w[i]), e))
    return ("gallery", G) if len(G) >= 2 else None


def dist(mem, row: int, W: dict) -> float:
    if mem is None or row < 0:
        return np.nan
    e = _unit(np.asarray(W["emb"][row], dtype=np.float32))
    if e is None:
        return np.nan
    if mem[0] == "mean":
        return 1.0 - float(mem[1] @ e)
    w = float(W["P"].bb[row, 2] - W["P"].bb[row, 0])
    gw, ge = min(mem[1], key=lambda g: abs(np.log(max(g[0], 1.0) / max(w, 1.0))))
    return 1.0 - float(ge @ e)


def _truth(owner: int, a: int, b: int, a_right: bool, b_right: bool, same: bool) -> str:
    """FIX / BREAK, or why NEUTRAL: nt:track (no clear chain), nt:box (unlabelled box), nt:same (one car -
    a duplicate box, or the rival on the same car), nt:both (both right or both wrong)."""
    if owner < 0:
        return "nt:track"
    if a < 0 or b < 0:
        return "nt:box"
    if same:
        return "nt:same"
    if not a_right and b_right:
        return "FIX"
    if a_right and not b_right:
        return "BREAK"
    return "nt:both"


def prepare(W: dict, mode: str) -> list[dict]:
    """Every decision torn at the widest M, with its appearance distances and its truth."""
    P, mmax = W["P"], max(MS)
    out = []
    t0 = time.time()
    for rec in W["dec"]:
        f, tid, stage, was_lost, C, cc, R, cr, kid, ck, KD = rec
        row_t, col_t = cr - cc <= mmax, ck - cc <= mmax
        if not (row_t or col_t):
            continue
        rc = P.row(f, C, DEC_IOU)
        x_t = track_chain(W, tid, f)
        mt = memory(W, tid, f, mode)
        d = {"f": f, "tid": tid, "stage": stage, "C": C, "rowC": rc, "dm_row": np.inf, "dm_col": np.inf}
        chC = int(P.chain[rc]) if rc >= 0 else -1
        dTC = dist(mt, rc, W)
        if row_t:
            rr = P.row(f, R, DEC_IOU)
            chR = int(P.chain[rr]) if rr >= 0 else -1
            dTR = dist(mt, rr, W)
            truth = _truth(x_t, chC, chR, chC == x_t, chR == x_t, chC == chR)
            d.update(dm_row=cr - cc, app_row=dTC - dTR, truth_row=truth, R=R, rowR=rr)
        if col_t:
            x_k = track_chain(W, kid, f)
            dKC = dist(memory(W, kid, f, mode), rc, W)
            truth = _truth(min(x_t, x_k), chC, chC, chC == x_t, chC == x_k, x_t == x_k)
            d.update(dm_col=ck - cc, app_col=dTC - dKC, truth_col=truth, kid=kid)
        out.append(d)
    print(f"  {len(out)} decisions torn at M <= {mmax} ({time.time() - t0:.0f}s)", flush=True)
    return out


def census_map(W: dict, torn: list[dict]) -> tuple[dict, int]:
    """wrong census switch -> index into torn (or absent)."""
    by_f = defaultdict(list)
    for i, d in enumerate(torn):
        by_f[d["f"]].append(i)
    n_wrong, hit = 0, {}
    for k, e in enumerate(W["events"]):
        if e["kind"] not in WRONG:
            continue
        n_wrong += 1
        for i in by_f.get(int(e["f_first_B"]), []):
            if iou_mat(np.asarray([e["box_B"]]), np.asarray([torn[i]["C"]]))[0, 0] >= DEC_IOU:
                hit[k] = i
                break
    return hit, n_wrong


def flips(d: dict, M: float, D: float) -> list[str]:
    """Truths of the flips this decision makes at (M, D): row, column, or both."""
    out = []
    if d["dm_row"] <= M and np.isfinite(d.get("app_row", np.nan)) and d["app_row"] > D:
        out.append(d["truth_row"])
    if d["dm_col"] <= M and np.isfinite(d.get("app_col", np.nan)) and d["app_col"] > D:
        out.append(d["truth_col"])
    return out


def evaluate(torn: list[dict], hit: dict, n_wrong: int, M: float, D: float) -> dict:
    c = Counter()
    fix_idx = set()
    n_torn = 0
    for i, d in enumerate(torn):
        if d["dm_row"] <= M or d["dm_col"] <= M:
            n_torn += 1
        fl = flips(d, M, D)
        c.update(fl)
        c["flip"] += bool(fl)
        if "FIX" in fl:
            fix_idx.add(i)
    caught = sum(1 for i in hit.values() if i in fix_idx)
    nt = {k: v for k, v in c.items() if k.startswith("nt:")}
    return {"M": M, "D": D, "torn": n_torn, "flips": c["flip"], "fix": c["FIX"], "break": c["BREAK"],
            "neutral": sum(nt.values()), "neutral_why": nt, "net": c["FIX"] - c["BREAK"], "census_at_torn": len(hit),
            "caught": caught, "n_wrong": n_wrong, "caught_share": caught / max(n_wrong, 1)}


def fmt(r: dict) -> str:
    return (f"M {r['M']:.2f} D {r['D']:.2f}: torn {r['torn']:>6}  flips {r['flips']:>5}  FIX {r['fix']:>4}  "
            f"BREAK {r['break']:>4}  nt {r['neutral']:>5}  net {r['net']:+5d}  caught {r['caught']:>3}/{r['n_wrong']} "
            f"({r['caught_share']:.0%}; {r['census_at_torn']} switches start at a torn decision)  nt why "
            + " ".join(f"{k[3:]} {v}" for k, v in sorted(r["neutral_why"].items())))


def sheet(W: dict, torn: list[dict], M: float, D: float, tag: str) -> None:
    """Contact sheet: SHEET_N random FIX and BREAK flips - track's last box before f | chosen | other."""
    import cv2
    from backend.services.vehicle_verifier import square_crop
    rng = np.random.default_rng(0)
    for kind in ("FIX", "BREAK"):
        pick = [d for d in torn if kind in flips(d, M, D)]
        if not pick:
            continue
        pick = [pick[i] for i in sorted(rng.choice(len(pick), min(SHEET_N, len(pick)), replace=False),
                                        key=lambda i: pick[i]["f"])]
        cap = cv2.VideoCapture(W["vpath"])
        tiles = []
        for d in pick:
            fr, rows = W["H"][d["tid"]]
            b = np.searchsorted(fr, d["f"]) - 1
            row_kind = d["dm_row"] <= M and d.get("truth_row") == kind and d.get("app_row", -1) > D
            other = d.get("R") if row_kind else None
            prev_f = int(fr[b]) if b >= 0 else d["f"]
            prev_box = W["P"].bb[rows[b]] if b >= 0 and rows[b] >= 0 else None
            crops = []
            for f, box in ((prev_f, prev_box), (d["f"], d["C"]), (d["f"], other)):
                if box is None:
                    crops.append(np.zeros((96, 96, 3), np.uint8))
                    continue
                cap.set(cv2.CAP_PROP_POS_FRAMES, f)
                ok, img = cap.read()
                crops.append(square_crop(img, np.asarray(box, dtype=np.float32), 96) if ok
                             else np.zeros((96, 96, 3), np.uint8))
            t = np.concatenate(crops, axis=1)
            lab = f"f{d['f']} {d['stage']} {'row' if row_kind else 'col k' + str(d.get('kid'))}"
            t = cv2.copyMakeBorder(t, 14, 2, 2, 2, cv2.BORDER_CONSTANT, value=(255, 255, 255))
            cv2.putText(t, lab, (2, 11), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1)
            tiles.append(t)
        cap.release()
        cols = 4
        while len(tiles) % cols:
            tiles.append(np.full_like(tiles[0], 255))
        grid = np.concatenate([np.concatenate(tiles[i:i + cols], axis=1) for i in range(0, len(tiles), cols)])
        out = Path(f"runs/v2_week1/tiebreak_sheet_{tag}_{kind}.png")
        cv2.imwrite(str(out), grid)
        print(f"  sheet -> {out} (memory's last box | motion's choice | runner-up, blank = column tie)")


def main() -> int:
    smoke = int(sys.argv[sys.argv.index("--smoke") + 1]) if "--smoke" in sys.argv else 0
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if smoke:
        args.remove(str(smoke))
    mode = "gallery" if "--memory" in sys.argv and sys.argv[sys.argv.index("--memory") + 1] == "gallery" else "mean"
    args = [a for a in args if a != "gallery"]
    proj, cam, variants = args[0], int(args[1]), args[2:]
    chosen, verdict = None, []
    for vi, v in enumerate(variants):
        W = window(proj, cam, v, smoke)
        torn = prepare(W, mode)
        hit, n_wrong = census_map(W, torn)
        grid = [evaluate(torn, hit, n_wrong, M, D) for M in MS for D in DS]
        for r in grid:
            print("  " + fmt(r), flush=True)
        if vi == 0:
            chosen = max(grid, key=lambda r: r["net"])
            print(f"  OPERATING POINT (max FIX - BREAK on {v}): M {chosen['M']}, D {chosen['D']}")
        op = next(r for r in grid if r["M"] == chosen["M"] and r["D"] == chosen["D"])
        ok = op["fix"] >= 2 * op["break"] and op["caught_share"] >= 0.15
        verdict.append(ok)
        print(f"  {v} [{mode} memory]: {fmt(op)} -> {'PASS' if ok else 'FAIL'}", flush=True)
        tag = f"{proj}_{cam}_{v}" + ("_gallery" if mode == "gallery" else "") + ("_smoke" if smoke else "")
        Path(f"runs/v2_week1/tiebreak_{tag}.json").write_text(json.dumps(
            {"memory": mode, "grid": grid, "chosen_on": variants[0], "operating_point": op}, indent=1))
        sheet(W, torn, chosen["M"], chosen["D"], tag)
        print()
    print(f"GATE T1 [{mode} memory] (FIX >= 2 x BREAK AND caught >= 15%, every window): "
          f"{'PASS' if all(verdict) else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
