"""PLA cover-pin fit trial v4. Two retention sizes, identical free-running stems.

Rigid overlap checks do not establish elastic strength or physical fit.
"""
from pathlib import Path
import json, re, shutil, subprocess, zipfile
import numpy as np
import trimesh
import manifold3d as md

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'ender3-original-pla-v1/pecas-individuais'
for name in ('stl','modelos-fatiados','gcode','perfis','projetos','verificacao','previas'):(ROOT/name).mkdir(exist_ok=True)
def cyl(r,h,z=0,r2=None):return md.Manifold.cylinder(h,r,r if r2 is None else r2,96).translate([0,0,z])
def box(pos,size):return md.Manifold.cube(size).translate(pos)
def union(items):return md.Manifold.batch_boolean(items,md.OpType.Add)
def mesh(s):
    m=s.to_mesh64();return trimesh.Trimesh(np.array(m.vert_properties[:,:3]),np.array(m.tri_verts),process=False)
def original(name):
    m=trimesh.load(OLD/(name+'.stl'))
    return md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
def save(s,name):
    m=mesh(s);m.apply_translation(-m.bounds[0]);m.export(ROOT/'stl'/(name+'.stl'))
    q=trimesh.load(ROOT/'stl'/(name+'.stl'))
    assert q.is_watertight and q.is_winding_consistent and q.volume>0 and len(q.split())==1
    return dict(name=name,size_mm=q.extents.tolist(),volume_mm3=q.volume,watertight=True,one_part=True)

def pin(bead_radius,marks):
    # Same head contact plane and blind-hole depth as v3; full shaft is smaller.
    # Shaft stops at bead, so it no longer masks the tapered nose.
    tip=union([cyl(1.90,.15,8.40,bead_radius),
               cyl(bead_radius,.20,8.55),
               cyl(bead_radius,.90,8.75,1.50),
               cyl(1.50,.15,9.65,1.30)])
    # Remove the circumferential bead outside the bending direction. A full
    # circular bead cannot be assumed to shrink radially when split arms close
    # along X. Lateral wings stay within Y=+-1.4, with a flat printing face.
    tip=tip^box([-5,-1.40,8.30],[10,2.80,2])
    s=union([cyl(3.4,2.4),cyl(1.90,6.25,2.30),
             cyl(1.98,.40,2.25,1.90),tip])
    # Longer free arms, wider slot and larger rounded root.
    s=s-box([-.70,-4,2.80],[1.40,8,10])
    rounded=md.Manifold.cylinder(8,.70,.70,64).rotate([-90,0,0]).translate([0,-4,2.80])
    s=s-rounded
    # Common flat supports both arms directly; print axis lies in the bed plane.
    s=s-box([-5,-5,-1],[10,3.6,13])
    # One or two shallow grooves in external head face identify retention size.
    # Marks remain in the head, away from its arm junction.
    for x in ([0] if marks==1 else [-.80,.80]):
        s=s-box([x-.30,.10,-.10],[.60,1.80,.65])
    assert str(s.status())=='Error.NoError'
    return s

