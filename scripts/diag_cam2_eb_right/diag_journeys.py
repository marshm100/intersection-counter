import sys, sqlite3
from collections import Counter, defaultdict
from pathlib import Path
sys.path.insert(0, 'scripts'); sys.path.insert(0, '.')
import eval_journeys as EJ
import backend.services.journey_eval as JE
from backend.services.journey_labels import list_clips, list_labels
con = sqlite3.connect(f"file:data/projects/{EJ.PROJ}/project.db?mode=ro", uri=True)
for clip in list_clips(EJ.PROJ):
    if clip['camera_id'] != 2: continue
    labels = list_labels(EJ.PROJ, clip['clip_id'])
    if not labels: print(clip['clip_id'], 'no labels'); continue
    window = 'study_' + clip['clip_id'].split('_')[1]
    chash, fps = con.execute("SELECT content_hash, fps FROM videos WHERE video_id=?", (clip['video_id'],)).fetchone()
    db, rows = EJ.locate('sf0', {2: 'sf0_'}, 2, window, chash)
    d = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cols = ("vehicle_track_id","origin_leg_id","destination_leg_id","start_frame","src","frame_number")
    events = [dict(zip(cols, r)) for r in d.execute("SELECT vehicle_track_id, origin_leg_id, destination_leg_id, COALESCE(start_frame, frame_number), coalesce(posterior_source,'-'), frame_number FROM vehicle_events WHERE camera_id=2 AND COALESCE(rejected,0)=0")]
    f_lo, f_hi = int(clip['start_frame']), int(clip['end_frame'])
    byf = JE.index_rows(rows, f_lo - JE.SEARCH_FRAMES, f_hi + JE.SEARCH_FRAMES)
    dups = JE.duplicate_labels(labels, fps, byf)
    labs = [lb for lb in labels if lb['label_id'] not in dups]
    entry_of, exit_of = JE._assign_clicks(labs, rows, byf, fps)
    owner = {}
    for side in (exit_of, entry_of):
        for lid, t in side.items(): owner[t] = lid
    ev_by = defaultdict(list)
    for e in events: ev_by[int(e['vehicle_track_id'])].append(e)
    print(f"\n### {clip['clip_id']} frames {f_lo}-{f_hi} labels {len(labs)} (dups {len(dups)})")
    for lb in labs:
        lid = lb['label_id']; tin, tout = entry_of.get(lid), exit_of.get(lid)
        if lb.get('entry_frame') is None or lb.get('exit_frame') is None: continue
        tids = {t for t in (tin, tout) if t is not None}
        evs = [e for t in tids if owner.get(t) == lid for e in ev_by.get(t, ())]
        truth = (lb['entry_leg_id'], lb['exit_leg_id'])
        ok = len(evs) == 1 and (evs[0]['origin_leg_id'], evs[0]['destination_leg_id']) == truth
        if ok: continue
        print(f"  VEH {lid} truth {truth[0]}->{truth[1]} entry_f {lb['entry_frame']} exit_f {lb['exit_frame']} tin {tin} tout {tout} events " +
              str([(e['vehicle_track_id'], f"{e['origin_leg_id']}->{e['destination_leg_id']}", e['src']) for e in evs]))
    claimed = set(owner)
    ph = [e for e in events if f_lo <= int(e['start_frame'] or -1) <= f_hi and int(e['vehicle_track_id']) not in claimed]
    print('  PHANTOMS:')
    for e in ph:
        t = int(e['vehicle_track_id']); r = rows[rows[:,0]==t]
        print(f"    tid {t} {e['origin_leg_id']}->{e['destination_leg_id']} src {e['src']} frames {int(r[:,1].min()) if len(r) else '?'}-{int(r[:,1].max()) if len(r) else '?'} n {len(r)} first ({r[0,2]:.0f},{r[0,3]:.0f}) last ({r[-1,2]:.0f},{r[-1,3]:.0f}) w {float(r[:,4].mean()) if len(r) else 0:.0f}")
    print('  phantom cells', Counter(f"{e['origin_leg_id']}->{e['destination_leg_id']}" for e in ph))
