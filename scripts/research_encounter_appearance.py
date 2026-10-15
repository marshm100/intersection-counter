"""CAN APPEARANCE TELL TWO CARS APART WHERE THEIR TRACKS MEET? (2026-10-15, operator: "go for that, plan it
out"; plan C:\\Users\\marsh\\.claude\\plans\\proud-wiggling-swan.md, step 1 - a MEASUREMENT, nothing changes).
research_encounters: motion cannot (true swaps: swap smoother 3, keep smoother 12, too short 46). av1 used
appearance as a one-frame veto mid-overlap and failed. Here, offline, each car's look over CLEAN frames
BEFORE the meeting against CLEAN frames AFTER it, from the car verifier (verifier_v1_all, the .ver1 sidecar:
an embedding for every detection; learned from the sites' own tracks, no labels).
Encounters: two tracks labelled cars ride, centres within MEET_W widths, INSIDE the intersection (the
meeting lies between both cars' entry and exit clicks). Truth from the labels:
  SWAP  a car entered on one id and left on the other (the pair's closest in-box meeting)
  KEEP  each id carries one labelled car through
Side appearance = normalised mean of the track's latest (BEFORE) / earliest (AFTER) M s of CLEAN boxes within
2M s of the meeting - clean: not overlapping or abutting another detection (build_verifier_pairs.ambiguous),
width >= MIN_W, embedding non-zero. margin = keep - swap pairing distance (cosine); flip if margin > D.
  both sides of both ids:  keep = d(Ab,Aa) + d(Bb,Ba)   swap = d(Ab,Ba) + d(Bb,Aa)
  X has no AFTER (ends):   keep = d(Yb,Ya)              swap = d(Xb,Ya)
  X has no BEFORE (born):  keep = d(Yb,Ya)              swap = d(Yb,Xa)
  otherwise UNJUDGEABLE (counted)
GATE A (declared before running): at the (M, D) chosen on DEV, on dev AND held-out separately CAUGHT >=
2 x BROKEN and CAUGHT >= 30% of judgeable swaps; cam2 with verifier_v1_nocam2 (never saw cam2) also
CAUGHT >= 2 x BROKEN.
Usage: .venv/Scripts/python.exe -X utf8 scripts/research_encounter_appearance.py [STEM] [--nocam2]
"""
from __future__ import annotations

import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.services import journey_eval as je  # noqa: E402
from backend.services.detection_cache import parquet_path  # noqa: E402
from backend.services.journey_labels import list_clips, list_labels  # noqa: E402
from backend.services.two_pass import _appearance_embeddings  # noqa: E402
from build_verifier_pairs import MIN_W, ambiguous  # noqa: E402
from eval_journeys import PROJ, is_heldout, locate  # noqa: E402
from research_encounters import MEET_W, runs  # noqa: E402
from research_track_qc import join_rows  # noqa: E402

MS = (0.5, 1.0, 2.0)
DS = (0.0, 0.05, 0.1, 0.15, 0.2)
PAD_S = 60
NOCAM2 = Path("data/models/verifier_v1_nocam2.pt")


def unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 0 else None


