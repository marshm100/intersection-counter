"""ENCOUNTER FLAGS (2026-10-15; moved from scripts/research_review_queue.py for the failure predictor, plan
proud-wiggling-swan). Two COUNTED tracks meeting - centres within MEET_W box widths - where a count can change:
one of the two journeys is partial (gate tag not 'full'), or one id is born / dies within EDGE_S of the meeting.
Meetings of the same pair within MERGE_S are one flag. Label-free; diagnostics and review only - never counts.
"""
from __future__ import annotations

import numpy as np

MEET_W = 1.0
EDGE_S = 1.0
MERGE_S = 3.0


def encounter_flags(tag: dict, rows: np.ndarray, fps: float, f_lo=None, f_hi=None) -> list[dict]:
    """tag: {track id: gate tag} of the counted tracks; rows: dump rows [tid, frame, cx, cy, w, h, ...].
    Returns [{a, b, f0, f1, why}] with a < b, in frame order."""
    sel = rows[np.isin(rows[:, 0], list(tag))]
    if f_lo is not None:
        sel = sel[(sel[:, 1] >= f_lo) & (sel[:, 1] <= f_hi)]
    if not len(sel):
        return []
    tids, i0, cnt = np.unique(sel[:, 0], return_index=True, return_counts=True)
    srt = sel[np.lexsort((sel[:, 1], sel[:, 0]))]
    born = dict(zip(tids.astype(int), srt[i0, 1]))
    died = dict(zip(tids.astype(int), srt[i0 + cnt - 1, 1]))
    edge = EDGE_S * fps
    order = np.argsort(sel[:, 1], kind="stable")
    fr = sel[order, 1]
    uf, s0 = np.unique(fr, return_index=True)
    e0 = np.append(s0[1:], len(fr))
    last: dict = {}
    out: list[dict] = []
    for f, a, b in zip(uf, s0, e0):
        if b - a < 2:
            continue
        R = sel[order[a:b]]
        w = np.minimum(R[:, None, 4], R[None, :, 4])
        d = np.hypot(R[:, None, 2] - R[None, :, 2], R[:, None, 3] - R[None, :, 3]) / np.maximum(w, 1)
        ii, jj = np.where(np.triu(d <= MEET_W, 1))
        for i, j in zip(ii, jj):
            A, B = int(R[i, 0]), int(R[j, 0])
            key = (min(A, B), max(A, B))
            partial = tag.get(A) != "full" or tag.get(B) != "full"
            ends = any(abs(f - born[t]) <= edge or abs(f - died[t]) <= edge for t in key)
            if not (partial or ends):
                continue
            if key in last and f - last[key]["f1"] <= MERGE_S * fps:
                last[key]["f1"] = f
                continue
            fl = {"a": key[0], "b": key[1], "f0": f, "f1": f, "why": "partial" if partial else "id ends"}
            last[key] = fl
            out.append(fl)
    return out
