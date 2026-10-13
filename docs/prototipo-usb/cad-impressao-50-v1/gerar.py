"""ChargeGrid Mini 50% v1. Python + numpy + trimesh + manifold3d.
Meshes derived from user's STEP; edits in actual millimeters, not scaled hardware.
Source meshes are at 70%; only those are scaled 5/7. New joints retain their dimensions.
"""
from pathlib import Path
import json, math, hashlib, zipfile
import numpy as np
import trimesh
import manifold3d as md
ROOT=Path(__file__).resolve().parent
for folder in ['stl','montagem','verificacao']:(ROOT/folder).mkdir(exist_ok=True)
P={'scale':0.5,'reference_mesh_scale':0.7,'split_world_z':58.05,'split_gap':0.25,'bed_xy':[220,220], 'cassette_width':60,'cassette_height':112,'cassette_world_origin':[-30,90.2,34], 'physical_fit_tested':False,'power_module_selected':False}
(ROOT/'parametros.json').write_text(json.dumps(P,indent=2)+'\n')
def box(pos,size):return md.Manifold.cube(size).translate(pos)
def cyl(pos,r,h,r2=None):return md.Manifold.cylinder(h,r,r if r2 is None else r2,48).translate(pos)
def cy(pos,r,h):return md.Manifold.cylinder(h,r,r,48).rotate([-90,0,0]).translate(pos)
def union(items):return md.Manifold.batch_boolean(items,md.OpType.Add)
def subtract(a,items):return md.Manifold.batch_boolean([a]+items,md.OpType.Subtract)
def profile(points,depth):return md.Manifold.extrude(md.CrossSection([points]),depth)
def xzprofile(points,y0,depth):return profile(points,depth).rotate([90,0,0]).translate([0,y0+depth,0])
def mesh(s):
 mm=s.to_mesh64();return trimesh.Trimesh(np.array(mm.vert_properties[:,:3]),np.array(mm.tri_verts),process=False)
def load(i):
 d=np.load(ROOT/'referencia'/f'solid-{i}-clean.npz')
 return md.Manifold(md.Mesh64(d['vertices'],d['faces'].astype(np.uint64))).scale([5/7]*3)
def volume(s):return max(0,s.volume())
def largest(s,label):
 pieces=s.decompose();kept=max(pieces,key=lambda x:x.volume())
 discarded=sorted([p.volume() for p in pieces],reverse=True)[1:]
 assert sum(abs(v) for v in discarded)<10,(label,discarded)
 print(label,'shells',len(pieces),'discarded_abs_volume',round(sum(abs(v) for v in discarded),3),flush=True)
 removed.append({'operation':label,'discarded_small_shell_count':len(discarded),'discarded_signed_volumes_mm3':discarded,'discarded_absolute_volume_mm3':sum(abs(v) for v in discarded),'main_print_shell_preserved':True})
 return kept
removed=[];tests=[];parts=[];accessories=[]
rear,front,cap=[load(i) for i in [0,1,8]]
# Reclaim only the cassette envelope; keep outer skin and decorative shape.
rear=rear-box([-31,63,33],[62,30,115])
rear=largest(rear,'clear internal cassette volume')
# Rear bayonet collar shares original fastening locations with frame.
fix=[(-35.364,148.894,66.0),(35.364,148.894,66.0),(-31.791,26,66.0),(31.791,26,66.0)]
for x,z,yfront in fix:
 front=front+cy([x,yfront,z],6.5,79-yfront)
 rear=rear+cy([x,79.4,z],6.5,18.0)
 # Shaft + insertion slots through rear; counterpart has a recessed turning chamber.
 rear=subtract(rear,[cy([x,61,z],2.4,49),box([x-4.3,61,z-1.5],[8.6,49,3.0]),cy([x,97.2,z],6.1,14)])
 front=subtract(front,[cy([x,67.3,z],2.4,13),box([x-4.3,71.3,z-1.5],[8.6,9,3]),cy([x,67.3,z],4.6,4.0)])
