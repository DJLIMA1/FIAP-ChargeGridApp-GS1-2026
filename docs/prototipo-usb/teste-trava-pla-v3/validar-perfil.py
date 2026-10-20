from pathlib import Path
import re,json,subprocess,zipfile
r=Path(__file__).resolve().parent
records=[]
def config(t):
 if '; prusaslicer_config = begin' in t:t=t.split('; prusaslicer_config = begin',1)[1].split('; prusaslicer_config = end',1)[0]
 return dict(re.findall(r'^; (\w+) = (.*)$',t,re.M))
base=config((r.parent/'ender3-pla-gcode-v2/gcode/00TESTE.gcode').read_text())
for p in sorted((r/'gcode').glob('*.gcode')):
 t=p.read_text();cfg=config(t)
 diffs={k:[base[k],v] for k,v in cfg.items() if k in base and base[k]!=v}
 assert set(diffs)<= {'fill_density','print_settings_id'},diffs
 debt=0.;peak=0.
 for n,line in enumerate(t.splitlines(),1):
  line=line.split(';')[0]
  if not line.startswith(('G0 ','G1 ')):continue
  match=re.search(r'\bE(-?[.\d]+)',line)
  if not match:continue
  e=float(match[1])
  if e<0:debt-=e;peak=max(debt,peak)
  else:
   if re.search('[XYZ]',line):assert debt<.001,(p.name,n,debt)
   debt=max(0,debt-e)
   if debt<.001:debt=0.
 assert peak<5.001 and abs(debt-5)<.001
 with zipfile.ZipFile(r/'projetos'/(p.stem+'.3mf')) as z:
  emb=config(z.read('Metadata/Slic3r_PE.config').decode());assert cfg==emb
 records.append(dict(file=p.name,differences_from_successful_profile=diffs,restores_verified=True,embedded_profile_matches=True))
(r/'verificacao/perfil-validado.json').write_text(json.dumps(records,indent=2)+'\n')
exe='/tmp/chargegrid-prusa-dmg/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
with (r/'verificacao/00TRAVA-reaberto.log').open('w') as log:
 subprocess.run([exe,'--datadir','/tmp/chargegrid-prusa-settings','--threads','4','--export-gcode','--output','/tmp/chargegrid-v3-reopen.gcode',str(r/'projetos/00TRAVA.3mf')],check=True,stdout=log,stderr=subprocess.STDOUT)
a=config(Path('/tmp/chargegrid-v3-reopen.gcode').read_text());b=config((r/'gcode/00TRAVA.gcode').read_text());assert a==b
print('Perfil térmico e movimentos preservados; apenas pinos com 100% de preenchimento. Retrações e 3MF conferidos.')
