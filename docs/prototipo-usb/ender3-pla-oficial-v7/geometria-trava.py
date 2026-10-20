from pathlib import Path
import numpy as np
import trimesh
import manifold3d as md

def cyl(r,h,z=0,r2=None):return md.Manifold.cylinder(h,r,r if r2 is None else r2,96).translate([0,0,z])

def box(pos,size):return md.Manifold.cube(size).translate(pos)

def union(items):return md.Manifold.batch_boolean(items,md.OpType.Add)

def mesh(s):
    m=s.to_mesh64();return trimesh.Trimesh(np.array(m.vert_properties[:,:3]),np.array(m.tri_verts),process=False)

def pin(bead_radius,marks,extra=0.0):
    # Head seats on the actual plate surface; tip has 0.25 mm clearance at floor.
    # Shaft stops at bead, so it no longer masks the tapered nose.
    tip=union([cyl(1.90,.10,8.35+extra,bead_radius),
               cyl(bead_radius,.30,8.45+extra),
               cyl(bead_radius,.65,8.75+extra,1.50),
               cyl(1.50,.15,9.40+extra,1.30)])
    # Remove the circumferential bead outside the bending direction. A full
    # circular bead cannot be assumed to shrink radially when split arms close
    # along X. Lateral wings stay within Y=+-1.4, with a flat printing face.
    tip=tip^box([-5,-1.40,8.20+extra],[10,2.80,2])
    s=union([cyl(3.4,2.4),cyl(1.90,6.15+extra,2.30),
             cyl(1.98,.40,2.25,1.90),tip])
    # Longer free arms, wider slot and larger rounded root.
    s=s-box([-.70,-4,2.80],[1.40,8,10])
    rounded=md.Manifold.cylinder(8,.70,.70,64).rotate([-90,0,0]).translate([0,-4,2.80])
    s=s-rounded
    # Common flat supports both arms directly; print axis lies in the bed plane.
    s=s-box([-5,-5,-1],[10,3.6,13])
    # Three shallow grooves in external head face identify retention size.
    # Marks remain in the head, away from its arm junction.
    for x in ([-1.20,0,1.20] if marks==3 else [-1.80,-.60,.60,1.80]):
        s=s-box([x-.30,.10,-.10],[.60,1.80,.65])
    assert str(s.status())=='Error.NoError'
    return s
