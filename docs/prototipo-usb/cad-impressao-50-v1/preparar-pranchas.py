"""Pranchas 3MF somente de geometria; não contêm perfil, suportes ou G-code."""
from pathlib import Path
import ast,zipfile,json
import numpy as np,trimesh
ROOT=Path(__file__).resolve().parent
(ROOT/'pranchas').mkdir(exist_ok=True)
# Reuse the pure 3MF writer without re-running geometry generation.
tree=ast.parse((ROOT/'gerar.py').read_text())
fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='export3mf')
exec(compile(ast.Module(body=[fn],type_ignores=[]),'export3mf','exec'))
manifest=json.loads((ROOT/'verificacao/relatorio.json').read_text());byid={p['id']:p for p in manifest['parts']}
plates=[('00-ensaios',[('16-cupom-quarto-volta',1),('17-cupom-bucha-tampa',1),('18-cupom-placa-tampa',1),('20-cupom-trilho-berco',1),('21-cupom-macho-berco',1),('07-pino-quarto-volta',1),('08-pino-tampa-1',1)])]
for n,pid in enumerate(['01-traseira-superior','01-traseira-inferior','03-quadro-superior','03-quadro-inferior','05-tampa-frontal'],1):plates.append((f'{n:02d}-{pid[3:]}',[(pid,1)]))
inside=[('09-bandeja-removivel',1),('11-berco-esp32',1),('10-berco-potencia',1),('06-chave-emenda',4),('07-pino-quarto-volta',4)]+[(f'08-pino-tampa-{i}',1) for i in range(1,6)]+[('12-pino-trava-berco',2),('13-trava-bandeja',2),('14-espacador-3mm',4),('14-espacador-5mm',4)]
plates.append(('06-internos-e-fixacoes',inside))
plates.append(('07-cabos-5mm-OPCIONAL',[('19-inserto-duplo-5mm-a',1),('19-inserto-duplo-5mm-b',1),('15-prensa-cabo-5mm-meia',4)]))
records=[]
for name,selection in plates:
 objects=[];placed=[];x=y=10.;row_h=0
 for pid,qty in selection:
  for i in range(qty):
   m=trimesh.load(ROOT/'stl'/f'{pid}.stl',force='mesh');w,h,d=m.extents
   if x+w>210:x=10.;y+=row_h+10.;row_h=0
   assert y+h<210,(name,y+h)
   m.apply_translation([x,y,0]);objname=f'{pid}--{i+1}'
   objects.append((objname,m));placed.append({'id':pid,'instance':i+1,'xy_mm':[x,y],'size_xyz_mm':[w,h,d]})
   x+=w+10;row_h=max(row_h,h)
 export3mf(ROOT/'pranchas'/f'{name}.3mf',objects)
 records.append({'plate':name,'part_count':len(objects),'bed_xy_mm':[220,220],'placement':placed})
(ROOT/'pranchas/indice.json').write_text(json.dumps(records,indent=2)+'\n')
# Independently read all generated 3MF meshes and validate units, index ranges, topology and bed coordinates.
import xml.etree.ElementTree as ET
checks=[]
for p in sorted((ROOT/'pranchas').glob('*.3mf')):
 with zipfile.ZipFile(p) as z:
  assert z.testzip() is None
  doc=ET.fromstring(z.read('3D/3dmodel.model'))
  assert doc.attrib['unit']=='millimeter'
  names=[]
  for ob in doc.findall('.//{*}object'):
   vs=np.array([[float(e.attrib[a]) for a in ['x','y','z']] for e in ob.findall('.//{*}vertex')])
   fs=np.array([[int(e.attrib[a]) for a in ['v1','v2','v3']] for e in ob.findall('.//{*}triangle')])
   assert fs.min()>=0 and fs.max()<len(vs)
   m=trimesh.Trimesh(vs,fs,process=True)
   assert m.is_watertight and m.is_winding_consistent and m.volume>0,(p,ob.attrib['name'])
   assert (m.bounds[0]>=-1e-5).all() and (m.bounds[1,:2]<220).all()
   names.append(ob.attrib['name'])
  checks.append({'file':str(p.relative_to(ROOT)),'verified_objects':len(names),'unit':'millimeter','topology_and_placement_valid':True})
(ROOT/'verificacao/pranchas.json').write_text(json.dumps(checks,indent=2)+'\n')
print('Validated',len(checks),'3MF plates;',sum(c['verified_objects'] for c in checks),'placed objects')