socket=original('17-cupom-bucha-tampa').translate([-8,-8,0])
plate=original('18-cupom-placa-tampa').translate([-8,-8,4.25])
records=[];parts=[]
for label,radius,marks in [('A',2.40,1),('B',2.50,2)]:
    s=pin(radius,marks)
    ident='08-trava-'+label+'-PLA-v4'
    exported=save(s.rotate([90,0,0]),ident)
    installed=s.rotate([180,0,0]).translate([0,0,11.10])
    overlaps={
        'socket_installed_mm3':max(0,(installed^socket).volume()),
        'plate_installed_mm3':max(0,(installed^plate).volume()),
    }
    assert max(overlaps.values())<.001,(label,overlaps)
    # Stem must remain clear in the guide when only the tip has passed it.
    shaft=s^box([-5,-5,2.40],[10,10,5.99])
    stem=shaft.rotate([180,0,0]).translate([0,0,11.10])
    assert max(0,(stem^plate).volume())<.001
    pull=[dict(distance_mm=d,interference_with_socket_mm3=max(0,(installed.translate([0,0,d])^socket).volume())) for d in [0,.1,.2,.3,.5,.7,1.0]]
    assert pull[4]['interference_with_socket_mm3']>.001,(label,pull)
    # Geometric envelope only: required tip translation along X to enter a
    # nominal circular hole. Actual elastic deformation is NOT simulated.
    right_tip=mesh(s^box([0,-4,8.40],[5,8,2]))
    assert np.max(np.abs(right_tip.vertices[:,1]))<2.30
    required_closure=max(0,float(np.max(right_tip.vertices[:,0]-np.sqrt(2.30**2-right_tip.vertices[:,1]**2))))
    assert 2*required_closure<1.40
    records.append(dict(label=label,head_marks=marks,bead_diameter_mm=2*radius,
                        shaft_diameter_mm=3.80,root_transition_max_diameter_mm=3.90,
                        slot_mm=1.40,slot_root_radius_mm=.70,slot_root_center_from_head_outer_face_mm=2.80,
                        head_thickness_mm=2.40,length_mm=9.80,
                        entry_diameter_mm=4.60,nominal_radial_tip_deflection_mm=radius-2.30,
                        nominal_bead_to_socket_radial_clearance_mm=2.65-radius,
                        tip_y_extent_limited_mm=2.80,
                        geometric_tip_closure_per_arm_mm=required_closure,
                        geometric_envelope_check_only_not_elastic_simulation=True,
                        tip_to_blind_floor_clearance_mm=.10,
                        physical_fit_passed=False,geometry=exported,installed_checks=overlaps,pull_checks=pull))
    m=trimesh.load(ROOT/'stl'/(ident+'.stl'));m.apply_translation([len(parts)*20,0,0]);parts.append(m)

combined=trimesh.util.concatenate(parts)
combined.apply_translation([110-combined.bounds[:,0].mean(),110-combined.bounds[:,1].mean(),0])
combined.export(ROOT/'modelos-fatiados/00FLEX4.stl')
(ROOT/'verificacao/geometria.json').write_text(json.dumps(records,indent=2)+'\n')

cfg=dict(re.findall(r'^(\w+) = (.*)$',(ROOT.parent/'ender3-pla-gcode-v2/perfis/00TESTE.ini').read_text(),re.M))
cfg.update(fill_density='100%',print_settings_id='ChargeGrid trava flexivel PLA v4 A e B')
profile=ROOT/'perfis/00FLEX4.ini'
profile.write_text('\n'.join(f'{k} = {v}' for k,v in sorted(cfg.items()))+'\n')
exe='/tmp/chargegrid-prusa-dmg/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
base=[exe,'--datadir','/tmp/chargegrid-prusa-settings','--threads','4','--load',str(profile),'--center','110,110']
for action,folder,ext in [('gcode','gcode','.gcode'),('3mf','projetos','.3mf')]:
    with (ROOT/'verificacao'/('00FLEX4-'+action+'.log')).open('w') as log:
        subprocess.run(base+['--export-'+action,'--output',str(ROOT/folder/('00FLEX4'+ext)),str(ROOT/'modelos-fatiados/00FLEX4.stl')],stdout=log,stderr=subprocess.STDOUT,check=True)
gc=(ROOT/'gcode/00FLEX4.gcode').read_text()
full=gc.split('; prusaslicer_config = begin',1)[1].split('; prusaslicer_config = end',1)[0].strip()+'\n'
project=ROOT/'projetos/00FLEX4.3mf'
with zipfile.ZipFile(project) as z:entries={n:z.read(n) for n in z.namelist() if n!='Metadata/Slic3r_PE.config'}
entries['Metadata/Slic3r_PE.config']=('; generated by PrusaSlicer 2.9.6\n\n'+full).encode()
with zipfile.ZipFile(project,'w',zipfile.ZIP_DEFLATED) as z:
    for n,data in entries.items():z.writestr(n,data)
print('PRONTO: 00FLEX4.gcode; pino A com 1 marca; pino B com 2 marcas.',flush=True)
print(json.dumps(records,indent=2))
