# Reuse audited loader without rerunning the static report.
from pathlib import Path
src=Path(__file__).parent/'auditar.py'
exec(src.read_text().split('pairs=[];',1)[0])
results=[]
def sweep(label,moving,obstacles,transforms,expect_retention=False):
 obs=union(solids[n] for n in obstacles);body=union(solids[n] for n in moving);vals=[]
 for param,transform in transforms:
  value=overlap(body.transform(transform),obs);vals.append({'parameter':param,'intersection_mm3':value})
 mx=max(v['intersection_mm3'] for v in vals);passed=(mx>.001) if expect_retention else (mx<.001)
 results.append({'test':label,'moving':moving,'obstacles':obstacles,'expected_retention':expect_retention,'passed':passed,'max_intersection_mm3':mx,'samples':vals})
 print('PASS' if passed else 'FAIL',label,round(mx,6),flush=True)
def translation(v):return [[1,0,0,v[0]],[0,1,0,v[1]],[0,0,1,v[2]]]
def shift(label,moving,obstacles,vs,retention=False):sweep(label,moving,obstacles,[(v,translation(v)) for v in vs],retention)
allnames=set(solids);rear=[n for n in solids if n.startswith('01-traseira') or (n.startswith('chave-') and n.endswith('90.8'))]
frame=[n for n in solids if n.startswith('03-quadro') or (n.startswith('chave-') and n.endswith('57.2'))]
cap=['05-tampa-frontal'];snaps=[n for n in solids if n.startswith('08-')];bayonets=[n for n in solids if n.startswith('pino-casca')]
tray=['09-bandeja-removivel'];carriers=['10-berco-potencia','11-berco-esp32'];cpins=[n for n in solids if n.startswith('trava-berco')];stops=[n for n in solids if n.startswith('trava-bandeja')];cable=[n for n in solids if n.startswith('19-')]
# Unlock and withdraw all four bayonet pins; include all other installed parts.
for n in bayonets:
 m=meshes[n];center=m.bounds.mean(axis=0);x,z=center[0],center[2]
 transforms=[]
 for angle in np.linspace(0,90,19):
  t=trimesh.transformations.rotation_matrix(np.radians(angle),[0,1,0],[x,100,z]);transforms.append((float(angle),t[:3].tolist()))
 sweep(n+'_unlock_0_90', [n],sorted(allnames-{n}),transforms)
 rot=trimesh.transformations.rotation_matrix(np.pi/2,[0,1,0],[x,100,z]);xs=[]
 for d in np.linspace(0,40,41):
  t=rot.copy();t[1,3]+=d;xs.append((float(d),t[:3].tolist()))
 sweep(n+'_withdraw_unlocked',[n],sorted(allnames-{n}),xs)
 shift(n+'_retains_locked',[n],frame,[[0,d,0] for d in [.25,.5,1]],True)
front=frame+cap+snaps
shift('front_complete_withdrawal',front,sorted(allnames-set(front)-set(bayonets)),[[0,-float(d),0] for d in np.linspace(0,45,46)])
shift('cap_removed_after_releasing_pins',cap,frame,[[0,-float(d),0] for d in np.linspace(0,30,31)])
for n in snaps:shift(n+'_retention',[n],cap,[[0,float(d),0] for d in [.1,.25,.5]],True)
# Internal tray removes with carriers and their retaining pins installed; front and stops removed first.
tray_loaded=tray+carriers+cpins;remaining=rear+cable
shift('loaded_tray_slide_up',tray_loaded,remaining,[[0,0,float(d)] for d in np.linspace(0,5,21)])
shift('loaded_tray_withdraw_after_slide',tray_loaded,remaining,[[0,-float(d),5] for d in np.linspace(0,45,46)])
shift('tray_stops_prevent_release',tray_loaded+stops,remaining,[[0,0,float(d)] for d in [.25,.5,1,2,3,5]],True)
# Carrier rails: remove locking pins, slide in the local +Y direction = world +Z, then withdraw forward.
for n in reversed(carriers):
 # ESP32 first; power carrier follows after ESP32 has been removed.
 obstacles=tray+([carriers[0]] if n==carriers[1] else [])
 shift(n+'_slide_out', [n],obstacles,[[0,0,float(d)] for d in np.linspace(0,10.5,43)])
 shift(n+'_withdraw_from_rails',[n],obstacles,[[0,-float(d),10.5] for d in np.linspace(0,15,16)])
 shift(n+'_retains_on_rails',[n],tray,[[0,-d,0] for d in [.2,.5,1]],True)
 pin='trava-berco-8' if n.startswith('10') else 'trava-berco-54'
 shift(n+'_locking_pin_blocks_slide',[n],tray+[pin],[[0,0,d] for d in [.25,.5,1,2]],True)
# Are the small retaining pins actually retained in their receptacles?
for n in cpins:shift(n+'_own_retention',[n],tray,[[0,-d,0] for d in [.25,.5,1]],True)
for n in stops:shift(n+'_own_retention',[n],tray,[[0,-d,0] for d in [.25,.5,1]],True)
(ROOT/'movimentos.json').write_text(json.dumps({'package':str(PKG),'results':results,'failed':[r['test'] for r in results if not r['passed']]},indent=2)+'\n')
