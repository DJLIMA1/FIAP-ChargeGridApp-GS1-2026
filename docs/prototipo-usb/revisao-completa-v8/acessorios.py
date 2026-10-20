from pathlib import Path
import ast
exec((Path(__file__).parent/'auditar.py').read_text().split('pairs=[];',1)[0])
source=(ROOT.parent/'cad-impressao-50-v1/gerar.py').read_text()
for n in ast.parse(source).body:
 if isinstance(n,ast.FunctionDef) and n.name in ['box','cyl','cy','profile','xzprofile','subtract']:exec(ast.get_source_segment(source,n))
records=[]
def check(label,a,b,positive=False):
 v=overlap(a,b);ok=v>.001 if positive else v<.001
 records.append({'test':label,'intersection_mm3':v,'pass':ok});assert ok,(label,v)
rear=union([s for n,s in solids.items() if n.startswith(('01-traseira','03-quadro'))])
for tag,holes in [('4mm',[(0,4.5)]),('5mm',[(0,5.5)]),('6mm',[(0,6.5)]),('duplo-5mm',[(-4,5.5),(4,5.5)])]:
 gland=union([box([-9.7,-6.7,0],[19.4,13.4,5.6]),box([-15,-9,3.6],[30,18,2])])
 gland=subtract(gland,[cyl([x,0,-1],dia/2,8) for x,dia in holes]+[box([-13.8,-3,-1],[2.8,6,8]),box([11,-3,-1],[2.8,6,8])])
 halves=[gland.split_by_plane([0,1,0],.075)[0],gland.split_by_plane([0,1,0],-.075)[1]]
 for suf,s in zip('ab',halves):
  stl=trimesh.load(PKG/'stl'/f'19-inserto-{tag}-{suf}.stl');assert abs(stl.volume-s.volume())<.01
  w=s.translate([0,85,-38.85]);check(f'{tag}_{suf}_installed',w,rear)
  for dz in np.linspace(0,12,25):check(f'{tag}_{suf}_withdraw_{dz:.1f}',w.translate([0,0,float(dz)]),rear)
  check(f'{tag}_{suf}_flange_retains',w.translate([0,0,-1]),rear,True)
 # Actual nominal cables have .25 mm radial room in inserts.
 for x,dia in holes:check(f'{tag}_cable_at_{x}',cyl([x,0,-2],(dia-.5)/2,10),gland)
 check(f'{tag}_split_halves',*halves)
for dia in [4,5,6]:
 saddle=box([-9,-6,0],[18,12,5])-cy([0,-10,5],dia/2,20)
 saddle=subtract(saddle,[box([-7,-1.6,-1],[3,3.2,7]),box([4,-1.6,-1],[3,3.2,7])])
 stl=trimesh.load(PKG/'stl'/f'15-prensa-cabo-{dia}mm-meia.stl');assert abs(stl.volume-saddle.volume())<.01
 other=saddle.rotate([180,0,0]).translate([0,0,10]);check(f'saddle_{dia}_halves',saddle,other)
 check(f'saddle_{dia}_nominal_cable',union([saddle,other]),cy([0,-10,5],dia/2,20))
records.append({'test':'spacer_tab_slot_nominal_clearance','tab_mm':[3,3,1.5],'slot_mm':[3.8,8,2],'clearance_xy_mm':[.8,5],'pass':True})
# Generic equipment reserve only. Real board, connectors and cables are still unspecified.
wm=[[1,0,0,-30],[0,0,-1,90.2],[0,1,0,34]]
for name,pos,size in [('ESP32_generic',[14,51,12.95],[32,58,8]),('power_generic',[6,10,10.95],[48,29,15])]:
 env=box(pos,size).transform(wm)
 for n in ['01-traseira-superior','01-traseira-inferior','03-quadro-superior','03-quadro-inferior','05-tampa-frontal']:
  check(name+'_'+n,env,solids[n])
(ROOT/'acessorios.json').write_text(json.dumps({'results':records,'actual_electronics_and_cable_fit_pending':True},indent=2)+'\n')
print('ACCESSORIES PASS',len(records))
