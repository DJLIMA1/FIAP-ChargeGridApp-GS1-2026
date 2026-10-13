"""Cupons de trilho e trava PETG; requer Python 3, numpy e cadquery-ocp.
Executar no diretório deste arquivo. Saídas STEP/STL são cupons, não peças da casca.
Os STLs individuais e a bandeja do kit já ficam orientados para impressão.
"""
from pathlib import Path
import json, math, struct, hashlib
from collections import Counter
import numpy as np
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism, BRepPrimAPI_MakeCylinder
from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse, BRepAlgoAPI_Common
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.gp import gp_Pnt, gp_Vec, gp_Trsf, gp_Ax1, gp_Dir
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_SOLID, TopAbs_REVERSED
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.TopLoc import TopLoc_Location
from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorType
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB

ROOT=Path(__file__).resolve().parent
P=json.loads((ROOT/'parametros-cupons.json').read_text())
R,L=P['rail'],P['latch']
(ROOT/'stl').mkdir(exist_ok=True);(ROOT/'step').mkdir(exist_ok=True)
def bbox(shape):
 b=Bnd_Box();BRepBndLib.AddOptimal_s(shape,b,False,False)
 return np.array(b.CornerMin().Coord()),np.array(b.CornerMax().Coord())
def volume(shape):
 p=GProp_GProps();BRepGProp.VolumeProperties_s(shape,p);return float(p.Mass())
def box(pos,dims):return BRepPrimAPI_MakeBox(gp_Pnt(*pos),*dims).Shape()
def prism(points,vec):
 w=BRepBuilderAPI_MakePolygon()
 for p in points:w.Add(gp_Pnt(*p))
 w.Close();return BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(w.Wire()).Face(),gp_Vec(*vec)).Shape()
def move(s,v):
 t=gp_Trsf();t.SetTranslation(gp_Vec(*v));return BRepBuilderAPI_Transform(s,t,True).Shape()
def rotate(s,axis,ang):
 t=gp_Trsf();t.SetRotation(gp_Ax1(gp_Pnt(0,0,0),gp_Dir(*axis)),ang);return BRepBuilderAPI_Transform(s,t,True).Shape()
def origin(s):return move(s,-bbox(s)[0])
def fuse(a,b):
 o=BRepAlgoAPI_Fuse(a,b);o.Build();assert o.IsDone();return o.Shape()
def cut(a,b):
 o=BRepAlgoAPI_Cut(a,b);o.Build();assert o.IsDone();return o.Shape()
def common_vol(a,b):
 o=BRepAlgoAPI_Common(a,b);o.Build();assert o.IsDone();return abs(volume(o.Shape()))
def solids(s):
 ex=TopExp_Explorer(s,TopAbs_SOLID);n=0
 while ex.More():n+=1;ex.Next()
 return n

wb,wt,h,ln=R['male_bottom_width'],R['male_top_width'],R['male_height'],R['length']
# Matching flanks: x_wall(z) = x_male(z) + side_clearance at common Z.
male=prism([(-wb/2,0,0),(wb/2,0,0),(wt/2,0,h),(-wt/2,0,h)],(0,ln,0))
male=fuse(male,box((-R['pull_tab_width']/2,-R['pull_tab_length'],0),(R['pull_tab_width'],R['pull_tab_length'],h)))
parts=[];assemblies=[];tests=[]
parts.append({'id':'trilho-macho-comum','shape':origin(male),'color':(.22,.56,.67),'role':'Macho comum dos tres trilhos; puxador para desmontagem','orientation':'Base larga plana na mesa; puxador no mesmo plano.'})
for idx,c in enumerate(R['side_clearances'],1):
 f=R['floor_height'];fw=R['female_width'];fh=R['female_height'];slope=(wb-wt)/(2*h)
 floor_half=wb/2+(1+slope)*c
 top_half=wt/2+(1-slope)*c
 upper_z=f+h+2*c
 female=box((-fw/2,0,0),(fw,ln+R['end_stop'],fh))
 cutter=prism([(-floor_half,-1,f),(floor_half,-1,f),(top_half,-1,upper_z),(top_half,-1,fh+1),(-top_half,-1,fh+1),(-top_half,-1,upper_z)],(0,ln+1,0))
 female=cut(female,cutter)
 for k in range(idx):
  marker=BRepPrimAPI_MakeCylinder(R['marker_diameter']/2,R['marker_depth']+1).Shape()
  marker=move(marker,(-10,7+6*k,fh-R['marker_depth']))
  female=cut(female,marker)
 pid=f'trilho-femea-{int(round(c*100)):02d}'
 parts.append({'id':pid,'shape':origin(female),'color':(.76,.44,.17),'role':f'{idx} ponto(s) = folga horizontal de {c:.2f} mm por lado','orientation':'Base plana na mesa; cavidade aberta para cima; sem suporte.'})
 assembled_male=move(male,(0,0,f+c))
 assert common_vol(female,assembled_male)<1e-7
 withdrawal=[]
 for dy in [0,-2,-10,-20,-40]:withdrawal.append({'translation_y':dy,'intersection_mm3':common_vol(female,move(assembled_male,(0,dy,0)))})
 assert max(a['intersection_mm3'] for a in withdrawal)<1e-7
 lift=common_vol(female,move(assembled_male,(0,0,2)))
 over=common_vol(female,move(assembled_male,(0,.5,0)))
 assert lift>0.01 and over>0.01
 tests.append({'test':pid,'nominal_assembly_intersection_mm3':common_vol(female,assembled_male),'withdrawal':withdrawal,'lift_2mm_intersection_mm3':lift,'overtravel_0p5mm_intersection_mm3':over,'expected':'zero collision assembled/withdrawal; positive collision on lift/overtravel confirms geometric retention only','horizontal_clearance_per_flank':c,'bottom_clearance':c,'mark_count':idx})
 assemblies.append((pid,female,assembled_male))

