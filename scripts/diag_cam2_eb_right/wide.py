import sys, sqlite3, numpy as np
from collections import Counter
from datetime import datetime, time as dtime
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
import eval_journeys as EJ, v2_score_dev as S
site=S.SITES[S.CORRIDOR]; leg_dir=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
chash=con.execute('select content_hash from videos where video_id=2').fetchone()[0]
print('leg_dir', leg_dir)
for win in ('study_0700','study_1100','study_1600'):
    db, rows = EJ.locate('sf0', {2:'sf0_'}, 2, win, chash)
    lo,hi=site['windows'][win]; mm=set(m for m in (dtime(h,x) for h in range(lo,hi) for x in range(60)) if m in mio)
    W={}
    order=np.argsort(rows[:,0]); r=rows[order]; t,i=np.unique(r[:,0],return_index=True); i=list(i)+[len(r)]
    for k,tt in enumerate(t): W[int(tt)]=(np.median(r[i[k]:i[k+1],4]), (r[i[k+1]-1,1]-r[i[k],1])/25)
    d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    c=Counter(); dur=Counter()
    for tid,o,ts in d.execute("select vehicle_track_id,origin_leg_id,timestamp_real from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
        if not ts or datetime.fromisoformat(ts).time().replace(second=0,microsecond=0) not in mm: continue
        w,du=W.get(int(tid),(0,0)); a=leg_dir.get(o)
        c[(a, 'w>=100' if w>=100 else 'w60-100' if w>=60 else 'w<60')]+=1
        if du>=30: dur[a]+=1
    mt=Counter()
    for m in mm:
        for k,v in mio.get(m,{}).items(): mt[k[0]]+=v
    print(win)
    for a in ('EB','WB','SB','NB'):
        ours=sum(v for k,v in c.items() if k[0]==a)
        print(f'  {a}: mio {mt[a]:5} ours {ours:5} ({ours-mt[a]:+4})  w<60 {c[(a,"w<60")]:5}  w60-100 {c[(a,"w60-100")]:4}  w>=100 {c[(a,"w>=100")]:4}   tracks>=30s {dur[a]:4}')