# Five blind snap sockets under the cosmetic cover; exterior skin not drilled.
capfix=[(-19,139.763,42.0,46.25),(18.899,139.763,42.0,46.25),(-15.646,94.763,41.5,45.75),(15.646,94.763,41.5,45.75),(0,34.763,44.2,48.7)]
for x,z,start,end in capfix:
 cap=cap+cy([x,start,z],4.6,end-start)
 cap=subtract(cap,[cy([x,start+1.2,z],2.3,end-start+14),cy([x,start+1.2,z],2.65,1.5)])
 front=front+cy([x,end+.35,z],4.6,4.0)
 front=subtract(front,[cy([x,end-.2,z],2.3,5.0),cy([x,start-1,z],4.9,end-start+1.30),cy([x,end+4.30,z],3.7,12)])
# Reinforced transverse joins; separate butterfly keys register both halves.
seam=P['split_world_z']
key_outline=[(-5,-11),(-3,0),(-5,11),(5,11),(3,0),(5,-11)]
# Positive orientation required by manifold CrossSection.
key_outline=list(reversed(key_outline))
key=profile(key_outline,3.0)
for x in [-22,22]:
 rear=rear+box([x-7,90.7,seam-13],[14,6.2,26])
 pocket=xzprofile([(a*1.07+x,b*1.025+seam) for a,b in key_outline],90.4,3.8)
 rear=rear-pocket
 front=front+box([x-7,51.3,seam-13],[14,9.2,26])
 pocket=xzprofile([(a*1.07+x,b*1.025+seam) for a,b in key_outline],56.8,4.1)
 front=front-pocket
# Remove two redundant industrial cover hooks; new removable pins retain the cover.
cap=subtract(cap,[box([44.2,55,104.5],[3,5,4.4]),box([-47.2,55,104.5],[3,5,4.4])])
# Clear two original fine ribs in the cassette removal path, staying inside the roof.
rear=subtract(rear,[box([2.8,87,147],[1.6,6,5]),box([20.6,87,147],[1.7,6,5])])
# Four standoffs, mushroom keyhole retainers for a removable service cassette.
mounts=[(-25,44),(25,44),(-23,139),(23,139)]
for x,z in mounts:
 rear=rear+cy([x,90.65,z],4.2,6.0)
 rear=rear+cy([x,87.35,z],2.1,3.6)
 rear=rear+cy([x,85.6,z],3.5,1.75)
# Remove new socket interference against the native rear profile, with 0.25 mm clearance.
for x,z,yfront in fix:
 local=rear ^ box([x-8,60,z-8],[16,20,16])
 clear=union([local.translate(v) for v in [[0,0,0],[.25,0,0],[-.25,0,0],[0,.25,0],[0,-.25,0],[0,0,.25],[0,0,-.25]]])
 front=front-clear
# Rebuild only the lower cable exit platform, with an intact-plug opening and tie anchors.
rear=rear+box([-19,73,-38],[38,24,2.4])
rear=subtract(rear,[box([-10,78,-46],[20,14,17]),box([-3.5,60,-41],[7,19,8]),box([-17.5,82,-40],[3.2,6,7]),box([14.3,82,-40],[3.2,6,7]),box([-15.3,75.7,-35.3],[30.6,18.6,3])])
# Cosmetic bodies split along a horizontal joint for small print beds.
rear=largest(rear,'rear additions');front=largest(front,'frame additions');cap=largest(cap,'cover additions')
# Keep exact parts separate for assembly tests and visual exports.
assembly_base=[('rear',rear),('frame',front),('cap',cap)]
print('main geometries complete',flush=True)

