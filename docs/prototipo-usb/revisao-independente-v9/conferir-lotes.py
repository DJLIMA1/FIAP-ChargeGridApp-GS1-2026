from pathlib import Path
import itertools,json,hashlib
import numpy as np,trimesh
from scipy.spatial import cKDTree
R=Path(__file__).resolve().parent;P=R.parent/'ender3-pla-oficial-v9'
rot=[]
for perm in itertools.permutations(range(3)):
 for signs in itertools.product([-1,1],repeat=3):
  q=np.eye(3)[list(perm)]*np.array(signs)[:,None]
  if np.linalg.det(q)>.9:rot.append(q)
def congruent(a,b):
 target=b.vertices-b.bounds[0];tree=cKDTree(target);best=float('inf')
 for r in rot:
  v=a.vertices@r;v-=v.min(axis=0)
  if not np.allclose(v.max(axis=0),b.extents,atol=.0001):continue
  d=tree.query(v)[0].max()
  if d<best:best=max(d,cKDTree(v).query(target)[0].max())
 return best
mapping={'01CHAVE':['06-chave-emenda']*4,'02TRSUP':['01-traseira-superior'],'03TRINF7':['01-traseira-inferior'],'04QDSUP':['03-quadro-superior'],'05QDINF8':['03-quadro-inferior'],'06TAMPA':['05-tampa-frontal'],'07PTAMP':[f'08-pino-tampa-{i}' for i in range(1,5)],'08PTINF':['08-pino-tampa-5'],'09PINO':['07-pino-quarto-volta']*4,'10BERCO9':['09-bandeja-removivel','10-berco-potencia','11-berco-esp32'],'11TRAVA9':['12-pino-trava-berco']*2+['13-bloqueio-bandeja-esquerda','13-bloqueio-bandeja-direita']+['14-espacador-3mm']*4+['14-espacador-5mm']*4,'12CABO':['19-inserto-duplo-5mm-a','19-inserto-duplo-5mm-b']+['15-prensa-cabo-5mm-meia']*4}
rows=[]
for ident,names in mapping.items():
 parts=list(trimesh.load(P/'modelos-fatiados'/(ident+'.stl')).split());assert len(parts)==len(names)
 for name in names:
  m=trimesh.load(P/'stl'/(name+'.stl'));best=min((congruent(m,q),i) for i,q in enumerate(parts));assert best[0]<.0001,(ident,name,best)
  parts.pop(best[1]);rows.append({'batch':ident,'part':name,'error_mm':float(best[0])})
 print('PASS',ident,flush=True)
(R/'congruencia-lotes-v9.json').write_text(json.dumps(rows,indent=2)+'\n')
# Freeze exact 01 and 02 assets across delivery generations.
files={}
for ident in ['01CHAVE','02TRSUP']:
 for folder,ext in [('gcode','gcode'),('projetos','3mf'),('perfis','ini'),('modelos-fatiados','stl')]:
  name=f'{folder}/{ident}.{ext}';data=(P/name).read_bytes();assert data==(R.parent/'ender3-pla-oficial-v6'/name).read_bytes();files[name]=hashlib.sha256(data).hexdigest()
(R/'arquivos-01-02-preservar.json').write_text(json.dumps(files,indent=2)+'\n')
print('39 PARTS MATCH; 01/02 FROZEN')
