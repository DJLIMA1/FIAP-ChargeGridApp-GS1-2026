"""Renderiza as malhas CAD efetivas e um desenho de seção. Requer numpy e Pillow."""
from pathlib import Path
import numpy as np,json,math
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent
P=json.loads((ROOT/'parametros-cupons.json').read_text());ms=np.load(ROOT/'malhas-para-preview.npy',allow_pickle=True)
M=json.loads((ROOT/'manifesto-verificacao.json').read_text())
def fmt(v):return f'{v:g}'.replace('.',',')
W,H=2500,1750;im=Image.new('RGB',(W,H),'#f2f5f7');d=ImageDraw.Draw(im)
fontpaths=[Path('/System/Library/Fonts/Supplemental/Arial.ttf'),Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')]
F=next((p for p in fontpaths if p.exists()),None)
def font(sz,b=False):
 if F:
  bf=F.with_name('Arial Bold.ttf') if F.name=='Arial.ttf' else F.with_name('DejaVuSans-Bold.ttf')
  return ImageFont.truetype(str(bf if b and bf.exists() else F),sz)
 return ImageFont.load_default(size=sz)
def txt(x,y,s,sz=28,b=False,c='#193949'):d.text((x,y),s,font=font(sz,b),fill=c)
def wrap(x,y,s,width,sz=28,b=False,c='#405766'):
 line='';yy=y
 for word in s.split():
  test=(line+' '+word).strip()
  if d.textlength(test,font=font(sz,b))>width:
   txt(x,yy,line,sz,b,c);yy+=sz*1.3;line=word
  else:line=test
 if line:txt(x,yy,line,sz,b,c);yy+=sz*1.3
 return yy

def arrow(a,b,c='#42768a',heads='both'):
 d.line([a,b],fill=c,width=3)
 for p,q in ([(a,b),(b,a)] if heads=='both' else [(b,a)]):
  v=np.array(q,dtype=float)-p;v/=np.linalg.norm(v);o=np.array([-v[1],v[0]])
  d.polygon([p,tuple(np.array(p)+v*13+o*5),tuple(np.array(p)+v*13-o*5)],fill=c)
def raster(items,size,direction=(.7,-1.1,1.1)):
 w,h=size;tris=np.concatenate([m['triangles']+np.array(m['layout']) for m in items]);cols=np.concatenate([np.tile(m['color'],(len(m['triangles']),1)) for m in items])
 z=np.array(direction,float);z/=np.linalg.norm(z);x=np.cross([0,0,1],z);x/=np.linalg.norm(x);y=np.cross(z,x);rot=np.array([x,-y,z]).T
 p=tris@rot;scale=min((w-50)/np.ptp(p[:,:,0]),(h-50)/np.ptp(p[:,:,1]));p[:,:,:2]*=scale;p[:,:,0]+=(w-p[:,:,0].max()-p[:,:,0].min())/2;p[:,:,1]+=(h-p[:,:,1].max()-p[:,:,1].min())/2
 normals=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);normals/=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-10);normals*=np.where(normals[:,2]<0,-1,1)[:,None]
 light=np.array([-.4,-.55,.72]);light/=np.linalg.norm(light);shade=.4+.6*np.maximum(0,normals@light)
 colors=np.uint8(np.clip((cols**(1/2.2))*shade[:,None]*255,0,255));img=np.full((h,w,3),255,np.uint8);dep=np.full((h,w),-1e10)
 for tri,color in zip(p,colors):
  ax,ay=np.floor(tri[:,:2].min(0)).astype(int);bx,by=np.ceil(tri[:,:2].max(0)).astype(int);ax=max(0,ax);ay=max(0,ay);bx=min(w-1,bx);by=min(h-1,by)
  if bx<ax or by<ay:continue
  q=np.array(tri);den=(q[1,1]-q[2,1])*(q[0,0]-q[2,0])+(q[2,0]-q[1,0])*(q[0,1]-q[2,1])
  if abs(den)<1e-10:continue
  xx,yy=np.meshgrid(np.arange(ax,bx+1)+.5,np.arange(ay,by+1)+.5)
  a=((q[1,1]-q[2,1])*(xx-q[2,0])+(q[2,0]-q[1,0])*(yy-q[2,1]))/den;b=((q[2,1]-q[0,1])*(xx-q[2,0])+(q[0,0]-q[2,0])*(yy-q[2,1]))/den;c=1-a-b
  zz=a*q[0,2]+b*q[1,2]+c*q[2,2];dst=dep[ay:by+1,ax:bx+1];mask=(a>=-1e-6)&(b>=-1e-6)&(c>=-1e-6)&(zz>dst);dst[mask]=zz[mask];img[ay:by+1,ax:bx+1][mask]=color
 return Image.fromarray(img)

txt(65,45,'ChargeGrid Mini | cupons de encaixe e recuperação',49,True)
txt(65,112,'6 peças pequenas para ajustar a impressão antes da carcaça • milímetros • PETG',28,c='#536b78')
d.rounded_rectangle((1880,40,2435,105),14,fill='#ffdfad');txt(1903,59,'ENSAIO FÍSICO AINDA NÃO REALIZADO',24,True,c='#735017')
for box in [(45,188,1290,1388),(1320,188,2455,840),(1320,870,2455,1388)]:d.rounded_rectangle(box,18,fill='white',outline='#d6e1e7',width=2)
txt(75,222,'Kit na orientação de impressão',35,True)
txt(75,277,'Envelope do conjunto: '+' × '.join(fmt(v) for v in M['kit']['envelope_xyz_mm'])+' mm',29,c='#406779')
render=raster(list(ms),(1160,800));im.paste(render,(83,338));d=ImageDraw.Draw(im)
# names/colors checklist independent of 3D overlap
legend=[('#c2854b',str(len(P['rail']['side_clearances']))+' fêmeas: '+' | '.join(f'{i} ponto'+('s' if i>1 else '')+' = '+fmt(v) for i,v in enumerate(P['rail']['side_clearances'],1))+' mm por lado'),('#4c9cb2','1 macho comum com puxador: 16 × 40 × 3,2 mm'),('#43a474','1 trava flexível substituível: 36 × 14 × 8 mm'),('#787fb0','1 receptor: 12,7 × 14 × 8 mm, já orientado para imprimir')]
y=1174
for c,s in legend:
 d.ellipse((80,y+4,103,y+27),fill=c);txt(120,y,s,26);y+=46
