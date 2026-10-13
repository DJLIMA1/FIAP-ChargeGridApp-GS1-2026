"""Extrai casca do STEP original e testa a reserva do cassete, sem alterar paredes.

Uso: python extrair-referencia.py /caminho/original.stp
Requer cadquery-ocp. Saídas de REFERÊNCIA, não liberadas para fabricação.
"""
from pathlib import Path
import sys, json, hashlib
from OCP.STEPCAFControl import STEPCAFControl_Reader, STEPCAFControl_Writer
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Reader
from OCP.TDocStd import TDocStd_Document
from OCP.TCollection import TCollection_ExtendedString
from OCP.TDataStd import TDataStd_Name
from OCP.TDF import TDF_Label
from OCP.collections import Sequence_TDF_Label as TDF_LabelSequence
from OCP.XCAFDoc import XCAFDoc_DocumentTool, XCAFDoc_ColorType
from OCP.Quantity import Quantity_Color, Quantity_TOC_RGB
from OCP.TopLoc import TopLoc_Location
from OCP.gp import gp_Pnt, gp_Trsf
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRep import BRep_Builder
from OCP.TopoDS import TopoDS_Compound, TopoDS_Shape
from OCP.BRepTools import BRepTools
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.BRepGProp import BRepGProp
from OCP.GProp import GProp_GProps
from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.IFSelect import IFSelect_RetDone
from OCP.Interface import Interface_Static

OUT = Path(__file__).resolve().parent
SOURCE = Path(sys.argv[1])
EXPECTED_HASH = 'dad2a7a04d5e5ee3a4910721e62fedfcc08763ce41629c49d8e0bb8d1eab153d'
assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == EXPECTED_HASH, 'STEP diferente da referência analisada'
NAMES = {'KETI-1216': ('traseira_original_70_REFERENCIA', [.22, .25, .24]),
         'KETI-ZHONG': ('quadro_original_70_REFERENCIA', [.65, .69, .73]),
         'KETI-TOP': ('tampa_original_70_REFERENCIA', [1., 1., 1.])}

def bounds(shape):
    b = Bnd_Box(); BRepBndLib.AddOptimal_s(shape, b, False, False)
    lo, hi = b.CornerMin().Coord(), b.CornerMax().Coord()
    return {'min': list(lo), 'max': list(hi), 'size_xyz': [hi[i]-lo[i] for i in range(3)]}

def solids(shape):
    n = 0; ex = TopExp_Explorer(shape, TopAbs_SOLID)
    while ex.More(): n += 1; ex.Next()
    return n

def volume(shape):
    props = GProp_GProps(); BRepGProp.VolumeProperties_s(shape, props)
    return props.Mass()

doc = TDocStd_Document(TCollection_ExtendedString('chargegrid_source'))
r = STEPCAFControl_Reader(); r.SetNameMode(True)
print('Lendo STEP original...', flush=True)
assert r.ReadFile(str(SOURCE)) == IFSelect_RetDone
assert r.Transfer(doc)
st = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
roots = TDF_LabelSequence(); st.GetFreeShapes(roots)
parts = []
scale = gp_Trsf(); scale.SetScale(gp_Pnt(0, 0, 0), .7)

def walk(label, loc):
    loc = loc.Multiplied(st.GetLocation_s(label))
    if st.IsReference_s(label):
        ref = TDF_Label(); st.GetReferredShape_s(label, ref); label = ref
    attr = TDataStd_Name()
    name = attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ''
    if st.IsAssembly_s(label):
        seq = TDF_LabelSequence(); st.GetComponents_s(label, seq)
        for i in range(1, seq.Length()+1): walk(seq.Value(i), loc)
    elif name in NAMES:
        shape = st.GetShape_s(label).Located(loc)
        shape = BRepBuilderAPI_Transform(shape, scale, True).Shape()
        parts.append((NAMES[name][0], shape, NAMES[name][1]))

for i in range(1, roots.Length()+1): walk(roots.Value(i), TopLoc_Location())
assert len(parts) == 3
print('Casca extraída.', flush=True)