def add(pid,s,color,qty=1,world=None,orientation='Base plana na mesa',note=''):
 assert str(s.status())=='Error.NoError' and s.num_tri()>0,(pid,s.status())
 pieces=s.decompose();assert sum(p.volume()>1e-8 for p in pieces)==1,(pid,[(p.volume()) for p in pieces])
 # Print shapes may already be oriented; translate to positive octant.
 bb=np.array(s.bounding_box());lo=bb[:3];s=s.translate(-lo)
 m=mesh(s)
 # Normalize at the precision that binary STL actually stores. Remove collapsed
 # edges before writing, so the delivered file does not rely on slicer repair.
 m.vertices=np.asarray(m.vertices,dtype=np.float32).astype(np.float64)
 m.merge_vertices(digits_vertex=5)
 m.update_faces(np.array([len(set(f))==3 for f in m.faces]));m.update_faces(m.unique_faces());m.remove_unreferenced_vertices()
 assert m.is_watertight and m.is_winding_consistent and m.volume>0,pid
 m.export(ROOT/'stl'/f'{pid}.stl')
 parts.append({'id':pid,'quantity':qty,'shape':s,'world':world,'color':color,'orientation':orientation,'note':note})
 return s
for label,s,color in [('01-traseira',rear,[55,63,69]),('03-quadro',front,[130,143,152])]:
 top=s.split_by_plane([0,0,1],seam+.125)[0]
 bottom=s.split_by_plane([0,0,1],seam-.125)[1]
 add(label+'-superior',top,color,world=top,orientation='Emenda horizontal plana sobre a mesa; suporte nas saliências internas.')
 add(label+'-inferior',bottom.rotate([180,0,0]),color,world=bottom,orientation='STL invertido: emenda horizontal na mesa; suporte nas saliências internas.')
# Cover: interior upwards, external skin below; supports required on the curved exterior.
add('05-tampa-frontal',cap.rotate([-90,0,0]),[235,237,237],world=cap,orientation='Face externa curva voltada para a mesa, cavidade para cima. Usar suporte orgânico externo.')
add('06-chave-emenda',key,[36,142,152],qty=4,orientation='Perfil de borboleta plano na mesa.',note='Alinha as emendas. Colar apenas as emendas estruturais da casca; manutenção pela frente removível.')
# Bayonet pin along local Z; lugs extend along X when inserting, turn 90 degrees to retain.
# Placed with head at the build plate for strength/reproducibility; supports beneath lug ends.
pin=union([cyl([0,0,0],5.8,2.5),cyl([0,0,2.3],2.1,28.5),box([-4,-1.2,29.3],[8,2.4,2.4])])
pin=pin-box([-4.5,-.75,-.1],[9,1.5,1.35])
# Coin slot is recessed in the exposed outer face of the head.
add('07-pino-quarto-volta',pin,[36,142,152],qty=4,orientation='Cabeça plana na mesa, haste vertical; suporte somente sob as duas abas finais.')
for k,(x,z,start,end) in enumerate(capfix):
 # Print two lengths to accommodate the lower original cap fixing geometry.
 H=end+6.05
 bead_center=start+1.95
 L=H-(start+1.3)
 snap=union([cyl([0,0,0],3.4,1.6),cyl([0,0,1.5],2.08,L-1.5),cyl([0,0,H-bead_center-.45],2.48,.9,1.95)])
 snap=snap-box([-.65,-3,3.5],[1.3,6,L+1])
 snap=snap-cy([0,-3,3.5],.65,6)
 # save installed position for both geometric checks and assembled preview
 sw=snap.rotate([90,0,0]).translate([x,H,z])
 tests.append({'test':f'cap_pin_{k}_cap_intersection_mm3','value':volume(sw^cap)})
 tests.append({'test':f'cap_pin_{k}_frame_intersection_mm3','value':volume(sw^front)})
 add(f'08-pino-tampa-{k+1}',snap,[36,142,152],world=sw,orientation='Cabeça na mesa; PETG. Ponta bipartida; sem suporte.',note='Trava de pressão substituível. Testar encaixe com cupom antes da tampa.')
# Cassette in local coordinates X width, Y height, Z into the cavity towards the front.
base=box([0,0,0],[60,112,2.4])
base=base-profile([(0,100),(6,113),(0,113)],4).translate([0,0,-.5])
base=base-profile([(60,100),(60,113),(54,113)],4).translate([0,0,-.5])
for x,v in [(5,10),(55,10),(7,105),(53,105)]:
 base=subtract(base,[cyl([x,v-5,-1],3.85,4.5),cyl([x,v,-1],2.4,4.5),box([x-2.4,v-5,-1],[4.8,5,4.5])])