# Replaceable latch coupon: beam runs in print XY, bends in XY; extrusion forms width.
gl,gw=L['grip_length'],L['grip_width'];b=L['beam_lower_y'];t=L['beam_thickness'];e=L['beam_end_x'];hb=L['hook_back_x'];ht=L['hook_tip_x'];hh=L['hook_height'];ew=L['extrusion_width']
profile=[(0,0,0),(gl,0,0),(gl,b,0),(e,b,0),(e,b+t,0),(ht,b+t,0),(hb,b+t+hh,0),(hb,b+t,0),(gl,b+t,0),(gl,gw,0),(0,gw,0)]
latch=prism(profile,(0,0,ew))
fillet=BRepFilletAPI_MakeFillet(latch);ex=TopExp_Explorer(latch,TopAbs_EDGE);added=0; selected=set()
while ex.More():
 ed=TopoDS.Edge(ex.Current());lo,hi=bbox(ed)
 if abs(lo[0]-gl)<1e-5 and abs(hi[0]-gl)<1e-5 and (abs(lo[1]-b)<1e-5 or abs(lo[1]-(b+t))<1e-5) and hi[2]-lo[2]>ew-.001:
  key=tuple(np.round(np.r_[lo,hi],5))
  if key not in selected:
   fillet.Add(L['root_radius'],ed);added+=1;selected.add(key)
 ex.Next()
assert added==2
fillet.Build();assert fillet.IsDone();latch=fillet.Shape();assert BRepCheck_Analyzer(latch).IsValid()
# Keeper is printed with its tunnel axis vertical, avoiding internal supports.
kx,kl=L['keeper_x_start'],L['keeper_length'];floor=L['keeper_floor'];vc=L['vertical_clearance_per_side'];kheight=floor+ew+2*vc+L['keeper_roof']
keeper=box((kx,0,0),(kl,gw,kheight))
slotlow=b-L['keeper_release_relief'];slothigh=b+t+L['keeper_side_clearance']
keeper=cut(keeper,box((kx-1,slotlow,floor),(kl+2,slothigh-slotlow,ew+2*vc)))
assembled_latch=move(latch,(0,0,floor+vc))
assert common_vol(keeper,assembled_latch)<1e-7
locked_pull=common_vol(keeper,move(assembled_latch,(-2,0,0)))
assert locked_pull>.01
# This is an aperture/path test of a displaced tongue envelope; not an elastic FEM model.
release=[]
for dx in [0,-2,-4,-8,-12,-18]:
 release.append({'translation_x':dx,'tongue_y_offset':-L['release_displacement_for_geometry_test'],'intersection_mm3':common_vol(keeper,move(assembled_latch,(dx,-L['release_displacement_for_geometry_test'],0)))})
