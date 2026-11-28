import sys, sqlite3, numpy as np
from collections import Counter
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ, v2_score_dev as S
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
chash=con.execute('select content_hash from videos where video_id=2').fetchone()[0]
NAME={(28,29):'EB_right',(27,29):'SB_thru',(27,28):'SB_right',(26,27):'WB_right',(28,26):'EB_thru',(28,27):'EB_left',(29,27):'NB_thru',(29,28):'NB_left',(27,26):'SB_left',(26,28):'WB_thru',(26,29):'WB_left',(29,26):'NB_right'}
for win in ('study_0700','study_1100','study_1600'):
    db,rows=EJ.locate('sf0',{2:'sf0_'},2,win,chash)
    rows=rows[np.lexsort((rows[:,1],rows[:,0]))]
    tids,idx=np.unique(rows[:,0],return_index=True); idx=list(idx)+[len(rows)]
    T={int(t):rows[idx[i]:idx[i+1]] for i,t in enumerate(tids)}
    lo,hi=S.SITES[S.CORRIDOR]['windows'][win]
    d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    tot=Counter(); still=Counter(); srcs=Counter()
    for t,o,de,s,ts in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,coalesce(posterior_source,'-'),timestamp_real from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
        if ts is None or not (lo<=int(ts[11:13])<hi): continue
        c=NAME.get((o,de),f'{o}->{de}'); tot[c]+=1
        r=T.get(int(t))
        if r is None: continue
        span=np.hypot(r[:,2].max()-r[:,2].min(), r[:,3].max()-r[:,3].min())
        if span < 2.0*np.median(r[:,4]): still[c]+=1; srcs[(c,s)]+=1
    print(f'{win}: counted tracks whose whole path spans < 2 box widths')
    print('  ', {c:f'{still[c]}/{n}' for c,n in tot.most_common() if still[c]})
    print('   EB_right by path', {k[1]:v for k,v in srcs.items() if k[0]=='EB_right'})
