r"""Sample counted events for the event audit (2026-10-01; backend/services/event_audit.py).

From an arm's working DBs (default: the shipped default's arm) every counted event is put in
a STRATUM by how the software decided it: the journey state machine's gate tag (full,
entry_only, exit_only, no_crossing) and the posterior source that set its movement. Per camera a
fixed-seed random sample is drawn per gate tag (full journeys as the control, the partial tags
as the suspects), avoiding the journey-label clip minutes. Each item keeps the track (from the
arm's linked dump) and a plain claim for the page.
Usage: .venv/Scripts/python.exe -X utf8 scripts/audit_sample.py BATCH [STEM]
"""
from __future__ import annotations

import random
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import eval_journeys as ej  # noqa: E402
from backend.services import event_audit as ea  # noqa: E402
from backend.services.journey_labels import list_clips  # noqa: E402

WINDOWS = [(1, "study_0700"), (1, "study_1600"), (2, "study_0700"), (2, "study_1100"),
           (2, "study_1600"), (3, "study_0600"), (4, "study_0700"), (4, "study_1100"),
           (4, "study_1600"), (5, "study_0700"), (5, "study_1100"), (5, "study_1600")]
PER_TAG = {"full": 5, "entry_only": 8, "exit_only": 8, "no_crossing": 6}
MAX_CLIP_S, PAD_S = 40.0, 1.0
SOURCE_WORDS = {None: "path shape", "-": "path shape", "gate_full": "both gate crossings",
                "branch1": "origin inferred", "rescue_supports": "destination by popularity",
                "rescue_exit": "rescued exit", "rescue_full": "rescued full journey",
                "straight_reroute": "straight-path reroute", "demoted": "demoted"}


def main() -> int:
    batch = sys.argv[1]
    stem = sys.argv[2] if len(sys.argv) > 2 else "fr3"
    rng = random.Random(20261001)
    con = sqlite3.connect(f"file:data/projects/{ej.PROJ}/project.db?mode=ro", uri=True)
    legname = {lid: card for lid, card in con.execute("SELECT leg_id, cardinal_direction FROM legs")}
    clip_spans = defaultdict(list)
    for c in list_clips(ej.PROJ):
        clip_spans[c["camera_id"]].append((c["start_frame"], c["end_frame"]))
    pool = defaultdict(list)          # (cam, tag) -> candidate events
    rows_of = {}
    for cam, window in WINDOWS:
        vid, chash, fps = con.execute("SELECT video_id, content_hash, fps FROM videos "
                                      "WHERE camera_id=?", (cam,)).fetchone()
        db, rows = ej.locate(stem, {}, cam, window, chash)
        if db is None:
            print(f"cam{cam} {window}: no {stem} DB, skipped")
            continue
        rows_of[(cam, window)] = rows
        d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for t, o, de, mv, src, sf, fn, gtag, go, gd in d.execute(
                "SELECT e.vehicle_track_id, e.origin_leg_id, e.destination_leg_id, e.movement, "
                "e.posterior_source, COALESCE(e.start_frame, e.frame_number), e.frame_number, "
                "f.gate_tag, f.gate_origin_leg_id, f.gate_dest_leg_id "
                "FROM vehicle_events e LEFT JOIN track_fates f ON f.camera_id=e.camera_id "
                "AND f.vehicle_track_id=e.vehicle_track_id AND f.disposition='counted' "
                "WHERE e.camera_id=? AND COALESCE(e.rejected,0)=0", (cam,)):
            if any(a - 300 <= sf <= b + 300 for a, b in clip_spans[cam]):
                continue
            tag = gtag or "unknown"
            pool[(cam, tag)].append(dict(cam=cam, window=window, vid=vid, fps=fps, t=int(t),
                                         o=o, de=de, mv=mv, src=src, tag=tag, go=go, gd=gd))
    n = 0
    for (cam, tag), evs in sorted(pool.items()):
        k = PER_TAG.get(tag, 4)
        for ev in rng.sample(evs, min(k, len(evs))):
            rows = rows_of[(ev["cam"], ev["window"])]
            tr = rows[rows[:, 0] == ev["t"]]
            if not len(tr):
                continue
            tr = tr[np.argsort(tr[:, 1])]
            fps = ev["fps"]
            f0, f1 = float(tr[0, 1]), float(tr[-1, 1])
            if (f1 - f0) / fps > MAX_CLIP_S:          # keep the end that decided it
                if tag == "exit_only":
                    f0 = f1 - MAX_CLIP_S * fps
                else:
                    f1 = f0 + MAX_CLIP_S * fps
            sel = tr[(tr[:, 1] >= f0) & (tr[:, 1] <= f1)]
            step = max(1, len(sel) // 300)
            track = [[int(r[1]), round(float(r[2]), 1), round(float(r[3]), 1),
                      round(float(r[4]), 1), round(float(r[5]), 1)] for r in sel[::step]]
            ln = lambda lid: legname.get(lid, "?") if lid is not None else "none"  # noqa: E731
            how = {"full": f"entered over {ln(ev['go'])}, left over {ln(ev['gd'])}",
                   "entry_only": f"entered over {ln(ev['go'])}, exit not seen",
                   "exit_only": f"entry not seen, left over {ln(ev['gd'])}",
                   "no_crossing": "crossed no gate line"}.get(tag, tag)
            src = SOURCE_WORDS.get(ev["src"], ev["src"] or "path shape")
            ea.add_item(ej.PROJ, {
                "batch": batch, "camera_id": cam, "video_id": ev["vid"], "window": ev["window"],
                "vehicle_track_id": ev["t"], "stratum": f"{tag}|{ev['src'] or '-'}",
                "claimed_origin_leg_id": ev["o"], "claimed_dest_leg_id": ev["de"],
                "claimed_movement": ev["mv"], "claim_detail": f"{how} · decided by {src}",
                "start_frame": int(f0 - PAD_S * fps), "end_frame": int(f1 + PAD_S * fps),
                "fps": fps, "track_json": track})
            n += 1
        print(f"cam{cam} {tag:12} pool {len(evs):5}  sampled {min(k, len(evs))}")
    print(f"{n} items in batch {batch}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
