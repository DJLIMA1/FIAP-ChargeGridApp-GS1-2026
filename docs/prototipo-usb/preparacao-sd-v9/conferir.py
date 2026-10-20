from pathlib import Path
import hashlib,json,zipfile,re,sys,itertools
import numpy as np,trimesh,manifold3d as md
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent;P=BASE/'ender3-pla-oficial-v9'
h=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((P/'SHA256SUMS.json').read_text())
for n,d in manifest['files'].items():assert h(P/n)==d,('manifest',n)
with zipfile.ZipFile(BASE/'ChargeGrid-Ender3-PLA-OFICIAL-v9.zip') as z:
 assert z.testzip() is None
 for n,d in manifest['files'].items():assert hashlib.sha256(z.read('ChargeGrid-OFICIAL-v9/'+n)).hexdigest()==d,('zip',n)
receipt=json.loads((BASE/'arquivo-sd/recibo-oficial-v6.json').read_text());prior={x['path']:x['sha256'] for x in receipt['files']}
protected=[]
for name in ['01CHAVE','02TRSUP']:
 assert h(P/'gcode'/(name+'.gcode'))==prior['CGFINAL/'+name+'.gcode']
 for folder,ext in [('gcode','gcode'),('perfis','ini'),('projetos','3mf'),('modelos-fatiados','stl')]:
  rel=folder+'/'+name+'.'+ext;assert h(P/rel)==h(BASE/'ender3-pla-oficial-v6'/rel);protected.append({'file':rel,'sha256':h(P/rel),'unchanged_from_sent_v6':True})
for name,version in [('03TRINF7','v7'),('05QDINF8','v8')]:
 for folder,ext in [('gcode','gcode'),('perfis','ini'),('projetos','3mf'),('modelos-fatiados','stl')]:
  rel=folder+'/'+name+'.'+ext;assert h(P/rel)==h(BASE/('ender3-pla-oficial-'+version)/rel)
review=json.loads((P/'verificacao/revisor-fatiamento.json').read_text())
for row in review:assert h(P/'gcode'/(row['job']+'.gcode'))==row['gcode_sha256'],row['job']
for i in range(1,5):assert h(P/'stl'/f'08-pino-tampa-{i}.stl')==h(BASE/'teste-trava-pla-v5/stl/08-trava-C-PLA-v5.stl')
assert not (P/'stl/13-trava-bandeja.stl').exists()
assert (P/'stl/13-bloqueio-bandeja-esquerda.stl').exists() and (P/'stl/13-bloqueio-bandeja-direita.stl').exists()
# Independently reassemble old sent rear/keys with the final v9 pieces.
src=BASE/'revisao-independente-v9/auditar.py'
ns={'__file__':str(src),'__name__':'audit_loader'};exec(src.read_text().split('pairs=[];',1)[0],ns)
load=ns['load'];overlap=ns['overlap'];union=ns['union'];meshes,solids=load(P/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf');om,os=load(BASE/'ender3-pla-oficial-v6/montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf')
oldnames=['01-traseira-superior']+[n for n in solids if n.startswith('chave-')]
for n in oldnames:solids[n]=os[n];meshes[n]=om[n]
checks=[]
for a,b in itertools.combinations(solids,2):
 if a not in oldnames and b not in oldnames:continue
 v=overlap(solids[a],solids[b]);assert v<.001,(a,b,v);checks.append({'a':a,'b':b,'intersection_mm3':v})
rear=union(solids[n] for n in solids if n.startswith('01-traseira'));frame=union(solids[n] for n in solids if n.startswith('03-quadro'));paths=[]
for n in oldnames:
 if not n.startswith('chave-'):continue
 y=90.8 if n.endswith('90.8') else 57.2;sign=-1 if y==90.8 else 1;body=rear if y==90.8 else frame
 for d in np.linspace(0,12,49):
  v=overlap(solids[n].translate([0,sign*float(d),0]),body);assert v<.001,(n,d,v)
  paths.append({'key':n,'distance_mm':float(d),'overlap_mm3':v})
 # The actual 01CHAVE reaches Z2.88 rather than its nominal STL thickness3.0.
 printed=solids[n].translate([0,-y,0]).scale([1,2.88/3,1]).translate([0,y,0]);assert overlap(printed,body)<.001
tray=union(solids[n] for n in solids if n.startswith(('09-','10-','11-','trava-berco')))
for d in np.linspace(0,5,21):assert overlap(tray.translate([0,0,float(d)]),rear)<.001
for d in np.linspace(0,45,46):assert overlap(tray.translate([0,-float(d),5]),rear)<.001
result={'release':'v9','all_release_hashes_verified':len(manifest['files']),'zip_checked':True,'protected_files':protected,'comparison_reference':'Actual SHA256 receipt after two SD readback cycles for v6','all_v7_v8_v9_corrections_present':True,'final_reviewer_gcodes_match':True,'four_standard_cover_pins_match_physically_approved_v5_stl':True,'hybrid_assembly_uses_original_sent_keys_and_upper_rear':True,'hybrid_pairs':checks,'old_key_insertion_paths':paths,'loaded_tray_clears_original_upper_rear':True,'physical_complete_assembly_not_tested':True,'numbering_note':'Official list starts at01CHAVE;00TESTE is a separate historical coupon batch, not a shell part','sd_updated':False}
(ROOT/'compatibilidade-e-correcoes.json').write_text(json.dumps(result,indent=2)+'\n')
print('VERIFIED',len(manifest['files']),'release files;',len(checks),'hybrid pairs;',len(paths),'key path samples; old upper rear clears loaded tray')
