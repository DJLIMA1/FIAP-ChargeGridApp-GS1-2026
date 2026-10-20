from pathlib import Path
import hashlib,json,trimesh,numpy as np
r=Path(__file__).resolve().parent;v8=r.parent/'ender3-pla-oficial-v8';v7=r.parent/'ender3-pla-oficial-v7';v6=r.parent/'ender3-pla-oficial-v6'
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
changes=[]
for p in sorted((v8/'stl').glob('*.stl')):
 if h(p)!=h(v7/'stl'/p.name):changes.append(p.name)
assert changes==['09-bandeja-removivel.stl','12-pino-trava-berco.stl','13-trava-bandeja.stl'],changes
jobs=json.loads((v8/'ordem-impressao.json').read_text());rows=[]
renames={'03TRINF7':'03TRINF','05QDINF8':'05QDINF','10BERCO8':'10BERCO','11TRAVA8':'11TRAVA'}
for j in jobs:
 n=j['id'];old=renames.get(n,n);p=v8/'gcode'/(n+'.gcode')
 rows.append({'file':p.name,'compared_with_v6':old+'.gcode','unchanged_from_v6':h(p)==h(v6/'gcode'/(old+'.gcode')),'sha256':h(p)})
assert [x['file'] for x in rows if not x['unchanged_from_v6']]==['03TRINF7.gcode','05QDINF8.gcode','10BERCO8.gcode','11TRAVA8.gcode']
assert h(v8/'modelos-fatiados/05QDINF8.stl')==h(v7/'modelos-fatiados/05QDINF.stl')
for n in ['01CHAVE','02TRSUP']:
 for f,e in [('gcode','gcode'),('projetos','3mf'),('modelos-fatiados','stl'),('perfis','ini')]:assert h(v8/f/(n+'.'+e))==h(v6/f/(n+'.'+e)),(n,f)
parts=[]
for j in jobs:
 m=trimesh.load(v8/'modelos-fatiados'/(j['id']+'.stl'));pieces=m.split();assert len(pieces)==j['quantity']
 assert m.is_watertight and m.is_winding_consistent and np.all(m.bounds[0]>=[0,0,-.001]) and np.all(m.bounds[1]<=[220,220,250])
 parts.append({'file':j['id'],'quantity':len(pieces),'bounds_mm':m.bounds.tolist(),'all_meshes_closed':True})
res={'gcodes':rows,'changed_individual_stls_from_v7':changes,'part_05_geometry_unchanged_support_only':True,'already_printed_keys_and_job02_preserved_in_all_formats':True,'job_parts':parts,'physical_full_assembly_pending':True}
(v8/'verificacao/escopo-da-correcao.json').write_text(json.dumps(res,indent=2)+'\n')
print('SCOPE OK',len(jobs),'jobs',sum(x['quantity'] for x in parts),'printed instances')
