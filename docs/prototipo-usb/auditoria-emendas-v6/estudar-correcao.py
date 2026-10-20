exec((__import__('pathlib').Path(__file__).parent/'verificar.py').read_text().split('out={',1)[0])
outline=[(-5,-11),(-3,0),(-5,11),(5,11),(3,0),(5,-11)][::-1]
def pocket(x):
 cs=md.CrossSection([[(a*1.07+x,b*1.025+58.05) for a,b in outline]])
 return md.Manifold.extrude(cs,14.2).rotate([90,0,0]).translate([0,94.2,0])
old=solids['01-traseira-inferior'];new=old-pocket(-22)-pocket(22)
print('removed',old.volume()-new.volume(),'components',len(new.decompose()),'cutbounds',(old-new).bounding_box(),flush=True)
rear=new+solids['01-traseira-superior'];cassette=solids['09-bandeja-removivel']
for x in [-22,22]:
 s=solids[f'chave-{x}-90.8'];print('key',x,[(d,max(0,(s.translate([0,-d,0])^rear).volume())) for d in [0,.25,.5,1,2,3,4,6,10]],flush=True)
for dy in [0,.2,.5,1,2,3]:print('cassette pull',dy,'old',max(0,(cassette.translate([0,-dy,0])^(old+solids['01-traseira-superior'])).volume()),'new',max(0,(cassette.translate([0,-dy,0])^rear).volume()),flush=True)
for x in [-25,25]:
 stem=md.Manifold.cylinder(3.6,2.1,2.1,48).rotate([-90,0,0]).translate([x,87.35,44])
 head=md.Manifold.cylinder(1.75,3.5,3.5,48).rotate([-90,0,0]).translate([x,85.6,44])
 print('mount',x,'stem_removed',(stem^(old-new)).volume(),'head_retained_percent',(head^new).volume()/head.volume()*100,flush=True)
