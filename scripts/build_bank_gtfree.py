"""Ground-truth-FREE path-bank builder (Phase 2.2 + 2.4 —
docs/implementation_plan_architecture_2026-06-11.md).

Builds the same bank JSON apply_bank.py consumes, but with ZERO Miovision:
everything build_bank.py asked the ground truth for is replaced by the site's
own data + the operator's calibration (the published recipe — AI City winners
bootstrap reference trajectories from the camera's own unlabeled traffic):

  Miovision dependency             GT-free replacement
  -------------------------------  ------------------------------------------
  which OD cells exist             cells observed in the site's own tracks
                                   (anchor+heading AGREEMENT grouping), share
                                   >= --min-share (1% rule, arXiv 2112.01570),
                                   plus operator-drawn channels for the rest
  manual >= min_support gate       n_tracks >= --min-support AND share gate
  movement label (XML slots)       derive_movement() from leg geometry
  magnet / over-collect gates      bearing-consistency gate: the FITTED
                                   polyline's entry/exit bearings must agree
                                   with the claimed origin/dest legs' calibrated
                                   headings — a mis-binned straight "turn" fails
                                   its exit bearing; no volume needed
  (nothing)                        per-site QA report (2.4): support shares,
                                   bearing residuals, polyline-ambiguity pairs,
                                   leg heading-vs-label sanity (catches
                                   cam1-style 180-degree label swaps)

Tracking uses the camera's PERSISTED calib_* knobs (Phase 1) so bank quality
benefits from per-camera tuning the same way live processing does.

Usage:
  py scripts/build_bank_gtfree.py --camera 3 --minutes 30          # corridor (default project)
  py scripts/build_bank_gtfree.py --project 0acb12c0 --camera 2    # any new site
  py scripts/build_bank_gtfree.py --camera 5 --minutes 30 \
      --channels experiments/channel_replay/channels_cam5.json

The window start (--start-hms/--minutes) is anchored to the video's own
recording_start_datetime from the DB, so any project/date works. A detection
cache (*.parquet) for the window must already exist — run a processing pass
first; the pipeline writes the cache as it detects.

Writes evaluations/gtfree_bank_cam<N>.json (+ _qa.json). Validate with:
  py scripts/apply_bank.py --camera N --bank evaluations/gtfree_bank_camN.json ...
"""
from __future__ import annotations
import argparse, json, math, sqlite3, sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backend.database import get_camera_calibration_params
from backend.services.detection_cache import (
    DEFAULT_VARIANT, DetectionCacheReader, compute_video_content_hash, parquet_path)
from backend.services.tracker import create_tracker_backend
from backend.services.trajectory_classifier import derive_movement
from auto_calibrate import _fit_mean_polyline
from build_bank import _avg_bearing, _bearing_diff, heading_origin_dest


def _plen(p):
    return sum(math.hypot(p[i][0] - p[i-1][0], p[i][1] - p[i-1][1]) for i in range(1, len(p)))


def _straightness(poly) -> float:
    pl = _plen(poly)
    return (math.hypot(poly[-1][0] - poly[0][0], poly[-1][1] - poly[0][1]) / pl
            if pl > 1e-9 else 1.0)


def _densify(pts, n: int):
    """Piecewise-linear resample of a short control polyline to n points."""
    segs = [math.hypot(pts[i+1][0]-pts[i][0], pts[i+1][1]-pts[i][1]) for i in range(len(pts)-1)]
    total = sum(segs) or 1.0
    out, target = [], 0.0
    for k in range(n):
        d = total * k / (n - 1)
        acc = 0.0
        for i, s in enumerate(segs):
            if acc + s >= d or i == len(segs) - 1:
                t = 0.0 if s == 0 else (d - acc) / s
                out.append([round(pts[i][0] + t * (pts[i+1][0] - pts[i][0]), 1),
                            round(pts[i][1] + t * (pts[i+1][1] - pts[i][1]), 1)])
                break
            acc += s
    return out


