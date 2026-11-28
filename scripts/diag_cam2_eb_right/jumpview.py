import sys, sqlite3, json, cv2, numpy as np
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
path,chash=con.execute('select path,content_hash from videos where video_id=2').fetchone()
legs=con.execute('select leg_id,gate_segment from legs where camera_id=2').fetchall()
db,rows=EJ.locate('sf0',{2:'sf0_'},2,'study_1600',chash)
d=json.load(open(sys.argv[2]))['study_1600']['EB_right']; sel={int(t) for t in sys.argv[3].split(',')}
cap=cv2.VideoCapture(path); tiles=[]
for e in d:
    if e[0] not in sel: continue
    t,fj=e[0],e[2]; r=rows[rows[:,0]==t]; r=r[np.argsort(r[:,1])]
    row=[]
    for f in (fj-25,fj,fj+12,fj+30):
        cap.set(cv2.CAP_PROP_POS_FRAMES,int(f)); ok,img=cap.read()
        for lid,g in legs:
            p=np.array(json.loads(g)).astype(int); cv2.line(img,tuple(p[0]),tuple(p[1]),(255,255,255),1)
        k=np.abs(r[:,1]-f).argmin(); x,y,w,h=r[k,2:6]
        cv2.rectangle(img,(int(x-w/2),int(y-h/2)),(int(x+w/2),int(y+h/2)),(0,0,255),2)
        cx=int(min(max(e[3],160),480)); crop=img[60:180,cx-160:cx+160]
        cv2.putText(crop,f'{t} f{f-fj:+d}',(3,14),0,0.45,(0,255,255),1); row.append(crop)
    tiles.append(np.hstack(row))
cv2.imwrite(sys.argv[1],np.vstack(tiles))
