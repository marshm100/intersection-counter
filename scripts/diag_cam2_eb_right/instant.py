import sys, sqlite3, numpy as np, json
from collections import Counter, defaultdict
from datetime import datetime, time as dtime
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ, v2_score_dev as S
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
chash=con.execute('select content_hash from videos where video_id=2').fetchone()[0]
NAME={(28,29):'EB_right',(27,29):'SB_thru',(27,28):'SB_right',(26,27):'WB_right',(28,26):'EB_thru',(28,27):'EB_left',(29,27):'NB_thru',(29,28):'NB_left',(27,26):'SB_left',(26,28):'WB_thru',(26,29):'WB_left',(29,26):'NB_right'}
FPS=25
def instant_start(r):
    """stationary >=2 s, then within 1 s the box is >=2x the area AND moving >= 0.08 box-widths/frame."""
    f=r[:,1]; x=r[:,2]; y=r[:,3]; w=r[:,4]; a=r[:,4]*r[:,5]
    j=0; n=len(r)
    while j<n:
        k=j
        while k+1<n and np.hypot(x[k+1]-x[j],y[k+1]-y[j])<0.3*max(w[j],8): k+=1
        if f[k]-f[j]>=2*FPS and k+1<n:
            a0=np.median(a[max(j,k-10):k+1]); w0=np.median(w[max(j,k-10):k+1])
            m=(f>f[k])&(f<=f[k]+FPS)
            if m.sum()>=4:
                a1=np.median(a[m][:5]); 
                fm=f[m]; xm=x[m]; ym=y[m]
                sp=np.hypot(xm[min(4,len(xm)-1)]-x[k],ym[min(4,len(xm)-1)]-y[k])/max(fm[min(4,len(xm)-1)]-f[k],1)
                if (a1/a0>=2.0 or a1/a0<=0.5) and sp>=0.08*w0:
                    return (int(f[k]),round(float(x[k])),round(float(y[k])),round(float(w0)),round(a1/a0,1),round(sp/w0,2))
        j=k+1
    return None
res={}
for win in ('study_0700','study_1100','study_1600'):
    db,rows=EJ.locate('sf0',{2:'sf0_'},2,win,chash)
    rows=rows[np.lexsort((rows[:,1],rows[:,0]))]
    tids,idx=np.unique(rows[:,0],return_index=True); idx=list(idx)+[len(rows)]
    T={int(t):rows[idx[i]:idx[i+1]] for i,t in enumerate(tids)}
    lo,hi=S.SITES[S.CORRIDOR]['windows'][win]
    d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
    tot=Counter(); hit=Counter(); ex=defaultdict(list); src=Counter()
    for t,o,de,s,ts in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id,coalesce(posterior_source,'-'),timestamp_real from vehicle_events where camera_id=2 and coalesce(rejected,0)=0"):
        if ts is None or not (lo<=int(ts[11:13])<hi): continue
        c=NAME.get((o,de),f'{o}->{de}'); tot[c]+=1
        r=T.get(int(t))
        if r is None or len(r)<10: continue
        h=instant_start(r)
        if h: hit[c]+=1; ex[c].append((int(t),s)+h); src[(c,s)]+=1
    print(f'\n{win}: cell counted instant-start(theft signature)')
    for c,n in tot.most_common(): print(f'  {c:9} {n:6} {hit[c]:5} ({100*hit[c]/n:4.1f}%)')
    print('  EB_right hits by path:', {k[1]:v for k,v in src.items() if k[0]=='EB_right'})
    res[win]=ex
json.dump(res,open(sys.argv[1],"w"),default=float)