# Ventilation/cable openings, not under the retaining edge rails.
for v in [25,38,67,81,94]:
 base=base-box([23,v,-1],[14,5,4.5])
# Carriers use short dovetail rails. Insert from +Y and slide down to the end stops.
rail=box([-5,0,2.35],[10,12,3.2])
cavity=xzprofile([(-3.4,3.15),(3.4,3.15),(2.3,5.55),(2.3,6.2),(-2.3,6.2),(-2.3,5.55)],1.5,12)
rail=rail-cavity
for v in [8,54]:
 for x in [16,44]:base=base+rail.translate([x,v,0])
# A small removable pin blocks each carrier's upward extraction until pulled.
for v in [8,54]:base=base+cyl([30,v+19,2.3],3.6,3.25)
for v in [8,54]:base=base-cyl([30,v+19,-.1],1.8,8)
world_matrix=[[1,0,0,-30],[0,0,-1,90.2],[0,1,0,34]]
baseworld=base.transform(world_matrix)
add('09-bandeja-removivel',base,[45,122,136],world=baseworld,orientation='Costas planas na mesa, trilhos para cima; sem suporte nos trilhos.')
for pid,width,length,v in [('10-berco-potencia',54,35,8),('11-berco-esp32',42,64,54)]:
 x0=30-width/2
 carrier=box([x0,v,5.95],[width,length,2.0])
 male=xzprofile([(-3.0,3.5),(3.0,3.5),(1.95,5.2),(-1.95,5.2)],1.85,9.8)
 # Stem joins male to underside of the carrier.
 male=male+box([-1.9,1.85,5.15],[3.8,9.8,1.0])
 for x in [16,44]:carrier=carrier+male.translate([x,v,0])
 # A retaining boss aperture meets the base pin; open bore only, not an electrical fixing.
 carrier=carrier-cyl([30,v+19,5.7],1.95,3)
 # Cable ties and movable spacers; no board-specific drilling on shell or carrier.
 for x in [x0+7,x0+width-7]:
  for yy in [v+5,v+length-13]:carrier=carrier-box([x-1.9,yy,5.7],[3.8,8,3])
 # extra tie slots across width, away from the rail anchors
 carrier=carrier-box([26,v+length-5,5.7],[8,2.8,3])
 cw=carrier.transform(world_matrix)
 tests.append({'test':pid+'_base_intersection_mm3','value':volume(cw^baseworld)})
 tests.append({'test':pid+'_rear_intersection_mm3','value':volume(cw^rear)})
 tests.append({'test':pid+'_frame_intersection_mm3','value':volume(cw^front)})
 add(pid,carrier.rotate([180,0,0]),[207,144,63],world=cw,orientation='STL com face superior do berço na mesa e machos para cima.',note='Suporte genérico. Fixar placa com cintas sobre espaçadores, sem pressionar componentes.')
# Actual short rail/male samples, matching the geometry used by the carriers.
rail_coupon=base ^ box([10,54,-1],[12,12,10])
male_coupon=carrier ^ box([10,54,-1],[12,12,11])
add('20-cupom-trilho-berco',rail_coupon,[100,110,120])
add('21-cupom-macho-berco',male_coupon.rotate([180,0,0]),[207,144,63])
# Carrier retaining pin: split snap nose through 3.6 mm base bore, replaceable.
clip=union([cyl([0,0,0],3.5,1.4),cyl([0,0,1.3],1.55,9.7),cyl([0,0,9.8],1.92,1.2,1.4)])
clip=clip-box([-.45,-3,3.5],[.9,6,8.5])
add('12-pino-trava-berco',clip,[35,145,154],qty=2)
# Cassette keyhole blocking plugs retain vertical position (plate slides 5 mm to release).
stop=union([cyl([0,0,0],4.7,1.2),cyl([0,0,1.1],3.6,4.0),cyl([0,0,4.2],3.95,.9,3.4)])
stop=stop-box([-.6,-5,2.2],[1.2,10,4])
stop=stop-box([-6,.3,-.1],[12,6,6])
add('13-trava-bandeja',stop,[35,145,154],qty=2)
for x in [5,55]:
 w=stop.rotate([0,180,0]).translate([x,5,3.8]).transform(world_matrix)
 accessories.append(('trava-bandeja-'+str(x),w,[35,145,154]))
 tests.append({'test':f'cassette_stop_{x}_base_intersection_mm3','value':volume(w^baseworld)})
 tests.append({'test':f'cassette_stop_{x}_rear_intersection_mm3','value':volume(w^rear)})