assert max(r['intersection_mm3'] for r in release)<1e-7
parts.append({'id':'trava-flexivel-substituivel','shape':origin(latch),'color':(.19,.59,.40),'role':'Pega + lingueta flexivel de cupom; independente da casca','orientation':'Perfil plano XY na mesa; lingua 1,2 mm flexiona em XY, largura extrudada 8 mm; sem suporte.'})
parts.append({'id':'receptor-da-trava','shape':origin(rotate(keeper,(0,1,0),math.pi/2)),'color':(.39,.43,.68),'role':'Receptor de ensaio manual da lingueta, com tunel livre','orientation':'STL ja girado: eixo do tunel vertical; altura impressa 8 mm; sem ponte interna ou suporte.'})
tests.append({'test':'latch','nominal_assembly_intersection_mm3':common_vol(keeper,assembled_latch),'pull_2mm_intersection_mm3':locked_pull,'release_path':release,'required_hook_deflection_nominal_mm':hh-L['keeper_side_clearance'],'tested_envelope_offset_mm':L['release_displacement_for_geometry_test'],'important':'Release path translates the tongue envelope; does not simulate actual elastic deformation. Manual pressure, force, fatigue and creep remain untested.'})

# Mesh, manifold and winding checks.
def mesh(s):
 BRepMesh_IncrementalMesh(s,P['mesh']['linear_deflection'],False,P['mesh']['angular_deflection_rad'],True)
 tris=[];ex=TopExp_Explorer(s,TopAbs_FACE)
 while ex.More():
  face=TopoDS.Face(ex.Current());loc=TopLoc_Location();tri=BRep_Tool.Triangulation_s(face,loc)
  if tri:
   vertices=[None]+[np.array(tri.Node(i).Transformed(loc.Transformation()).Coord()) for i in range(1,tri.NbNodes()+1)]
   for i in range(1,tri.NbTriangles()+1):
    ids=[tri.Triangle(i).Value(k) for k in (1,2,3)]
    if face.Orientation()==TopAbs_REVERSED:ids.reverse()
    tris.append([vertices[j] for j in ids])
  ex.Next()
 return np.array(tris)
def write_stl(path,tris):
 with path.open('wb') as f:
  f.write(b'ChargeGrid test coupon; millimeters; physical fit NOT verified'.ljust(80,b' ')[:80]);f.write(struct.pack('<I',len(tris)))
  for tri in tris:
   n=np.cross(tri[1]-tri[0],tri[2]-tri[0]);n/=np.linalg.norm(n)
   f.write(struct.pack('<12fH',*n,*tri.flatten(),0))
def meshcheck(tris):
 verts,idx=np.unique(np.round(tris.reshape(-1,3),P['mesh']['vertex_weld_decimals']),axis=0,return_inverse=True);idx=idx.reshape(-1,3)
 edges=Counter();winding=Counter()
 for tri in idx:
  for a,b in [(tri[0],tri[1]),(tri[1],tri[2]),(tri[2],tri[0])]:
   key=tuple(sorted((int(a),int(b))));edges[key]+=1;winding[key]+=1 if a<b else -1
 area=np.linalg.norm(np.cross(tris[:,1]-tris[:,0],tris[:,2]-tris[:,0]),axis=1)/2
 signed=float(np.einsum('ij,ij->i',tris[:,0],np.cross(tris[:,1],tris[:,2])).sum()/6)
 return {'triangles':len(tris),'welded_vertices':len(verts),'nonmanifold_or_boundary_edges':sum(v!=2 for v in edges.values()),'inconsistent_winding_edges':sum(v!=0 for v in winding.values()),'degenerate_triangles':int((area<1e-10).sum()),'signed_mesh_volume_mm3':signed}
def write_step(path,entries):
 doc=TDocStd_Document(TCollection_ExtendedString('ChargeGrid_TEST_COUPONS'))
 st=XCAFDoc_DocumentTool.ShapeTool_s(doc.Main());ct=XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
 for name,s,c in entries:
  lab=st.AddShape(s,False);TDataStd_Name.Set_s(lab,TCollection_ExtendedString(name));ct.SetColor(lab,Quantity_Color(*c,Quantity_TOC_RGB),XCAFDoc_ColorType.XCAFDoc_ColorGen)
 w=STEPCAFControl_Writer();w.SetNameMode(True);w.SetColorMode(True);assert w.Transfer(doc,STEPControl_AsIs);assert w.Write(str(path))==IFSelect_RetDone
 r=STEPControl_Reader();assert r.ReadFile(str(path))==IFSelect_RetDone;r.TransferRoots();s=r.OneShape();assert BRepCheck_Analyzer(s).IsValid()
 return {'read_back_valid':True,'read_back_solids':solids(s)}
