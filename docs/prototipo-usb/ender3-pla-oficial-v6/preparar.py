"""Official print release: validated v5 snap pins, successful v2 profile, per-job supports."""
from pathlib import Path
import json,re,shutil,subprocess,zipfile,xml.etree.ElementTree as ET,importlib.util
import numpy as np
import trimesh
import manifold3d as md
ROOT=Path(__file__).resolve().parent
BASE=ROOT.parent
OLD=BASE/'ender3-pla-gcode-v2'
EXE='/tmp/chargegrid-prusa-dmg/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
for folder in ['stl','modelos-fatiados','perfis','gcode','projetos','montagem','verificacao','previas']:(ROOT/folder).mkdir(exist_ok=True)
spec=importlib.util.spec_from_file_location('pins',ROOT/'geometria-trava.py');pins=importlib.util.module_from_spec(spec);spec.loader.exec_module(pins)
def to_manifold(m):return md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
def check(m,quantity=1):
 assert m.is_watertight and m.is_winding_consistent and m.volume>0
 assert len(m.split())==quantity,(quantity,len(m.split()))
 return dict(watertight=True,consistent=True,quantity=quantity,size_mm=m.extents.tolist())
# Read actual assembled geometry, preserving identities and original exterior.
with zipfile.ZipFile(BASE/'cad-impressao-50-v1/montagem/ChargeGrid-50-MONTAGEM-nao-fatiar.3mf') as z:
 entries={n:z.read(n) for n in z.namelist()}
xml=ET.fromstring(entries['3D/3dmodel.model']);ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
objects={};elements={}
for o in xml.findall('.//{*}object'):
 name=o.attrib['name'];elements[name]=o
 vs=np.array([[float(v.attrib[k]) for k in ['x','y','z']] for v in o.findall('.//{*}vertex')])
 fs=np.array([[int(v.attrib[k]) for k in ['v1','v2','v3']] for v in o.findall('.//{*}triangle')])
 objects[name]=trimesh.Trimesh(vs,fs,process=True)
cap=to_manifold(objects['05-tampa-frontal'])
frame=pins.union([to_manifold(objects[n]) for n in ['03-quadro-superior','03-quadro-inferior']])
placements=[(-19,139.763,42.,46.25),(18.899,139.763,42.,46.25),(-15.646,94.763,41.5,45.75),(15.646,94.763,41.5,45.75),(0,34.763,44.2,48.7)]
checks=[]
for i,(x,z,start,end) in enumerate(placements,1):
 extra=0 if i<5 else .25
 s=pins.pin(2.55,3 if i<5 else 4,extra)
 w=s.rotate([90,0,0]).translate([x,end+6.75,z])
 intersections={name:max(0,(w^obstacle).volume()) for name,obstacle in [('cover',cap),('frame',frame)]}
 assert max(intersections.values())<.001,(i,intersections)
 # Pulling away must encounter the socket lip, not merely rest by friction.
 pull=max(0,(w.translate([0,.25,0])^cap).volume())
 assert pull>.001,(i,pull)
 name=f'08-pino-tampa-{i}'
 m=pins.mesh(s.rotate([90,0,0]));m.apply_translation(-m.bounds[0])
 if i<5:
  tested=trimesh.load(BASE/'teste-trava-pla-v5/stl/08-trava-C-PLA-v5.stl')
  assert np.allclose(np.sort(m.vertices,axis=0),np.sort(tested.vertices,axis=0),atol=1e-6)
  shutil.copyfile(BASE/'teste-trava-pla-v5/stl/08-trava-C-PLA-v5.stl',ROOT/'stl'/(name+'.stl'))
 else:m.export(ROOT/'stl'/(name+'.stl'))
 checks.append(dict(position=i,head_marks=3 if i<5 else 4,extra_length_mm=extra,head_gap_mm=0,blind_floor_clearance_mm=.25,assembly_intersections_mm3=intersections,pull_retention_interference_mm3=pull,geometry=check(trimesh.load(ROOT/'stl'/(name+'.stl')))))
 world=pins.mesh(w);objects[name]=world
 o=elements[name];me=o.find('{*}mesh');me.clear();vs=ET.SubElement(me,'{'+ns+'}vertices');ts=ET.SubElement(me,'{'+ns+'}triangles')
 for a,b,c in world.vertices:ET.SubElement(vs,'{'+ns+'}vertex',x=f'{a:.7f}',y=f'{b:.7f}',z=f'{c:.7f}')
 for a,b,c in world.faces:ET.SubElement(ts,'{'+ns+'}triangle',v1=str(a),v2=str(b),v3=str(c))
# Retain all non-test individual production parts; replace all five old pins.
for p in (BASE/'ender3-original-pla-v1/pecas-individuais').glob('*.stl'):
 if p.name.startswith(('08-','16-','17-','18-','20-','21-')):continue
 shutil.copyfile(p,ROOT/'stl'/p.name)
