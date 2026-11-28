"""Tiles of the line-28 region at given frames; counted tracks yellow with id, the named track red, others green.
usage: xsheet.py WINDOW OUT.png f:tid,f:tid,...  (tid 0 = none)"""
import sys, sqlite3, json, cv2, numpy as np
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
W,out=sys.argv[1],sys.argv[2]; items=[tuple(int(v) for v in s.split(':')) for s in sys.argv[3].split(',')]
X0,Y0,X1,Y1=[int(v) for v in (sys.argv[4] if len(sys.argv)>4 else '300,60,640,210').split(',')]
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
path,chash=con.execute('select path,content_hash from videos where video_id=2').fetchone()
legs=con.execute('select leg_id,gate_segment from legs where camera_id=2').fetchall()
db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
d=sqlite3.connect(f'file:{db}?mode=ro',uri=True)
cnt={int(t):f'{o}>{de}' for t,o,de in d.execute("select vehicle_track_id,origin_leg_id,destination_leg_id from vehicle_events where camera_id=2 and coalesce(rejected,0)=0")}
fs=sorted({f for f,_ in items}); sub=rows[np.isin(rows[:,1],fs)]
cap=cv2.VideoCapture(path); tiles=[]
for f,tid in items:
    cap.set(cv2.CAP_PROP_POS_FRAMES,f); ok,img=cap.read()
    for lid,g in legs:
        p=np.array(json.loads(g)).astype(int); cv2.line(img,tuple(p[0]),tuple(p[1]),(255,255,255),1)
    S=3; big=cv2.resize(img[Y0:Y1,X0:X1],None,fx=S,fy=S)
    for q in sub[sub[:,1]==f]:
        t=int(q[0]); x,y,w,h=q[2:6]
        col=(0,0,255) if t==tid else (0,255,255) if t in cnt else (0,200,0)
        p0=(int((x-w/2-X0)*S),int((y-h/2-Y0)*S)); p1=(int((x+w/2-X0)*S),int((y+h/2-Y0)*S))
        cv2.rectangle(big,p0,p1,col,2 if t in cnt else 1)
        if t in cnt: cv2.putText(big,f'{t} {cnt[t]}',(p0[0],p0[1]-3),0,0.5,col,1)
    cv2.putText(big,f'f{f} T{tid}',(5,20),0,0.7,(255,0,255),2)
    tiles.append(big)
while len(tiles)%2: tiles.append(np.zeros_like(tiles[0]))
cv2.imwrite(out,np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,len(tiles),2)])); print(out)
