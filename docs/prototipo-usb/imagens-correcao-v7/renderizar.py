"""Actual CAD comparison, deterministic rasterization; no generated concept geometry."""
from pathlib import Path
import xml.etree.ElementTree as ET,zipfile,json
import numpy as np,trimesh,manifold3d as md
from PIL import Image,ImageDraw
ROOT=Path(__file__).resolve().parent;BASE=ROOT.parent
ref=BASE/'cad-impressao-50-v1/renderizar.py'
ns={'__file__':str(ref)};exec(ref.read_text().split('scene=trimesh.load',1)[0],ns)
lib,font=ns['lib'],ns['font']
BG='#f0f4f7';INK='#183746';GRAY=[137,153,166];ORANGE=[237,157,48];RED=[232,62,69];GREEN=[43,157,134];BLUE=[54,153,196]
def load(path):
 with zipfile.ZipFile(path) as z:t=ET.fromstring(z.read('3D/3dmodel.model'))
 objects={}
 for o in t.findall('.//{*}object'):
  v=[[float(a.attrib[k]) for k in ['x','y','z']] for a in o.findall('.//{*}vertex')];f=[[int(a.attrib[k]) for k in ['v1','v2','v3']] for a in o.findall('.//{*}triangle')];objects[o.attrib['name']]=trimesh.Trimesh(v,f,process=True)
 return objects
def solid(m):return md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
def mesh(s):
 t=s.to_mesh64();return trimesh.Trimesh(t.vert_properties[:,:3],t.tri_verts,process=False)
def box(pos,size):return md.Manifold.cube(size).translate(pos)
def render(items,direction,size,reference=None):
 W,H=size;z=np.array(direction,float);z/=np.linalg.norm(z);x=np.cross([0,0,1],z);x/=np.linalg.norm(x);y=np.cross(z,x);rot=np.array([x,-y,z]).T
 triangles=np.concatenate([m.triangles for m,c in items]);p=triangles@rot
 colors=np.concatenate([np.tile(c,(len(m.faces),1)) for m,c in items])
 norm=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0]);norm/=np.maximum(np.linalg.norm(norm,axis=1)[:,None],1e-12);norm*=np.where(norm[:,2]<0,-1,1)[:,None]
 light=np.array([-.4,-.6,.8]);light/=np.linalg.norm(light);shade=.45+.55*np.maximum(0,norm@light);rgb=np.uint8(np.clip(colors*shade[:,None],0,255))
 bound=p.reshape(-1,3) if reference is None else np.asarray(reference).reshape(-1,3)@rot
 lo,hi=bound[:,:2].min(axis=0),bound[:,:2].max(axis=0);scale=min((W-65)/(hi[0]-lo[0]),(H-65)/(hi[1]-lo[1]));offset=np.array([W/2,H/2])-(lo+hi)/2*scale
 p[:,:,:2]=p[:,:,:2]*scale+offset
 img=np.full((H,W,3),[240,244,247],np.uint8);zb=np.full((H,W),-1e20,np.float32)
 lib.raster(len(p),np.ascontiguousarray(p,dtype=np.float32),np.ascontiguousarray(rgb),W,H,img,zb)
 def project(pt):return (np.asarray(pt)@rot)[:2]*scale+offset
 return Image.fromarray(img),project
old=load(BASE/'ender3-pla-oficial-v6/montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf')
new=load(BASE/'ender3-pla-oficial-v7/montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf')
top=new['01-traseira-superior'];bottom=new['01-traseira-inferior'];oldbottom=old['01-traseira-inferior'];oldbody=solid(oldbottom);newbody=solid(bottom);removed=oldbody-newbody
printpart=trimesh.load(BASE/'ender3-pla-oficial-v7/modelos-fatiados/02TRSUP.stl')
# Image 1: actual current file and its location in the two-piece rear shell.
im=Image.new('RGB',(1800,1050),BG);d=ImageDraw.Draw(im)
d.text((45,28),'Esta é a peça 02 que você está imprimindo',font=font(38),fill=INK)
d.text((45,86),'02TRSUP.gcode • metade superior da traseira • sem alteração nesta correção',font=font(25),fill='#416072')
d.text((65,158),'POSIÇÃO NA TRASEIRA',font=font(24),fill=INK)
d.text((955,158),'PEÇA 02 SOZINHA',font=font(24),fill=INK)
scene=[(top,ORANGE),(bottom,GRAY)];picture,project=render(scene,(.25,-1,.20),(830,740));im.paste(picture,(30,200))
# Label the two genuine model parts with leader lines.
d=ImageDraw.Draw(im)
for label,point,xy,col in [('02',[-28,93,125],(60,265),'#bc6b0a'),('03',[-28,93,6],(60,785),'#617583')]:
 q=project(point)+[30,200];d.rounded_rectangle((xy[0],xy[1],xy[0]+66,xy[1]+47),radius=9,fill=col);d.text((xy[0]+13,xy[1]+8),label,font=font(27),fill='white');d.line((xy[0]+66,xy[1]+23,q[0],q[1]),fill=col,width=3)