entries['3D/3dmodel.model']=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
with zipfile.ZipFile(ROOT/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf','w',zipfile.ZIP_DEFLATED) as z:
 for n,data in entries.items():z.writestr(n,data)
scene=trimesh.Scene()
for name,m in objects.items():
 m.visual.face_colors=[230,232,232,255] if name=='05-tampa-frontal' else ([30,155,165,255] if name.startswith('08-') else [90,102,112,255]);scene.add_geometry(m,geom_name=name,node_name=name)
scene.export(ROOT/'montagem/ChargeGrid-50-OFICIAL.glb')
(ROOT/'verificacao/travas-na-montagem.json').write_text(json.dumps({'user_reported_v5_test_passed':True,'whole_body_physically_assembled':False,'standard_pins_byte_identical_to_v5':True,'pins':checks},indent=2)+'\n')
# Order follows assembly. Lower pin separate to make identification unambiguous.
jobs=[
 ('01CHAVE','06CHAVE','Quatro chaves das emendas',4,False,True),
 ('02TRSUP','02TRSUP','Traseira superior',1,True,False),
 ('03TRINF','03TRINF','Traseira inferior',1,True,False),
 ('04QDSUP','04QDSUP','Quadro superior',1,True,False),
 ('05QDINF','05QDINF','Quadro inferior',1,True,False),
 ('06TAMPA','01TAMPA','Tampa frontal branca',1,True,False),
 ('07PTAMP',None,'Quatro travas v5 para os pontos superiores e centrais',4,False,True),
 ('08PTINF',None,'Uma trava inferior, 0,25 mm mais longa',1,False,True),
 ('09PINO','07PINO','Quatro pinos de quarto de volta com suporte',4,True,True),
 ('10BERCO','09BERCO','Bandeja e dois berços modulares',3,False,False),
 ('11TRAVA','10TRAVA','Travas internas e espaçadores',12,False,True),
 ('12CABO','11CABO','Opcional: saída para dois cabos de 5 mm',6,False,True),
]
base=dict(re.findall(r'^(\w+) = (.*)$',(OLD/'perfis/00TESTE.ini').read_text(),re.M))
manifest=[]
for ident,origin,label,qty,support,solid in jobs:
 if origin:
  model=ROOT/'modelos-fatiados'/(ident+'.stl');shutil.copyfile(OLD/'modelos-fatiados'/(origin+'.stl'),model)
 else:
  parts=[]
  indices=range(1,5) if ident=='07PTAMP' else [5]
  for k,i in enumerate(indices):
   m=trimesh.load(ROOT/'stl'/f'08-pino-tampa-{i}.stl');m.apply_translation([k*20,0,0]);parts.append(m)
  m=trimesh.util.concatenate(parts);m.apply_translation([110-m.bounds[:,0].mean(),110-m.bounds[:,1].mean(),-m.bounds[0,2]])
  model=ROOT/'modelos-fatiados'/(ident+'.stl');m.export(model)
 geometry=check(trimesh.load(model),qty)
 cfg=base.copy()
 cfg['print_settings_id']='ChargeGrid OFICIAL v6 - '+ident
 if solid:cfg['fill_density']='100%'
 if support:
  previous=dict(re.findall(r'^(\w+) = (.*)$',(BASE/'ender3-pla-gcode-v1/perfis'/(origin+'.ini')).read_text(),re.M))
  cfg.update({k:v for k,v in previous.items() if k.startswith('support_') or k=='dont_support_bridges'})
 profile=ROOT/'perfis'/(ident+'.ini');profile.write_text('\n'.join(f'{k} = {v}' for k,v in sorted(cfg.items()))+'\n')
 record=dict(id=ident,label=label,quantity=qty,support=support,infill=cfg['fill_density'],optional=ident=='12CABO',geometry=geometry,source_previous_job=origin)
 manifest.append(record)
 print('FATIANDO',ident,label,flush=True)
 cmd=[EXE,'--datadir','/tmp/chargegrid-prusa-settings','--threads','4','--load',str(profile),'--center','110,110']
 for action,folder,ext in [('gcode','gcode','.gcode'),('3mf','projetos','.3mf')]:
  with (ROOT/'verificacao'/(ident+'-'+action+'.log')).open('w') as log:
   subprocess.run(cmd+['--export-'+action,'--output',str(ROOT/folder/(ident+ext)),str(model)],stdout=log,stderr=subprocess.STDOUT,check=True)
 gc=(ROOT/'gcode'/(ident+'.gcode')).read_text();full=gc.split('; prusaslicer_config = begin',1)[1].split('; prusaslicer_config = end',1)[0].strip()+'\n'
 project=ROOT/'projetos'/(ident+'.3mf')
 with zipfile.ZipFile(project) as z:contents={n:z.read(n) for n in z.namelist() if n!='Metadata/Slic3r_PE.config'}
 contents['Metadata/Slic3r_PE.config']=('; generated by PrusaSlicer 2.9.6\n\n'+full).encode()
 with zipfile.ZipFile(project,'w',zipfile.ZIP_DEFLATED) as z:
  for n,data in contents.items():z.writestr(n,data)
 print('PRONTO',ident,flush=True)
(ROOT/'ordem-impressao.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
