from pathlib import Path
exec((Path(__file__).parent/'auditar.py').read_text().split('pairs=[];',1)[0])
rows=[]
for side,x in [('esquerda',5),('direita',55)]:
 tie=solid(trimesh.load(ROOT/(f'cinta-{side}-envelope.stl')))
 for n,s in solids.items():
  v=overlap(tie,s);rows.append({'tie':side,'part':n,'overlap_mm3':v});assert v<.001,(side,n,v)
 stop=solids[f'trava-bandeja-{x}'];v=overlap(stop.translate([0,-.5,0]),tie);assert v>.001,(side,'retention',v)
 rows.append({'tie':side,'retains_rigid_stop_pull_0_5_mm':v})
 # Ties travel with tray; they clear the rear during installation before stops are inserted.
 rear=union(s for n,s in solids.items() if n.startswith('01-traseira'))
 for dz in np.linspace(0,5,21):
  v=overlap(tie.translate([0,0,float(dz)]),rear);assert v<.001,(side,'slide',dz,v)
(ROOT/'verificacao-cintas.json').write_text(json.dumps(rows,indent=2)+'\n');print('TIE ENVELOPES CLEAR; RIGID STOPS RETAINED')
