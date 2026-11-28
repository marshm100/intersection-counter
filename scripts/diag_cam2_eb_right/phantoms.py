import sys, sqlite3, numpy as np
sys.path.insert(0,'.'); sys.path.insert(0,'scripts'); sys.path.insert(0, sys.argv[1])
import journey_eval_x as JX
import eval_journeys as EJ
EJ.score_clip = JX.score_clip
from datetime import datetime
for ho in (False, True):
    res = EJ.run_arm('sf0', {2:'sf0_'}, heldout=ho)
    for clip, r in res.items():
        if not clip.startswith('cam2'): continue
        window = 'study_' + clip.split('_')[1]
        con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
        chash=con.execute('select content_hash from videos where video_id=2').fetchone()[0]
        db, rows = EJ.locate('sf0', {2:'sf0_'}, 2, window, chash)
        d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
        print(f'\n{clip}: {len(r["phantom_list"])} phantoms')
        print('  tid   o->d  src              gate        span/w  w_med  y_med  nfr  dur_s  start_xy -> end_xy')
        for e in r['phantom_list']:
            t=int(e['vehicle_track_id'])
            src=d.execute("select coalesce(posterior_source,'-') from vehicle_events where camera_id=2 and vehicle_track_id=?",(t,)).fetchone()[0]
            g=d.execute("select gate_tag, linked_to_tid from track_fates where camera_id=2 and vehicle_track_id=? and disposition='counted'",(t,)).fetchone()
            rr=rows[rows[:,0]==t]
            if len(rr):
                rr=rr[np.argsort(rr[:,1])]
                span=np.hypot(np.ptp(rr[:,2]),np.ptp(rr[:,3])); w=np.median(rr[:,4])
                print(f'  {t:5} {e["origin_leg_id"]}->{e["destination_leg_id"]}  {src:16} {str(g[0] if g else "?"):11} {span/w:6.1f} {w:6.1f} {np.median(rr[:,3]):6.0f} {len(rr):4} {(rr[-1,1]-rr[0,1])/25:6.1f}  ({rr[0,2]:.0f},{rr[0,3]:.0f})->({rr[-1,2]:.0f},{rr[-1,3]:.0f})')
            else:
                print(f'  {t:5} {e["origin_leg_id"]}->{e["destination_leg_id"]}  {src:16} {str(g[0] if g else "?"):11}  (no dump rows - linked id?) {g}')
