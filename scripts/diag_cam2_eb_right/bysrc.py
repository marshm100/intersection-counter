import sys, sqlite3
from datetime import time as dtime
from collections import defaultdict, Counter
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import v2_score_dev as S
from backend.services.rule595 import score_cells, compliance
site=S.SITES[S.CORRIDOR]; leg_dir=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
def ap(pm):
    o=defaultdict(lambda: defaultdict(int))
    for m,c in pm.items():
        for k,v in c.items(): o[m][k[0]]+=v
    return o
for win in ('study_0700','study_1100','study_1600'):
    db=f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{win}.db'
    lo,hi=site['windows'][win]; mm=set(m for m in (dtime(h,x) for h in range(lo,hi) for x in range(60)) if m in mio)
    d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    tag={t:g for t,g in d.execute('select vehicle_track_id,gate_tag from track_fates where camera_id=2 and disposition="counted"')}
    evs=[]
    for t,o,mv,ts,src in d.execute("select vehicle_track_id,origin_leg_id,movement,timestamp_real,coalesce(posterior_source,'-') from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
        if ts: evs.append(dict(origin_leg=o,movement=mv,wallclock=ts,key=f'{src}/{tag.get(t,"?")}'))
    def score(ev):
        pm=S.per_min_from_events(ev,leg_dir); return compliance(score_cells(ap(pm),ap(mio),sorted(mm)))['pct'], compliance(score_cells(pm,mio,sorted(mm)))['pct']
    base=score(evs)
    # count per key per approach within scored minutes
    from datetime import datetime
    cnt=defaultdict(Counter)
    for e in evs:
        if datetime.fromisoformat(e['wallclock']).time().replace(second=0,microsecond=0) in mm:
            cnt[e['key']][leg_dir.get(e['origin_leg'])]+=1
    print(f'\n{win} base approach {base[0]} movement {base[1]}')
    for k,c in sorted(cnt.items(),key=lambda kv:-sum(kv[1].values())):
        a,m=score([e for e in evs if e['key']!=k])
        print(f'  drop {k:28} n={sum(c.values()):5} EB{c["EB"]:4} WB{c["WB"]:4} SB{c["SB"]:4} NB{c["NB"]:4} -> approach {a:5} movement {m:5}')