for v in [8,54]:
 w=clip.rotate([0,180,0]).translate([30,v+19,9.5]).transform(world_matrix)
 accessories.append(('trava-berco-'+str(v),w,[35,145,154]))
 tests.append({'test':f'carrier_pin_{v}_base_intersection_mm3','value':volume(w^baseworld)})

for h in [3,5]:
 spacer=box([0,0,0],[8,6,h])
 spacer=spacer+box([2.5,1.5,-1.5],[3,3,1.6])
 add(f'14-espacador-{h}mm',spacer.rotate([180,0,0]),[207,144,63],qty=4,note='Escolher altura e pontos de apoio após conferir o verso da placa; usar cintas para retenção.')
# General cable saddle / service accessories, size variants for intact commercial cables.
for dia in [4,5,6]:
 saddle=box([-9,-6,0],[18,12,5])
 hole=md.Manifold.cylinder(20,dia/2,dia/2,48).rotate([90,0,0]).translate([0,10,5])
 saddle=saddle-hole
 saddle=subtract(saddle,[box([-7,-1.6,-1],[3,3.2,7]),box([4,-1.6,-1],[3,3.2,7])])
 add(f'15-prensa-cabo-{dia}mm-meia',saddle,[35,145,154],qty=2,note='Duas metades em torno do cabo, presas por cintas. Selecionar diâmetro sem esmagar a capa.')
# Test coupons replicate one bayonet socket and the cap snap profile before larger prints.
socket=box([-8,-8,0],[16,16,30])
socket=subtract(socket,[cyl([0,0,-1],2.4,33),box([-4.3,-1.5,4.5],[8.6,3,27]),cyl([0,0,0.5],4.6,4.0)])
add('16-cupom-quarto-volta',socket.rotate([0,90,0]),[100,110,120],orientation='Furo horizontal, base retangular na mesa; suporte local somente se necessário.',note='Ensaiar giro e retenção com pino 07 antes das peças principais.')
# Cap socket and stack coupon; use pin 08-1.
cap_coupon=box([-8,-8,0],[16,16,4.25])
cap_coupon=subtract(cap_coupon,[cyl([0,0,1.2],2.3,5),cyl([0,0,1.2],2.65,1.5)])
plate_coupon=box([-8,-8,0],[16,16,4.35])-cyl([0,0,-1],2.3,7)
add('17-cupom-bucha-tampa',cap_coupon,[100,110,120],note='Furo cego para teste do pino 08-1; usar junto da placa 18.')
add('18-cupom-placa-tampa',plate_coupon,[100,110,120],note='Sobrepor na bucha 17 e inserir pino 08-1; não colar os cupons.')
# Replaceable split cable inserts: both halves assemble around complete cables.
for tag,holes in [('4mm',[(0,4.5)]),('5mm',[(0,5.5)]),('6mm',[(0,6.5)]),('duplo-5mm',[(-4,5.5),(4,5.5)])]:
 gland=union([box([-9.7,-6.7,0],[19.4,13.4,5.6]),box([-15,-9,3.6],[30,18,2.0])])
 gland=subtract(gland,[cyl([x,0,-1],dia/2,8) for x,dia in holes]+[box([-13.8,-3,-1],[2.8,6,8]),box([11,-3,-1],[2.8,6,8])])
 # 0.15 mm central assembly gap; cable channels span the joint in both variants.
 half1=gland.split_by_plane([0,1,0],.075)[0]
 half2=gland.split_by_plane([0,1,0],-.075)[1]
 for suffix,half in [('a',half1),('b',half2)]:
  world=half.translate([0,85,-38.85]) if tag=='duplo-5mm' else None
  if world is not None:tests.append({'test':'cable_insert_'+suffix+'_rear_intersection_mm3','value':volume(world^rear)})
  add('19-inserto-'+tag+'-'+suffix,half.rotate([180,0,0]),[35,145,154],world=world,orientation='Flange maior na mesa. Selecionar um único par a/b.',note='Duas metades sobre cabo intacto; prender pelas ranhuras com cintas. Não cortar ou emendar o cabo USB-C.')
