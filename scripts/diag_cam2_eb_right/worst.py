import sys, sqlite3
from collections import Counter, defaultdict
from datetime import datetime, time as dtime
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
import v2_score_dev as S
site=S.SITES[S.CORRIDOR]; leg_dir=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
db='data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_study_1600.db'
d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
ev=defaultdict(list)
for t,o,de,ts,src,f in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,timestamp_real,coalesce(posterior_source,'-'),frame_number from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
    m=datetime.fromisoformat(ts).time().replace(second=0,microsecond=0); ev[(m,leg_dir[o])].append((t,o,de,src,f))
for a in ('EB','WB'):
    diffs=[]
    for h in range(16,18):
        for mi in range(60):
            m=dtime(h,mi)
            if m not in mio: continue
            r=sum(v for k,v in mio[m].items() if k[0]==a); o=len(ev[(m,a)])
            diffs.append((o-r,m,r,o))
    diffs.sort(reverse=True)
    print(a,'worst minutes (ours-mio, minute, mio, ours):',[(x[0],x[1].strftime('%H:%M'),x[2],x[3]) for x in diffs[:6]])
    print(a,'sum of positive minutes', sum(x[0] for x in diffs if x[0]>0),' negative', sum(x[0] for x in diffs if x[0]<0))
    for x in diffs[:3]:
        print('  ',x[1].strftime('%H:%M'), [(e[0],f'{e[1]}->{e[2]}',e[3]) for e in ev[(x[1],a)]])
