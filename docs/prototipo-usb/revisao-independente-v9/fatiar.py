from pathlib import Path
import json,re,subprocess,zipfile,trimesh
r=Path(__file__).resolve().parent.parent/'ender3-pla-oficial-v9'
exe='/tmp/chargegrid-prusa-dmg/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
jobs=json.loads((r/'ordem-impressao.json').read_text())
for old,new in [('10BERCO8','10BERCO9'),('11TRAVA8','11TRAVA9')]:
 j=next(x for x in jobs if x['id'] in [old,new])
 cfgpath=r/'perfis'/(new+'.ini')
 if not cfgpath.exists():cfgpath=r/'perfis'/(old+'.ini')
 cfg=cfgpath.read_text()
 cfg=re.sub(r'^print_settings_id = .*$',f'print_settings_id = ChargeGrid PLA v9 {new}',cfg,flags=re.M)
 (r/'perfis'/(new+'.ini')).write_text(cfg)
 args=[exe,'--datadir','/tmp/chargegrid-prusa-settings','--threads','4','--load',str(r/'perfis'/(new+'.ini')),'--dont-arrange',str(r/'modelos-fatiados'/(new+'.stl'))]
 with (r/'verificacao'/(new+'-fatiamento.log')).open('w') as log:
  subprocess.run(args+['--export-gcode','--output',str(r/'gcode'/(new+'.gcode'))],check=True,stdout=log,stderr=subprocess.STDOUT)
  subprocess.run(args+['--export-3mf','--output',str(r/'projetos'/(new+'.3mf'))],check=True,stdout=log,stderr=subprocess.STDOUT)
 g=(r/'gcode'/(new+'.gcode')).read_text()
 config=g.split('; prusaslicer_config = begin',1)[1].split('; prusaslicer_config = end',1)[0]
 p=r/'projetos'/(new+'.3mf')
 with zipfile.ZipFile(p) as z:data={n:z.read(n) for n in z.namelist()}
 data['Metadata/Slic3r_PE.config']=('; prusaslicer_config = begin'+config+'; prusaslicer_config = end\n').encode()
 with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
  for n,d in data.items():z.writestr(n,d)
 m=trimesh.load(r/'modelos-fatiados'/(new+'.stl'))
 j.update(id=new,source_previous_job=old,geometry=dict(watertight=bool(m.is_watertight),consistent=bool(m.is_winding_consistent),quantity=len(m.split()),size_mm=m.extents.tolist()))
 for folder,ext in [('gcode','.gcode'),('projetos','.3mf'),('modelos-fatiados','.stl'),('perfis','.ini'),('previas','.png')]:
  (r/folder/(old+ext)).unlink(missing_ok=True)
 print('FATIADO',new,flush=True)
(r/'ordem-impressao.json').write_text(json.dumps(jobs,ensure_ascii=False,indent=2)+'\n')
# Remove obsolete entries from incremental reports, then rerun the check scripts.
for name in ['perfis-e-projetos.json','auditoria-gcode.json']:
 p=r/'verificacao'/name;d=json.loads(p.read_text());rows=d if isinstance(d,list) else d['files'];rows[:]=[x for x in rows if Path(x['file']).stem not in ['10BERCO8','11TRAVA8','10BERCO9','11TRAVA9']];p.write_text(json.dumps(d,indent=2)+'\n')
