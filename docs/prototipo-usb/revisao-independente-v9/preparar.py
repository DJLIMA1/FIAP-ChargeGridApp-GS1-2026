from pathlib import Path
import ast,shutil,json,zipfile,xml.etree.ElementTree as ET
import numpy as np,trimesh,manifold3d as md
BASE=Path(__file__).resolve().parent.parent;OLD=BASE/'ender3-pla-oficial-v8';ROOT=BASE/'ender3-pla-oficial-v9';AUD=Path(__file__).resolve().parent
if not ROOT.exists():shutil.copytree(OLD,ROOT,ignore=shutil.ignore_patterns('__pycache__','SHA256SUMS.json'))
src=(BASE/'cad-impressao-50-v1/gerar.py').read_text()
for n in ast.parse(src).body:
 if isinstance(n,ast.FunctionDef) and n.name in ['box','cyl','cy','union','subtract','profile','xzprofile','mesh']:exec(ast.get_source_segment(src,n))
def solid(m):return md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
with zipfile.ZipFile(OLD/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf') as z:entries={n:z.read(n) for n in z.namelist()}
xml=ET.fromstring(entries['3D/3dmodel.model']);objects={};elements={};ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
for o in xml.findall('.//{*}object'):
 v=[[float(a.attrib[k]) for k in ['x','y','z']] for a in o.findall('.//{*}vertex')];f=[[int(a.attrib[k]) for k in ['v1','v2','v3']] for a in o.findall('.//{*}triangle')];n=o.attrib['name'];objects[n]=trimesh.Trimesh(v,f,process=True);elements[n]=o
wm=np.array([[1,0,0,-30],[0,0,-1,90.2],[0,1,0,34],[0,0,0,1.]])
base=solid(objects['09-bandeja-removivel']).transform(np.linalg.inv(wm)[:3].tolist())
fixtures=[];envelopes=[]
for x,side,direction in [(5,'esquerda',1),(55,'direita',-1)]:
 # Rigid D body fills the lower keyhole. No slot or oversized snap bead.
 stem=cyl([0,0,-.15],3.6,3.1)
 head=cyl([0,0,2.95],4.7,2.0)
 dcut=box([-12,.3,-1],[24,12,8]);stop=(stem+head)-dcut
 # Inward tab: 7 mm wide, two through-slots for a 2.5 mm nylon tie.
 tx=7.5*direction
 tab=box([min(3.5*direction,10.5*direction),-4,2.95],[7,7,2])
 stop=stop+tab
 base=base+box([x+tx-3,1,2.35],[6,7,.45])
 for y in [-2.5,1.5]:
  cut=box([tx-1.6,y-.9,-1],[3.2,1.8,8]);stop=stop-cut
  base=base-cut.translate([x,5,0])
 # Recess the return strap into the tray so it clears the original rear rib during installation.
 base=base-box([x+tx-1.6,2.5,-.1],[3.2,4,1.4])
 # Recessed strap lane, accessible from the front. End walls prevent lateral escape.
 stop=stop-box([tx-1.45,-2.5,4.65],[2.9,4,.5])
 placed=stop.translate([x,5,0]);objects[f'trava-bandeja-{x}']=mesh(placed.transform(wm[:3].tolist()))
 fixtures.append((side,stop))
 # Conservative nominal envelope: 2.5 x 1.0 strap, with 5 x 5 x 4 buckle.
 # Rounded bends are conservatively represented as rectangular intersections.
 tie=union([box([tx-1.25,-3,.15],[2.5,1,5.5]),box([tx-1.25,1,.15],[2.5,1,5.5]),box([tx-1.25,-3,.15],[2.5,5,1]),box([tx-1.25,-3,4.65],[2.5,5,1])])
 buckle=box([tx-2.5,-2.8,5.65],[5,4.8,4])
 tie=tie+buckle
 envelopes.append((f'cinta-{side}',tie.translate([x,5,0]).transform(wm[:3].tolist())))
objects['09-bandeja-removivel']=mesh(base.transform(wm[:3].tolist()))
def export(s,path):
 m=mesh(s);m.apply_translation(-m.bounds[0]);m.vertices=np.asarray(m.vertices,dtype=np.float32).astype(float);m.merge_vertices(digits_vertex=5);m.update_faces(np.array([len(set(f))==3 for f in m.faces]));m.update_faces(m.unique_faces());m.remove_unreferenced_vertices();assert m.is_watertight and m.is_winding_consistent and len(m.split())==1;m.export(path)
export(base,ROOT/'stl/09-bandeja-removivel.stl')
for side,s in fixtures:export(s.rotate([180,0,0]),ROOT/'stl'/f'13-bloqueio-bandeja-{side}.stl')
(ROOT/'stl/13-trava-bandeja.stl').unlink(missing_ok=True)
def batch(parts,path):
 m=trimesh.util.concatenate(parts);m.apply_translation([110-m.bounds[:,0].mean(),110-m.bounds[:,1].mean(),-m.bounds[0,2]]);assert m.extents[0]<200 and m.extents[1]<200;m.export(path)
parts=[]
for name,xy in [('09-bandeja-removivel',(0,0)),('10-berco-potencia',(76,0)),('11-berco-esp32',(76,55))]:
 m=trimesh.load(ROOT/'stl'/(name+'.stl'));m.apply_translation([*xy,0]);parts.append(m)
batch(parts,ROOT/'modelos-fatiados/10BERCO9.stl')
parts=[]
for name,qty,xy in [('12-pino-trava-berco',2,(0,0)),('13-bloqueio-bandeja-esquerda',1,(0,25)),('13-bloqueio-bandeja-direita',1,(25,25)),('14-espacador-3mm',4,(0,48)),('14-espacador-5mm',4,(0,68))]:
 for k in range(qty):
  m=trimesh.load(ROOT/'stl'/(name+'.stl'));m.apply_translation([xy[0]+k*20,xy[1],0]);parts.append(m)
batch(parts,ROOT/'modelos-fatiados/11TRAVA9.stl')
for n,m in objects.items():
 o=elements[n];me=o.find('{*}mesh');me.clear();vs=ET.SubElement(me,'{'+ns+'}vertices');ts=ET.SubElement(me,'{'+ns+'}triangles')
 for x,y,z in m.vertices:ET.SubElement(vs,'{'+ns+'}vertex',x=f'{x:.7f}',y=f'{y:.7f}',z=f'{z:.7f}')
 for a,b,c in m.faces:ET.SubElement(ts,'{'+ns+'}triangle',v1=str(a),v2=str(b),v3=str(c))
entries['3D/3dmodel.model']=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
with zipfile.ZipFile(ROOT/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf','w',zipfile.ZIP_DEFLATED) as z:
 for n,d in entries.items():z.writestr(n,d)
scene=trimesh.Scene()
for n,m in objects.items():m.visual.face_colors=[230,232,232,255] if n=='05-tampa-frontal' else [90,125,140,255];scene.add_geometry(m,geom_name=n,node_name=n)
scene.export(ROOT/'montagem/ChargeGrid-50-OFICIAL.glb')
for n,s in envelopes:mesh(s).export(AUD/(n+'-envelope.stl'))
(AUD/'cintas.json').write_text(json.dumps({'quantity':2,'nominal_strap_mm':[2.5,1.0],'reserved_buckle_mm':[5,4.8,4],'printed_slot_mm':[3.2,1.8],'release':'Cut ties from front, remove rigid stops, raise tray 5 mm then withdraw','needs_new_ties_after_service':True,'actual_tie_dimensions_to_confirm':True,'reference':'HellermannTyton T18R 111-01711','datasheet':'https://www.hellermanntyton.com.br/produtos/abracadeiras-com-serrilhado-interno/t18r/111-01711'},indent=2)+'\n')
print('V9 GEOMETRY PREPARED, VALIDATION PENDING')
