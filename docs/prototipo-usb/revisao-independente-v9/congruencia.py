from pathlib import Path
import itertools
from scipy.spatial import cKDTree
exec((Path(__file__).parent/'auditar.py').read_text().split('pairs=[];',1)[0])
rotations=[]
for perm in itertools.permutations(range(3)):
 for signs in itertools.product([-1,1],repeat=3):
  a=np.eye(3)[list(perm)]*np.array(signs)[:,None]
  if np.linalg.det(a)>.9:rotations.append(a)
rows=[]
for name,m in meshes.items():
 n=(('13-bloqueio-bandeja-esquerda' if name.endswith('-5') else '13-bloqueio-bandeja-direita') if name.startswith('trava-bandeja-') else '12-pino-trava-berco' if name.startswith('trava-berco-') else '07-pino-quarto-volta' if name.startswith('pino-casca-') else '06-chave-emenda' if name.startswith('chave-') else name)
 stl=trimesh.load(PKG/'stl'/(n+'.stl'));v=stl.vertices;target=m.vertices-m.bounds[0];tree=cKDTree(target);best=float('inf')
 for rot in rotations:
  q=v@rot;q-=q.min(axis=0)
  if not np.allclose(q.max(axis=0),m.extents,atol=.0001):continue
  d=tree.query(q)[0].max()
  if d<best:best=max(d,cKDTree(q).query(target)[0].max())
 assert best<.0001,(name,best)
 rows.append({'assembly':name,'delivered_stl':n,'rigid_vertex_cloud_max_error_mm':float(best),'pass':True})
(ROOT/'congruencia.json').write_text(json.dumps(rows,indent=2)+'\n');print('CONGRUENT',len(rows),max(x['rigid_vertex_cloud_max_error_mm'] for x in rows))
