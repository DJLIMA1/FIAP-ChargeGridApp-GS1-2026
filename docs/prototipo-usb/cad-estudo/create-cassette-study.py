"""Gera volumes conceituais do cassete. NÃO usar para fabricação.
Requer Python 3 e pacote cadquery-ocp (OCP), sem depender do CAD original.
Editar cassette-study-layout.json e executar este arquivo no mesmo diretório.
Valida apenas integridade BRep e round trip STEP; NÃO valida encaixe na casca.
"""
from pathlib import Path
import json
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorType
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.gp import gp_Pnt
from OCP.STEPCAFControl import STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs,STEPControl_Reader
from OCP.IFSelect import IFSelect_RetDone
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
root=Path(__file__).resolve().parent
layout=json.loads((root/'cassette-study-layout.json').read_text())
doc=TDocStd_Document(TCollection_ExtendedString('CONCEPT_STUDY_NOT_FOR_MANUFACTURE'))
st=XCAFDoc_DocumentTool.ShapeTool_s(doc.Main());ct=XCAFDoc_DocumentTool.ColorTool_s(doc.Main())
parts=[(p['name'],p['origin'],p['dimensions'],p['color']) for p in layout['parts']]
for name,pos,dims,col in parts:
 shape=BRepPrimAPI_MakeBox(gp_Pnt(*pos),*dims).Shape()
 assert BRepCheck_Analyzer(shape).IsValid()
 label=st.AddShape(shape,False)
 TDataStd_Name.Set_s(label,TCollection_ExtendedString(name))
 ct.SetColor(label,Quantity_Color(*col,Quantity_TOC_RGB),XCAFDoc_ColorType.XCAFDoc_ColorGen)
w=STEPCAFControl_Writer();w.SetNameMode(True);w.SetColorMode(True)
assert w.Transfer(doc,STEPControl_AsIs)
out=root/'cassette-volumes-CONCEITO.step'
assert w.Write(str(out))==IFSelect_RetDone
r=STEPControl_Reader();assert r.ReadFile(str(out))==IFSelect_RetDone;r.TransferRoots();shape=r.OneShape();assert BRepCheck_Analyzer(shape).IsValid()
box=Bnd_Box();BRepBndLib.AddOptimal_s(shape,box,False,False)
count=0;ex=TopExp_Explorer(shape,TopAbs_SOLID)
while ex.More():count+=1;ex.Next()
lo=box.CornerMin().Coord();hi=box.CornerMax().Coord()
report={'status':'concept_only_not_for_manufacture','file':out.name,'valid_BRep':True,'solids':count,'envelope_mm':[hi[i]-lo[i] for i in range(3)],'coordinates':'X width, Y cassette height, Z forward depth, local reference independent of original STEP','verified':'STEP write/read round trip and individual/composite BRep validity only','not_verified':['shell fit','board and cable fit','assembly motion','functional joints','snap-fit compliance','thermal behavior'],'parts':[{'name':n,'origin':p,'dimensions':d} for n,p,d,c in parts]}
(root/'cassette-volumes-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
