from pathlib import Path
import json,xml.etree.ElementTree as ET,zipfile,re
import numpy as np,trimesh,manifold3d as md
ROOT=Path(__file__).resolve().parent;PKG=ROOT.parent/'ender3-pla-oficial-v6'
with zipfile.ZipFile(PKG/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf') as z:xml=ET.fromstring(z.read('3D/3dmodel.model'))
meshes={};solids={}
for o in xml.findall('.//{*}object'):
 name=o.attrib['name'];v=np.array([[float(a.attrib[k]) for k in ['x','y','z']] for a in o.findall('.//{*}vertex')]);f=np.array([[int(a.attrib[k]) for k in ['v1','v2','v3']] for a in o.findall('.//{*}triangle')])
 m=trimesh.Trimesh(v,f,process=True);meshes[name]=m;solids[name]=md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
key=trimesh.load(PKG/'stl/06-chave-emenda.stl')
batch=trimesh.load(PKG/'modelos-fatiados/01CHAVE.stl')
assert len(batch.split())==4
for m in batch.split():assert np.allclose(m.extents,key.extents)
gc=(PKG/'gcode/01CHAVE.gcode').read_text();layers=[float(v) for v in re.findall(r'^;Z:([\d.]+)',gc,re.M)]
height=max(layers);assert abs(height-3.)<=.121
out={'key_stl_mm':key.extents.tolist(),'key_gcode_commanded_top_mm':height,'key_count':4,'joint_gap_mm':.25,'nominal_pocket_max_width_mm':10.7,'nominal_pocket_neck_width_mm':6.42,'nominal_key_neck_width_mm':6.,'nominal_pocket_length_mm':22.55,'checks':[]}
for side,group,opening_sign in [('rear','01-traseira',-1),('frame','03-quadro',1)]:
 body=solids[group+'-superior']+solids[group+'-inferior']
 for x in [-22,22]:
  y=90.8 if side=='rear' else 57.2;name=f'chave-{x}-{y}';s=solids[name]
  inter=max(0,(s^body).volume());print('INTERSECTION',name,inter,flush=True)
  steps=[]
  for d in [0,.25,.5,1,2,3,4,6,10]:
   v=max(0,(s.translate([0,opening_sign*d,0])^body).volume());None
   steps.append({'withdrawal_mm':d,'intersection_mm3':v})
  # Scale thickness only to the actual slicer's final layer envelope, at the same seat.
  s_print=s.translate([0,-y,0]).scale([1,height/3,1]).translate([0,y,0])
  vi=max(0,(s_print^body).volume());None
  out['checks'].append({'key':name,'interference_bounds_xyz_mm':list((s^body).bounding_box()) if inter>1e-6 else None,'assembled_bounds_xyz_mm':meshes[name].bounds.tolist(),'nominal_installed_intersection_mm3':inter,'printed_height_envelope_intersection_mm3':vi,'insertion_withdrawal':steps})
(ROOT/'resultado.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps(out,indent=2))