# Rail section nominal c=.35
R=P['rail'];c=R['side_clearances'][len(R['side_clearances'])//2];f=R['floor_height'];h=R['male_height'];wb=R['male_bottom_width'];wt=R['male_top_width'];k=(wb-wt)/(2*h);fw=R['female_width'];fh=R['female_height'];floorhalf=wb/2+(1+k)*c;tophalf=wt/2+(1-k)*c
sc=31;ox=1878;oy=644
def xy(x,z):return (ox+x*sc,oy-z*sc)
fem=[(-fw/2,0),(fw/2,0),(fw/2,fh),(tophalf,fh),(tophalf,f+h+2*c),(floorhalf,f),(-floorhalf,f),(-tophalf,f+h+2*c),(-tophalf,fh),(-fw/2,fh)]
d.polygon([xy(*p) for p in fem],fill='#d6af79',outline='#99622a',width=3)
mal=[(-wb/2,f+c),(wb/2,f+c),(wt/2,f+c+h),(-wt/2,f+c+h)]
d.polygon([xy(*p) for p in mal],fill='#5698aa',outline='#245b6c',width=3)
txt(1350,220,'Trilho: folga horizontal em cada lado',34,True)
txt(1350,267,'Seção ilustrada: variante de '+fmt(c)+' mm por lado',27,c='#486675')
arrow(xy(-13,-1.3),xy(13,-1.3));txt(1800,696,fmt(fw)+' mm',25,True)
# male foot dimension line through empty upper area
arrow(xy(-6,9.6),xy(6,9.6));txt(1800,309,fmt(wb)+' mm',23,True)
d.line([xy(5.3,5),(2290,515)],fill='#426b7e',width=3);txt(2138,433,'folga por lado',24,True);txt(2140,471,fmt(c)+' mm',26,True)
wrap(1360,752,'O mesmo macho entra nas três fêmeas. Escolha o menor valor que deslize com a mão e permita desmontar sem forçar.',1030,27)
# latch plan drawing from parameter shape, keeper translucent in plan
L=P['latch'];txt(1350,898,'Trava separada: trocar só a peça pequena',32,True)
ss=23;xx=1395;yy=1228
# root atx0 y0 lowerleft, profile clockwise in2d fromparams
b=L['beam_lower_y'];t=L['beam_thickness'];gl=L['grip_length'];gw=L['grip_width'];e=L['beam_end_x'];hb=L['hook_back_x'];ht=L['hook_tip_x'];hh=L['hook_height']
def lp(x,y):return (xx+x*ss,yy-y*ss)
pr=[(0,0),(gl,0),(gl,b),(e,b),(e,b+t),(ht,b+t),(hb,b+t+hh),(hb,b+t),(gl,b+t),(gl,gw),(0,gw)]
# draw smaller to allowlabel top? y14 ->906 overlapsheading. shift baseline1288
ss=20;xx=1405;yy=1270
prpoly=[lp(*p) for p in pr]
d.polygon(prpoly,fill='#6cb58b',outline='#2b7451',width=3)
# keeper cross-section rails outlined, opening withblade visible
x0=L['keeper_x_start'];x1=x0+L['keeper_length'];low=b-L['keeper_release_relief'];high=b+t+L['keeper_side_clearance']
for ya,yb in [(0,low),(high,gw)]:d.rectangle((lp(x0,yb),lp(x1,ya)),fill='#acacd0',outline='#565b8a',width=3)
d.line([lp(x0,low),lp(x0,high)],fill='#565b8a',width=2);d.line([lp(x1,low),lp(x1,high)],fill='#565b8a',width=2)
# motion and labels in freespaces right
arrow((2135,1070),(2235,1070),heads='end');txt(2140,1028,'Inserir',25,True)
arrow((2100,1100),(2100,1180),heads='end');txt(2140,1130,'Pressionar',25,True);txt(2140,1164,'para liberar',25)
wrap(1355,1300,'Língua de 1,2 mm, raiz arredondada e gancho de 0,8 mm. Alívio nominal de 0,45 mm; esquema em planta, sem simular a flexão.',1025,24)
# footerd.rounded
d.rounded_rectangle((45,1420,2455,1695),18,fill='#dfecef')
txt(78,1454,'O que foi verificado digitalmente',31,True)
wrap(78,1500,'6 sólidos válidos e 6 malhas fechadas. Retirada dos trilhos sem colisão. Retenção e passagem da trava verificadas geometricamente.',1030,28)
txt(1280,1454,'O que vocês testarão na impressora',31,True)
wrap(1280,1500,'Folga real, qualidade da língua, esforço de montagem e dez ciclos de abertura. Registrar material e perfil. O resultado não libera automaticamente a casca final.',1090,28)
txt(78,1638,'100% da escala • camada de 0,20 mm • bico de 0,4 mm • sem suportes nos STLs orientados',26,True)
im.save(ROOT/'guia-visual-cupons.png')
print(ROOT/'guia-visual-cupons.png')
