import sys, sqlite3, json, cv2, numpy as np
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
path,chash=con.execute('select path,content_hash from videos where video_id=2').fetchone()
legs=con.execute('select leg_id,gate_segment from legs where camera_id=2').fetchall()
db,rows=EJ.locate('sf0',{2:'sf0_'},2,'study_1600',chash)
out=sys.argv[1]; tids=[int(t) for t in sys.argv[2].split(',')]
cap=cv2.VideoCapture(path); lines=[]
for t in tids:
    r=rows[rows[:,0]==t]; r=r[np.argsort(r[:,1])]; tiles=[]
    for k in np.linspace(0,len(r)-1,4).astype(int):
        f=int(r[k,1]); cap.set(cv2.CAP_PROP_POS_FRAMES,f); ok,img=cap.read()
        for lid,g in legs:
            p=np.array(json.loads(g)).astype(int); cv2.line(img,tuple(p[0]),tuple(p[1]),(255,255,255),1)
            cv2.putText(img,str(lid),tuple(p[0]),0,0.5,(255,255,255),1)
        x,y,w,h=r[k,2:6]; cv2.rectangle(img,(int(x-w/2),int(y-h/2)),(int(x+w/2),int(y+h/2)),(0,0,255),2)
        cv2.putText(img,f'{t} f{f} w{w:.0f}',(5,20),0,0.6,(0,255,255),2)
        tiles.append(cv2.resize(img,(320,240)))
    lines.append(np.hstack(tiles))
cv2.imwrite(out,np.vstack(lines))
