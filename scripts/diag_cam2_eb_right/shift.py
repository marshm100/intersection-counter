import sys, sqlite3, glob
from collections import defaultdict
from datetime import datetime, timedelta, time as dtime
sys.path.insert(0,'.'); sys.path.insert(0,'scripts')
import v2_score_dev as S
from backend.services.rule595 import score_cells, compliance
site=S.SITES[S.CORRIDOR]
def ap(pm):
    o=defaultdict(lambda: defaultdict(int))
    for m,c in pm.items():
        for k,v in c.items(): o[m][k[0]]+=v
    return o
cams=[int(c) for c in sys.argv[1].split(',')]
shifts=[-60,-45,-30,-15,0,15,30,45,60,90]
print('shift(s)        '+'  '.join(f'{s:>9}' for s in shifts))
for cam in cams:
    leg_dir=S.leg_dir_for(S.CORRIDOR,cam,site); mio=S.load_miovision(cam,site)
    for db in sorted(glob.glob(f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam{cam}_sf0_study_*.db')):
        win='study_'+db.split('study_')[1][:4]
        lo,hi=site['windows'][win]; mm=[m for m in (dtime(h,x) for h in range(lo,hi) for x in range(60)) if m in mio]
        ev=S.events_from_db(db,cam,site); out=[]
        for s in shifts:
            e2=[dict(e,wallclock=(datetime.fromisoformat(e['wallclock'])+timedelta(seconds=s)).isoformat()) for e in ev]
            pm=S.per_min_from_events(e2,leg_dir)
            out.append(f"{compliance(score_cells(pm,mio,mm))['pct']:4}/{compliance(score_cells(ap(pm),ap(mio),mm))['pct']:4}")
        print(f'cam{cam} {win[6:]}  '+'  '.join(f'{o:>9}' for o in out))
