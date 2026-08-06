"""Pipeline-V2 — assembly as a dump re-ID pass (the D4 correction).

Takes a D1 tracklet table, runs the frozen-cost greedy assembler, and
writes a NEW pass-1 dump variant ("v2a_<variant>") whose rows are
byte-identical to the original except track_id: every tracklet in an
assembled chain carries the chain's id. The untouched PRODUCTION pass-2
(banks, matcher, fallbacks, merge) then counts the assembled tracks —
assembly improves pass-2's input instead of replacing its attribution
(day-3 finding: naive gate-pair counting loses the truncated-track mass
that production's bank machinery recovers).

Additive artifact: originals untouched; the new variant sits alongside.

Usage:
  py -X utf8 scripts/v2_reid_dump.py runs/v2_week1/tracklets_cam2_study_0700.npz
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                     # noqa: E402
from v2_common import (fit_motion_residual, load_table,  # noqa: E402
                       premerge_concurrent, table_from_pieces,
                       twin_pairs_structural)
from v2_baseline_greedy import stitch_greedy           # noqa: E402
from backend.services import two_pass as TP            # noqa: E402


def _merge_pairs(t: dict, pairs) -> tuple[list, list]:
    parent = list(range(t["n"]))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for x, y in pairs:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[ry] = rx
    groups: dict[int, list[int]] = {}
    for i in range(t["n"]):
        groups.setdefault(find(i), []).append(i)
    pieces = []
    for members in groups.values():
        seg = np.concatenate([np.asarray(
            t["rows"][int(t["starts"][i]):int(t["ends"][i])])
            for i in members])
        if len(members) > 1:
            seg = seg[np.lexsort((-seg[:, 6], seg[:, 1]))]
            _, first = np.unique(seg[:, 1], return_index=True)
            seg = seg[np.sort(first)]
        else:
            seg = seg[np.argsort(seg[:, 1])]
        pieces.append(seg)
    return pieces, [g for g in groups.values() if len(g) > 1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("table")
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--twin-mode", default="structural",
                    choices=["structural", "iou", "off"])
    args = ap.parse_args()

    t = load_table(args.table)
    stem = Path(args.table).stem.replace("tracklets_", "")
    camera_id = int(stem.split("_")[0].replace("cam", ""))
    variant = "_".join(stem.split("_")[1:])
    new_variant = f"v2a_{variant}"

    # Stage 3a: concurrent-twin merge. 'structural' = continuation/origin
    # collision (the untried channel); 'iou' = the ledgered-dead co-life
    # IoU (kept for A/B archaeology only); 'off' = none.
    if args.twin_mode == "structural":
        cal0 = fit_motion_residual(t)
        pairs = twin_pairs_structural(t, cal0)
        pieces, groups = _merge_pairs(t, pairs)
    elif args.twin_mode == "iou":
        pieces, groups = premerge_concurrent(
            np.asarray(t["rows"]), t["starts"], t["ends"], t["fps"])
    else:
        pieces = [np.asarray(t["rows"][int(t["starts"][i]):int(t["ends"][i])])
                  for i in range(t["n"])]
        groups = []
    t2 = table_from_pieces(pieces, t["fps"], t["meta"])

    # Stage 3b: sequential assembly (mutual-best + ratio, frozen R)
    cal = fit_motion_residual(t2)
    links, chains = stitch_greedy(t2, cal)

    newid = np.array(t2["track_id"], dtype=np.float32).copy()
    n_multi = 0
    for ch in chains:
        if len(ch) > 1:
            n_multi += 1
            cid = min(float(t2["track_id"][i]) for i in ch)
            for i in ch:
                newid[i] = cid
    rows_out = []
    for i in range(t2["n"]):
        seg = np.asarray(pieces[i], dtype=np.float32).copy()
        seg[:, 0] = newid[i]
        rows_out.append(seg)
    rows = np.concatenate(rows_out)
    rows = rows[np.lexsort((rows[:, 0], rows[:, 1]))]     # frame-major

    src_tdir = TP.tracks_dir(TP._camera_parquet(args.project, camera_id, variant))
    dst_tdir = TP.tracks_dir(TP._camera_parquet(args.project, camera_id, new_variant))
    dst_tdir.mkdir(parents=True, exist_ok=True)
    meta = json.loads((src_tdir / "meta.json").read_text())
    meta["variant"] = new_variant
    meta["complete"] = True
    meta["v2_assembly"] = {
        "source_variant": variant, "engine": "premerge+ratio_greedy",
        "premerge_groups": len(groups),
        "premerged_tracklets": sum(len(g) for g in groups),
        "links": len(links), "multi_chains": n_multi,
        "cal": {k: v for k, v in cal.items() if k != "table"}}
    np.save(dst_tdir / "rows.npy", rows)
    (dst_tdir / "count.txt").write_text(str(len(rows)))
    (dst_tdir / "meta.json").write_text(json.dumps(meta))
    uniq = len(np.unique(rows[:, 0]))
    print(f"[reid] cam{camera_id} {variant} -> {new_variant}: "
          f"{t['n']} tracklets -> premerge {len(groups)} groups "
          f"({sum(len(g) for g in groups)} twins) -> {t2['n']} -> "
          f"{uniq} track ids ({len(links)} links, {n_multi} multi-chains) "
          f"-> {dst_tdir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