manifest={'schema_version':1,'status':P['status'],'units':'mm','physical_test_performed':False,'parts':[],'geometric_tests':tests,'limitations':['No physical fit, fatigue, force, thermal or creep test has been performed.','These are independent coupons, not final charger parts.','The latch root is a hand-held grip, not a finalized casing socket.','Exact tolerances depend on printer, material, profile and cooling.'],'print_profile':P['print']}
all_tris=[];all_entries=[];meshdata=[]
layout={'trilho-macho-comum':(0,41,0),'trava-flexivel-substituivel':(27,45,0),'receptor-da-trava':(74,45,0)}
for i,c in enumerate(R['side_clearances']):layout[f'trilho-femea-{int(round(c*100)):02d}']=(i*(R['female_width']+8),0,0)
for item in parts:
 s=item['shape'];pid=item['id'];assert BRepCheck_Analyzer(s).IsValid();assert solids(s)==1
 tri=mesh(s);chk=meshcheck(tri)
 assert chk['nonmanifold_or_boundary_edges']==0 and chk['inconsistent_winding_edges']==0 and chk['degenerate_triangles']==0 and chk['signed_mesh_volume_mm3']>0, (pid,chk)
 stl=ROOT/'stl'/f'{pid}.stl';step=ROOT/'step'/f'{pid}.step'
 write_stl(stl,tri)
 raw=stl.read_bytes();count=struct.unpack('<I',raw[80:84])[0];assert len(raw)==84+50*count
 parsed=np.frombuffer(raw[84:],dtype=np.dtype([('normal','<f4',(3,)),('vertices','<f4',(3,3)),('attribute','<u2')]))['vertices'].astype(float)
 stlcheck=meshcheck(parsed);assert stlcheck['nonmanifold_or_boundary_edges']==0 and stlcheck['inconsistent_winding_edges']==0 and stlcheck['degenerate_triangles']==0
 assert np.max(np.abs(np.sort(parsed.reshape(-1,3),axis=0)-np.sort(tri.reshape(-1,3),axis=0)))<1e-5
 stepchk=write_step(step,[(pid,s,item['color'])]);lo,hi=bbox(s)
 manifest['parts'].append({'id':pid,'quantity':1,'role':item['role'],'orientation':item['orientation'],'STL':str(stl.relative_to(ROOT)),'STEP':str(step.relative_to(ROOT)),'envelope_xyz_mm':(hi-lo).tolist(),'BRep_valid':True,'solids':solids(s),'BRep_volume_mm3':volume(s),'mesh':chk,'STL_read_back':stlcheck,'step':stepchk,'STL_sha256':hashlib.sha256(stl.read_bytes()).hexdigest()})
 shift=np.array(layout[pid]);all_tris.append(tri+shift);all_entries.append((pid,move(s,shift),item['color']));meshdata.append({'id':pid,'triangles':tri,'color':item['color'],'layout':layout[pid]})
combined=np.concatenate(all_tris);write_stl(ROOT/'stl'/'kit-completo-6-pecas.stl',combined);write_step(ROOT/'step'/'kit-completo-6-pecas.step',all_entries)
manifest['kit']={'STL':'stl/kit-completo-6-pecas.stl','STEP':'step/kit-completo-6-pecas.step','part_count':6,'envelope_xyz_mm':np.ptp(combined.reshape(-1,3),axis=0).tolist(),'layout_mm':layout,'combined_mesh':meshcheck(combined)}
write_step(ROOT/'step'/'montagens-DEMONSTRACAO-nao-imprimir.step',[(name,move(s,(40*i,0,0)),(.76,.44,.17)) for i,(name,s,m) in enumerate(assemblies)]+[(name+'-macho',move(m,(40*i,0,0)),(.22,.56,.67)) for i,(name,s,m) in enumerate(assemblies)]+[('trava-encaixada',move(assembled_latch,(0,55,0)),(.19,.59,.40)),('receptor',move(keeper,(0,55,0)),(.39,.43,.68))])
(ROOT/'manifesto-verificacao.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
np.save(ROOT/'malhas-para-preview.npy',np.array(meshdata,dtype=object),allow_pickle=True)
print(json.dumps({'parts':len(parts),'envelope':manifest['kit']['envelope_xyz_mm'],'all_meshes_manifold':True,'physical_test':False},ensure_ascii=False))
