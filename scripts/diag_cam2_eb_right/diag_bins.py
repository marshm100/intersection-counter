import sys, sqlite3
from collections import defaultdict, Counter
from datetime import datetime, time as dtime
sys.path.insert(0, 'scripts'); sys.path.insert(0, '.')
import v2_score_dev as S
win = sys.argv[1]; cells = [tuple(c.split(':')) for c in sys.argv[2].split(',')]
lo, hi = S.SITES[S.CORRIDOR]['windows'][win]
db = f'data/projects/97a7849a/_replay_scratch/fleet_20260908/sf0_cam2_sf0_{win}.db'
leg_dir = S.leg_dir_for(S.CORRIDOR, 2, S.SITES[S.CORRIDOR])
mio = S.load_miovision(2, S.SITES[S.CORRIDOR])
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
rows = c.execute("select origin_leg_id,movement,timestamp_real,coalesce(posterior_source,'-') from vehicle_events where camera_id=2 and coalesce(rejected,0)=0").fetchall()
for (d, mv) in cells:
    print(f'\n== {win} {d} {mv}')
    srcs = Counter(); per = defaultdict(Counter); refb = Counter()
    for ol, m, ts, src in rows:
        if leg_dir.get(ol) != d or S.NORM.get(m, m) != mv or ts is None: continue
        t = datetime.fromisoformat(ts).time()
        if not (lo <= t.hour < hi): continue
        b = dtime(t.hour, t.minute // 15 * 15)
        if dtime(t.hour, t.minute) not in mio: continue
        per[b][src] += 1; srcs[src] += 1
    for tm, cl in mio.items():
        if lo <= tm.hour < hi: refb[dtime(tm.hour, tm.minute // 15 * 15)] += cl.get((d, mv), 0)
    top = [s for s, _ in srcs.most_common()]
    print('bin    ref  ours  diff | ' + ' '.join(f'{s[:10]:>10}' for s in top))
    for b in sorted(refb):
        o = sum(per[b].values())
        print(f'{b.strftime("%H:%M")} {refb[b]:5} {o:5} {o-refb[b]:+5} | ' + ' '.join(f'{per[b][s]:>10}' for s in top))
    print(f'TOTAL {sum(refb.values()):5} {sum(srcs.values()):5} {sum(srcs.values())-sum(refb.values()):+5} | ' + ' '.join(f'{srcs[s]:>10}' for s in top))
