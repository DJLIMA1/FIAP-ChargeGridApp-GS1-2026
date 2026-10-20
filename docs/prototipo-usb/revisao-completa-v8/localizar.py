from pathlib import Path
src=Path(__file__).parent/'auditar.py';exec(src.read_text().split('pairs=[];',1)[0])
groups=['09-bandeja-removivel','10-berco-potencia','11-berco-esp32','trava-berco-8','trava-berco-54']
for d in [1,2,3,4,5]:
 for name in groups:
  for ob in ['01-traseira-superior','01-traseira-inferior']:
   x=solids[name].translate([0,0,d])^solids[ob]
   if x.volume()>.001:print('tray',d,name,ob,x.volume(),x.bounding_box(),flush=True)
# Test carrier removal clearance at 10.5 mm, instead of the arbitrary initial 14 mm sweep.
for n in ['10-berco-potencia','11-berco-esp32']:
 other='11-berco-esp32' if n.startswith('10') else '10-berco-potencia';ob=solids['09-bandeja-removivel']+solids[other]
 print('carrier',n,'slide10.5',max(overlap(solids[n].translate([0,0,float(d)]),ob) for d in np.linspace(0,10.5,43)),'pull',max(overlap(solids[n].translate([0,-float(d),10.5]),ob) for d in np.linspace(0,15,31)),flush=True)