class Clip:
    """One labelled clip: the dump rows near it joined to detector rows, clean flags, embeddings."""

    def __init__(self, clip, stem):
        con = sqlite3.connect(f"file:data/projects/{PROJ}/project.db?mode=ro", uri=True)
        self.cam = clip["camera_id"]
        self.window = "study_" + clip["clip_id"].split("_")[1]
        self.vpath, chash, fps = con.execute("SELECT path, content_hash, fps FROM videos WHERE video_id=?",
                                             (clip["video_id"],)).fetchone()
        self.fps = float(fps)
        con.close()
        db, rows = locate(stem, {}, self.cam, self.window, chash)
        self.f_lo, self.f_hi = int(clip["start_frame"]), int(clip["end_frame"])
        pad = int(PAD_S * self.fps)
        self.rows = rows[(rows[:, 1] >= self.f_lo - pad) & (rows[:, 1] <= self.f_hi + pad)]
        self.pqp = parquet_path(PROJ, self.cam, chash, self.window)
        self.join, self.bb = join_rows(self.rows, self.pqp)
        fr = pq.read_table(self.pqp, columns=["frame_idx"]).column("frame_idx").to_numpy().astype(np.int64)
        self.det_frame = fr
        lo, hi = np.searchsorted(fr, self.f_lo - pad), np.searchsorted(fr, self.f_hi + pad, side="right")
        self.clean = np.zeros(len(fr), dtype=bool)
        for f in np.unique(fr[lo:hi]):
            a, b = np.searchsorted(fr, f), np.searchsorted(fr, f, side="right")
            B = self.bb[a:b]
            self.clean[a:b] = ~ambiguous(B) & ((B[:, 2] - B[:, 0]) >= MIN_W)
        self.emb = _appearance_embeddings(self.pqp)
        self.override: dict[int, np.ndarray] = {}
        labels = list_labels(PROJ, clip["clip_id"])
        byf = je.index_rows(rows, self.f_lo - je.SEARCH_FRAMES, self.f_hi + je.SEARCH_FRAMES)
        dups = je.duplicate_labels(labels, self.fps, byf)
        self.labs = [lb for lb in labels if lb["label_id"] not in dups
                     and lb.get("entry_frame") is not None and lb.get("exit_frame") is not None]
        self.ein, self.eout = je._assign_clicks(self.labs, rows, byf, self.fps)
        self.idx = defaultdict(list)
        for i, t in enumerate(self.rows[:, 0].astype(int)):
            self.idx[t].append(i)

    def vec(self, j):
        if j in self.override:
            return self.override[j]
        v = np.asarray(self.emb[j], dtype=np.float32)
        return v if np.any(v) else None

    def side(self, t, f, m_s, before):
        """Normalised mean embedding of the track's clean boxes on one side of frame f (None if none)."""
        n_take = max(1, int(round(m_s * self.fps)))
        span = 2 * m_s * self.fps
        ii = self.idx.get(t, [])
        cand = []
        for i in ii:
            fr = self.rows[i, 1]
            if (before and f - span <= fr < f) or (not before and f < fr <= f + span):
                j = int(self.join[i])
                if j >= 0 and self.clean[j]:
                    v = self.vec(j)
                    if v is not None:
                        cand.append((fr, v))
        if not cand:
            return None
        cand.sort(key=lambda c: c[0], reverse=before)
        return unit(np.mean([v for _, v in cand[:n_take]], axis=0))

    def used_rows(self, t, f, m_s, before):
        span = 2 * m_s * self.fps
        out = []
        for i in self.idx.get(t, []):
            fr = self.rows[i, 1]
            if (before and f - span <= fr < f) or (not before and f < fr <= f + span):
                j = int(self.join[i])
                if j >= 0 and self.clean[j]:
                    out.append(j)
        return out