# Confirm empty equipment reserve only; not the dimensions of an approved purchased module.
for label,pos,size in [('ESP32_reserve',[14,57,12.95],[32,58,8]),('power_reserve',[6,10,10.95],[48,29,15])]:
 env=box(pos,size).transform(world_matrix)
 for body,b in [('rear',rear),('frame',front),('cap',cap)]:tests.append({'test':label+'_'+body+'_intersection_mm3','value':volume(env^b)})
# Rigid assembly paths: captive cover can be removed straight forward after releasing its pins.
for distance in [0.5,1,2,3,5,8,25]:
 tests.append({'test':f'cover_removal_{distance}mm_frame_intersection_mm3','value':volume(cap.translate([0,-distance,0])^front)})
for d in [1,3,8,25]:tests.append({'test':f'front_removal_{d}mm_rear_intersection_mm3','value':volume(front.translate([0,-d,0])^rear)})
# The cassette slides up 5 mm off its mushroom studs, then withdraws forward.
for dz in [0,1,3,5]:tests.append({'test':f'cassette_slide_{dz}mm_rear_intersection_mm3','value':volume(baseworld.translate([0,0,dz])^rear)})
for dy in [2,5,15,35]:tests.append({'test':f'cassette_withdraw_{dy}mm_rear_intersection_mm3','value':volume(baseworld.translate([0,-dy,5])^rear)})
# Build reference assembly: visible bodies plus cassette, carriers, pins and join keys.
scene=trimesh.Scene();manifest=[]
for name,w,color in accessories:
 wm=mesh(w);wm.visual.face_colors=color+[255];scene.add_geometry(wm,node_name=name,geom_name=name)
for p in parts:
 s=p['shape'];m=mesh(s)
 # Verify exported float32 STL, not only the float64 in-memory manifold.
 loaded=trimesh.load(ROOT/'stl'/f"{p['id']}.stl",force='mesh')
 assert loaded.is_watertight and loaded.is_winding_consistent and loaded.volume>0,p['id']
 check={'watertight':bool(loaded.is_watertight),'winding_consistent':bool(loaded.is_winding_consistent),'positive_volume':bool(loaded.volume>0),'connected_components':len(loaded.split(only_watertight=False))}
 print('verify',p['id'],len(m.faces),check,flush=True)
 manifest.append({'id':p['id'],'quantity':p['quantity'],'size_xyz_mm':m.extents.tolist(),'volume_mm3':float(m.volume),'file':'stl/'+p['id']+'.stl','orientation':p['orientation'],'note':p['note'],'stl_readback':check})
 if p['world'] is not None:
  wm=mesh(p['world']);wm.visual.face_colors=p['color']+[255];scene.add_geometry(wm,node_name=p['id'],geom_name=p['id'])
