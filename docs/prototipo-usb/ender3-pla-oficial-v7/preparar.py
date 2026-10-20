"""Fix rear join-key sockets after all cassette mounts; preserve the already printed keys.
Run in this v7 directory, which starts as a copy of the v6 print package.
"""
from pathlib import Path
import xml.etree.ElementTree as ET,zipfile,json,re,subprocess
import numpy as np,trimesh,manifold3d as md
ROOT=Path(__file__).resolve().parent;OLD=ROOT.parent/'ender3-pla-oficial-v6'
EXE='/tmp/chargegrid-prusa-dmg/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
def mesh(s):
 m=s.to_mesh64();return trimesh.Trimesh(m.vert_properties[:,:3],m.tri_verts,process=False)
def solid(m):return md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
with zipfile.ZipFile(OLD/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf') as z:entries={n:z.read(n) for n in z.namelist()}
xml=ET.fromstring(entries['3D/3dmodel.model']);ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02';meshes={};solids={};elements={}
for o in xml.findall('.//{*}object'):
 name=o.attrib['name'];v=np.array([[float(a.attrib[k]) for k in ['x','y','z']] for a in o.findall('.//{*}vertex')]);f=np.array([[int(a.attrib[k]) for k in ['v1','v2','v3']] for a in o.findall('.//{*}triangle')]);m=trimesh.Trimesh(v,f,process=True)
 meshes[name]=m;solids[name]=solid(m);elements[name]=o
outline=[(-5,-11),(-3,0),(-5,11),(5,11),(3,0),(5,-11)][::-1]
def cavity(x):
 points=[(a*1.07+x,b*1.025+58.05) for a,b in outline]
 return md.Manifold.extrude(md.CrossSection([points]),14.2).rotate([90,0,0]).translate([0,94.2,0])
old=solids['01-traseira-inferior'];new=old-cavity(-22)-cavity(22);removed=old-new
assert str(new.status())=='Error.NoError' and len(new.decompose())==1
rear=new+solids['01-traseira-superior'];frame=solids['03-quadro-superior']+solids['03-quadro-inferior']
checks=[]
for group,body,y,sign in [('rear',rear,90.8,-1),('frame',frame,57.2,1)]:
 for x in [-22,22]:
  name=f'chave-{x}-{y}';key=solids[name]
  nominal=max(0,(key^body).volume());assert nominal<1e-6,(name,nominal)
  # The successful profile slices the nominal 3 mm key at 2.88 mm.
  printed=key.translate([0,-y,0]).scale([1,2.88/3,1]).translate([0,y,0]);assert max(0,(printed^body).volume())<1e-6
  path=[]
  for d in np.linspace(0,12,49):
   value=max(0,(key.translate([0,sign*float(d),0])^body).volume());assert value<1e-6,(name,d,value)
   path.append({'distance_mm':float(d),'intersection_mm3':value})
  # Confirm a real in-plane tolerance rather than only no-overlap at a single point.
  for axis in [0,2]:
   for d in [-.15,.15]:
    shift=[0,0,0];shift[axis]=d;assert max(0,(key.translate(shift)^body).volume())<1e-6,(name,axis,d)
  checks.append({'key':name,'nominal_intersection_mm3':nominal,'height_2_88_envelope_clear':True,'xy_in_plane_shifts_0_15_mm_clear':True,'path':path})
# Only internal material is removed. Cassette stems stay intact and head retaining area remains.
mounts=[]
for x in [-25,25]:
 stem=md.Manifold.cylinder(3.6,2.1,2.1,48).rotate([-90,0,0]).translate([x,87.35,44])
 head=md.Manifold.cylinder(1.75,3.5,3.5,48).rotate([-90,0,0]).translate([x,85.6,44])
 stem_removed=max(0,(stem^removed).volume());retained=(head^new).volume()/head.volume();assert stem_removed<1e-6 and retained>.94
 mounts.append({'x':x,'stem_removed_mm3':stem_removed,'head_retained_fraction':retained})
cassette=solids['09-bandeja-removivel'];assert max(0,(cassette^rear).volume())<1e-6
# Each lower retainer still blocks a normal pull; removing cassette requires the original upward slide.
for x in [-25,25]:
 region=md.Manifold.cube([14,22,18]).translate([x-7,80,36])
 assert ((cassette.translate([0,-1,0])^rear)^region).volume()>1
for dz in [0,1,3,5]:assert max(0,(cassette.translate([0,0,dz])^rear).volume())<1e-6
for dy in [2,5,15,35]:assert max(0,(cassette.translate([0,-dy,5])^rear).volume())<1e-6
name='01-traseira-inferior';world=mesh(new);meshes[name]=world
# Check rotation/centering against the previous STL before applying it to the changed shape.
def orient(m,angle,center=False):
 m=m.copy();m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(angle),[1,0,0]));m.apply_translation(-m.bounds[0])
 if center:m.apply_translation([110-m.extents[0]/2,110-m.extents[1]/2,0])
 return m
