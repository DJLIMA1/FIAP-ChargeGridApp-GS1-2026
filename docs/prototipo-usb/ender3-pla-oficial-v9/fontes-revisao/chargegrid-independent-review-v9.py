from pathlib import Path
import json,hashlib,zipfile,xml.etree.ElementTree as ET,itertools
import numpy as np,trimesh,manifold3d as md
root=Path('/Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/docs/prototipo-usb'); pkg=root/'ender3-pla-oficial-v9'; out=root/'revisao-independente-v9'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
ident=[]
for job in ['01CHAVE','02TRSUP']:
 for sub,ext in [('gcode','.gcode'),('modelos-fatiados','.stl'),('perfis','.ini'),('projetos','.3mf')]:
  a=pkg/sub/(job+ext);b=root/'ender3-pla-oficial-v6'/sub/(job+ext)
  ident.append({'file':str(a.relative_to(pkg)),'same_as_v6':sha(a)==sha(b),'sha256':sha(a)})
meshes={};solids={}
with zipfile.ZipFile(pkg/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf') as z:doc=ET.fromstring(z.read('3D/3dmodel.model'))
for o in doc.findall('.//{*}object'):
 vs=np.array([[float(v.get(k)) for k in ['x','y','z']] for v in o.findall('.//{*}vertex')]);fs=np.array([[int(v.get(k)) for k in ['v1','v2','v3']] for v in o.findall('.//{*}triangle')]);n=o.get('name');m=trimesh.Trimesh(vs,fs,process=True);meshes[n]=m;solids[n]=md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
collisions=[];tested=0
for a,b in itertools.combinations(meshes,2):
 tested+=1
 if np.any(meshes[a].bounds[1]<meshes[b].bounds[0]) or np.any(meshes[b].bounds[1]<meshes[a].bounds[0]):continue
 overlap=(solids[a]^solids[b]).volume()
 if overlap>1e-3:collisions.append({'a':a,'b':b,'intersection_mm3':overlap})
geo=[]
for f in sorted((pkg/'stl').glob('*.stl')):
 m=trimesh.load(f);geo.append({'file':f.name,'watertight':bool(m.is_watertight),'winding':bool(m.is_winding_consistent),'bodies':len(m.split()),'volume':float(m.volume),'extents':m.extents.tolist()})
# Independently test rigid stop removal and the pre-threaded tie rear return.
def union(names):return md.Manifold.batch_boolean([solids[n] for n in names],md.OpType.Add)
records=[]
rear=union([n for n in solids if n.startswith('01-traseira') or (n.startswith('chave-') and n.endswith('90.8'))])
front=[n for n in solids if n.startswith(('03-quadro','05-tampa','08-pino')) or (n.startswith('chave-') and n.endswith('57.2'))]
for side,x in [('esquerda',5),('direita',55)]:
    tie_mesh=trimesh.load(out/f'cinta-{side}-envelope.stl');tie=md.Manifold(md.Mesh64(tie_mesh.vertices,tie_mesh.faces.astype(np.uint64)))
    for n,other in solids.items():
        volume=(tie^other).volume();records.append({'test':side+'_tie_static_'+n,'value':volume,'pass':volume<.001})
    for dz in np.linspace(0,5,101):
        volume=(tie.translate([0,0,float(dz)])^rear).volume();records.append({'test':side+'_tie_slide_'+str(dz),'value':volume,'pass':volume<.001})
    name=f'trava-bandeja-{x}';other=union([n for n in solids if n not in front+[name]])
    for distance in np.linspace(0,15,151):
        volume=(solids[name].translate([0,-float(distance),0])^other).volume();records.append({'test':side+'_stop_remove_'+str(distance),'value':volume,'pass':volume<.001})
    # Head of tie is accessible from front after front frame is removed; 4x3 mm corridor.
    # This tests visibility/access volume only, not a specific cutter shape.
    cx=(-17.5 if x==5 else 17.5)
    access=md.Manifold.cube([4,25,3]).translate([cx-2,55,37.1])
    for n in solids:
        if n in front:continue
        volume=(access^solids[n]).volume();records.append({'test':side+'_front_access_'+n,'value':volume,'pass':volume<.001})
result={'reviewer':'independent-subagent','protected_files':ident,'stl_checks':geo,'pair_tests':tested,'static_collisions':collisions,'correction_checks':records,'failures':[r for r in records if not r['pass']]}
(out/'revisor-independente-evidencias.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'protected_files_ok':all(i['same_as_v6'] for i in ident),'stls':len(geo),'pair_tests':tested,'static_collisions':collisions,'correction_checks':len(records),'failures':result['failures']},indent=2))
