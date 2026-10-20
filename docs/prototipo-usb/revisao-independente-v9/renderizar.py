from pathlib import Path
R=Path(__file__).resolve().parent;B=R.parent
s=(B/'cad-impressao-50-v1/renderizar.py').read_text().split('scene=trimesh.load',1)[0].replace('ROOT=Path(__file__).resolve().parent',"ROOT=Path("+repr(str(B/'cad-impressao-50-v1'))+")")
exec(s)
r=B/'ender3-pla-oficial-v9'
paths=sorted((r/'stl').glob('*.stl'));im=Image.new('RGB',(1800,2800),'white');d=ImageDraw.Draw(im)
for i,p in enumerate(paths):
 m=trimesh.load(p);x=(i%5)*360;y=(i//5)*400
 im.paste(render([(m.triangles,[100,170,195])],[.6,-1,.8],(355,310)),(x,y));name=p.stem
 d.text((x+8,y+313),name[:27],font=font(15),fill='#17333d');d.text((x+8,y+337),name[27:],font=font(15),fill='#17333d');d.text((x+8,y+363),' × '.join(f'{a:.2f}' for a in m.extents)+' mm',font=font(15),fill='#17333d')
im.save(r/'todas-as-31-pecas.png')
import zipfile,xml.etree.ElementTree as ET,manifold3d as md
with zipfile.ZipFile(r/'montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf') as z:xml=ET.fromstring(z.read('3D/3dmodel.model'))
objects={}
for o in xml.findall('.//{*}object'):
 v=[[float(q.attrib[k]) for k in ['x','y','z']] for q in o.findall('.//{*}vertex')];f=[[int(q.attrib[k]) for k in ['v1','v2','v3']] for q in o.findall('.//{*}triangle')];objects[o.attrib['name']]=trimesh.Trimesh(v,f,process=True)
def section(m):
 s=md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)));s=s^md.Manifold.cube([90,35,23]).translate([-45,70,32]);a=s.to_mesh64();return trimesh.Trimesh(a.vert_properties[:,:3],a.tri_verts,process=False)
tray=section(objects['09-bandeja-removivel']);items=[(tray.triangles,[70,130,145])]
for x in [5,55]:items.append((objects[f'trava-bandeja-{x}'].triangles,[230,148,45]))
for side in ['esquerda','direita']:
 m=trimesh.load(R/f'cinta-{side}-envelope.stl');items.append((m.triangles,[35,190,180]))
im=Image.new('RGB',(1800,1020),'#f0f4f7');d=ImageDraw.Draw(im)
d.text((40,25),'Retenção da bandeja — revisão independente v9',font=font(38),fill='#17333d')
d.text((40,79),'Geometria real | Laranja: bloqueios rígidos | Verde: reserva para cintas de nylon',font=font(23),fill='#31515e')
for k,(title,direction) in enumerate([('FRENTE: abas voltadas para o centro',[.12,-1,.45]),('VERSO: retorno das cintas nos canais',[.12,1,-.45])]):
 d.text((40+k*890,135),title,font=font(25),fill='#17333d');im.paste(render(items,direction,(860,520)),(25+k*890,180))
lines=['1. Pré-passe a ponta das cintas; deixe os bloqueios afastados e as cintas abertas.', '2. Instale e abaixe a bandeja 5 mm. Assente os bloqueios e feche as cintas manualmente.', '3. Para retirar: corte as fivelas pela frente, retire cintas e bloqueios; suba a bandeja 5 mm.', 'Cintas: referência 100 × 2,5 × 1,0 mm. Não são peças impressas; trocar após a abertura.', 'A imagem mostra a posição final. Flexão da cinta e montagem física ainda precisam de conferência.']
for i,t in enumerate(lines):d.text((40,735+i*45),t,font=font(24 if i<4 else 21),fill='#17333d')
im.save(r/'montagem-bloqueios-v9.png')
# Refresh the previous full interior view with the actual v9 geometry.
items=[]
for n,m in objects.items():
 if n.startswith(('03','05','08','pino-casca')) or (n.startswith('chave') and n.endswith('57.2')):continue
 c=[207,144,63] if n.startswith(('10','11','trava-bandeja')) else [45,122,136] if n.startswith('09') else [75,88,97];items.append((m.triangles,c))
render(items,[.2,-1,.16],(1000,1400)).save(r/'interior-revisado.png')
print('ACTUAL V9 MESH IMAGES GENERATED')
