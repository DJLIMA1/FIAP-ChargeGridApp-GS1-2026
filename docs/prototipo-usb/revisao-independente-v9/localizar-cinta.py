from pathlib import Path
exec((Path(__file__).parent/'auditar.py').read_text().split('pairs=[];',1)[0])
for side in ['esquerda','direita']:
 tie=solid(trimesh.load(ROOT/(f'cinta-{side}-envelope.stl')))
 for n,s in solids.items():
  for dz in [0,4.25,5]:
   c=tie.translate([0,0,dz])^s
   if c.volume()>.001:print(side,n,dz,c.volume(),c.bounding_box())
