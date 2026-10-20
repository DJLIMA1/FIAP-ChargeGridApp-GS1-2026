from pathlib import Path
import ast,shutil,json,zipfile,xml.etree.ElementTree as ET
import numpy as np,trimesh,manifold3d as md
BASE=Path(__file__).resolve().parent.parent;OLD=BASE/'ender3-pla-oficial-v7';ROOT=BASE/'ender3-pla-oficial-v8'
if not ROOT.exists():shutil.copytree(OLD,ROOT,ignore=shutil.ignore_patterns('__pycache__','SHA256SUMS.json'))
source=(BASE/'cad-impressao-50-v1/gerar.py').read_text();tree=ast.parse(source)
for n in tree.body:
 if isinstance(n,ast.FunctionDef) and n.name in ['box','cyl','cy','union','subtract','profile','xzprofile','mesh']:exec(ast.get_source_segment(source,n))
with zipfile.ZipFile(OLD/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf') as z:entries={n:z.read(n) for n in z.namelist()}
xml=ET.fromstring(entries['3D/3dmodel.model']);objects={};elements={};ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02'
def solid(m):return md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
for o in xml.findall('.//{*}object'):
 v=[[float(a.attrib[k]) for k in ['x','y','z']] for a in o.findall('.//{*}vertex')];f=[[int(a.attrib[k]) for k in ['v1','v2','v3']] for a in o.findall('.//{*}triangle')];n=o.attrib['name'];objects[n]=trimesh.Trimesh(v,f,process=True);elements[n]=o
snippet=source.split('# Cassette in local coordinates',1)[1].split("add('09-bandeja-removivel'",1)[0]
snippet='# Cassette in local coordinates'+snippet
snippet=snippet.replace('for v in [8,54]','for v in [8,48]').replace('cyl([30,v+19,2.3],3.6,3.25)','cyl([30,v+19,0],3.6,5.55)')
exec(snippet)
objects['09-bandeja-removivel']=mesh(baseworld)
objects['11-berco-esp32']=objects['11-berco-esp32'].copy();objects['11-berco-esp32'].apply_translation([0,0,-6])
# Removable carrier pin: same receiving bores; continuous pad now provides the seat.
# Lateral wings can move toward X=0 without a full circumferential oversized bead.
head=cyl([0,0,0],3.5,2.4)
shaft=cyl([0,0,2.3],1.55,8.5)
tip=union([cyl([0,0,10.65],1.55,.15,1.92),cyl([0,0,10.8],1.92,.2),cyl([0,0,11],1.92,.8,1.15),cyl([0,0,11.8],1.15,.2,.95)])
tip=tip^box([-4,-1.,10.5],[8,2.,2])
clip=union([head,shaft,tip])-box([-.6,-4,2.8],[1.2,8,12])-cy([0,-4,2.8],.6,8)
clip=clip-box([-5,-5,-1],[10,4,15])
# D stop: rounded slot and lateral retention wings, with no oversized lower circular arc.
stop_tip=union([cyl([0,0,4.0],3.6,.2,3.95),cyl([0,0,4.2],3.95,.15),cyl([0,0,4.35],3.95,.75,3.4)])
stop_tip=stop_tip^box([-5,-2.4,3.9],[10,2.7,2])
stop=union([cyl([0,0,0],4.7,1.2),cyl([0,0,1.1],3.6,4),stop_tip])
stop=stop-box([-.6,-5,2.2],[1.2,10,4])-cy([0,-5,2.2],.6,10)-box([-6,.3,-.1],[12,6,6])
for x in [5,55]:objects['trava-bandeja-'+str(x)]=mesh(stop.rotate([0,180,0]).translate([x,5,3.8]).transform(world_matrix))
for oldname,v in [('trava-berco-8',8),('trava-berco-54',48)]:objects[oldname]=mesh(clip.rotate([0,180,0]).translate([30,v+19,10.5]).transform(world_matrix))
def export(s,path):
 m=mesh(s);m.apply_translation(-m.bounds[0]);m.vertices=np.asarray(m.vertices,dtype=np.float32).astype(float);m.merge_vertices(digits_vertex=5);m.update_faces(np.array([len(set(f))==3 for f in m.faces]));m.update_faces(m.unique_faces());m.remove_unreferenced_vertices();assert m.is_watertight and m.is_winding_consistent and len(m.split())==1;m.export(path)
export(base,ROOT/'stl/09-bandeja-removivel.stl');export(clip.rotate([90,0,0]),ROOT/'stl/12-pino-trava-berco.stl');export(stop,ROOT/'stl/13-trava-bandeja.stl')
# Rebuild only affected batches. Preserve exact original positions of other components.
parts=[]
for name,xy in [('09-bandeja-removivel',(0,0)),('10-berco-potencia',(76,0)),('11-berco-esp32',(76,55))]:
 m=trimesh.load(ROOT/'stl'/(name+'.stl'));m.apply_translation([*xy,0]);parts.append(m)
def batch(parts,path):
 m=trimesh.util.concatenate(parts);m.apply_translation([110-m.bounds[:,0].mean(),110-m.bounds[:,1].mean(),-m.bounds[0,2]]);assert m.extents[0]<200 and m.extents[1]<200;m.export(path)
batch(parts,ROOT/'modelos-fatiados/10BERCO8.stl')
parts=[]
for name,qty,y in [('12-pino-trava-berco',2,0),('13-trava-bandeja',2,25),('14-espacador-3mm',4,48),('14-espacador-5mm',4,68)]:
 for k in range(qty):
  m=trimesh.load(ROOT/'stl'/(name+'.stl'));m.apply_translation([k*20,y,0]);parts.append(m)
batch(parts,ROOT/'modelos-fatiados/11TRAVA8.stl')
for n,m in objects.items():
 o=elements[n];me=o.find('{*}mesh');me.clear();vs=ET.SubElement(me,'{'+ns+'}vertices');ts=ET.SubElement(me,'{'+ns+'}triangles')
 for x,y,z in m.vertices:ET.SubElement(vs,'{'+ns+'}vertex',x=f'{x:.7f}',y=f'{y:.7f}',z=f'{z:.7f}')
 for a,b,c in m.faces:ET.SubElement(ts,'{'+ns+'}triangle',v1=str(a),v2=str(b),v3=str(c))
entries['3D/3dmodel.model']=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
with zipfile.ZipFile(ROOT/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf','w',zipfile.ZIP_DEFLATED) as z:
 for n,d in entries.items():z.writestr(n,d)
scene=trimesh.Scene()
for n,m in objects.items():
 m.visual.face_colors=[230,232,232,255] if n=='05-tampa-frontal' else [90,125,140,255];scene.add_geometry(m,geom_name=n,node_name=n)
scene.export(ROOT/'montagem/ChargeGrid-50-OFICIAL.glb')
# Conservative geometric closing envelope for the two revised small pins.
closing=[]
for name,s,basez,rhole,slot in [('12',clip,10.6,1.8,1.2),('13',stop,3.9,3.85,1.2)]:
 m=mesh(s^box([0,-5,basez],[5,10,3]));assert np.max(np.abs(m.vertices[:,1]))<rhole
 required=max(0,float(np.max(m.vertices[:,0]-np.sqrt(rhole**2-m.vertices[:,1]**2))));assert 2*required<slot
 closing.append({'part':name,'required_geometric_closure_per_arm_mm':required,'slot_mm':slot,'elastic_strength_not_simulated':True})
(ROOT/'verificacao/revisao-interna-v8.json').write_text(json.dumps({'upper_carrier_shift_down_mm':6,'carrier_size_preserved':True,'retaining_bosses_now_reach_base_bottom':True,'new_clip_and_stop_wings_and_rounded_slots':True,'closing_envelopes':closing,'pin_assembly_names_retained_for_tracking':True,'old_name_trava_berco_54_now_local_station':48,'physical_fit_pending':True},indent=2)+'\n')
print('V8 geometria preparada; ainda depende de verificacao e fatiamento.',flush=True)