def export_step(filename, items):
    builder = BRep_Builder(); compound = TopoDS_Compound(); builder.MakeCompound(compound)
    for _, shape, _ in items: builder.Add(compound, shape)
    native_name = filename.replace('.step', '.brep')
    assert BRepTools.Write_s(compound, str(OUT/native_name))
    check = TopoDS_Shape(); assert BRepTools.Read_s(check, str(OUT/native_name), BRep_Builder())
    native_valid = BRepCheck_Analyzer(check).IsValid()
    assert native_valid, 'BRep nativo inválido'
    d = TDocStd_Document(TCollection_ExtendedString('REFERENCE_NOT_FOR_MANUFACTURE'))
    s = XCAFDoc_DocumentTool.ShapeTool_s(d.Main()); c = XCAFDoc_DocumentTool.ColorTool_s(d.Main())
    for name, shape, rgb in items:
        lab = s.AddShape(shape, False)
        TDataStd_Name.Set_s(lab, TCollection_ExtendedString(name))
        c.SetColor(lab, Quantity_Color(*rgb, Quantity_TOC_RGB), XCAFDoc_ColorType.XCAFDoc_ColorGen)
    w = STEPCAFControl_Writer(); w.SetNameMode(True); w.SetColorMode(True)
    Interface_Static.SetIVal_s("write.surfacecurve.mode", 0)
    assert w.Transfer(d, STEPControl_AsIs)
    assert w.Write(str(OUT/filename)) == IFSelect_RetDone
    rr = STEPControl_Reader(); assert rr.ReadFile(str(OUT/filename)) == IFSelect_RetDone
    rr.TransferRoots(); sh = rr.OneShape()
    valid = BRepCheck_Analyzer(sh).IsValid()
    if not valid: (OUT/filename).unlink()
    return {'file': filename if valid else None, 'STEP_round_trip_BRep_valid': valid, 'STEP_discarded_when_invalid': not valid, 'native_file': native_name, 'native_BRep_round_trip_valid': native_valid, 'solids': solids(check), 'bounds_mm': bounds(check)}

report = {'status': 'REFERENCE_NOT_FOR_MANUFACTURE', 'source_sha256': EXPECTED_HASH,
          'scale': .7, 'coordinates': 'X largura; Y positivo para traseira; Z altura; origem STEP original escalada',
          'parts': [{'name': n, 'BRep_valid': BRepCheck_Analyzer(s).IsValid(), 'solids': solids(s), 'bounds_mm': bounds(s)} for n,s,c in parts]}
report['shell_export'] = export_step('casca-original-70-REFERENCIA.step', parts)

# Cassete: coordenadas locais X largura, Y altura, Z profundidade para frente.
z_low = -133.90133242281664 * .7
transform = gp_Trsf()
transform.SetValues(1., 0., 0., -42., 0., 0., -1., 176*.7, 0., 1., 0., z_low+142.)
layout = json.loads((OUT.parent/'cad-estudo/cassette-study-layout.json').read_text())
cassette = []
for p in layout['parts']:
    shape = BRepPrimAPI_MakeBox(gp_Pnt(*p['origin']), *p['dimensions']).Shape()
    shape = BRepBuilderAPI_Transform(shape, transform, True).Shape()
    cassette.append((p['name']+'_CONCEITO', shape, p['color']))
report['assembly_export'] = export_step('casca-e-cassete-posicionado-ESTUDO.step', parts+cassette)

envelope = BRepPrimAPI_MakeBox(gp_Pnt(0, 0, 0), 84, 156, 40).Shape()
envelope = BRepBuilderAPI_Transform(envelope, transform, True).Shape()
report['cassette_envelope_mm'] = bounds(envelope)
report['collision_tests'] = []
for name, shape, _ in parts:
    print('Interseção com', name, flush=True)
    op = BRepAlgoAPI_Common(shape, envelope); op.SetRunParallel(True); op.Build()
    entry = {'original_shell_part': name, 'algorithm_done': op.IsDone()}
    if op.IsDone():
        common = op.Shape()
        entry.update({'common_BRep_valid': BRepCheck_Analyzer(common).IsValid(),
                      'intersection_volume_mm3': volume(common), 'intersecting_solids': solids(common)})
        if solids(common): entry['intersection_bounds_mm'] = bounds(common)
    report['collision_tests'].append(entry)
report['placement_screening'] = []
for back_y in [124.2, 125.2, 126.2, 127.2, 128.2, 129.2, 130.2, 131.2]:
    e = BRepPrimAPI_MakeBox(gp_Pnt(-42., back_y-40., z_low+142.), 84., 40., 156.).Shape()
    volumes = []
    for name, shape, _ in parts:
        op = BRepAlgoAPI_Common(shape, e); op.Build()
        volumes.append({'part': name, 'done': op.IsDone(), 'volume_mm3': volume(op.Shape()) if op.IsDone() else None})
    report['placement_screening'].append({'backplane_y_scaled_mm': back_y, 'intersections': volumes})
report['limits'] = [
    'Casca original apenas escalada: mantém nervuras, postes e furos industriais, sem reconstrução FDM.',
    'Interseção testa o envelope maciço reservado contra material da casca; não demonstra contenção, montagem ou espessura de parede.',
    'Não modela cabo, plugs, conectores, ventilação ou movimento de remoção; podem ultrapassar o envelope.',
    'Validade BRep/round trip não é aprovação de impressão ou segurança elétrica.'
]
(OUT/'verificacao-referencia.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
