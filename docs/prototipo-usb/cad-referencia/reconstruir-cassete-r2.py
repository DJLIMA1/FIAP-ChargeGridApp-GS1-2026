"""Reconstrói somente as caixas do cassete r2 e exporta STEP/BREP.
Requer cadquery-ocp. Lê reserva-corrigida.json; não altera/importa a casca original.
As caixas são reservas genéricas, não peças finais nem modelos de placas reais.
"""
from pathlib import Path
import json
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.gp import gp_Pnt,gp_Trsf
from OCP.BRep import BRep_Builder
from OCP.BRepTools import BRepTools
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.TopoDS import TopoDS_Compound,TopoDS_Shape
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.XCAFDoc import XCAFDoc_DocumentTool,XCAFDoc_ColorType
from OCP.Quantity import Quantity_Color,Quantity_TOC_RGB
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs,STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
ROOT=Path(__file__).resolve().parent
report=json.loads((ROOT/'reserva-corrigida.json').read_text());e=report['selected_envelope']
t=gp_Trsf();t.SetValues(1,0,0,e['bounds_mm']['min'][0],0,0,-1,e['back_Y_mm'],0,1,0,e['bounds_mm']['min'][2])
builder=BRep_Builder();compound=TopoDS_Compound();builder.MakeCompound(compound)
doc=TDocStd_Document(TCollection_ExtendedString('ChargeGrid_cassette_R2_STUDY_ONLY'))
st=XCAFDoc_DocumentTool.ShapeTool_s(doc.Main());ct=XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
colors=[(.65,.75,.78),(.93,.58,.16),(.93,.58,.16),(.2,.56,.42),(.25,.36,.7),(.18,.48,.61),(.83,.9,.87),(.81,.84,.94),(.77,.88,.92)]
for i,p in enumerate(report['corrected_cassette']['parts']):
 s=BRepPrimAPI_MakeBox(gp_Pnt(*p['local_origin_mm']),*p['local_dimensions_mm']).Shape();s=BRepBuilderAPI_Transform(s,t,True).Shape();assert BRepCheck_Analyzer(s).IsValid();builder.Add(compound,s)
 lab=st.AddShape(s,False);TDataStd_Name.Set_s(lab,TCollection_ExtendedString('R2_'+p['name']));ct.SetColor(lab,Quantity_Color(*colors[i],Quantity_TOC_RGB),XCAFDoc_ColorType.XCAFDoc_ColorGen)
assert BRepCheck_Analyzer(compound).IsValid()
brep=ROOT/'cassete-reserva-36mm-POSICIONADO-ESTUDO.brep';assert BRepTools.Write_s(compound,str(brep))
step=ROOT/'cassete-r2-36mm-POSICIONADO-ESTUDO.step';w=STEPCAFControl_Writer();w.SetNameMode(True);w.SetColorMode(True);assert w.Transfer(doc,STEPControl_AsIs);assert w.Write(str(step))==IFSelect_RetDone
r=STEPControl_Reader();assert r.ReadFile(str(step))==IFSelect_RetDone;r.TransferRoots();s=r.OneShape();assert BRepCheck_Analyzer(s).IsValid()
n=0;ex=TopExp_Explorer(s,TopAbs_SOLID)
while ex.More():n+=1;ex.Next()
assert n==9
b=Bnd_Box();BRepBndLib.AddOptimal_s(s,b,False,False);lo=list(b.CornerMin().Coord());hi=list(b.CornerMax().Coord())
assert all(abs(lo[i]-e['bounds_mm']['min'][i])<1e-5 and abs(hi[i]-e['bounds_mm']['max'][i])<1e-5 for i in range(3))
report['corrected_cassette']['STEP_export']={'file':step.name,'roundtrip_BRep_valid':True,'roundtrip_solids':n,'roundtrip_bounds_mm':{'min':lo,'max':hi,'size_xyz':[hi[i]-lo[i] for i in range(3)]}}
report['baseline_revision']='r2: generic reserve depth 36 mm; prior 40 mm concept remains historical and collides with the original frame'
(ROOT/'reserva-corrigida.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report['corrected_cassette']['STEP_export'],indent=2))
