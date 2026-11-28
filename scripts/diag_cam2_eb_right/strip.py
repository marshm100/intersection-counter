import sys, sqlite3, json, cv2, numpy as np
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
path,chash=con.execute('select path,content_hash from videos where video_id=2').fetchone()
legs=con.execute('select leg_id,gate_segment from legs where camera_id=2').fetchall()
win=sys.argv[4] if len(sys.argv)>4 else 'study_1600'
db,rows=EJ.locate('sf0',{2:'sf0_'},2,win,chash)
out=sys.argv[1]; tids=[int(t) for t in sys.argv[2].split(',')]; n=int(sys.argv[3])
cap=cv2.VideoCapture(path)
tiles=[]
for t in tids:
    r=rows[rows[:,0]==t]; r=r[np.argsort(r[:,1])]
    for k in np.linspace(0,len(r)-1,n).astype(int):
        f=int(r[k,1]); cap.set(cv2.CAP_PROP_POS_FRAMES,f); ok,img=cap.read()
        for lid,g in legs:
            p=np.array(json.loads(g)).astype(int); cv2.line(img,tuple(p[0]),tuple(p[1]),(255,255,255),1)
        x,y,w,h=r[k,2:6]; cv2.rectangle(img,(int(x-w/2),int(y-h/2)),(int(x+w/2),int(y+h/2)),(0,0,255),1)
        crop=img[60:200,:].copy(); crop=cv2.resize(crop,None,fx=1.5,fy=1.5)
        cv2.putText(crop,f'tid {t} f{f} ({x:.0f},{y:.0f}) w{w:.0f}',(5,20),0,0.6,(0,255,255),2)
        tiles.append(crop)
cv2.imwrite(out,np.vstack(tiles))
