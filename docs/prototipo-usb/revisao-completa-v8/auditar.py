from pathlib import Path
import json,zipfile,xml.etree.ElementTree as ET,itertools,hashlib,sys
import numpy as np,trimesh,manifold3d as md
ROOT=Path(__file__).resolve().parent;PKG=ROOT.parent/(sys.argv[1] if len(sys.argv)>1 else 'ender3-pla-oficial-v7')
def load(path):
 with zipfile.ZipFile(path) as z:t=ET.fromstring(z.read('3D/3dmodel.model'))
 meshes={};solids={}
 for o in t.findall('.//{*}object'):
  n=o.attrib.get('name',o.attrib['id']);v=[[float(a.attrib[k]) for k in ['x','y','z']] for a in o.findall('.//{*}vertex')];f=[[int(a.attrib[k]) for k in ['v1','v2','v3']] for a in o.findall('.//{*}triangle')];m=trimesh.Trimesh(v,f,process=True);s=md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)));assert str(s.status())=='Error.NoError',n
  meshes[n]=m;solids[n]=s
 return meshes,solids
def mesh(s):
 m=s.to_mesh64();return trimesh.Trimesh(m.vert_properties[:,:3],m.tri_verts,process=False)
def solid(m):return md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
def union(s):return md.Manifold.batch_boolean(list(s),md.OpType.Add)
def overlap(a,b):return max(0,(a^b).volume())
meshes,solids=load(PKG/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf')
pairs=[];collisions=[]
for a,b in itertools.combinations(solids,2):
 ma,mb=meshes[a],meshes[b]
 if np.any(ma.bounds[1]<mb.bounds[0]) or np.any(mb.bounds[1]<ma.bounds[0]):v=0.
 else:v=overlap(solids[a],solids[b])
 pairs.append({'a':a,'b':b,'intersection_mm3':v})
 if v>.001:collisions.append(pairs[-1]);print('COLISAO',a,b,round(v,6),flush=True)
# Compare each instantiated assembly object with the delivered individual STL.
identities=[]
for name,m in meshes.items():
 n=('13-trava-bandeja' if name.startswith('trava-bandeja-') else '12-pino-trava-berco' if name.startswith('trava-berco-') else '07-pino-quarto-volta' if name.startswith('pino-casca-') else '06-chave-emenda' if name.startswith('chave-') else name)
 stl=trimesh.load(PKG/'stl'/(n+'.stl'))
 diff=abs(stl.volume-m.volume);bounds=np.sort(stl.extents)-np.sort(m.extents)
 identities.append({'assembly':name,'stl':n,'volume_difference_mm3':diff,'max_extent_difference_mm':max(abs(bounds)),'pass':diff<max(.05,abs(m.volume)*1e-5) and max(abs(bounds))<1e-4})
parts=[]
for p in sorted((PKG/'stl').glob('*.stl')):
 m=trimesh.load(p);parts.append({'file':p.name,'dimensions_mm':m.extents.tolist(),'volume_mm3':m.volume,'watertight':m.is_watertight,'consistent_winding':m.is_winding_consistent,'positive_volume':m.volume>0,'components':len(m.split()),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
res={'package':str(PKG),'individual_stl_count':len(parts),'assembly_instances':len(solids),'all_static_pairs':len(pairs),'collisions':collisions,'pairwise':pairs,'assembly_to_individual':identities,'individual_parts':parts}
(ROOT/'auditoria-estatica.json').write_text(json.dumps(res,indent=2,default=lambda x:x.item() if isinstance(x,np.generic) else str(x))+'\n')
print('PARTS',len(parts),'ASSEMBLY',len(solids),'PAIRS',len(pairs),'COLLISIONS',len(collisions),'IDENTITY_ERRORS',[x['assembly'] for x in identities if not x['pass']],flush=True)