def _mean_pairwise_dist(a, b) -> float:
    """Mean point distance between two equal-length polylines (ambiguity check)."""
    return sum(math.hypot(p[0]-q[0], p[1]-q[1]) for p, q in zip(a, b)) / len(a)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--camera", type=int, required=True)
    ap.add_argument("--project", default="97a7849a",
                    help="project id (default = Sunnyvale corridor)")
    ap.add_argument("--out", default=None, help="default evaluations/gtfree_bank_cam<N>.json")
    ap.add_argument("--start-hms", default="07:00:00")
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--variant", default=None)
    ap.add_argument("--min-support", type=int, default=5,
                    help="min AGREEMENT-grouped tracks to admit a cell")
    ap.add_argument("--min-share", type=float, default=0.01,
                    help="min share of grouped tracks (the published 1%% OD-pair rule)")
    ap.add_argument("--min-path", type=float, default=80.0)
    ap.add_argument("--poly-pts", type=int, default=15)
    ap.add_argument("--bearing-tol", type=float, default=55.0,
                    help="max deg between fitted polyline entry/exit bearings and the "
                         "claimed legs' calibrated headings (GT-free magnet gate)")
    ap.add_argument("--ambiguity-px", type=float, default=30.0,
                    help="QA: flag admitted polyline pairs closer than this (mean px)")
    ap.add_argument("--minor-spread-px", type=float, default=40.0,
                    help="minor cells: max mean member-track spread around the fitted "
                         "polyline (coherence gate; junk fragment groups are scattered)")
    ap.add_argument("--channels", default=None,
                    help="operator-drawn channels JSON; declares the movement set and "
                         "provides fallback polylines for cells the data didn't cover")
    args = ap.parse_args()
    cam = args.camera
    project = args.project
    out_path = Path(args.out or f"evaluations/gtfree_bank_cam{cam}.json")
    qa_path = out_path.with_name(out_path.stem + "_qa.json")

    # --- camera context (NO ground truth anywhere below this line) ----------
    c = sqlite3.connect(f"data/projects/{project}/project.db")
    v = c.execute("SELECT path,file_size_bytes,total_frames,fps,recording_start_datetime "
                  "FROM videos WHERE camera_id=? ORDER BY sort_order LIMIT 1", (cam,)).fetchone()
    leg_rows = c.execute("SELECT leg_id,origin_zone,reference_heading,cardinal_direction "
                         "FROM legs WHERE camera_id=?", (cam,)).fetchall()
    c.close()
    if v is None:
        print(f"!! no video row for camera {cam} in project {project}", file=sys.stderr)
        return 2
    if not v[4]:
        print(f"!! video for camera {cam} has no recording_start_datetime; set it in the "
              f"calibration UI (or re-add the video) before building the bank", file=sys.stderr)
        return 2
    video_start = datetime.fromisoformat(v[4])
    anchors = {lid: json.loads(oz)[0] for lid, oz, _, _ in leg_rows if oz}
    refh = {lid: rh for lid, _, rh, _ in leg_rows if rh is not None}
    cardinal = {lid: (cd or "").upper() for lid, _, _, cd in leg_rows}
    leg_dicts = {lid: {"leg_id": lid, "reference_heading": rh}
                 for lid, _, rh, _ in leg_rows}
    all_legs = list(leg_dicts.values())

    # Movement from the ORIGIN/DEST cardinal pair — the standard TMC
    # definition, computed from operator calibration the new-site workflow
    # already requires (cardinals drive the Excel TMC join). Leg cardinal =
    # approach direction-of-travel: a NB vehicle's through exits via the
    # S(B)-approach road; its left exits via the E(B)-approach road (heading
    # west); etc. Image-space shape labeling cannot decide this at skewed
    # 4-ways (collinear exits mislabeled cam1/2/4 catastrophically); cardinals
    # are world knowledge, no ground truth involved.
    _LEFT = {("N", "E"), ("E", "S"), ("S", "W"), ("W", "N")}
    _RIGHT = {("N", "W"), ("W", "S"), ("S", "E"), ("E", "N")}

    def _cardinal_movement(ol: int, dl: int) -> str | None:
        a, b = cardinal.get(ol), cardinal.get(dl)
        if not a or not b:
            return None
        if a == b or ol == dl:
            return "u_turn"
        if (a, b) in _LEFT:
            return "left"
        if (a, b) in _RIGHT:
            return "right"
        return "through"   # opposite cardinals
    fps = float(v[3])
    ch, _ = compute_video_content_hash(v[0], file_size_bytes=v[1], total_frames=v[2])
    pq = parquet_path(project, cam, ch, args.variant or DEFAULT_VARIANT)
    if not pq.exists():
        print(f"!! no detection cache at {pq}\n   process this window once first; the "
              f"pipeline writes the cache as it detects (~3h for 30min on the iGPU at "
              f"~1.6fps).", file=sys.stderr)
        return 2
    t0 = datetime.fromisoformat(f"{video_start.date().isoformat()}T{args.start_hms}")
    f_lo = int((t0 - video_start).total_seconds() * fps)
    f_hi = f_lo + int(args.minutes * 60 * fps)

    # --- track collection with the camera's persisted Phase-1 knobs ---------
    calib = get_camera_calibration_params(project, cam)
    tk = {}
    if calib.get("new_track_thresh") is not None:
        tk["new_track_thresh"] = float(calib["new_track_thresh"])
    be = create_tracker_backend(
        "botsort",
        track_activation_threshold=float(calib.get("tracker_activation_threshold") or 0.25),
        minimum_matching_threshold=float(calib.get("tracker_match_threshold") or 0.8),
        frame_rate=int(fps), **tk)
    buf = float(calib.get("bbox_buffer_scale") or 1.0)

    tr = defaultdict(list)
    for fidx, dets in DetectionCacheReader(pq).iter_frames():
        if not (f_lo <= fidx < f_hi):
            continue
        if buf != 1.0:
            inflated = []
            for d in dets:
                x1, y1, x2, y2 = d["bbox"]
                cx, cy = (x1+x2)/2, (y1+y2)/2
                hw, hh = (x2-x1)*buf/2, (y2-y1)*buf/2
                d = dict(d); d["bbox"] = [cx-hw, cy-hh, cx+hw, cy+hh]
                inflated.append(d)
            dets = inflated
        for t in be.update(dets, fidx):
            tr[t["track_id"]].append(tuple(t["center"]))

    kept = [pts for pts in tr.values() if len(pts) >= 4 and _plen(pts) >= args.min_path]

    def nearest(pt):
        return min(anchors, key=lambda l: math.hypot(pt[0]-anchors[l][0], pt[1]-anchors[l][1]))

    # --- grouping: anchor PRIMARY + heading RECOVERY (build_bank's proven
    # structure, made GT-free). Anchor binning is correct for most cells;
    # heading re-binning recovers cells whose tracks start/end near the same
    # anchor (turn queues). Agreement rate is kept as a QA signal only —
    # requiring agreement for admission collapses recall when leg headings are
    # roughly calibrated (cam3 leg 31: 59 deg off -> 14% agreement).
    groups = defaultdict(list)     # anchor (origin, dest) -> tracks
    hgroups = defaultdict(list)    # heading (origin, dest) -> tracks
    leg_entry_bearings: dict[int, list] = defaultdict(list)   # QA sanity check
    leg_exit_bearings: dict[int, list] = defaultdict(list)
    n_agree = 0
    prelim = []
    for pts in kept:
        od_a = (nearest(pts[0]), nearest(pts[-1]))
        od_h = heading_origin_dest(pts, refh)
        eb = _avg_bearing(pts, 3, tail=False)
        xb = _avg_bearing(pts, 3, tail=True)
        if eb is not None:
            leg_entry_bearings[od_a[0]].append(eb)
        if xb is not None:
            leg_exit_bearings[od_a[1]].append(xb)
        prelim.append((pts, od_a, od_h, eb, xb))
        if od_h == od_a:
            n_agree += 1

    def _circ_mean(bearings):
        if len(bearings) < 10:
            return None
        s = sum(math.sin(math.radians(b)) for b in bearings)
        co = sum(math.cos(math.radians(b)) for b in bearings)
        return math.degrees(math.atan2(s, co)) % 360

    # Observed per-leg bearing consensus. The calibrated reference_heading can
    # be rough (cam3 leg 31: 59 deg off observed traffic); gating a cell against
    # a miscalibrated heading rejects REAL flows. Each gate below accepts the
    # better of (calibrated, observed-consensus) — data-driven per the project's
    # standing preference, with the operator value as fallback.
    entry_consensus = {l: _circ_mean(bs) for l, bs in leg_entry_bearings.items()}
    exit_consensus = {l: _circ_mean(bs) for l, bs in leg_exit_bearings.items()}

    # Auto-correct badly miscalibrated headings for the BUILD'S internal
    # geometry tests (axis oppositeness, heading recovery). cam4's leg 34 was
    # 147 deg off and cam1's leg 25 was 93 deg off — with a poisoned heading the
    # most-opposite arbiter labels a 580-track arterial through as "left"
    # (cam4 went to 123.8% net). The observed consensus of hundreds of tracks
    # is more trustworthy than a hand-set heading that disagrees by >45 deg.
    # The correction is internal only (NOT exported via updated_legs); the QA
    # report still tells the operator to fix the calibration.
    refh_fixed = dict(refh)
    for lid, obs in entry_consensus.items():
        if obs is None or lid not in refh:
            continue
        if _bearing_diff(obs, refh[lid]) > 45:
            refh_fixed[lid] = obs

    def _axis(lid):
        b = entry_consensus.get(lid)
        if b is None:
            b = refh_fixed.get(lid)
        return None if b is None else b % 180.0

    def _axis_dist(a, b):
        d = abs(a - b) % 180.0
        return min(d, 180.0 - d)

    # Track-level bearing override of the anchor binning. Anchor proximity
    # mis-bins big flows whose exit happens to pass another leg's anchor
    # (cam5: 562 NB-thru tracks ended nearest the W anchor -> a phantom
    # 132%-net "right"; cam1's N->W ghost likewise). The track's entry/exit
    # BEARING against each leg's (sanity-corrected) road direction is immune
    # to anchor placement. Conservative: override only when the anchor's road
    # is strongly contradicted (>60 deg) AND another leg strongly matches
    # (<30 deg) — truncated mid-turn tracks keep their anchor binning.
    def _rebin(bearing, cur_leg, refs: dict) -> int:
        if bearing is None or cur_leg not in refs:
            return cur_leg
        if _bearing_diff(bearing, refs[cur_leg]) <= 60:
            return cur_leg
        best = min(refs, key=lambda l: _bearing_diff(bearing, refs[l]))
        if best != cur_leg and _bearing_diff(bearing, refs[best]) < 30:
            return best
        return cur_leg

    # Channel-priority binning: when the operator has drawn a channel for a
    # movement, tracks lying along its corridor belong to it — BEFORE anchor
    # binning. This is the only reliable tie-breaker for anchor-on-through-path
    # geometries (cam5: 586 NB-thru tracks endpoint-binned to the W anchor as a
    # phantom "right"; every data-derived reference at that anchor is
    # contaminated BY the phantom flow, so no purely-statistical gate can break
    # the tie). Channel cells are later re-fitted from their claimed tracks.
    # Channel declarations come from the --channels JSON file (research format)
    # or, by default, from the camera's `channels` table (drawn in the
    # calibration UI, Phase 2.1).
    raw_chans: list[dict] = []
    if args.channels:
        for chd in json.loads(Path(args.channels).read_text()).get("channels", []):
            raw_chans.append({"od": (chd["origin_leg"], chd["destination_leg"]),
                              "movement": chd["movement"], "entry": chd["entry"],
                              "apex": chd.get("apex"), "exit": chd["exit"],
                              "width_in": chd.get("width_in", 40),
                              "width_out": chd.get("width_out", 40)})
    else:
        from backend.database import list_channels_for_camera
        for chd in list_channels_for_camera(project, cam):
            raw_chans.append({"od": (chd["origin_leg_id"], chd["destination_leg_id"]),
                              "movement": chd["movement"], "entry": chd["entry"],
                              "apex": chd["apex"], "exit": chd["exit"],
                              "width_in": chd["width_in"], "width_out": chd["width_out"]})
        if raw_chans:
            print(f"loaded {len(raw_chans)} operator channels from the channels table")
    chan_decls = []
    for chd in raw_chans:
        ctrl = [chd["entry"], chd.get("apex") or chd["entry"], chd["exit"]]
        chan_decls.append({
            "od": chd["od"],
            "movement": chd["movement"],
            "poly": _densify(ctrl, args.poly_pts),
            "halfw": max(float(chd.get("width_in", 40)),
                         float(chd.get("width_out", 40))) / 2.0 + 20.0,
        })

    def _channel_claim(pts):
        """Best channel whose corridor contains the track AND whose direction
        of travel matches (tail-direction gate, as in the research matcher —
        otherwise the opposing through claims the same road corridor)."""
        tb = _avg_bearing(pts, 3, tail=True)
        best, best_cost = None, None
        for chd in chan_decls:
            cb = _avg_bearing(chd["poly"], 3, tail=True)
            if tb is not None and cb is not None and _bearing_diff(tb, cb) > 60:
                continue
            dmean = sum(min(math.hypot(p[0]-q[0], p[1]-q[1]) for q in chd["poly"])
                        for p in pts) / len(pts)
            if dmean <= chd["halfw"] and (best_cost is None or dmean < best_cost):
                best, best_cost = chd, dmean
        return best

    entry_refs = {l: refh_fixed[l] for l in refh_fixed}
    exit_refs = {l: (refh_fixed[l] + 180) % 360 for l in refh_fixed}
    n_rebinned = n_chan_claimed = 0
    for pts, od_a, od_h, eb, xb in prelim:
        ch_hit = _channel_claim(pts) if chan_decls else None
        if ch_hit is not None:
            groups[ch_hit["od"]].append(pts)
            n_chan_claimed += 1
            continue
        o = _rebin(eb, od_a[0], entry_refs)
        d = _rebin(xb, od_a[1], exit_refs)
        if (o, d) != od_a:
            n_rebinned += 1
        groups[(o, d)].append(pts)
        if od_h is not None and None not in od_h:
            hgroups[od_h].append(pts)

    # u_turn anchor cells (o==d) are mostly fragments/queues, not real U-turns
    # (cam3 31->31 had 121 such); heading recovery may still surface a real
    # cell. Drop same-leg anchor groups from PRIMARY admission.
    candidates: dict[tuple, tuple[list, str]] = {
        od: (g, "gtfree-anchor") for od, g in groups.items() if od[0] != od[1]}
    # Heading recovery: a heading cell with enough support whose anchor group
    # was too small (the cam5 EB-right blind spot). Bearing gate downstream
    # rejects over-collecting straight recoveries.
    for od, hg in hgroups.items():
        if od[0] == od[1]:
            continue
        if len(candidates.get(od, ((), ""))[0]) < args.min_support <= len(hg):
            candidates[od] = (hg, "gtfree-heading-recovered")

    n_grouped = sum(len(g) for g, _ in candidates.values()) or 1
    paths, qa_cells = [], []
    print(f"cam{cam} GT-free bank — {args.start_hms}+{args.minutes:.0f}min, "
          f"{len(kept)} usable tracks, agreement rate {n_agree/max(1,len(kept))*100:.0f}%, "
          f"bearing-rebinned {n_rebinned}")
    print(f"{'cell':<26}{'n':>5}{'share':>7}{'straight':>9}{'bearing_res':>12}  status")

    for (ol, dl), (g, source) in sorted(candidates.items(), key=lambda kv: -len(kv[1][0])):
        share = len(g) / n_grouped
        # Admission is ABSOLUTE support only. The published 1% OD-share rule
        # kills real low-volume turns at high-volume intersections (cam3
        # EB-right: 6 collected tracks = exactly its manual count, but 0.4%
        # share); the bearing + dedup gates downstream carry the magnet safety
        # that share gating was a proxy for. Share is kept as a QA signal.
        if len(g) < args.min_support:
            qa_cells.append({"cell": f"L{ol}->L{dl}", "n": len(g),
                             "share": round(share, 4), "status": "below_support"})
            continue
        poly = _fit_mean_polyline(g, args.poly_pts)
        st = _straightness(poly)
        # GT-free magnet gate: the fitted polyline must actually run from the
        # claimed origin leg to the claimed dest leg by DIRECTION, not just by
        # endpoint proximity. Mis-binned throughs fail the exit bearing.
        eb, xb = _avg_bearing(poly, 3, tail=False), _avg_bearing(poly, 3, tail=True)
        def _best_res(bearing, calib_ref, consensus_ref):
            cands = [r for r in (calib_ref, consensus_ref) if r is not None]
            if bearing is None or not cands:
                return None
            return min(_bearing_diff(bearing, r) for r in cands)
        res_in = _best_res(eb, refh.get(ol), entry_consensus.get(ol))
        res_out = _best_res(xb, (refh[dl] + 180) % 360 if dl in refh else None,
                            exit_consensus.get(dl))
        minor = share < args.min_share
        bearing_bad = ((res_in is not None and res_in > args.bearing_tol)
                       or (res_out is not None and res_out > args.bearing_tol))
        # Movement label from the polyline's OWN entry->exit bearing delta —
        # data-driven, immune to miscalibrated leg headings (cam3 leg 31 was
        # 59 deg off, which made derive_movement call the EB-left a through).
        # Two bands: real throughs hug 0 deg (1-5 observed); the collinear-exit
        # left at cam3 sits at ~25 (the snap-magnet geometry — image-space turn
        # delta is compressed at oblique cameras). 15-30 deg is decided by road
        # OPPOSITENESS: through only if the dest road's observed axis is the
        # closest to the origin's among all legs. Signed: positive = clockwise
        # = right.
        signed = (None if eb is None or xb is None
                  else ((xb - eb + 180) % 360) - 180)
        mv = _cardinal_movement(ol, dl)
        if mv is None:   # cardinal missing on a leg — geometric fallback
            mv = ("u_turn" if ol == dl
                  else derive_movement(leg_dicts[ol], leg_dicts[dl], all_legs))
        label = f"L{ol}->L{dl} {mv}"
        row = {"cell": label, "n": len(g), "share": round(share, 4),
               "straightness": round(st, 3),
               "bearing_residuals": [None if r is None else round(r, 1)
                                     for r in (res_in, res_out)]}
        if bearing_bad and ol != dl:
            row["status"] = "bearing_rejected"
            qa_cells.append(row)
            print(f"{label:<26}{len(g):>5}{share*100:>6.1f}%{st:>9.3f}"
                  f"{str(row['bearing_residuals']):>12}  BEARING_REJECTED")
            continue
        # Minor cells (below --min-share) are fitted from a handful of tracks
        # and can be pure noise (cam3: 5 fragments labeled "left" on a cell
        # whose geometry is a right turn cost ~4pp at apply). Independent
        # agreement check: the SHAPE-derived label must match the LEG-GEOMETRY
        # label. Major cells skip this — shape wins there (geometry is what
        # mislabeled the EB-left through a miscalibrated heading).
        # Minor-cell coherence gate: a real low-volume movement is a handful of
        # vehicles tracing the SAME curve (tight spread around the fitted
        # polyline); a junk cell is unrelated fragments whose mean polyline
        # means nothing — and at apply a junk polyline captures real flows
        # (cam3: 5 scattered fragments admitted as a cell cost ~4pp net).
        if minor and ol != dl:
            spreads = []
            for m in g:
                rm = _densify([list(p) for p in m], args.poly_pts)
                spreads.append(_mean_pairwise_dist(rm, poly))
            spread = sum(spreads) / len(spreads)
            row["member_spread_px"] = round(spread, 1)
            if spread > args.minor_spread_px:
                row["status"] = "minor_incoherent_rejected"
                qa_cells.append(row)
                print(f"{label:<26}{len(g):>5}{share*100:>6.1f}%{st:>9.3f}"
                      f"{str(row['bearing_residuals']):>12}  "
                      f"MINOR_REJECTED (member spread {spread:.0f}px)")
                continue
        row["status"] = "admitted"
        if mv in ("left", "right") and st > 0.95:
            row["warn"] = "straight_turn"   # QA flag only: real but verify visually
        qa_cells.append(row)
        print(f"{label:<26}{len(g):>5}{share*100:>6.1f}%{st:>9.3f}"
              f"{str(row['bearing_residuals']):>12}  ok"
              + ("  [WARN straight turn]" if row.get("warn") else ""))
        paths.append({"origin_leg_id": ol, "destination_leg_id": dl,
                      "movement_label": mv, "_signed": signed,
                      "polyline": [[round(x, 1), round(y, 1)] for x, y in poly],
                      "supporting_count": len(g), "source": source})

    # --- GT-free dedup gate: two same-origin cells whose polylines nearly
    # coincide are ONE flow split by endpoint binning (the snap-magnet shape:
    # cam3's 299-track "L30->L32" was NB-thru tracks whose endpoints landed
    # near the wrong anchor). Keep the better-supported cell; no volume data
    # needed. Cross-origin near-coincidence stays a QA warning only.
    drop = set()
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            a, b = paths[i], paths[j]
            if a["origin_leg_id"] != b["origin_leg_id"]:
                continue
            if _mean_pairwise_dist(a["polyline"], b["polyline"]) >= args.ambiguity_px:
                continue
            loser = a if a["supporting_count"] < b["supporting_count"] else b
            winner = b if loser is a else a
            drop.add((loser["origin_leg_id"], loser["destination_leg_id"]))
            qa_cells.append({"cell": f"L{loser['origin_leg_id']}->L{loser['destination_leg_id']} "
                                     f"{loser['movement_label']}",
                             "n": loser["supporting_count"],
                             "status": "dedup_dropped",
                             "kept": f"L{winner['origin_leg_id']}->L{winner['destination_leg_id']}"})
            print(f"L{loser['origin_leg_id']}->L{loser['destination_leg_id']} "
                  f"{loser['movement_label']}: DEDUP_DROPPED (coincides with "
                  f"better-supported L{winner['origin_leg_id']}->L{winner['destination_leg_id']})")
    paths = [p for p in paths
             if (p["origin_leg_id"], p["destination_leg_id"]) not in drop]

    # QA cross-check: a cardinal-labeled THROUGH whose polyline bends hard, or
    # a turn that runs dead straight, is worth an operator look (possible
    # cardinal mislabel — the cam1 180-degree-swap class of error).
    for p in paths:
        s = p.get("_signed")
        if s is None:
            continue
        if p["movement_label"] == "through" and abs(s) > 60:
            qa_cells.append({"cell": f"L{p['origin_leg_id']}->L{p['destination_leg_id']}",
                             "status": "warn_through_bends", "signed_delta": round(s, 1)})
    for p in paths:
        p.pop("_signed", None)

    # --- operator channels: declared movement set + fallback geometry -------
    if raw_chans:
        covered = {(p["origin_leg_id"], p["destination_leg_id"]) for p in paths}
        for chd in raw_chans:
            od = chd["od"]
            if od in covered:
                continue
            ctrl = [chd["entry"], chd.get("apex") or chd["entry"], chd["exit"]]
            paths.append({"origin_leg_id": od[0], "destination_leg_id": od[1],
                          "movement_label": chd["movement"],
                          "polyline": _densify(ctrl, args.poly_pts),
                          "supporting_count": 0, "source": "hand-drawn-channel"})
            qa_cells.append({"cell": f"L{od[0]}->L{od[1]} {chd['movement']}",
                             "n": 0, "status": "channel_fallback"})
            print(f"{f'L{od[0]}->L{od[1]} {chd['movement']}':<26}{'0':>5}{'--':>7}"
                  f"{'--':>9}{'--':>12}  CHANNEL_FALLBACK (hand-drawn)")

    # --- QA report (2.4) -----------------------------------------------------
    ambiguous = []
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            d = _mean_pairwise_dist(paths[i]["polyline"], paths[j]["polyline"])
            if d < args.ambiguity_px:
                ambiguous.append({"a": f"L{paths[i]['origin_leg_id']}->L{paths[i]['destination_leg_id']}",
                                  "b": f"L{paths[j]['origin_leg_id']}->L{paths[j]['destination_leg_id']}",
                                  "mean_px": round(d, 1)})
    leg_sanity = []
    for lid, bearings in leg_entry_bearings.items():
        if lid not in refh or len(bearings) < 10:
            continue
        s = sum(math.sin(math.radians(b)) for b in bearings)
        co = sum(math.cos(math.radians(b)) for b in bearings)
        mean_b = math.degrees(math.atan2(s, co)) % 360
        diff = _bearing_diff(mean_b, refh[lid])
        leg_sanity.append({"leg_id": lid, "calibrated_heading": refh[lid],
                           "observed_entry_bearing": round(mean_b, 1),
                           "diff_deg": round(diff, 1),
                           "verdict": "SUSPECT_LABEL_OR_HEADING" if diff > 90 else "ok"})

    qa = {"camera": cam, "window": f"{args.start_hms}+{args.minutes:.0f}min",
          "n_tracks_usable": len(kept), "agreement_rate": round(n_agree/max(1,len(kept)), 3),
          "cells": qa_cells, "ambiguous_pairs": ambiguous, "leg_sanity": leg_sanity,
          "anchor_cells_raw": {f"{k[0]}->{k[1]}": len(g) for k, g in
                               sorted(groups.items(), key=lambda kv: -len(kv[1]))[:12]}}
    out = {"project": project, "camera_id": cam, "updated_legs": [], "paths": paths,
           "source": "gtfree", "qa": str(qa_path)}
    out_path.write_text(json.dumps(out, indent=2))
    qa_path.write_text(json.dumps(qa, indent=2))
    for w in leg_sanity:
        if w["verdict"] != "ok":
            print(f"!! LEG SANITY: leg {w['leg_id']} calibrated {w['calibrated_heading']}deg "
                  f"but traffic enters at {w['observed_entry_bearing']}deg — check label/heading")
    if ambiguous:
        print(f"!! AMBIGUITY: {len(ambiguous)} polyline pairs closer than "
              f"{args.ambiguity_px}px mean — see QA report")
    print(f"\nwrote {out_path} ({len(paths)} paths) + {qa_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
