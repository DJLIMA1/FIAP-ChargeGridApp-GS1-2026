from pathlib import Path
import numpy as np,trimesh,manifold3d as md
from PIL import Image,ImageDraw,ImageFont
root=Path('/Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/docs/prototipo-usb/teste-trava-pla-v3')
reference=root.parent/'cad-impressao-50-v1/renderizar.py'
ns={'__file__':str(reference)}
exec(reference.read_text().split("scene=trimesh.load",1)[0],ns)
render=ns['render'];font=ns['font']
def load(name):return trimesh.load(root/'stl'/(name+'.stl'))
def shift(m,v):
 m=m.copy();m.apply_translation(v);return m
socket=shift(load('17-cupom-bucha-tampa'),[-8,-8,0])
plate=shift(load('18-cupom-placa-tampa'),[-8,-8,4.25])
pin=load('08-pino-tampa-1-a-4-PLA-v3')
pin.apply_translation([-3.4,-9.8,-1.7])
pin.apply_transform(trimesh.transformations.rotation_matrix(-np.pi/2,[1,0,0]))
pin.apply_transform(trimesh.transformations.rotation_matrix(np.pi,[1,0,0]))
pin.apply_translation([0,0,11.1])
def half(m):
 s=md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
 s=s^md.Manifold.cube([30,20,30]).translate([-15,0,-1])
 mm=s.to_mesh64();return trimesh.Trimesh(mm.vert_properties[:,:3],mm.tri_verts,process=False)
colors={'socket':[71,93,113],'plate':[227,160,66],'pin':[26,163,157]}
sets=[
 [('socket',shift(socket,[-13,0,0])),('plate',shift(plate,[13,0,-4.25]))],
 [('socket',socket),('plate',shift(plate,[0,0,4])),('pin',shift(pin,[0,0,11]))],
 [('socket',half(socket)),('plate',half(plate)),('pin',half(pin))]]
img=Image.new('RGB',(1800,1050),'#f0f4f7');d=ImageDraw.Draw(img)
d.text((40,25),'Teste da trava pequena • tampa branca do ChargeGrid',font=font(34),fill='#183746')
d.text((40,78),'Use os dois bloquinhos do teste anterior. O bloco grande da baioneta não participa deste teste.',font=font(22),fill='#415d6d')
labels=['1. Identifique os dois blocos','2. Sobreponha e pressione reto','3. Confira a retenção']
for i,items in enumerate(sets):
 d.text((35+i*595,145),labels[i],font=font(25),fill='#183746')
 pic=render([(m.triangles,np.array(colors[n],float)) for n,m in items],(.6,-1,.9) if i<2 else (.1,-1,.30),(570,540))
 img.paste(pic,(15+i*595,200))
texts=[['17 • azul: bloco com furo cego','18 • amarelo: placa com furo passante','Ambos medem 16 × 16 mm.'],['Furo cego voltado para cima.','Placa 18 por cima, furos alinhados.','Pino verde entra pelo lado da placa.'],['Vista cortada, apenas para explicar.','A cabeça fica fora, sobre a placa.','A ponta trava dentro do bloco 17.']]
for i,lines in enumerate(texts):
 for j,t in enumerate(lines):d.text((35+i*595,775+j*33),t,font=font(22),fill='#284755')
d.text((40,940),'Sem cola e sem martelar. Teste encaixar, reter e retirar com os dedos; pare se houver trinca ou embranquecimento.',font=font(22),fill='#183746')
d.text((40,982),'Cores ilustrativas: a impressão será da cor do seu filamento. Protótipo v3 ainda depende de ensaio físico.',font=font(20),fill='#536974')
img.save(root/'como-testar.png')
