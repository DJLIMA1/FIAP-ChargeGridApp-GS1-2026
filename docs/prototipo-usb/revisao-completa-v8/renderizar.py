from pathlib import Path
R=Path(__file__).resolve().parent;B=R.parent
s=(B/'cad-impressao-50-v1/renderizar.py').read_text().split('scene=trimesh.load',1)[0].replace('ROOT=Path(__file__).resolve().parent',"ROOT=Path("+repr(str(B/'cad-impressao-50-v1'))+")")
exec(s)
r=B/'ender3-pla-oficial-v8'
paths=sorted((r/'stl').glob('*.stl'))
im=Image.new('RGB',(1800,2400),'white');d=ImageDraw.Draw(im)
for i,p in enumerate(paths):
 m=trimesh.load(p);x=(i%5)*360;y=(i//5)*400
 im.paste(render([(m.triangles,[100,170,195])],[.6,-1,.8],(355,310)),(x,y))
 name=p.stem;d.text((x+8,y+313),name[:27],font=font(15),fill='#17333d');d.text((x+8,y+337),name[27:],font=font(15),fill='#17333d');d.text((x+8,y+363),' × '.join(f'{a:.2f}' for a in m.extents)+' mm',font=font(15),fill='#17333d')
im.save(R/'todas-as-30-pecas.png')
scene=trimesh.load(r/'montagem/ChargeGrid-50-OFICIAL.glb');items=[]
for n,m in scene.geometry.items():
 if n.startswith(('03','05','08','pino-casca')) or (n.startswith('chave') and n.endswith('57.2')):continue
 c=[207,144,63] if n.startswith(('10','11')) else [45,122,136] if n.startswith('09') else [75,88,97]
 items.append((m.triangles,c))
render(items,[.2,-1,.16],(1000,1400)).save(R/'interior-revisado.png')
