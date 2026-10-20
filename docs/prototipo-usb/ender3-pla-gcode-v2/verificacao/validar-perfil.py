from pathlib import Path
import json,re,zipfile,subprocess
root=Path('/Users/djmurillo/Desktop/Aulas FIAP/ChargeGridApp/docs/prototipo-usb/ender3-pla-gcode-v2')
expected=json.loads((root/'verificacao/configuracao-solicitada.json').read_text())
keys='layer_height first_layer_height extrusion_width first_layer_extrusion_width external_perimeter_extrusion_width top_infill_extrusion_width perimeters perimeter_generator top_solid_layers bottom_solid_layers top_solid_min_thickness bottom_solid_min_thickness fill_density fill_pattern fill_angle solid_infill_below_area first_layer_temperature temperature bed_temperature first_layer_speed first_layer_acceleration external_perimeter_speed external_perimeter_acceleration perimeter_speed perimeter_acceleration small_perimeter_speed infill_speed infill_acceleration solid_infill_speed top_solid_infill_speed bridge_speed bridge_flow_ratio bridge_fan_speed travel_speed travel_speed_z default_acceleration retract_length retract_speed deretract_speed retract_lift retract_before_travel disable_fan_first_layers full_fan_speed_layer slowdown_below_layer_time min_print_speed filament_max_volumetric_speed brim_type brim_width brim_separation skirts skirt_height skirt_distance support_material raft_layers elefant_foot_compensation xy_size_compensation z_offset gcode_flavor use_relative_e_distances complete_objects nozzle_diameter filament_diameter filament_density start_gcode end_gcode'.split()
results=[]
for path in sorted((root/'gcode').glob('*.gcode')):
 t=path.read_text();actual=dict(re.findall(r'^; (\w+) = (.*)$',t,re.M))
 mismatches={k:[expected[k],actual.get(k)] for k in keys if expected[k]!=actual.get(k)}
 assert not mismatches,(path.name,mismatches)
 assert ';TYPE:Support material' not in t
 with zipfile.ZipFile(root/'projetos'/f'{path.stem}.3mf') as z:
  assert z.testzip() is None
  embedded=dict(re.findall(r'^; (\w+) = (.*)$',z.read('Metadata/Slic3r_PE.config').decode(),re.M))
  assert all(embedded[k]==actual[k] for k in keys)
 layer=0;fans=[];temps=[];lines=t.splitlines()
 for i,line in enumerate(lines):
  if line==';LAYER_CHANGE':layer+=1
  if line.startswith('M106'):
   upcoming=layer+1 if lines[i+1]==';LAYER_CHANGE' else layer
   fans.append([upcoming,line])
  if line.startswith(('M104','M109')):temps.append([layer,line])
 assert all('S0' in cmd for lay,cmd in fans if lay<3),(path.name,fans[:4])
 results.append(dict(file=path.name,checked_settings=len(keys),settings_match=True,embedded_3mf_matches=True,temperature_commands=temps,first_fan_commands=fans[:4]))
(root/'verificacao/perfil-validado.json').write_text(json.dumps(results,indent=2)+'\n')
print('12 perfis conferidos, 3MF embutidos conferidos, ventilador das duas primeiras camadas conferido.',flush=True)
exe='/tmp/chargegrid-prusa-dmg/Original Prusa Drivers/PrusaSlicer.app/Contents/MacOS/PrusaSlicer'
reopened=[]
for name in ['00TESTE','01TAMPA']:
 out=Path('/tmp')/f'chargegrid-v2-reopen-{name}.gcode'
 with (root/'verificacao'/f'{name}-reaberto.log').open('w') as log:
  subprocess.run([exe,'--datadir','/tmp/chargegrid-prusa-settings','--threads','4','--export-gcode','--output',str(out),str(root/'projetos'/f'{name}.3mf')],stdout=log,stderr=subprocess.STDOUT,check=True)
 a=dict(re.findall(r'^; (\w+) = (.*)$',out.read_text(),re.M))
 assert all(a[k]==expected[k] for k in keys),name
 reopened.append(dict(project=name,settings_match_after_reslicing=True))
 print('3MF reaberto e refatiado com perfil embutido:',name,flush=True)
(root/'verificacao/projetos-reabertos.json').write_text(json.dumps(reopened,indent=2)+'\n')
