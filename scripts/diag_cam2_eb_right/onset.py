"""Per track: motion onset (first frame after which the box keeps moving >= 0.03 w/frame for 1 s), widths before/after,
and any other track (counted or not) whose box overlaps ours (>=0.5 of smaller) at onset and which DIES within 2 s
after onset (a victim: we may have taken its car). usage: onset.py WINDOW tid,..."""
import sys, sqlite3, numpy as np
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
W=sys.argv[1]; tids=[int(t) for t in sys.argv[2].split(',')]
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
chash=con.execute('select content_hash from videos where video_id=2').fetchone()[0]
db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
cnt={int(t):f'{o}>{de}' for t,o,de in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id from vehicle_events where camera_id=2 and coalesce(rejected,0)=0")}
def cont(a,b):
    iw=max(0,min(a[0]+a[2]/2,b[0]+b[2]/2)-max(a[0]-a[2]/2,b[0]-b[2]/2)); ih=max(0,min(a[1]+a[3]/2,b[1]+b[3]/2)-max(a[1]-a[3]/2,b[1]-b[3]/2))
    return iw*ih/min(a[2]*a[3],b[2]*b[3])
for t in tids:
    r=rows[rows[:,0]==t]; r=r[np.argsort(r[:,1])]; f=r[:,1]; w=r[:,4]
    sp=np.r_[0,np.hypot(*np.diff(r[:,2:4],axis=0).T)/np.diff(f)]/np.maximum(w,1)
    on=None
    for i in range(len(r)):
        j=np.searchsorted(f,f[i]+25)
        if j<len(r) and f[j]-f[i]<=35 and np.hypot(*(r[j,2:4]-r[i,2:4]))/(f[j]-f[i])>=0.03*w[i]:
            on=i; break
    if on is None: print(t,cnt.get(t),'never moves'); continue
    still=(f[on]-f[0])/25
    wb=np.median(w[max(0,on-10):on+1]); wa=np.median(w[on:on+10])
    # victims
    F=f[on]; near=rows[(rows[:,1]>=F-5)&(rows[:,1]<=F)&(rows[:,0]!=t)]
    vic=[]
    for q in near:
        if cont(r[on,2:6],q[2:6])>=0.5:
            u=int(q[0]); last=rows[rows[:,0]==u][:,1].max()
            if F<=last<=F+50: vic.append(f'{u}({cnt.get(u,"-")}) dies +{(last-F)/25:.1f}s')
    vic=sorted(set(vic))
    print(f'{t} {cnt.get(t)} still {still:.0f}s before onset; w {wb:.0f}->{wa:.0f}; victims: {vic}')
