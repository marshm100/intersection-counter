"""Per track: full-frame path overview + 4 crops (2x) along its life, with every other COUNTED track's box drawn
(yellow, with id) so a second track on the same car is visible. Read-only.
usage: sheet2.py WINDOW OUT.png tid,tid,..."""
import sys, sqlite3, json, cv2, numpy as np
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
W,out=sys.argv[1],sys.argv[2]; tids=[int(t) for t in sys.argv[3].split(',')]
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
path,chash=con.execute('select path,content_hash from videos where video_id=2').fetchone()
legs=con.execute('select leg_id,gate_segment from legs where camera_id=2').fetchall()
db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
cnt={int(t):f'{o}>{de}' for t,o,de in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id from vehicle_events where camera_id=2 and coalesce(rejected,0)=0")}
rows=rows[np.isin(rows[:,0],list(cnt))]
byf={}
cap=cv2.VideoCapture(path)
def frame(f):
    cap.set(cv2.CAP_PROP_POS_FRAMES,f); ok,img=cap.read()
    for lid,g in legs:
        p=np.array(json.loads(g)).astype(int); cv2.line(img,tuple(p[0]),tuple(p[1]),(255,255,255),1)
        cv2.putText(img,str(lid),tuple(p[0]),0,0.5,(255,255,255),1)
    return img
def box(img,b,col,lab):
    x,y,w,h=b; cv2.rectangle(img,(int(x-w/2),int(y-h/2)),(int(x+w/2),int(y+h/2)),col,1)
    cv2.putText(img,lab,(int(x-w/2),int(y-h/2)-2),0,0.35,col,1)
out_rows=[]
for t in tids:
    r=rows[rows[:,0]==t]; r=r[np.argsort(r[:,1])]
    f0,f1=int(r[0,1]),int(r[-1,1])
    ov=frame(int(r[len(r)//2,1]))
    pts=r[:,2:4].astype(np.int32); cv2.polylines(ov,[pts],False,(0,0,255),2); cv2.circle(ov,tuple(pts[0]),5,(0,255,0),-1)
    cv2.putText(ov,f'{t} {cnt[t]} {(f1-f0)/25:.0f}s',(5,25),0,0.8,(0,255,255),2)
    H,Wd=ov.shape[:2]; tiles=[cv2.resize(ov,(480,int(480*H/Wd)))]
    th=tiles[0].shape[0]
    for k in np.linspace(0,len(r)-1,5).astype(int):
        f=int(r[k,1]); img=frame(f)
        oth=rows[(rows[:,1]==f)&(rows[:,0]!=t)]
        for q in oth: box(img,q[2:6],(0,255,255),f'{int(q[0])} {cnt[int(q[0])]}')
        box(img,r[k,2:6],(0,0,255),'')
        x,y,w,h=r[k,2:6]; s=max(60,int(3*max(w,h)))
        x0,y0=int(max(0,min(Wd-2*s,x-s))),int(max(0,min(H-2*s,y-s)))
        c=img[y0:y0+2*s,x0:x0+2*s]; c=cv2.resize(c,(th,th))
        cv2.putText(c,f'+{(f-f0)/25:.1f}s w{w:.0f}',(3,14),0,0.45,(0,255,0),1)
        tiles.append(c)
    out_rows.append(np.hstack(tiles))
cv2.imwrite(out,np.vstack(out_rows)); print(out)
