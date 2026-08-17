"""Position-based PATH-OVER-TIME re-attribution (PPT).
docs/plan_t3_ppt_reattr_2026-08-13.md — operator direction (a): the
movement is the path of the car over time; position survives the
projection that killed the heading feature.

Modes:
  --mode instrument   G-PPT-i: split-half held-out precision + coverage
                      of the CONSTRAINED re-decision on the window's own
                      fulls (destination-given-origin from the last 60%;
                      origin-given-destination from the first 60%).
  --mode compose      G-PPT-a: WAL-safe copy of the control DB; kept
                      events whose track has ONE gate-proven endpoint
                      get the OTHER endpoint re-decided by the scorer;
                      overwrite only on decisive floor-passing fits;
                      event count invariant asserted.

Prototype/scorer machinery imported from v2_f2m_pilot (instrument
reuse, recorded in the plan doc; the F2M FAMILY stays closed).

Usage:
  py -X utf8 scripts/v2_ppt_reattr.py --camera 2 --variant study_0700 --mode instrument
  py -X utf8 scripts/v2_ppt_reattr.py --camera 2 --variant study_0700 --mode compose \
      --control-db <d1ctrl db> --out-db <ppt db>
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, "scripts")
sys.path.insert(0, ".")

import numpy as np                                                  # noqa: E402

from backend.database import get_connection, list_paths_for_camera  # noqa: E402
from backend.services.entry_gates import build_gates, classify      # noqa: E402
from backend.services.pass2_replay import load_dump, tracks_dir     # noqa: E402
from backend.services.track_chains import build_chain_map_ev        # noqa: E402
from backend.services.trajectory_classifier import derive_movement  # noqa: E402
from backend.services.two_pass import (                             # noqa: E402
    _camera_parquet, _tracks_from_rows, gate_axes_for)
from v2_common import fit_motion_residual, load_table               # noqa: E402
from v2_f2m_pilot import build_prototypes, score_track              # noqa: E402

SEED = 42
HELDOUT_PRECISION = 0.95
MARGIN_SWEEP = [round(0.5 + 0.05 * k, 2) for k in range(9)]


def load_window(project, cam, variant):
    conn = get_connection(project)
    mouths, heads = {}, {}
    for lid, oz, rh in conn.execute(
            "SELECT leg_id, origin_zone, reference_heading FROM legs "
            "WHERE camera_id = ?", (cam,)):
        if oz:
            z = json.loads(oz)
            mouths[lid] = tuple(z[0])
            heads[lid] = rh
    conn.row_factory = sqlite3.Row
    legs_full = {r["leg_id"]: dict(r) for r in conn.execute(
        "SELECT * FROM legs WHERE camera_id=?", (cam,))}
    fps = float(conn.execute(
        "SELECT fps FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1",
        (cam,)).fetchone()[0])
    conn.close()
    rows = load_dump(tracks_dir(_camera_parquet(project, cam, variant)))
    tracks = {tid: sorted(p) for tid, p in _tracks_from_rows(rows).items()}
    gates = build_gates(mouths, list_paths_for_camera(project, cam), heads,
                        leg_axes=gate_axes_for(mouths, tracks.values()))
    info = {}
    for tid, pts in tracks.items():
        if len(pts) < 5:
            continue
        o, d, of, df, _op, _dp, tag = classify(pts, gates, fps)
        info[tid] = {"o": o, "d": d, "of": of, "df": df, "tag": tag,
                     "pts": pts}
    return legs_full, fps, tracks, gates, info


def calibrate(info, w_ang, rng, admission=None):
    """Split-half floors + full-data prototypes (the F2M convention).
    Returns (protos_full, attr_max, margin, cal_report). admission =
    the PPT-3 prototype filter (plan_ppt3_2026-08-17), applied to BOTH
    the split-half and the final prototype sets; None = original."""
    full_recs = []
    for v in info.values():
        if v["tag"] != "full" or v["o"] == v["d"]:
            continue
        clip = [(x, y) for f, x, y in v["pts"] if v["of"] <= f <= v["df"]]
        full_recs.append(((int(v["o"]), int(v["d"])), clip, v["pts"]))
    rng.shuffle(full_recs)
    half = len(full_recs) // 2
    protos_A = build_prototypes([(c, clip) for c, clip, _p in full_recs[:half]],
                                admission=admission)
    held = [r for r in full_recs[half:] if r[0] in protos_A]
    # constrained held-out rows: (true_cell, entry-mode scores, exit-mode scores)
    ho = []
    for cell, _clip, pts in held:
        se = score_track(pts, protos_A, "entry", cell[0], w_ang)
        sx = score_track(pts, protos_A, "exit", cell[1], w_ang)
        ho.append((cell, se, sx))
    best_costs = ([s[0][0] for _c, s, _x in ho if s]
                  + [s[0][0] for _c, _e, s in ho if s])
    attr_max = float(np.percentile(best_costs, 95)) if best_costs else 0.0

    def eval_floor(m):
        ok = tot = acc = 0
        for cell, se, sx in ho:
            for sc, truth in ((se, cell), (sx, cell)):
                if not sc:
                    continue
                tot += 1
                if sc[0][0] > attr_max:
                    continue
                if len(sc) > 1 and sc[0][0] >= m * sc[1][0]:
                    continue
                ok += 1
                acc += (sc[0][1] == truth)
        return (acc / ok if ok else 0.0), (ok / tot if tot else 0.0)

    margin = precision = coverage = None
    for m in sorted(MARGIN_SWEEP, reverse=True):
        p, c = eval_floor(m)
        if p >= HELDOUT_PRECISION:
            margin, precision, coverage = m, p, c
            break
    if margin is None:
        margin, precision, coverage = 0.0, 0.0, 0.0
    protos = build_prototypes([(c, clip) for c, clip, _p in full_recs],
                              admission=admission)
    return protos, attr_max, margin, {
        "n_fulls": len(full_recs), "heldout_n": len(ho),
        "attr_max_px": round(attr_max, 1), "margin": margin,
        "heldout_precision": round(precision, 4) if precision else 0.0,
        "heldout_coverage": round(coverage, 4) if coverage else 0.0}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="97a7849a")
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--variant", required=True)
    ap.add_argument("--mode", choices=["instrument", "compose"],
                    required=True)
    ap.add_argument("--control-db")
    ap.add_argument("--out-db")
    ap.add_argument("--freeze-origin", type=str, default=None,
                    help="PPT-2 (plan doc): no re-decision may read or "
                         "write a cell with this origin — the proven-"
                         "unresolvable pair stays exactly as the control "
                         "attributed it.")
    ap.add_argument("--t-lo", type=float, default=None,
                    help="window filter (timestamp_video seconds): only "
                         "events in [t_lo, t_hi) are considered — REQUIRED "
                         "when composing on a full live table so other "
                         "windows' events (whose tids can collide with "
                         "this window's dump tids) are never touched.")
    ap.add_argument("--t-hi", type=float, default=None)
    ap.add_argument("--unfloored", action="store_true",
                    help="VALIDATION-NEGATIVE GENERATOR ONLY (GATE-AG2 N6): "
                         "moves every scored candidate whose best cell "
                         "differs, ignoring the ATTR_MAX/margin floors — "
                         "the runaway-re-attributor archetype the "
                         "moved_share cap exists to catch. Never a "
                         "production mode.")
    ap.add_argument("--legacy", action="store_true",
                    help="reproduce the PPT-2-era behavior exactly: no "
                         "prototype admission, no two-sided freeze "
                         "(plan_ppt3_2026-08-17 G-PPT3-p reproduction "
                         "gate; the applied cam2 artifacts' era).")
    args = ap.parse_args()
    frozen = (set(int(x) for x in args.freeze_origin.split(","))
              if args.freeze_origin else set())
    cam, variant = args.camera, args.variant
    rng = np.random.default_rng(SEED)

    legs_full, fps, tracks, gates, info = load_window(
        args.project, cam, variant)
    all_legs = list(legs_full.values())
    npz = Path("runs/v2_week1") / f"tracklets_cam{cam}_{variant}.npz"
    cal = fit_motion_residual(load_table(npz))
    w_ang = cal["zv_radius"] / 45.0

    # ---- PPT-3 admission (plan_ppt3_2026-08-17, Phase A) -------------------
    # Built from the CONTROL DB's window (blind: live counts + modal stored
    # movements) + intersection_paths + derive_movement. Compose mode only
    # (the instrument measures scorer precision on fulls, not composition);
    # --legacy disables (PPT-2-era reproduction).
    # R_MAX: declared rule — tightest round value keeping every known-
    # good destination cell with >= 1.4x margin. Re-frozen PER CAMERA
    # 2026-08-17 under the (b-amended) contingency: the global
    # extension over the Mio-confirmed cam2 WB_left good (ratio 2.15
    # -> 3.0) is UNSAFE globally — cam1's measured EB_left flood cell
    # sits at 2.55 < 3.0, and the cap cannot backstop ratio-inflated
    # cells (h grows with the corruption). Per-camera like freeze
    # sets: cam2 3.0 (next-highest admitted cell 1.93 — only WB_left
    # enters), all others 2.0 (every corridor kill stands).
    R_MAX = {2: 3.0}.get(args.camera, 2.0)
    admission = None
    adm_report = {}
    adm_ratio = {}                   # admitted cell -> census/live ratio
    live_cells = {}
    # PPT-3 Phase B saturation cap (G-PPT3-f verdict, plan_ppt3): a
    # receiving cell's admitted NET gain <= CAP_BETA + CAP_ALPHA *
    # max(exp_vol - live_n, 0) with exp_vol = ratio * live_n. Constants
    # by the tightest-round rule on the Phase-A good/bad table: beta in
    # [1.4*28, 81/1.4] -> 40; alpha = tightest one-decimal passing the
    # shipped cam2 goods with >=1.4x margin (+87 @ h=101.6 -> 0.9).
    CAP_ALPHA = 0.9
    CAP_BETA = 40.0
    if args.mode == "compose" and not args.legacy:
        wsql0, wargs0 = "", []
        if args.t_lo is not None and args.t_hi is not None:
            wsql0 = " AND timestamp_video >= ? AND timestamp_video < ?"
            wargs0 = [args.t_lo, args.t_hi]
        cctl = sqlite3.connect(f"file:{args.control_db}?mode=ro", uri=True)
        live_cells = {(o, d): n for o, d, n in cctl.execute(
            "SELECT origin_leg_id, destination_leg_id, COUNT(*) FROM "
            "vehicle_events WHERE camera_id=? AND COALESCE(rejected,0)=0 "
            "AND origin_leg_id IS NOT NULL AND destination_leg_id IS NOT "
            f"NULL{wsql0} GROUP BY 1,2", (cam, *wargs0))}
        modal_mvt = {}
        for o, d, m, n in cctl.execute(
                "SELECT origin_leg_id, destination_leg_id, movement, "
                "COUNT(*) FROM vehicle_events WHERE camera_id=? AND "
                f"COALESCE(rejected,0)=0{wsql0} GROUP BY 1,2,3 "
                "ORDER BY COUNT(*)", (cam, *wargs0)):
            modal_mvt[(o, d)] = m          # last row per cell = the mode
        cctl.close()
        total_kept = sum(live_cells.values())
        path_set = {(p["origin_leg_id"], p["destination_leg_id"])
                    for p in list_paths_for_camera(args.project, cam)}
        total_fulls = sum(1 for v in info.values()
                          if v["tag"] == "full" and v["o"] != v["d"])

        def admission(cell, n_fulls):
            o, d = int(cell[0]), int(cell[1])
            # (b-amended), operator-ruled 2026-08-17: a pathless cell
            # with >= 10 in-window gate-verified fulls (the prototype
            # floor, PROTO_MIN_FULLS) falls through to (c)/(a) instead
            # of dying — the paths artifact is DERIVED from this same
            # evidence class and has measured gaps (cam2 WB_left/EB).
            pathless = (o, d) not in path_set
            if pathless and n_fulls < 10:                    # (b)
                adm_report[f"{o}->{d}"] = "rejected:no_path"
                return False
            live_n = live_cells.get((o, d), 0)
            if live_n >= 5:                                  # (c)
                dm = derive_movement(legs_full[o], legs_full.get(d),
                                     all_legs)
                if modal_mvt.get((o, d)) and dm != modal_mvt[(o, d)]:
                    adm_report[f"{o}->{d}"] = (
                        f"rejected:label_conflict({dm}!="
                        f"{modal_mvt[(o, d)]})")
                    return False
            if live_n == 0:                                  # (a) RATIO inf
                adm_report[f"{o}->{d}"] = "rejected:zero_live"
                return False
            ratio = ((n_fulls / total_fulls) / (live_n / total_kept)
                     if total_fulls and total_kept else 0.0)
            if ratio > R_MAX:                                # (a)
                adm_report[f"{o}->{d}"] = f"rejected:ratio({ratio:.2f})"
                return False
            tag_b = ", no_path_fallback" if pathless else ""
            adm_report[f"{o}->{d}"] = f"admitted(ratio {ratio:.2f}{tag_b})"
            adm_ratio[(o, d)] = ratio
            return True

    protos, attr_max, margin, cal_rep = calibrate(info, w_ang, rng,
                                                  admission=admission)
    print(f"[ppt] cam{cam} {variant} calibration: {cal_rep}")
    if adm_report:
        for k, v in sorted(adm_report.items()):
            print(f"[ppt]   admission {k}: {v}")

    if args.mode == "instrument":
        dst = Path("runs/v2_week1") / f"ppt_i_cam{cam}_{variant}.json"
        dst.write_text(json.dumps(cal_rep, indent=1))
        gate = (cal_rep["heldout_precision"] >= 0.90
                and cal_rep["heldout_coverage"] >= 0.60)
        print(f"[ppt] G-PPT-i this window: "
              f"{'PASS' if gate else 'FAIL'} "
              f"(precision {cal_rep['heldout_precision']} >= 0.90, "
              f"coverage {cal_rep['heldout_coverage']} >= 0.60)")
        print(f"[ppt] -> {dst}")
        return 0

    # ---- compose ------------------------------------------------------------
    out = Path(args.out_db)
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    src = sqlite3.connect(args.control_db)
    dst = sqlite3.connect(out)
    src.backup(dst)
    src.close()
    dst.row_factory = sqlite3.Row
    wsql, wargs = "", []
    if args.t_lo is not None and args.t_hi is not None:
        wsql = " AND timestamp_video >= ? AND timestamp_video < ?"
        wargs = [args.t_lo, args.t_hi]
    evs = dst.execute(
        "SELECT event_id, vehicle_track_id, origin_leg_id, "
        "destination_leg_id, movement FROM vehicle_events "
        f"WHERE camera_id=? AND COALESCE(rejected,0)=0{wsql}",
        (cam, *wargs)).fetchall()
    n_before = len(evs)
    census = Counter()
    moves = Counter()
    updates = []
    proposals = []
    for ev in evs:
        tid = int(ev["vehicle_track_id"])
        v = info.get(tid)
        if v is None:
            census["short_track"] += 1
            continue
        tag = v["tag"]
        if tag == "full":
            census["full_untouched"] += 1
            continue
        if tag == "entry_only":
            if v["o"] is None or int(v["o"]) != ev["origin_leg_id"]:
                census["contradiction_skipped"] += 1
                continue
            sc = score_track(v["pts"], protos, "entry", int(v["o"]), w_ang)
            fixed_o = True
        elif tag == "exit_only":
            if v["d"] is None or int(v["d"]) != ev["destination_leg_id"]:
                census["contradiction_skipped"] += 1
                continue
            sc = score_track(v["pts"], protos, "exit", int(v["d"]), w_ang)
            fixed_o = False
        else:
            census["no_crossing_out_of_scope"] += 1
            continue
        if ev["origin_leg_id"] in frozen:
            census["frozen_origin_current"] += 1
            continue
        if not args.legacy and admission is not None and (
                ev["origin_leg_id"], ev["destination_leg_id"]) not in protos:
            # PPT-3 (d) two-sided: current cell has no ADMITTED prototype —
            # the constrained argmax would force-relocate it (the cam1/cam5
            # drain class). Never re-decide out of an unsupported cell.
            census["unsupported_current"] += 1
            continue
        if not sc:
            census["no_candidates"] += 1
            continue
        if not args.unfloored and (
                sc[0][0] > attr_max or margin == 0.0 or (
                len(sc) > 1 and sc[0][0] >= margin * sc[1][0])):
            census["floors_not_cleared"] += 1
            continue
        cell = sc[0][1]
        if int(cell[0]) in frozen:
            census["frozen_origin_proposed"] += 1
            continue
        cur = (ev["origin_leg_id"], ev["destination_leg_id"])
        if tuple(cell) == cur:
            census["confirmed_unchanged"] += 1
            continue
        mv = derive_movement(legs_full[cell[0]], legs_full.get(cell[1]),
                             all_legs)
        if mv == "insufficient_data":
            census["movement_underivable"] += 1
            continue
        fitm = (sc[1][0] / sc[0][0]) if (len(sc) > 1 and sc[0][0] > 0) \
            else float("inf")
        proposals.append((fitm, int(ev["event_id"]),
                          (int(cur[0]), int(cur[1])),
                          (int(cell[0]), int(cell[1])), mv, ev["movement"]))
    # Cap enforcement: rank proposals by scorer fit margin (runner-up /
    # best cost; single-candidate = inf), ties by event_id, and admit
    # while the receiving cell's running NET gain stays under its cap.
    # An admitted outflow loosens its source cell for LATER proposals
    # only (deterministic, conservative). Legacy: no cap, original
    # event order — byte-identical to the applied-era composer.
    cap_on = (not args.legacy) and bool(adm_ratio)
    order = (sorted(proposals, key=lambda p: (-p[0], p[1]))
             if cap_on else proposals)
    net = Counter()
    for fitm, eid, cur, cell, mv, old_mvt in order:
        if cap_on:
            live_n = live_cells.get(cell, 0)
            r = adm_ratio.get(cell, 0.0)
            cap = CAP_BETA + CAP_ALPHA * max(live_n * (r - 1.0), 0.0)
            if net[cell] + 1 > cap:
                census["cap_blocked"] += 1
                continue
        net[cell] += 1
        net[cur] -= 1
        updates.append((cell[0], cell[1], mv, eid))
        moves[f"{cur[0]}->{cur[1]}:{old_mvt} => "
              f"{cell[0]}->{cell[1]}:{mv}"] += 1
        census["reattributed"] += 1
    with dst:
        dst.executemany(
            "UPDATE vehicle_events SET origin_leg_id=?, "
            "destination_leg_id=?, movement=? WHERE event_id=?", updates)
    n_after = dst.execute(
        "SELECT COUNT(*) FROM vehicle_events WHERE camera_id=? "
        f"AND COALESCE(rejected,0)=0{wsql}", (cam, *wargs)).fetchone()[0]
    dst.close()
    assert n_after == n_before, "zero-mass invariant violated"

    # PPT-3 (e): the camera-level mis-gating signal (plan_ppt3, declared
    # formula). >= 0.10 stands the CAMERA down in Phase-C evaluation.
    denom = n_before - census["full_untouched"] - \
        census["no_crossing_out_of_scope"]
    c_rate = census["contradiction_skipped"] / denom if denom else 0.0
    census["contradiction_rate"] = round(c_rate, 4)
    if c_rate >= 0.10:
        print(f"[ppt] WARNING camera gate (e): contradiction_rate "
              f"{c_rate:.3f} >= 0.10 — this camera is structurally "
              f"mis-gated; candidates from it STAND DOWN per plan_ppt3")

    diag = {"camera": cam, "variant": variant, "calibration": cal_rep,
            "events_kept": n_before, "census": dict(census),
            "admission": adm_report, "legacy": bool(args.legacy),
            "cap": {"alpha": CAP_ALPHA, "beta": CAP_BETA, "active": cap_on,
                    "blocked": census.get("cap_blocked", 0)},
            "movement_matrix": dict(moves.most_common())}
    dpath = Path("runs/v2_week1") / f"ppt_c_cam{cam}_{variant}.json"
    dpath.write_text(json.dumps(diag, indent=1))
    print(f"[ppt] compose cam{cam} {variant}: kept={n_before} "
          f"reattributed={census['reattributed']} census={dict(census)}")
    top = moves.most_common(8)
    for k, n in top:
        print(f"    {n:>4d}  {k}")
    print(f"[ppt] -> {out}")
    print(f"[ppt] -> {dpath}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
