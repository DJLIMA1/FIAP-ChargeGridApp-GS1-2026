"""Renderiza as malhas entregues, sem IA generativa. Requer numpy, trimesh e Pillow.
No macOS, compila raster.c em diretório temporário com o compilador cc.
"""
from pathlib import Path
import ctypes,json,sys,subprocess,tempfile
import numpy as np,trimesh
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent
_raster_temp=tempfile.TemporaryDirectory(prefix='chargegrid-raster-')
libpath=Path(_raster_temp.name)/'raster.dylib'
subprocess.run(['cc','-O3','-dynamiclib',str(ROOT/'raster.c'),'-o',str(libpath)],check=True)
lib=ctypes.CDLL(str(libpath));ptr=np.ctypeslib.ndpointer
lib.raster.argtypes=[ctypes.c_int,ptr(np.float32,flags='C_CONTIGUOUS'),ptr(np.uint8,flags='C_CONTIGUOUS'),ctypes.c_int,ctypes.c_int,ptr(np.uint8,flags='C_CONTIGUOUS'),ptr(np.float32,flags='C_CONTIGUOUS')]
fontpath='/System/Library/Fonts/Supplemental/Arial.ttf'
def font(n):return ImageFont.truetype(fontpath,n)
def render(items,direction,size=(720,1040)):
 W,H=size;z=np.array(direction,float);z/=np.linalg.norm(z);x=np.cross([0,0,1],z);x/=np.linalg.norm(x);y=np.cross(z,x);rot=np.array([x,-y,z]).T
 p=np.concatenate([t for t,c in items])@rot;colors=np.concatenate([np.tile(c,(len(t),1)) for t,c in items])
 n=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);n/=np.maximum(np.linalg.norm(n,axis=1)[:,None],1e-12);n*=np.where(n[:,2]<0,-1,1)[:,None]
 light=np.array([-.4,-.6,.8]);light/=np.linalg.norm(light);shade=.38+.62*np.maximum(0,n@light)
 rgb=np.uint8(np.clip(colors*shade[:,None],0,255));scale=min((W-70)/np.ptp(p[:,:,0]),(H-70)/np.ptp(p[:,:,1]));p[:,:,:2]*=scale
 p[:,:,0]+=W/2-(p[:,:,0].min()+p[:,:,0].max())/2;p[:,:,1]+=H/2-(p[:,:,1].min()+p[:,:,1].max())/2
 img=np.full((H,W,3),[240,244,247],np.uint8);zb=np.full((H,W),-1e20,np.float32)
 lib.raster(len(p),np.ascontiguousarray(p,dtype=np.float32),np.ascontiguousarray(rgb),W,H,img,zb)
 return Image.fromarray(img)
scene=trimesh.load(ROOT/'montagem/ChargeGrid-50-montado.glb')
items=[];inner=[];explode=[]
for name,m in scene.geometry.items():
 c=np.array(m.visual.face_colors[0,:3],float);t=m.triangles
 items.append((t,c))
 if not name.startswith(('03','05','08','pino-casca')) and not (name.startswith('chave') and name.endswith('57.2')):inner.append((t,c))
 shift=np.zeros(3)
 if name.startswith('03') or (name.startswith('chave') and name.endswith('57.2')):shift=[0,-48,0]
 elif name.startswith('05'):shift=[0,-92,0]
 elif name.startswith('08'):shift=[0,-75,0]
 elif name.startswith(('09','10','11','trava')):shift=[0,-20,0]
 elif name.startswith('pino-casca'):shift=[0,20,0]
 explode.append((t+shift,c))
img=Image.new('RGB',(2400,1580),(240,244,247));d=ImageDraw.Draw(img)
d.text((70,42),'ChargeGrid Mini · 50% · revisão de impressão v1',font=font(48),fill='#162d3b')
d.text((72,107),'Geometria real dos arquivos entregues  |  Corpo: 225 × 104 × 82 mm',font=font(27),fill='#536974')
for i,(label,objects,direction) in enumerate([('EXTERIOR',items,(.55,-1,.22)),('INTERIOR MODULAR',inner,(.38,-1,.20)),('MONTAGEM EXPLODIDA',explode,(1,-1,.2))]):
 d.text((75+i*780,175),label,font=font(25),fill='#168b97')
 im=render(objects,direction,(760,1050));img.paste(im,(40+i*780,220))
texts=[['Forma original em meia escala','Frente branca separada','Pinos removíveis, sem rosca'],['Bandeja removível de 60 × 112 mm','Berços separados para ESP32 e potência','Saída com inserto bipartido'],['5 peças principais da carcaça','Emendas alinhadas por chaves + cola','Acesso de manutenção pela frente']]
for i,lines in enumerate(texts):
 for j,line in enumerate(lines):d.text((75+i*780,1300+j*39),line,font=font(25),fill='#344d59')
d.line((70,1455,2330,1455),fill='#b9c8cd',width=2)
d.text((72,1485),'STL já na escala final: importar a 100%. Ensaiar os cupons antes das peças maiores.',font=font(27),fill='#162d3b')
img.save(ROOT/'visao-geral.png')
render(inner,(.15,-1,.15),(1100,1600)).save(ROOT/'interior.png')
render(explode,(1,-1,.2),(1500,1500)).save(ROOT/'vista-explodida.png')
print('Rendered geometry previews')
