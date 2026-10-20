"""Audit textual Marlin G-code and draw actual extrusion paths. No printer is operated."""
from pathlib import Path
import re,json,math,csv
import numpy as np
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parent
font=lambda n:ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',n)
report=[]
for p in sorted((ROOT/'gcode').glob('*.gcode')):
 xyz=np.zeros(3);elo=0.;relative_e=True;absolute_xyz=True;feed=0;feature='Custom';layer=0.;temps=[];beds=[];layers=set();cmds=set();segments=[];features={};bad=[];moves=[];peakflow=0.;firstextrude=False
 text=p.read_text(encoding='ascii')
 for lineno,line in enumerate(text.splitlines(),1):
  if line.startswith(';TYPE:'):feature=line[6:].strip()
  if line.startswith(';Z:'):layer=float(line[3:]);layers.add(layer)
  clean=line.split(';')[0].strip()
  if not clean:continue
  cmd=clean.split()[0];cmds.add(cmd)
  vals={a:float(b) for a,b in re.findall(r'([XYZEFST])\s*(-?\d*\.?\d+)',clean[len(cmd):])}
  if cmd=='G90':absolute_xyz=True
  elif cmd=='G91':absolute_xyz=False
  elif cmd=='M83':relative_e=True
  elif cmd=='M82':relative_e=False
  elif cmd=='G28':xyz[:]=0
  elif cmd=='G92':
   for i,a in enumerate('XYZ'):
    if a in vals:xyz[i]=vals[a]
   if 'E' in vals:elo=vals['E']
  elif cmd in ('M104','M109'):
   if 'S' in vals:temps.append(vals['S'])
  elif cmd in ('M140','M190'):
   if 'S' in vals:beds.append(vals['S'])
  elif cmd in ('G0','G1'):
   prior=xyz.copy()
   for i,a in enumerate('XYZ'):
    if a in vals:xyz[i]=vals[a] if absolute_xyz else xyz[i]+vals[a]
   if 'F' in vals:feed=vals['F']
   de=vals.get('E',0) if relative_e else vals.get('E',elo)-elo
   if 'E' in vals:elo=elo+de if relative_e else vals['E']
   if (xyz<-.01).any() or xyz[0]>220.01 or xyz[1]>220.01 or xyz[2]>250.01:bad.append({'line':lineno,'xyz':xyz.tolist()})
   moves.append(xyz.copy());length=np.linalg.norm(xyz-prior)
   if de>0 and length>1e-5:
    assert temps and temps[-1]>=190,(p,lineno,'cold extrusion')
    if feature!='Custom':
     features[feature]=features.get(feature,0)+de
     segments.append([*prior,*xyz,layer,1 if 'Support' in feature else (2 if 'Skirt' in feature else 0)])
     flow=de*math.pi*(1.75/2)**2*feed/60/length;peakflow=max(peakflow,flow)
 assert not bad,(p,bad[:5])
 assert 'G28' in cmds and 'M83' in cmds
 assert not (cmds & {'G29','M420','M500','M502','G2','G3','M600'}),(p,cmds)
 assert temps[-1]==0 and beds[-1]==0 and 'M84' in cmds and 'M107' in cmds
 assert max(temps)<=210 and max(beds)<=60
 assert len(segments)>100 and len(layers)>2
 g=float(re.search(r'; filament used \[g\] = ([\d.]+)',text)[1]);time_string=re.search(r'; estimated printing time \(normal mode\) = (.*)',text)[1]
 sec=sum(float(v)*{'d':86400,'h':3600,'m':60,'s':1}[u] for v,u in re.findall(r'(\d+)([dhms])',time_string))
 a=np.array(segments,dtype=np.float32);del segments
 support_g=sum(v for k,v in features.items() if 'Support' in k)*math.pi*(1.75/2)**2*1.24/1000
 mov=np.array(moves);del moves
 # Motion and extrusion limits include supports and brim, not just the source STL.
 result={'file':p.name,'grams_slicer':g,'time_slicer':time_string,'seconds_slicer':sec,'layers':len(layers),'extrusion_segments':len(a),'xyz_motion_min_mm':mov.min(axis=0).tolist(),'xyz_motion_max_mm':mov.max(axis=0).tolist(),'support_grams_from_paths':round(support_g,2),'max_nominal_flow_mm3_s':round(peakflow,3),'nozzle_max_c':max(temps),'bed_max_c':max(beds),'bounds_pass':True,'home_and_shutdown_pass':True,'no_abl_or_eeprom_commands':True}
 assert peakflow<6.15,(p,peakflow)
 report.append(result)
 im=Image.new('RGB',(1800,720),'#f1f5f6');d=ImageDraw.Draw(im);d.text((24,16),f'{p.name} | {g:.1f} g | {time_string}',font=font(30),fill='#17333d')
 palette={0:'#d28a2b',1:'#218d9b',2:'#89949b'}
 # First layer and mid layer paths, no sampling.
 mid=sorted(layers)[len(layers)//2]
 for panel,z,title in [(0,min(layers),'Primeira camada'),(1,mid,f'Camada intermediária Z={mid:.2f} mm')]:
  ox=20+panel*590;oy=100;d.text((ox,70),title,font=font(23),fill='#17333d')
  d.rectangle((ox,oy,ox+550,oy+550),fill='white',outline='#809aa2',width=2)
  for row in a[np.abs(a[:,6]-z)<1e-4]:
   x1,y1,_,x2,y2,_,_,kind=row;d.line((ox+x1*2.5,oy+(220-y1)*2.5,ox+x2*2.5,oy+(220-y2)*2.5),fill=palette[int(kind)],width=1)
 # Actual paths projected isometrically. Sample only the overview; section views above are exact paths.
 subset=a[::max(1,len(a)//130000)]
 points=np.stack([subset[:,:3],subset[:,3:6]],axis=1);direction=np.array([.7,-1,.8]);direction/=np.linalg.norm(direction);x=np.cross([0,0,1],direction);x/=np.linalg.norm(x);y=np.cross(direction,x);rot=np.array([x,-y,direction]).T;proj=points@rot
 lo=proj[:,:,:2].min(axis=(0,1));hi=proj[:,:,:2].max(axis=(0,1));scale=min(530/(hi-lo));proj[:,:,:2]=(proj[:,:,:2]-(hi+lo)/2)*scale+[1490,375]
 d.text((1200,70),'Trajetos 3D — vista resumida',font=font(23),fill='#17333d')
 for idx in np.argsort(proj[:,:,2].mean(axis=1)):
  q=proj[idx];d.line((q[0,0],q[0,1],q[1,0],q[1,1]),fill=palette[int(subset[idx,7])],width=1)
 d.text((24,675),'Laranja: peça | Azul: suporte/interface | Cinza: brim. Estimativas do fatiador, sem ensaio físico.',font=font(22),fill='#31515e')
 im.save(ROOT/'previas'/f'{p.stem}.png')
 print(p.name,g,time_string,'support',round(support_g,1),'g','flow',round(peakflow,2),flush=True)
(ROOT/'verificacao/auditoria-gcode.json').write_text(json.dumps({'slicer':'PrusaSlicer 2.9.6','physical_print_tested':False,'files':report,'total_grams':sum(r['grams_slicer'] for r in report),'total_seconds':sum(r['seconds_slicer'] for r in report)},indent=2)+'\n')
with (ROOT/'verificacao/estimativas.csv').open('w') as f:
 w=csv.writer(f);w.writerow(['arquivo','gramas','tempo_estimado','suportes_g'])
 for r in report:w.writerow([r['file'],r['grams_slicer'],r['time_slicer'],r['support_grams_from_paths']])
