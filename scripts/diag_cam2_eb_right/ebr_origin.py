"""EB-right counted tracks: where they start/end and how long they wait, split by 15-min bins where ours-Mio EB-right is
small (<=+5, 'match') vs large (>=+12, 'excess'). Also draws all start points on one frame per window. Read-only."""
import sys, sqlite3, json, cv2, numpy as np
from collections import defaultdict
from datetime import datetime, time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ, v2_score_dev as S
site=S.SITES[S.CORRIDOR]; ld=S.leg_dir_for(S.CORRIDOR,2,site); mio=S.load_miovision(2,site)
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
vpath,chash=con.execute('select path,content_hash from videos where video_id=2').fetchone()
legs=[(lid,np.array(json.loads(g)).astype(int)) for lid,g in con.execute('select leg_id,gate_segment from legs where camera_id=2')]
out=sys.argv[1] if len(sys.argv)>1 else 'screenshots/cam2_ebr_origin'
import os; os.makedirs(out,exist_ok=True)
for W in ('study_0700','study_1100','study_1600'):
    db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
    d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    ev={}
    for t,o,de,ts,src in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,timestamp_real,coalesce(posterior_source,'-') from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
        if ld[o]=='EB' and S.leg_dir_for and (o,de)==(28,29): ev[int(t)]=(datetime.fromisoformat(ts),src)
    # bin excess
    bx={}
    for t,(ts,_) in ev.items():
        b=(ts.hour,ts.minute//15*15); bx.setdefault(b,[0,0]); bx[b][1]+=1
    for (h,q) in bx:
        bx[(h,q)][0]=sum(mio.get(dtime(h,q+i),{}).get(('EB','right'),0) for i in range(15))
    cls={b:('match' if v[1]-v[0]<=5 else 'excess' if v[1]-v[0]>=12 else 'mid') for b,v in bx.items()}
    stat=defaultdict(list)
    cap=cv2.VideoCapture(vpath); f0=int(rows[0,1]); cap.set(cv2.CAP_PROP_POS_FRAMES,f0); ok,img=cap.read()
    for lid,p in legs: cv2.line(img,tuple(p[0]),tuple(p[1]),(255,255,255),1); cv2.putText(img,str(lid),tuple(p[0]),0,0.5,(255,255,255),1)
    for t,(ts,src) in ev.items():
        r=rows[rows[:,0]==t]
        if not len(r): continue
        r=r[np.argsort(r[:,1])]; c=cls[(ts.hour,ts.minute//15*15)]
        bx0=r[0,2],r[0,3]+r[0,5]/2; bx1=r[-1,2],r[-1,3]+r[-1,5]/2
        sp=np.hypot(np.diff(r[:,2]),np.diff(r[:,3])); still=(sp<0.3*np.median(r[:,4])/25).sum()/25
        stat[c].append((bx0[0],bx0[1],bx1[0],bx1[1],len(r)/25,still,np.median(r[:,4]),src))
        col={'match':(0,255,0),'excess':(0,0,255),'mid':(0,255,255)}[c]
        cv2.circle(img,(int(bx0[0]),int(bx0[1])),2,col,-1)
    cv2.imwrite(f'{out}/{W}_starts.png',img)
    print(f'\n{W}  bins', {f'{h:02}:{q:02}':f'{v[0]}/{v[1]} {cls[(h,q)]}' for (h,q),v in sorted(bx.items())})
    for c,L in stat.items():
        a=np.array([x[:7] for x in L],float)
        srcs=defaultdict(int)
        for x in L: srcs[x[7]]+=1
        q=lambda i: np.percentile(a[:,i],[10,50,90]).round(0).tolist()
        print(f'  {c:6} n={len(L):3} start x{q(0)} y{q(1)}  end x{q(2)} y{q(3)}  dur{q(4)} still_s{q(5)} w{q(6)}')
        print(f'         src {dict(srcs)}')
