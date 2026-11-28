"""Full-res frame with gate lines and the full paths (box bottom-centre) of given tracks. usage: paths.py WINDOW FRAME OUT tid,..."""
import sys, sqlite3, json, cv2, numpy as np
sys.path.insert(0,'scripts'); sys.path.insert(0,'.')
import eval_journeys as EJ
W,F,out=sys.argv[1],int(sys.argv[2]),sys.argv[3]; tids=[int(t) for t in sys.argv[4].split(',')]
con=sqlite3.connect('file:data/projects/97a7849a/project.db?mode=ro',uri=True)
path,chash=con.execute('select path,content_hash from videos where video_id=2').fetchone()
db,rows=EJ.locate('sf0',{2:'sf0_'},2,W,chash)
cap=cv2.VideoCapture(path); cap.set(cv2.CAP_PROP_POS_FRAMES,F); ok,img=cap.read()
for lid,g in con.execute('select leg_id,gate_segment from legs where camera_id=2'):
    p=np.array(json.loads(g)).astype(int); cv2.line(img,tuple(p[0]),tuple(p[1]),(255,255,255),1); cv2.putText(img,str(lid),tuple(p[0]),0,0.5,(255,255,255),1)
cols=[(0,0,255),(255,0,255),(0,255,255),(255,128,0),(0,255,0),(128,0,255)]
for i,t in enumerate(tids):
    r=rows[rows[:,0]==t]; r=r[np.argsort(r[:,1])]; c=cols[i%len(cols)]
    pts=np.c_[r[:,2],r[:,3]+r[:,5]/2].astype(np.int32); cv2.polylines(img,[pts],False,c,1)
    cv2.circle(img,tuple(pts[0]),3,c,-1); cv2.putText(img,str(t),tuple(pts[0]+[0,-4]),0,0.4,c,1)
cv2.imwrite(out,cv2.resize(img,None,fx=2,fy=2)); print(out)