def export_stl(m,path):
 m.vertices=np.asarray(m.vertices,dtype=np.float32).astype(np.float64)
 m.merge_vertices(digits_vertex=5)
 m.update_faces(np.array([len(set(f))==3 for f in m.faces]));m.update_faces(m.unique_faces());m.remove_unreferenced_vertices()
 assert m.is_watertight and m.is_winding_consistent and m.volume>0
 m.export(path)
reference=orient(mesh(old),-90,True);oldprint=trimesh.load(OLD/'modelos-fatiados/03TRINF.stl')
assert np.allclose(reference.bounds,oldprint.bounds,atol=1e-4)
assert abs(reference.volume-oldprint.volume)<.1
# Individual STL retains the original orientation; actual sliced batch retains its optimized orientation.
export_stl(orient(world,180),ROOT/'stl/01-traseira-inferior.stl')
export_stl(orient(world,-90,True),ROOT/'modelos-fatiados/03TRINF7.stl')
for path in [ROOT/'stl/01-traseira-inferior.stl',ROOT/'modelos-fatiados/03TRINF7.stl']:
 m=trimesh.load(path);assert m.is_watertight and m.is_winding_consistent and m.volume>0 and len(m.split())==1
assert np.allclose(world.bounds,mesh(old).bounds,atol=1e-6)
o=elements[name];me=o.find('{*}mesh');me.clear();vs=ET.SubElement(me,'{'+ns+'}vertices');ts=ET.SubElement(me,'{'+ns+'}triangles')
for a,b,c in world.vertices:ET.SubElement(vs,'{'+ns+'}vertex',x=f'{a:.7f}',y=f'{b:.7f}',z=f'{c:.7f}')
for a,b,c in world.faces:ET.SubElement(ts,'{'+ns+'}triangle',v1=str(a),v2=str(b),v3=str(c))
entries['3D/3dmodel.model']=ET.tostring(xml,encoding='utf-8',xml_declaration=True)
with zipfile.ZipFile(ROOT/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf','w',zipfile.ZIP_DEFLATED) as z:
 for n,data in entries.items():z.writestr(n,data)
scene=trimesh.Scene()
for name,m in meshes.items():
 m.visual.face_colors=[230,232,232,255] if name=='05-tampa-frontal' else ([30,155,165,255] if name.startswith('08-') else [90,102,112,255]);scene.add_geometry(m,geom_name=name,node_name=name)
scene.export(ROOT/'montagem/ChargeGrid-50-OFICIAL.glb')
profile=ROOT/'perfis/03TRINF7.ini';cfg=profile.read_text().replace('OFICIAL v6','OFICIAL v7');profile.write_text(cfg)
base=[EXE,'--datadir','/tmp/chargegrid-prusa-settings','--threads','4','--load',str(profile),'--center','110,110']
for action,folder,ext in [('gcode','gcode','.gcode'),('3mf','projetos','.3mf')]:
 with (ROOT/'verificacao'/('03TRINF7-'+action+'.log')).open('w') as log:
  subprocess.run(base+['--export-'+action,'--output',str(ROOT/folder/('03TRINF7'+ext)),str(ROOT/'modelos-fatiados/03TRINF7.stl')],stdout=log,stderr=subprocess.STDOUT,check=True)
gc=(ROOT/'gcode/03TRINF7.gcode').read_text();full=gc.split('; prusaslicer_config = begin',1)[1].split('; prusaslicer_config = end',1)[0].strip()+'\n';p=ROOT/'projetos/03TRINF7.3mf'
with zipfile.ZipFile(p) as z:entries={n:z.read(n) for n in z.namelist() if n!='Metadata/Slic3r_PE.config'}
entries['Metadata/Slic3r_PE.config']=('; generated by PrusaSlicer 2.9.6\n\n'+full).encode()
with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
 for n,data in entries.items():z.writestr(n,data)
report={'cause':'Cassette mounts added after original key-pocket subtraction overlapped two rear keys','changed_production_job':'03TRINF7','original_intersection_per_key_mm3':12.541612343736162,'key_stl_nominal_mm':[10,22,3],'key_gcode_final_layer_mm':2.88,'nominal_pocket_max_width_mm':10.7,'nominal_pocket_waist_mm':6.42,'nominal_pocket_length_mm':22.55,'removed_internal_volume_mm3':removed.volume(),'removed_bounds_xyz_mm':list(removed.bounding_box()),'cassette_mounts':mounts,'cassette_slide_and_withdrawal_clear':True,'both_lower_mounts_retain_on_pull':True,'not_a_strength_or_physical_fit_test':True,'keys':checks}
(ROOT/'verificacao/emendas-corrigidas.json').write_text(json.dumps(report,indent=2)+'\n')
print('Traseira inferior corrigida e refatiada. Quatro chaves: posição, folga e 49 posições de inserção verificadas.',flush=True)
