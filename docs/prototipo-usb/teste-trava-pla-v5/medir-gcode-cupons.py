from pathlib import Path
import re,json,math,statistics
ROOT=Path(__file__).resolve().parent
p=ROOT.parent/'ender3-pla-gcode-v2/gcode/00TESTE.gcode'
x=y=z=0.;w=.44;typ='';layer=0.;samples={};maxz={'17':0,'18':0}
for line in p.read_text().splitlines():
 if line.startswith(';TYPE:'):typ=line[6:]
 if line.startswith(';Z:'):layer=float(line[3:])
 if line.startswith(';WIDTH:'):w=float(line[7:])
 s=line.split(';')[0].strip()
 if not s.startswith(('G0 ','G1 ')):continue
 v={k:float(n) for k,n in re.findall(r'([XYZEF])(-?[.\d]+)',s)}
 ox,oy=x,y;x=v.get('X',x);y=v.get('Y',y);z=v.get('Z',z)
 if v.get('E',0)<=0 or math.hypot(x-ox,y-oy)<.001:continue
 for name,cx in [('17',89),('18',121)]:
  if abs(x-cx)<8.01 and abs(y-86.15)<8.01:maxz[name]=max(maxz[name],layer)
 if typ!='External perimeter':continue
 a=math.hypot(x-89,y-86.15);b=math.hypot(ox-89,oy-86.15)
 if 2<a<3.5 and 2<b<3.5:samples.setdefault(layer,[]).append((a+b)-w)
summary=[{'top_z_mm':z,'median_void_diameter_from_external_path_mm':round(statistics.median(v),3)} for z,v in sorted(samples.items())]
assert maxz=={'17':4.32,'18':4.32},maxz
assert abs(next(v['median_void_diameter_from_external_path_mm'] for v in summary if v['top_z_mm']==2.64)-5.3)<.02
assert abs(next(v['median_void_diameter_from_external_path_mm'] for v in summary if v['top_z_mm']==2.88)-4.6)<.02
out={'file':str(p),'top_layer_by_coupon_mm':maxz,'hole_path_approximation':summary,'ideal_layer_envelope':{'floor_z_mm':1.20,'lip_underside_z_mm':2.64,'stack_height_mm':8.64,'distance_top_to_lip_mm':6.00,'distance_top_to_floor_mm':7.44},'note':'Comandos do arquivo efetivamente usado no teste v2, nao medidas fisicas. Envelope ideal por camadas de 0.24 mm; nao inclui deformacao, largura real ou queda de pontes.'}
(ROOT/'medidas-gcode-cupons.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