# Add quarter-turn pins in LOCKED position to the assembly; axis Z maps to -Y.
for k,(x,z,yf) in enumerate(fix):
 # head base at Y100; locking lug Y69.6..72 before later length validation.
 w=pin.rotate([0,0,90]).rotate([90,0,0]).translate([x,100,z])
 pm=mesh(w);pm.visual.face_colors=[36,142,152,255];scene.add_geometry(pm,node_name=f'pino-casca-{k}',geom_name=f'pino-casca-{k}')
 tests.append({'test':f'bayonet_pin_{k}_frame_intersection_mm3','value':volume(w^front)})
 tests.append({'test':f'bayonet_pin_{k}_rear_intersection_mm3','value':volume(w^rear)})
 for angle in [0,30,60,90]:
  pos=pin.rotate([0,0,angle]).rotate([90,0,0]).translate([x,100,z])
  tests.append({'test':f'bayonet_{k}_turn_{angle}_intersection_mm3','value':volume(pos^(front+rear))})
 unlocked=pin.rotate([90,0,0]).translate([x,100,z])
 for d in [1,5,15,35]:tests.append({'test':f'bayonet_{k}_unlocked_withdraw_{d}_intersection_mm3','value':volume(unlocked.translate([0,d,0])^(front+rear))})
 tests.append({'test':f'bayonet_{k}_locked_pull_1mm_EXPECT_POSITIVE','value':volume(w.translate([0,1,0])^front)})

for x in [-22,22]:
 for y in [90.8,57.2]:
  w=xzprofile([(a+x,b+seam) for a,b in key_outline],y,3.0)
  km=mesh(w);km.visual.face_colors=[36,142,152,255];scene.add_geometry(km,node_name=f'chave-{x}-{y}',geom_name=f'chave-{x}-{y}')
for label,a,b in [('front_rear',front,rear),('cap_frame',cap,front),('cassette_rear',baseworld,rear),('cassette_frame',baseworld,front)]:tests.append({'test':label+'_intersection_mm3','value':volume(a^b)})
scene.export(ROOT/'montagem'/'ChargeGrid-50-montado.glb')
# Simple 3MF preserving units and per-object names, without printer-specific settings.
def export3mf(path,objects):
 import xml.etree.ElementTree as ET
 ns='http://schemas.microsoft.com/3dmanufacturing/core/2015/02';ET.register_namespace('',ns)
 model=ET.Element('{'+ns+'}model',unit='millimeter');resources=ET.SubElement(model,'resources');build=ET.SubElement(model,'build')
 for k,(name,m) in enumerate(objects,1):
  ob=ET.SubElement(resources,'object',id=str(k),type='model',name=name);me=ET.SubElement(ob,'mesh');vs=ET.SubElement(me,'vertices');ts=ET.SubElement(me,'triangles')
  for x,y,z in m.vertices:ET.SubElement(vs,'vertex',x=f'{x:.7f}',y=f'{y:.7f}',z=f'{z:.7f}')
  for a,b,c in m.faces:ET.SubElement(ts,'triangle',v1=str(a),v2=str(b),v3=str(c))
  ET.SubElement(build,'item',objectid=str(k))
 with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
  z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
  z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
  z.writestr('3D/3dmodel.model',ET.tostring(model,encoding='utf-8',xml_declaration=True))
export3mf(ROOT/'montagem'/'ChargeGrid-50-MONTAGEM-nao-fatiar.3mf',[(name,g) for name,g in scene.geometry.items()])
report={'version':'50-v1','source_STEP_sha256':'dad2a7a04d5e5ee3a4910721e62fedfcc08763ce41629c49d8e0bb8d1eab153d','units':'millimeters','scale':0.5,'physical_test':False,'parts':manifest,'geometric_tests':tests,'detached_geometry_removed':removed}
(ROOT/'verificacao'/'relatorio.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
assert all(all(p['stl_readback'][k] for k in ['watertight','winding_consistent','positive_volume']) for p in manifest)
assert all(p['size_xyz_mm'][0]<200 and p['size_xyz_mm'][1]<200 for p in manifest)
for t in tests:
 if 'EXPECT_POSITIVE' in t['test']:assert t['value']>0.1,t
 else:assert t['value']<1e-4,t
print('DONE',len(parts),'STL variants;',len(tests),'geometric checks passed',flush=True)
