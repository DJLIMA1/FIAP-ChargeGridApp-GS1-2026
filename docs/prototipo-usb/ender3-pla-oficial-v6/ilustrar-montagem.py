from pathlib import Path
import numpy as np,trimesh
from PIL import Image,ImageDraw
root=Path(__file__).resolve().parent
ref=root.parent/'cad-impressao-50-v1/renderizar.py'
ns={'__file__':str(ref)};exec(ref.read_text().split('scene=trimesh.load',1)[0],ns)
render,font=ns['render'],ns['font']
scene=trimesh.load(root/'montagem/ChargeGrid-50-OFICIAL.glb')
items=[]
for name,m in scene.geometry.items():
 if name.startswith(('03-','05-','08-')):
  c=np.array([225,229,231] if name.startswith('05-') else ([20,162,158] if name.startswith('08-') else [120,138,155]),float)
  shift=[0,-28,0] if name.startswith('05-') else ([0,18,0] if name.startswith('08-') else [0,0,0])
  items.append((m.triangles+shift,c))
im=Image.new('RGB',(1800,1150),'#f0f4f7');d=ImageDraw.Draw(im)
d.text((40,25),'ChargeGrid • fixação oficial da tampa',font=font(36),fill='#183746')
d.text((40,80),'Geometria real • tampa, quadro e cinco travas • vista explodida pelo lado interno',font=font(23),fill='#415d6d')
im.paste(render(items,(.35,1,.16),(900,940)),(10,155))
d.text((980,180),'07PTAMP.gcode',font=font(31),fill='#183746')
d.text((980,228),'4 travas iguais à v5 aprovada',font=font(26),fill='#183746')
d.text((980,268),'3 riscos • 2 no alto + 2 no meio',font=font(24),fill='#415d6d')
d.text((980,575),'08PTINF.gcode',font=font(31),fill='#183746')
d.text((980,623),'1 trava para o ponto inferior',font=font(26),fill='#183746')
d.text((980,663),'4 riscos • comprimento +0,25 mm',font=font(24),fill='#415d6d')
for idx,name in enumerate(['08-pino-tampa-1','08-pino-tampa-5']):
 m=trimesh.load(root/'stl'/(name+'.stl'));pic=render([(m.triangles,np.array([20,162,158]))],(.4,1,1),(560,235));im.paste(pic,(1000,305+idx*395))
d.text((40,1100),'Insira pelo lado interno do quadro em direção à tampa branca. Não colar essas cinco travas.',font=font(25),fill='#183746')
im.save(root/'montagem-travas.png')
