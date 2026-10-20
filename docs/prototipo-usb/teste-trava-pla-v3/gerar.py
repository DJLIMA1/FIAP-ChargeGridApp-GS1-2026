"""Replaceable PLA cover pin prototype; original sockets remain unchanged."""
from pathlib import Path
import json, math, re, shutil, subprocess, zipfile
import numpy as np
import trimesh
import manifold3d as md

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'ender3-original-pla-v1/pecas-individuais'
for name in ('stl','modelos-fatiados','gcode','perfis','projetos','verificacao'):(ROOT/name).mkdir(exist_ok=True)
def cylinder(r,h,z=0,r2=None):return md.Manifold.cylinder(h,r,r if r2 is None else r2,96).translate([0,0,z])
def box(p,s):return md.Manifold.cube(s).translate(p)
def union(items):return md.Manifold.batch_boolean(items,md.OpType.Add)
def mesh(s):
    m=s.to_mesh64()
    return trimesh.Trimesh(np.array(m.vert_properties[:,:3]),np.array(m.tri_verts),process=False)
def original(name):
    m=trimesh.load(OLD/(name+'.stl'))
    return md.Manifold(md.Mesh64(m.vertices,m.faces.astype(np.uint64)))
def save(s,name):
    m=mesh(s);m.apply_translation(-m.bounds[0]);m.export(ROOT/'stl'/(name+'.stl'))
    r=trimesh.load(ROOT/'stl'/(name+'.stl'))
    assert r.is_watertight and r.is_winding_consistent and r.volume>0
    assert len(r.split())==1
    return dict(name=name,dimensions_mm=r.extents.tolist(),volume_mm3=r.volume,watertight=True,one_connected_part=True)

def pin(lower=False):
    # Same installed nose / retention positions as original 08; thicker head
    # projects 0.8 mm farther into the enclosure, never farther into blind socket.
    delta=.25 if lower else 0
    length=9.8+delta
    bead_start=8.7+delta
    s=union([cylinder(3.4,2.4),cylinder(2.15,length-2.3,2.3),
             cylinder(2.28,.70,2.3,2.15),
             cylinder(2.15,.30,bead_start-.30,2.40),
             cylinder(2.40,.90,bead_start,1.95)])
    # Rounded slot root, open to the tip. The two arms remain connected at head.
    slot=box([-.60,-4,3.70],[1.20,8,length])
    root=md.Manifold.cylinder(8,.60,.60,64).rotate([-90,0,0]).translate([0,-4,3.70])
    s=s-slot-root
    # Flat across the entire length allows horizontal printing without supports
    # inside the split. Slot stays vertical, with arms side by side on the bed.
    s=s-box([-5,-5,-1],[10,3.3,length+3])
    assert str(s.status())=='Error.NoError'
    return s

records=[]
standard=pin();lower=pin(True)
for s,name in [(standard,'08-pino-tampa-1-a-4-PLA-v3'),(lower,'08-pino-tampa-5-PLA-v3')]:
    # original Y=-1.7 becomes print Z=0 after normalizing
    records.append(save(s.rotate([90,0,0]),name))
for name in ['17-cupom-bucha-tampa','18-cupom-placa-tampa']:
    shutil.copyfile(OLD/(name+'.stl'),ROOT/'stl'/(name+'.stl'))

