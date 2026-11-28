import sys, sqlite3, json, cv2, numpy as np
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
path,chash=con.execute('select path,content_hash from videos where video_id=2').fetchone()
legs=con.execute('select leg_id,gate_segment from legs where camera_id=2').fetchall()
db,rows=EJ.locate('sf0',{2:'sf0_'},2,sys.argv[5] if len(sys.argv)>5 else 'study_1600',chash)
out=sys.argv[1]; t=int(sys.argv[2]); f0,f1=int(sys.argv[3]),int(sys.argv[4])
r=rows[rows[:,0]==t]; r=r[np.argsort(r[:,1])]
cap=cv2.VideoCapture(path); tiles=[]
for f in np.linspace(f0,f1,10).astype(int):
    cap.set(cv2.CAP_PROP_POS_FRAMES,int(f)); ok,img=cap.read()
    for lid,g in legs:
        p=np.array(json.loads(g)).astype(int); cv2.line(img,tuple(p[0]),tuple(p[1]),(255,255,255),1)
    k=np.abs(r[:,1]-f).argmin(); x,y,w,h=r[k,2:6]
    col=(0,0,255) if abs(r[k,1]-f)<=2 else (0,255,255)
    cv2.rectangle(img,(int(x-w/2),int(y-h/2)),(int(x+w/2),int(y+h/2)),col,1)
    crop=cv2.resize(img[70:170,:],None,fx=1.5,fy=1.5)
    cv2.putText(crop,f'tid {t} f{f} row f{int(r[k,1])} ({x:.0f},{y:.0f}) w{w:.0f}',(5,18),0,0.55,(0,255,255),2)
    tiles.append(crop)
cv2.imwrite(out,np.vstack(tiles))
gaps=np.diff(r[:,1]); print('rows',len(r),'max gap',gaps.max(),'at',r[np.argmax(gaps),1], 'pos before/after', r[np.argmax(gaps),2:5], r[np.argmax(gaps)+1,2:5])
