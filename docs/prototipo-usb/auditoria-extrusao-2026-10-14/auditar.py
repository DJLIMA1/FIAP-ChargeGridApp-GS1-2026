"""Read-only analysis of delivered files; does not operate a printer."""
from pathlib import Path
import hashlib, json, math, re

BASE = Path(__file__).resolve().parent
PACKAGE = BASE.parent / 'ender3-pla-gcode-v1'
manifest = json.loads((PACKAGE / 'SHA256SUMS.json').read_text())['files']
reports = []
for path in sorted((PACKAGE / 'gcode').glob('*.gcode')):
    data = path.read_bytes()
    lines = data.decode('ascii').splitlines()
    config = dict(re.findall(r'^; (\w+) = (.*)$', data.decode('ascii'), re.M))
    xyz = dict.fromkeys('XYZ', 0.0)
    relative_e, absolute_xyz, epos = True, True, 0.0
    feed, layer, debt, peak_debt = 0.0, 0, 0.0, 0.0
    cycles, restores, retracted = 0, 0, 0.0
    cycles_by_layer, temperatures, commands, anomalies = {}, [], {}, []
    flows, speeds, net_e = [], [], 0.0
    feature = 'Custom'
    peak_debt_before_last_deposition = 0.0
    for number, line in enumerate(lines, 1):
        if line.startswith(';LAYER_CHANGE'): layer += 1
        if line.startswith(';TYPE:'): feature = line[6:]
        clean = line.split(';')[0].strip()
        if not clean: continue
        command = clean.split()[0]
        commands.setdefault(command, number)
        values = {k: float(v) for k, v in re.findall(r'([A-Z])\s*(-?(?:\d*\.)?\d+)', clean[len(command):])}
        if command in ('M104', 'M109'):
            temperatures.append(dict(line=number, layer=layer, command=clean))
        if command == 'G90': absolute_xyz = True
        if command == 'G91': absolute_xyz = False
        if command == 'M83': relative_e = True
        if command == 'M82': relative_e = False
        if command == 'G28': xyz = dict.fromkeys('XYZ', 0.0)
        if command == 'G92':
            for axis in 'XYZ':
                if axis in values: xyz[axis] = values[axis]
            if 'E' in values: epos = values['E']
        if command not in ('G0', 'G1'): continue
        old = xyz.copy()
        for axis in 'XYZ':
            if axis in values: xyz[axis] = values[axis] + (0 if absolute_xyz else xyz[axis])
        feed = values.get('F', feed)
        length = math.sqrt(sum((xyz[a] - old[a])**2 for a in 'XYZ'))
        extrusion = values.get('E', 0) if relative_e else values.get('E', epos) - epos
        if 'E' in values: epos += extrusion
        net_e += extrusion
        if extrusion < 0:
            if debt < 0.001:
                cycles += 1
                cycles_by_layer[layer] = cycles_by_layer.get(layer, 0) + 1
            retracted -= extrusion
            debt -= extrusion
            peak_debt = max(peak_debt, debt)
        elif extrusion > 0:
            if debt > 0.001 and length > 0.001:
                anomalies.append(dict(line=number, debt_mm=debt, extrusion_mm=extrusion))
            if debt > 0.001 and extrusion >= debt - 0.001: restores += 1
            deposited = max(0, extrusion - debt)
            debt = max(0, debt - extrusion)
            if debt < 0.001: debt = 0
            if deposited > 0 and length > 0.001 and feature != 'Custom':
                peak_debt_before_last_deposition = peak_debt
                flows.append((deposited * math.pi * (1.75/2)**2 * feed/60/length, number))
                speeds.append(feed/60)
    reports.append(dict(file=path.name,
        sha256=hashlib.sha256(data).hexdigest(),
        matches_delivery_hash=hashlib.sha256(data).hexdigest() == manifest['gcode/'+path.name],
        temperatures=temperatures,
        configuration={k:config.get(k) for k in ['nozzle_diameter','filament_diameter','extrusion_multiplier','retract_length','retract_speed','layer_height','first_layer_height','use_volumetric_e']},
        estimated_time=re.search(r'^; estimated printing time \(normal mode\) = (.*)$',data.decode('ascii'),re.M)[1],
        first_command_lines={k:commands.get(k) for k in ['G21','G1','M83','M200','M220','M221','M92','M500']},
        layers=layer, retract_cycles_including_shutdown=cycles, completed_restores=restores,
        peak_retraction_debt_mm=round(peak_debt,5), shutdown_unrestored_mm=round(debt,5),
        peak_retraction_before_last_deposition_mm=round(peak_debt_before_last_deposition,5),
        total_retracted_mm=round(retracted,3), max_cycles_one_layer=max(cycles_by_layer.values()),
        cycles_first_layer=cycles_by_layer.get(1,0), extrusion_before_full_restore=anomalies,
        peak_nominal_flow_mm3_s=round(max(flows)[0],4), peak_flow_line=max(flows)[1],
        peak_deposition_speed_mm_s=max(speeds), net_e_mm=round(net_e,3)))
(BASE/'resultados.json').write_text(json.dumps(reports,indent=2)+'\n')
print(json.dumps(reports[0],indent=2))
print('All delivery hashes match:', all(r['matches_delivery_hash'] for r in reports))
print('All restore balances during printing pass:', all(not r['extrusion_before_full_restore'] and r['peak_retraction_before_last_deposition_mm'] < 4.001 for r in reports))