# Rigid installed checks only. This is not an elastic / fatigue validation.
socket=original('17-cupom-bucha-tampa').translate([-8,-8,0])
plate=original('18-cupom-placa-tampa').translate([-8,-8,4.25])
installed=standard.rotate([180,0,0]).translate([0,0,11.10])
tests={
    'installed_socket_overlap_mm3':max(0,(installed^socket).volume()),
    'installed_plate_overlap_mm3':max(0,(installed^plate).volume()),
    'tip_to_blind_floor_clearance_mm':.10,
    'head_to_plate_clearance_mm':.10,
    'shaft_nominal_diameter_mm':4.30,
    'socket_entry_diameter_mm':4.60,
    'bead_max_diameter_mm':4.80,
    'nominal_radial_deflection_to_enter_mm':.10,
    'old_nominal_radial_deflection_mm':.18,
    'head_thickness_mm':2.40,
    'old_head_thickness_mm':1.60,
    'physical_test_passed':False,
    'requires_actual_retention_removal_and_repeat_cycle_test':True,
}
assert tests['installed_socket_overlap_mm3']<.001,tests
assert tests['installed_plate_overlap_mm3']<.001,tests
# Pulling 0.9 mm must reach the retaining lip: geometric capture, not proof of force.
tests['pull_0_9mm_expected_interference_mm3']=max(0,(installed.translate([0,0,.9])^socket).volume())
assert tests['pull_0_9mm_expected_interference_mm3']>.001,tests
(ROOT/'verificacao/geometria.json').write_text(json.dumps(dict(parts=records,checks=tests),indent=2)+'\n')

def arrange(spec,name):
    parts=[];x=0
    for stem,count in spec:
        for _ in range(count):
            m=trimesh.load(ROOT/'stl'/(stem+'.stl'));m.apply_translation(-m.bounds[0]);m.apply_translation([x,0,0]);parts.append(m);x+=m.extents[0]+12
    joined=trimesh.util.concatenate(parts)
    joined.apply_translation([110-(joined.bounds[0,0]+joined.bounds[1,0])/2,110-(joined.bounds[0,1]+joined.bounds[1,1])/2,0])
    joined.export(ROOT/'modelos-fatiados'/(name+'.stl'))
arrange([('08-pino-tampa-1-a-4-PLA-v3',2)],'00TRAVA')
arrange([('17-cupom-bucha-tampa',1),('18-cupom-placa-tampa',1)],'01ENCAIX')

cfg=dict(re.findall(r'^(\w+) = (.*)$',(ROOT.parent/'ender3-pla-gcode-v2/perfis/00TESTE.ini').read_text(),re.M))
exe='/tmp/chargegrid-prusa-dmg/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
for name in ['00TRAVA','01ENCAIX']:
    c=cfg.copy()
    c['print_settings_id']='ChargeGrid teste trava PLA v3'
    # Only change from the successful thermal / motion profile: solid small pins.
    if name=='00TRAVA':c['fill_density']='100%'
    profile=ROOT/'perfis'/(name+'.ini')
    profile.write_text('\n'.join(f'{k} = {v}' for k,v in sorted(c.items()))+'\n')
    model=ROOT/'modelos-fatiados'/(name+'.stl')
    base=[exe,'--datadir','/tmp/chargegrid-prusa-settings','--threads','4','--load',str(profile),'--center','110,110']
    for action,folder,ext in [('gcode','gcode','.gcode'),('3mf','projetos','.3mf')]:
        with (ROOT/'verificacao'/(name+'-'+action+'.log')).open('w') as log:
            subprocess.run(base+['--export-'+action,'--output',str(ROOT/folder/(name+ext)),str(model)],stdout=log,stderr=subprocess.STDOUT,check=True)
    gc=(ROOT/'gcode'/(name+'.gcode')).read_text()
    full=gc.split('; prusaslicer_config = begin',1)[1].split('; prusaslicer_config = end',1)[0].strip()+'\n'
    project=ROOT/'projetos'/(name+'.3mf')
    with zipfile.ZipFile(project) as z:entries={n:z.read(n) for n in z.namelist() if n!='Metadata/Slic3r_PE.config'}
    entries['Metadata/Slic3r_PE.config']=('; generated by PrusaSlicer 2.9.6\n\n'+full).encode()
    with zipfile.ZipFile(project,'w',zipfile.ZIP_DEFLATED) as z:
        for n,data in entries.items():z.writestr(n,data)
    print('PRONTO',name,flush=True)
print(json.dumps(tests,indent=2))