def encounters(C: Clip):
    """(A, B, fs, fe, truth) for in-box encounters of labelled cars' tracks."""
    one = {}
    for lb in C.labs:
        a, b = C.ein.get(lb["label_id"]), C.eout.get(lb["label_id"])
        if a is not None and a == b:
            one[a] = lb
    swapped = {}
    for lb in C.labs:
        a, b = C.ein.get(lb["label_id"]), C.eout.get(lb["label_id"])
        if a is not None and b is not None and a != b:
            swapped[frozenset((a, b))] = lb
    ids = sorted(set(one) | {t for p in swapped for t in p})
    tr = {t: C.rows[C.idx[t]] for t in ids if C.idx.get(t)}
    tr = {t: r[np.argsort(r[:, 1])] for t, r in tr.items()}
    out = []
    lst = sorted(tr)
    for i, A in enumerate(lst):
        for B in lst[i + 1:]:
            a, b = tr[A], tr[B]
            com, ia, ib = np.intersect1d(a[:, 1], b[:, 1], return_indices=True)
            if len(com) < 2:
                continue
            w = np.maximum(np.minimum(a[ia, 4], b[ib, 4]), 1)
            d = np.hypot(a[ia, 2] - b[ib, 2], a[ia, 3] - b[ib, 3]) / w
            key = frozenset((A, B))
            meets = [(int(com[s]), int(com[e]), float(d[s:e + 1].min())) for s, e in runs(d <= MEET_W)]
            if key in swapped:
                lb = swapped[key]
                inb = [m for m in meets if lb["entry_frame"] <= m[0] and m[1] <= lb["exit_frame"]]
                if inb:
                    fs, fe, _ = min(inb, key=lambda m: m[2])
                    out.append((A, B, fs, fe, "SWAP"))
            elif A in one and B in one:
                la, lb_ = one[A], one[B]
                lo = max(la["entry_frame"], lb_["entry_frame"])
                hi = min(la["exit_frame"], lb_["exit_frame"])
                for fs, fe, _ in meets:
                    if lo <= fs and fe <= hi:
                        out.append((A, B, fs, fe, "KEEP"))
    return out


def margin(C: Clip, A, B, fs, fe, m_s):
    d = lambda x, y: 1.0 - float(x @ y)  # noqa: E731
    Ab, Bb = C.side(A, fs, m_s, True), C.side(B, fs, m_s, True)
    Aa, Ba = C.side(A, fe, m_s, False), C.side(B, fe, m_s, False)
    if all(v is not None for v in (Ab, Bb, Aa, Ba)):
        return d(Ab, Aa) + d(Bb, Ba) - (d(Ab, Ba) + d(Bb, Aa))
    if Ab is not None and Bb is not None:
        if Aa is None and Ba is not None:
            return d(Bb, Ba) - d(Ab, Ba)
        if Ba is None and Aa is not None:
            return d(Ab, Aa) - d(Bb, Aa)
    if Aa is not None and Ba is not None:
        if Ab is None and Bb is not None:
            return d(Bb, Ba) - d(Bb, Aa)
        if Bb is None and Ab is not None:
            return d(Ab, Aa) - d(Ab, Ba)
    return None


def nocam2_override(C: Clip, encs):
    """Re-embed, from the video, every clean box the cam2 encounters use, with the never-saw-cam2 model."""
    import cv2
    from backend.services.vehicle_verifier import Verifier
    need = set()
    for A, B, fs, fe, _ in encs:
        for t in (A, B):
            for m_s in MS:
                need.update(C.used_rows(t, fs, m_s, True))
                need.update(C.used_rows(t, fe, m_s, False))
    byf = defaultdict(list)
    for j in need:
        byf[int(C.det_frame[j])].append(j)
    if not byf:
        return
    v = Verifier(NOCAM2)
    cap = cv2.VideoCapture(C.vpath)
    for f in sorted(byf):
        cap.set(cv2.CAP_PROP_POS_FRAMES, f)
        ok, img = cap.read()
        if not ok:
            continue
        js = byf[f]
        feats = v.features(C.bb[js], img)
        for j, e in zip(js, feats):
            C.override[j] = e
    cap.release()


def table(results, label):
    """results: list of (truth, {m_s: margin}) ; prints the grid, returns {(m,D): (caught, broken, nswap)}"""
    out = {}
    print(f"\n  {label}")
    for m_s in MS:
        sw = [r[1][m_s] for r in results if r[0] == "SWAP"]
        kp = [r[1][m_s] for r in results if r[0] == "KEEP"]
        swj = [x for x in sw if x is not None]
        kpj = [x for x in kp if x is not None]
        line = []
        for D in DS:
            c = sum(x > D for x in swj)
            b = sum(x > D for x in kpj)
            out[(m_s, D)] = (c, b, len(swj))
            line.append(f"D{D:.2f} {c:3}/{b:3}")
        print(f"    M {m_s:.1f}s  swaps {len(swj):3} judged ({len(sw) - len(swj)} not)  keeps {len(kpj):4} judged "
              f"({len(kp) - len(kpj)} not)   caught/broken  " + "  ".join(line))
        if swj and kpj:
            print(f"             margin SWAP median {np.median(swj):+.3f} (q25 {np.percentile(swj, 25):+.3f})  "
                  f"KEEP median {np.median(kpj):+.3f} (q95 {np.percentile(kpj, 95):+.3f})")
    return out


