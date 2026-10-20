from pathlib import Path
import numpy as np
import trimesh
from PIL import Image, ImageDraw

ROOT=Path(__file__).resolve().parent
ns={'__file__':str(ROOT/'gerar.py')}
exec((ROOT/'gerar.py').read_text().split('evidence=[]',1)[0],ns)
render,font,BASE,jobs=ns['render'],ns['font'],ns['BASE'],ns['jobs']
OUT=ROOT/'por-arquivo'
OUT.mkdir(exist_ok=True)
complex_jobs={
 '10BERCO9':[
  ('09-bandeja-removivel','1 × bandeja removível'),
  ('10-berco-potencia','1 × berço de potência'),
  ('11-berco-esp32','1 × berço do ESP32')],
 '11TRAVA9':[
  ('12-pino-trava-berco','2 × pinos dos berços'),
  ('13-bloqueio-bandeja-esquerda','1 × bloqueio esquerdo'),
  ('13-bloqueio-bandeja-direita','1 × bloqueio direito'),
  ('14-espacador-3mm','4 × espaçadores de 3 mm'),
  ('14-espacador-5mm','4 × espaçadores de 5 mm')],
 '12CABO':[
  ('19-inserto-duplo-5mm-a','1 × metade A do inserto'),
  ('19-inserto-duplo-5mm-b','1 × metade B do inserto'),
  ('15-prensa-cabo-5mm-meia','4 × meias presilhas')]
}
for name,title,count,lines,badge in jobs:
    rows=2 if name=='11TRAVA9' else 1
    height=730 if rows==2 else 475
    im=Image.new('RGB',(900,height),'#f0f4f7');d=ImageDraw.Draw(im)
    d.text((25,18),name+'.gcode',font=font(30),fill='#126d7b')
    d.text((25,58),title+f' • {count} '+('peça' if count==1 else 'peças'),font=font(25),fill='#183746')
    if name in complex_jobs:
        for idx,(part,label) in enumerate(complex_jobs[name]):
            x=(idx%3)*300;y=105+(idx//3)*255
            mesh=trimesh.load(BASE/'stl'/(part+'.stl'),force='mesh')
            pic=render([(mesh.triangles,np.array([57,151,172],float))],(.6,-1,.75),(295,205))
            im.paste(pic,(x,y))
            d.text((x+12,y+210),label,font=font(21),fill='#183746')
    else:
        mesh=trimesh.load(BASE/'modelos-fatiados'/(name+'.stl'),force='mesh')
        pic=render([(mesh.triangles,np.array([57,151,172],float))],(.55,-1,1.1),(850,260))
        im.paste(pic,(25,100))
    for idx,line in enumerate(lines):d.text((25,height-100+idx*27),line,font=font(23),fill='#183746')
    foot=badge if badge else 'Modelo real • sem suportes ou brim • vistas em escalas diferentes'
    d.text((25,height-32),foot,font=font(19),fill='#415d6d')
    im.save(OUT/(name+'.png'))

text=['# Todos os 12 arquivos de impressão','',
      'São 12 G-codes e 39 peças contando as repetições. 01 e 02 já foram impressos e retirados do SD. O arquivo 12 é opcional.','']
for name,title,count,lines,badge in jobs:
    text.extend([f'## {name}.gcode — {title}','', ' '.join(lines), '', f'![{name}](por-arquivo/{name}.png)',''])
(ROOT/'TODOS-OS-ARQUIVOS.md').write_text('\n'.join(text))
print('12 imagens individuais geradas; componentes dos lotes 10, 11 e 12 identificados.')
