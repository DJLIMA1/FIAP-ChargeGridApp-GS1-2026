from pathlib import Path
import json,re,zipfile,subprocess,sys,xml.etree.ElementTree as ET
import trimesh,numpy as np
ROOT=Path(__file__).resolve().parent
EXE='/tmp/chargegrid-prusa-dmg/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
def config(t):
 if '; prusaslicer_config = begin' in t:t=t.split('; prusaslicer_config = begin',1)[1].split('; prusaslicer_config = end',1)[0]
 return dict(re.findall(r'^; (\w+) = (.*)$',t,re.M))
base=config((ROOT.parent/'ender3-pla-gcode-v2/gcode/00TESTE.gcode').read_text())
jobs=json.loads((ROOT/'ordem-impressao.json').read_text());results=[]
if len(sys.argv)>1:
 jobs=[j for j in jobs if j['id'] in sys.argv[1:]]
 results=[j for j in json.loads((ROOT/'verificacao/perfis-e-projetos.json').read_text()) if j['file'] not in sys.argv[1:]]
for job in jobs:
 ident=job['id'];t=(ROOT/'gcode'/(ident+'.gcode')).read_text();cfg=config(t)
 diffs={k:[base[k],v] for k,v in cfg.items() if k in base and base[k]!=v}
 assert all(k.startswith('support_') or k in ['dont_support_bridges','fill_density','print_settings_id'] for k in diffs),diffs
 assert cfg['fill_density']==job['infill']
 assert (';TYPE:Support material' in t)==job['support'],ident
 assert cfg['support_material']==str(int(job['support']))
 assert cfg['support_material_auto']==str(int(job['support']))
 assert cfg['raft_layers']=='0'
 debt=0;peak=0
 for n,line in enumerate(t.splitlines(),1):
  clean=line.split(';')[0]
  if not clean.startswith(('G0 ','G1 ')):continue
  match=re.search(r'\bE(-?[.\d]+)',clean)
  if not match:continue
  e=float(match[1])
  if e<0:debt-=e;peak=max(peak,debt)
  else:
   if re.search('[XYZ]',clean):assert debt<.001,(ident,n,debt)
   debt=max(0,debt-e)
   if debt<.001:debt=0
 assert peak<5.001 and abs(debt-5)<.001,(ident,peak,debt)
 with zipfile.ZipFile(ROOT/'projetos'/(ident+'.3mf')) as z:
  assert z.testzip() is None
  assert config(z.read('Metadata/Slic3r_PE.config').decode())==cfg
 out=Path('/tmp')/('chargegrid-v6-reopen-'+ident+'.gcode')
 with (ROOT/'verificacao'/(ident+'-reaberto.log')).open('w') as log:
  subprocess.run([EXE,'--datadir','/tmp/chargegrid-prusa-settings','--threads','4','--export-gcode','--output',str(out),str(ROOT/'projetos'/(ident+'.3mf'))],check=True,stdout=log,stderr=subprocess.STDOUT)
 reopened=out.read_text();assert config(reopened)==cfg,ident
 # The slicer may reorder disconnected parts when reopening a 3MF. Verify geometry,
 # persisted settings and comparable material instead of byte-identical toolpaths.
 with zipfile.ZipFile(ROOT/'projetos'/(ident+'.3mf')) as z:xml=ET.fromstring(z.read('3D/3dmodel.model'))
 meshes={}
 for ob in xml.findall('.//{*}object'):
  assert not ob.findall('.//{*}component')
  vertices=[[float(v.attrib[k]) for k in ['x','y','z']] for v in ob.findall('.//{*}vertex')]
  faces=[[int(v.attrib[k]) for k in ['v1','v2','v3']] for v in ob.findall('.//{*}triangle')]
  meshes[ob.attrib['id']]=trimesh.Trimesh(vertices,faces,process=True)
 placed=[]
 for it in xml.findall('.//{*}item'):
  m=meshes[it.attrib['objectid']].copy()
  if 'transform' in it.attrib:
   transform=np.eye(4);transform[:3,:]=np.array([float(v) for v in it.attrib['transform'].split()]).reshape(4,3).T
   m.apply_transform(transform)
  placed.append(m)
 model=trimesh.util.concatenate(placed)
 original=trimesh.load(ROOT/'modelos-fatiados'/(ident+'.stl'))
 model.merge_vertices();model.remove_unreferenced_vertices()
 assert np.allclose(model.bounds,original.bounds,atol=2e-5),(ident,model.bounds,original.bounds)
 assert abs(model.volume-original.volume)<max(.01,original.volume*1e-5),ident
 assert len(model.split())==job['quantity'],ident
 grams=lambda s:float(re.search(r'; filament used \[g\] = ([\d.]+)',s)[1])
 assert abs(grams(reopened)-grams(t))<max(.06,grams(t)*.03),ident
 results.append(dict(file=ident,differences_from_successful_profile=diffs,restore_balance_pass=True,support_presence_matches=True,project_embedded_profile_matches=True,reopened_project_settings_geometry_and_material_match=True))
 print('VALIDADO',ident,flush=True)
(ROOT/'verificacao/perfis-e-projetos.json').write_text(json.dumps(sorted(results,key=lambda j:j['file']),indent=2)+'\n')