def main() -> int:
    stem = next((a for a in sys.argv[1:] if not a.startswith("--")), "mm1")
    do_nc2 = "--nocam2" in sys.argv
    res = {"dev": [], "held": []}
    cam2_v1, cam2_nc2 = [], []
    for clip in list_clips(PROJ):
        if not list_labels(PROJ, clip["clip_id"]):
            continue
        C = Clip(clip, stem)
        encs = encounters(C)
        part = "held" if is_heldout(clip["clip_id"]) else "dev"
        rr = []
        for A, B, fs, fe, truth in encs:
            ms = {m_s: margin(C, A, B, fs, fe, m_s) for m_s in MS}
            rr.append((truth, ms))
            if truth == "SWAP":
                print(f"  {clip['clip_id']:14} SWAP t{A}/t{B} f{fs}-{fe}  margin " +
                      "  ".join("-" if v is None else f"{v:+.3f}" for v in ms.values()), flush=True)
        res[part] += rr
        print(f"{clip['clip_id']}: {sum(r[0] == 'SWAP' for r in rr)} swaps, {sum(r[0] == 'KEEP' for r in rr)} keeps",
              flush=True)
        if C.cam == 2:
            cam2_v1 += rr
            if do_nc2:
                nocam2_override(C, encs)
                cam2_nc2 += [(t, {m_s: margin(C, A, B, fs, fe, m_s) for m_s in MS})
                             for A, B, fs, fe, t in encs]
    print("\nRESULTS  (caught = true swaps the look would flip; broken = true keeps it would flip)")
    dev = table(res["dev"], "DEV (_m5 clips)")
    held = table(res["held"], "HELD-OUT (_m50 clips)")
    ok = [(k, v) for k, v in dev.items() if v[2] and v[0] >= 2 * v[1] and v[0] > 0]
    if not ok:
        print("\nGATE A: FAIL - no (M, D) on dev catches swaps at >= 2x the keeps it breaks")
        return 0
    (m_s, D), (c, b, n) = max(ok, key=lambda kv: (kv[1][0] - 2 * kv[1][1], -kv[1][1]))
    hc, hb, hn = held[(m_s, D)]
    print(f"\nOPERATING POINT (dev): M {m_s}s D {D}  dev caught {c}/{n} broken {b};  held-out caught {hc}/{hn} broken {hb}")
    g1 = c >= 2 * b and hc >= 2 * hb
    g2 = n and c >= 0.3 * n and (not hn or hc >= 0.3 * hn)
    verdict = [f"dev+held caught >= 2x broken: {'PASS' if g1 else 'FAIL'}",
               f"caught >= 30% of judged swaps: {'PASS' if g2 else 'FAIL'}"]
    t1 = table(cam2_v1, "cam2 with verifier_v1_all")
    if do_nc2 and cam2_nc2:
        t2 = table(cam2_nc2, "cam2 with verifier_v1_nocam2 (never saw cam2)")
        c2, b2, _ = t2[(m_s, D)]
        verdict.append(f"cam2 never-saw model caught {c2} broken {b2} (v1_all {t1[(m_s, D)][0]}/{t1[(m_s, D)][1]}): "
                       f"{'PASS' if c2 >= 2 * b2 and c2 > 0 else 'FAIL'}")
    print("GATE A: " + "; ".join(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