picture,_=render([(printpart,ORANGE)],(.6,-1,.8),(870,640));im.paste(picture,(895,240))
d=ImageDraw.Draw(im);d.text((960,892),'Na orientação usada no fatiamento.',font=font(24),fill='#416072');d.text((960,930),'Suportes e brim ocultos nesta vista.',font=font(24),fill='#416072')
d.text((45,992),'Laranja: peça 02 atual. Cinza: peça 03, que será impressa depois. Cores apenas para identificação.',font=font(24),fill=INK)
im.save(ROOT/'01-peca-02-em-impressao.png')
# Image 2: full lower shell with exact removed material highlighted, plus section at a key.
# The section is from actual assembly meshes at x=-25 mm, cut only for illustration.
clip=box([-25,83,43],[12,15,17]);key=solid(new['chave--22-90.8'])
before_body=(oldbody-key)^clip;before_key=(key-oldbody)^clip;collision=(oldbody^key)^clip
assert collision.volume()>0
section_before=[(mesh(before_body),GRAY),(mesh(before_key),BLUE),(mesh(collision),RED)]
section_after=[(mesh(newbody^clip),GRAY),(mesh(key^clip),BLUE)]
ref_section=box([-25,83,43],[12,15,17]);ref_vertices=mesh(ref_section).vertices
im=Image.new('RGB',(2000,1570),BG);d=ImageDraw.Draw(im)
d.text((45,25),'Peça 03 — o que foi corrigido',font=font(40),fill=INK)
d.text((45,84),'Mesma traseira inferior e mesmas chaves. Alteração somente nos dois alojamentos internos.',font=font(26),fill='#416072')
d.text((65,150),'ANTES • 03TRINF.gcode',font=font(29),fill='#b03640')
d.text((1055,150),'DEPOIS • 03TRINF7.gcode',font=font(29),fill='#147864')
full_ref=oldbottom.vertices
for i,items in enumerate([[(bottom,GRAY),(mesh(removed),RED)],[(bottom,GRAY)]]):
 pic,project=render(items,(.08,-1,.28),(920,570),reference=full_ref);ox=35+i*1000;oy=195;im.paste(pic,(ox,oy));draw=ImageDraw.Draw(im)
 for x in [-25,25]:
  p=project([x,89,47.6])+[ox,oy];color='#ce3c47' if i==0 else '#178e77';draw.ellipse((p[0]-33,p[1]-33,p[0]+33,p[1]+33),outline=color,width=4)
 draw.text((ox+45,747),'Dois pontos interferiam com as chaves.' if i==0 else 'Os mesmos dois pontos agora estão livres.',font=font(24),fill=INK)
d=ImageDraw.Draw(im);d.line((45,805,1955,805),fill='#bdccd4',width=2)
d.text((45,830),'AMPLIAÇÃO EM CORTE DE UM DOS ENCAIXES',font=font(25),fill=INK)
d.text((45,870),'Corte virtual para enxergar dentro: a peça impressa continua inteira. O outro lado é simétrico.',font=font(23),fill='#416072')
for i,items in enumerate([section_before,section_after]):
 pic,proj=render(items,(-1,-.02,.025),(900,460),reference=ref_vertices);ox=45+i*1000;oy=920;im.paste(pic,(ox,oy));draw=ImageDraw.Draw(im)
 p=proj([-25,92,47.6])+[ox,oy]
 draw.ellipse((p[0]-48,p[1]-35,p[0]+48,p[1]+35),outline='#ce3c47' if i==0 else '#178e77',width=4)
 draw.text((ox+20,1394),'Vermelho: apoio ocupando o espaço da chave.' if i==0 else 'Folga liberada para a chave assentar.',font=font(24),fill=INK)
d=ImageDraw.Draw(im)
for x,color,label in [(55,GRAY,'Carcaça / apoio'),(610,BLUE,'Chave já impressa'),(1160,RED,'Interferência anterior')]:
 d.rectangle((x,1460,x+28,1488),fill=tuple(color));d.text((x+43,1457),label,font=font(24),fill=INK)
d.text((45,1518),'Imagens calculadas dos arquivos 3D reais. O formato externo e a peça 02 foram preservados.',font=font(23),fill='#416072')
im.save(ROOT/'02-peca-03-antes-depois.png')
(ROOT/'fontes.json').write_text(json.dumps({'current_file':'ender3-pla-oficial-v7/modelos-fatiados/02TRSUP.stl','before_assembly':'ender3-pla-oficial-v6/montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf','after_assembly':'ender3-pla-oficial-v7/montagem/ChargeGrid-50-OFICIAL-nao-fatiar.3mf','section_x_mm':-25,'red_material_in_full_view':'old body minus new body','red_material_in_section':'old body intersecting assembled join key','section_is_illustration_only':True,'removed_volume_mm3':removed.volume()},indent=2)+'\n')
print('Duas imagens renderizadas dos modelos reais.',flush=True)
