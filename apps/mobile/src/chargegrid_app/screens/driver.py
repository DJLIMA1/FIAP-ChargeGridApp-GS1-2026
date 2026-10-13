"""Modo motorista de app: planeja recargas no turno para ganhar mais e parar menos.

Todo cálculo vem da API (``/v1/driver/*``) ou, no modo demo, do mesmo motor
``chargegrid_core.driver`` executado localmente. Demanda é sempre estimativa.
"""
import flet as ft

from chargegrid_core.driver import PRESETS
from chargegrid_core.formatting import brl, duration, km, kwh

from ..api_client import ApiError
from ..demo import DEMO_LOCATIONS
from ..preferences import DriverProfileStore
from ..services import driver as helpers
from ..services.location import geocode_address, geocode_demo_address
from ..ui import theme
from ..ui.components import button, card, disclosure_field, field, pill, title

DEMO_REGION = 'Praça da Sé'


def _colors():
    return {'rodando': theme.GREEN, 'recarga': theme.BLUE, 'refeicao_recarga': theme.AMBER,
            'refeicao': theme.SLATE, 'pausa': theme.ERROR}


def _dropdown(label, value, options):
    return ft.Dropdown(label=label, value=value, options=[ft.DropdownOption(key=k, text=t) for k, t in options],
                       color=theme.TEXT_COLOR, bgcolor=theme.WHITE, expand=True)


def _wide(control):
    """Dropdown ocupa a largura toda do cartão (Row + expand)."""
    return ft.Row([control])


def _heading(text):
    return ft.Text(text, size=11, weight=ft.FontWeight.BOLD, color=theme.ACCENT)


def _small(text, color=None, **kwargs):
    return ft.Text(text, size=12, color=color or theme.GRAY_TEXT, **kwargs)


def _number_field(label, value):
    control = field(label, '' if value is None else str(value).replace('.', ','))
    control.keyboard_type = ft.KeyboardType.NUMBER
    return control


def _demo_locations():
    from ..services.driver_demo import DEMO_DRIVER_NETWORK
    return tuple(DEMO_LOCATIONS) + tuple(DEMO_DRIVER_NETWORK)


async def build(app):
    demo = getattr(app.api, 'is_demo', False) is True
    state = getattr(app, 'driver_state', None)
    if not isinstance(state, dict):
        state = {}
        app.driver_state = state
    store = DriverProfileStore()
    remote = await app.api.request('GET', 'driver/profile')
    local = None if demo else store.load()
    profile = remote if remote.get('saved') or not local else {**remote, **local}
    vehicle = dict(profile.get('vehicle') or {})
    prefs = dict(profile.get('preferences') or {})
    presets = remote.get('presets') or [p.to_dict() for p in PRESETS.values()]

    # --- carro -----------------------------------------------------------------------
    preset_key = vehicle.get('preset') if vehicle.get('preset') in {p['key'] for p in presets} else 'custom'
    model = _dropdown('Modelo do carro', preset_key,
                      [(p['key'], p['name']) for p in presets] + [('custom', 'Outro (personalizado)')])
    by_key = {p['key']: p for p in presets}
    base = by_key.get(preset_key, {})
    battery = _number_field('Bateria útil (kWh)', vehicle.get('usable_battery_kwh') or base.get('usable_battery_kwh'))
    consumption = _number_field('Consumo (kWh/100 km)',
                                vehicle.get('consumption_kwh_per_100km') or base.get('consumption_kwh_per_100km'))
    vehicle_info = _small(helpers.vehicle_summary(vehicle | {'preset': preset_key}))
    soc = _number_field('Bateria agora (%)', state.get('soc') or (local or {}).get('soc_percent') or 60)

    async def preset_changed(event=None):
        chosen = by_key.get(model.value)
        if chosen:
            battery.value = str(chosen['usable_battery_kwh']).replace('.', ',')
            consumption.value = str(chosen['consumption_kwh_per_100km']).replace('.', ',')
        vehicle_info.value = helpers.vehicle_summary(current_vehicle(strict=False))
        app.page.update()
    model.on_select = preset_changed

    def current_vehicle(strict=True):
        try:
            data = {'usable_battery_kwh': helpers.number(battery.value, 'a bateria útil (kWh)', 5, 250),
                    'consumption_kwh_per_100km': helpers.number(consumption.value, 'o consumo (kWh/100 km)', 5, 60)}
        except ApiError:
            if strict:
                raise
            data = {}
        chosen = by_key.get(model.value)
        if chosen:
            data['preset'] = chosen['key']
            if data and abs(data['usable_battery_kwh'] - chosen['usable_battery_kwh']) < 1e-6 and \
                    abs(data['consumption_kwh_per_100km'] - chosen['consumption_kwh_per_100km']) < 1e-6:
                data = {'preset': chosen['key']}
        else:
            data.update(preset='custom', name='Meu carro')
        return data

    vehicle_section, _ = disclosure_field('Ajustar bateria e consumo', 'Use se o seu carro gasta diferente da média.',
                                          [battery, consumption], on_update=lambda: app.page.update())

    # --- turno, ganhos e refeições -------------------------------------------------------
    shift_start = field('Início do turno (HH:MM)', prefs.get('shift_start', '10:00'))
    shift_end = field('Fim do turno (HH:MM)', prefs.get('shift_end', '22:00'))
    earnings = _number_field('Ganho médio por hora rodando (R$)', prefs.get('earnings_per_hour', 38))
    speed = _number_field('Km rodados por hora', prefs.get('km_per_hour', 22))
    reserve = _number_field('Reserva mínima (%)', prefs.get('reserve_percent', 15))
    target = _number_field('Carregar até (%)', prefs.get('max_charge_percent', 80))
    home = ft.Switch(label='Tenho carregador em casa', value=bool(prefs.get('home_charging', True)))
    home_price = _number_field('Tarifa em casa (R$/kWh)', prefs.get('home_price_per_kwh', 0.95))
    saved_meals = {meal.get('kind'): meal for meal in prefs.get('meals') or []}
    meal_controls = []
    meal_rows = []
    for kind, label, default_start, default_duration, default_flex in helpers.MEALS:
        saved = saved_meals.get(kind)
        enabled = ft.Switch(label=label, value=bool(saved and saved.get('enabled', True)))
        start = field(f'{label} às (HH:MM)', (saved or {}).get('start', default_start))
        length = _number_field(f'Duração do {label.lower()} (min)', (saved or {}).get('duration_minutes', default_duration))
        flex = _dropdown('Flexibilidade', helpers.meal_flex(saved) if saved else default_flex, helpers.FLEX_CHOICES)
        meal_controls.append((kind, enabled, start, length, flex))
        meal_rows.append(ft.Column([enabled, ft.Row([ft.Container(start, expand=1), ft.Container(length, expand=1)]),
                                    _wide(flex)], spacing=8))

    shift_summary = f"{prefs.get('shift_start', '10:00')}–{prefs.get('shift_end', '22:00')} · refeições e ganhos"
    shift_section, _ = disclosure_field(
        'Turno, ganhos e refeições', shift_summary,
        [ft.Row([ft.Container(shift_start, expand=1), ft.Container(shift_end, expand=1)]), earnings, speed,
         ft.Row([ft.Container(reserve, expand=1), ft.Container(target, expand=1)]), home, home_price,
         _small('Refeições: o planejador tenta parar para comer num posto com restaurante ou café, '
                'recarregando enquanto você come.'), *meal_rows],
        expanded=not remote.get('saved') and not local, on_update=lambda: app.page.update())

    mode = _dropdown('O que planejar', state.get('mode') or ('full_shift' if demo else 'auto'), helpers.MODES)
    region = field('Onde você está (bairro ou endereço, opcional)', state.get('region', DEMO_REGION if demo else ''))
    rain = ft.Checkbox(label='Está chovendo agora', value=bool(state.get('rain')))

    def collect_profile():
        meals = [helpers.build_meal(kind, enabled.value, start.value, length.value, flex.value)
                 for kind, enabled, start, length, flex in meal_controls]
        preferences = {
            'shift_start': helpers.clock(shift_start.value, 'o início do turno'),
            'shift_end': helpers.clock(shift_end.value, 'o fim do turno'),
            'earnings_per_hour': helpers.number(earnings.value, 'o ganho médio por hora (R$)', 0, 500),
            'km_per_hour': helpers.number(speed.value, 'os km rodados por hora', 5, 80),
            'reserve_percent': helpers.number(reserve.value, 'a reserva mínima (%)', 5, 50),
            'max_charge_percent': helpers.number(target.value, 'o alvo máximo de carga (%)', 50, 100),
            'home_charging': bool(home.value),
            'home_price_per_kwh': helpers.number(home_price.value, 'a tarifa em casa (R$/kWh)', 0, 10),
            'meals': meals,
        }
        return {'vehicle': current_vehicle(), 'preferences': preferences}

    async def locate():
        text = (region.value or '').strip()
        state['region'] = text
        if not text:
            return None
        if state.get('region_cache', (None,))[0] == text:
            return state['region_cache'][1]
        found = geocode_demo_address(text, _demo_locations()) if demo else None
        if found is None and not demo:
            try:
                found = await geocode_address(text)
            except Exception:  # geocodificação é opcional: segue sem localização
                found = None
        if found is None:
            app.notice('Não encontramos esse local; planejando com todos os postos ativos.')
        state['region_cache'] = (text, found)
        return found

    async def request_body():
        profile = collect_profile()
        level = helpers.number(soc.value, 'a bateria agora (%)', 0, 100)
        state.update(soc=level, mode=mode.value, rain=bool(rain.value))
        body = {'soc_percent': level, **profile, 'context': {'rain': bool(rain.value)}}
        position = await locate()
        if position:
            body.update(lat=position[0], lng=position[1])
        await persist(profile, level)
        return body

    async def persist(profile, level):
        if not demo:
            store.save({**profile, 'soc_percent': level})
        try:
            await app.api.request('PUT', 'driver/profile', profile)
        except ApiError as error:
            if error.status == 422:
                raise
            # Sem rede: o perfil fica no aparelho e o plano usa os dados enviados.

    results = ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    async def plan_shift():
        body = await request_body()
        result = await app.api.request('POST', 'driver/plan', {**body, 'mode': mode.value})
        state.update(plan=result, next=None)
        show()

    async def next_stop():
        body = await request_body()
        result = await app.api.request('POST', 'driver/next-stop', body)
        state.update(next=result)
        show()

    def reserve_action(connector_id):
        async def reserve():
            key = state.setdefault('reserve_keys', {}).setdefault(connector_id, app.api.new_key())
            await app.api.request('POST', 'reservations', {'connector_id': connector_id}, key=key)
            state['reserve_keys'].pop(connector_id, None)
            await app.go('reservations')
        return app.action(reserve)

    def show():
        controls = []
        if state.get('next'):
            controls.extend(next_stop_view(state['next'], app, reserve_action))
        if state.get('plan'):
            controls.extend(plan_view(state['plan'], app, reserve_action))
        results.controls = controls
        app.page.update()

    if state.get('plan') or state.get('next'):
        results.controls = [*(next_stop_view(state['next'], app, reserve_action) if state.get('next') else []),
                            *(plan_view(state['plan'], app, reserve_action) if state.get('plan') else [])]

    header = [
        title('Modo motorista', 'Planeje recargas no seu turno de app: rode nos picos, carregue nas horas fracas.'),
        ft.Row([pill('Estimativas'), pill('Sem dados oficiais da Uber/99')], wrap=True, spacing=6),
    ]
    car_card = card([
        _heading('SEU CARRO'), _wide(model), vehicle_info, soc, vehicle_section,
    ])
    actions = card([
        _heading('PLANEJAMENTO'), _wide(mode), region, rain,
        button('Planejar meu turno', app.action(plan_shift)),
        button('Próxima parada agora', app.action(next_stop), secondary=True),
        _small('O plano considera consumo, autonomia, picos estimados de demanda, refeições, potência, tarifa '
               'e ocupação dos postos.'),
    ])
    return ft.ListView([*header, car_card, shift_section, actions, results], spacing=12, expand=True)


# --- resultados ------------------------------------------------------------------------------

def _alert_row(alert):
    icon, color = {'error': (ft.Icons.ERROR_OUTLINE, theme.ERROR),
                   'warning': (ft.Icons.WARNING_AMBER_ROUNDED, theme.AMBER)}.get(
        alert.get('level'), (ft.Icons.INFO_OUTLINE, theme.GRAY_TEXT))
    return ft.Row([ft.Icon(icon, size=18, color=color),
                   ft.Text(alert['message'], size=12, color=theme.TEXT_COLOR, expand=True)],
                  spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)


def _station_actions(app, reserve_action, item, *, can_reserve, emphasize=True):
    row = [button('Ver posto', app.link('stations', station_id=item['station_id']), secondary=True)]
    if can_reserve and item.get('connector_id') and item.get('available_now') is not False:
        row.append(button('Reservar', reserve_action(item['connector_id']), secondary=not emphasize))
    return ft.Row([ft.Container(control, expand=1) for control in row], spacing=8)


def summary_card(plan):
    totals, comparison, baseline = plan['totals'], plan['comparison'], plan['baseline']['totals']
    gain = comparison['net_profit_gain']
    gain_text = (f'+{brl(gain)} vs. recarregar só quando a bateria fica baixa' if gain >= 1
                 else 'Empata com recarregar só quando a bateria fica baixa')

    def metric(label, value):
        return ft.Column([_small(label), ft.Text(value, size=15, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR)],
                         spacing=2, expand=True)
    return card([
        _heading('LUCRO LÍQUIDO ESTIMADO DO TURNO'),
        ft.Text(brl(totals['net_profit']), size=32, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,
                font_family='BarlowCondensedBold'),
        ft.Text(gain_text, size=13, weight=ft.FontWeight.BOLD, color=theme.GREEN if gain >= 1 else theme.GRAY_TEXT),
        ft.Row([metric('Ganho bruto', brl(totals['gross_earnings'])),
                metric('Recargas', brl(totals['charging_cost'])),
                metric('Energia', kwh(totals['energy_kwh']))], spacing=8),
        _small(f"Paradas: {totals['stops']} ({duration(totals['stop_minutes'])}) · bateria no fim "
               f"{totals['end_soc_percent']:.0f}% · {km(totals['driving_km'])} rodados"),
        _small(f"Estratégia ingênua: {brl(baseline['net_profit'])} líquido, {baseline['stops']} parada(s), "
               f"{duration(baseline['peak_stop_minutes'])} parado no pico."),
        _small(comparison['message']),
    ])


def timeline_card(plan):
    colors = _colors()
    blocks, slots = plan['blocks'], [row for row in plan['slots'] if row['activity'] != 'fim']
    bar = ft.Row([ft.Container(expand=max(1, block['minutes']), height=28, bgcolor=colors[block['kind']],
                               border_radius=3) for block in blocks], spacing=2)
    peaks = ft.Row([ft.Container(expand=1, height=6, bgcolor=theme.RED if (row['demand'] or 0) >= 1.3 else theme.LIGHT_GRAY)
                    for row in slots], spacing=0)
    ticks = ft.Row([_small(plan['window']['start']), _small(plan['window']['end'])],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN)
    used = []
    for block in blocks:
        if block['kind'] not in used:
            used.append(block['kind'])
    legend = ft.Row([ft.Row([ft.Container(width=12, height=12, bgcolor=colors[kind], border_radius=3),
                             _small(helpers.KIND_LABELS[kind])], spacing=4, tight=True) for kind in used]
                    + [ft.Row([ft.Container(width=12, height=6, bgcolor=theme.RED), _small('Pico estimado')],
                              spacing=4, tight=True)], wrap=True, spacing=12, run_spacing=6)
    rows = [ft.Row([ft.Text(f"{block['start']}–{block['end']}", size=12, color=theme.TEXT_COLOR, width=92),
                    ft.Container(width=10, height=10, bgcolor=colors[block['kind']], border_radius=2),
                    ft.Text(f"{block['label']} · {block['soc_start']:.0f}% → {block['soc_end']:.0f}%", size=12,
                            color=theme.TEXT_COLOR, expand=True)], spacing=8) for block in blocks]
    return card([
        _heading('LINHA DO TEMPO DO TURNO'),
        ft.Semantics(label=helpers.plan_accessible_summary(plan), container=True,
                     content=ft.Column([bar, peaks, ticks], spacing=4)),
        legend, ft.Divider(height=8, color=theme.LIGHT_GRAY), *rows,
    ])


def soc_card(plan):
    rows = [row for row in plan['slots'] if row.get('soc') is not None]
    reserve = float(plan['preferences'].get('reserve_percent', 15))
    height = 96
    bars = [ft.Container(expand=1, height=max(2, row['soc'] / 100 * height), border_radius=1,
                         bgcolor=theme.ERROR if row['soc'] < reserve else
                         theme.AMBER if row['soc'] < reserve + 15 else theme.GREEN) for row in rows]
    chart = ft.Stack([
        ft.Container(ft.Row(bars, spacing=1, vertical_alignment=ft.CrossAxisAlignment.END), height=height,
                     alignment=ft.Alignment(0, 1)),
        ft.Container(height=1, bgcolor=theme.ERROR, left=0, right=0, top=height - reserve / 100 * height),
    ], height=height)
    return card([
        _heading('BATERIA PROJETADA (SoC)'),
        ft.Semantics(label=helpers.soc_summary(plan), container=True, content=chart),
        ft.Row([_small(plan['window']['start']), _small(f'Linha vermelha: reserva de {reserve:.0f}%'),
                _small(plan['window']['end'])], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        _small(helpers.soc_summary(plan)),
    ])


def stop_card(plan, stop, app, reserve_action):
    kind = 'refeicao_recarga' if stop['meal'] else 'recarga'
    label = f"{stop['meal']} + recarga" if stop['meal'] else 'Recarga'
    details = [
        ft.Row([ft.Container(width=10, height=36, bgcolor=_colors()[kind], border_radius=3),
                ft.Column([ft.Text(f"{stop['start']}–{stop['end']} · {label}", size=15, weight=ft.FontWeight.BOLD,
                                   color=theme.TEXT_COLOR),
                           ft.Text(stop['station_name'], size=13, color=theme.TEXT_COLOR)], spacing=2, expand=True)],
               spacing=10),
        _small(helpers.stop_line(stop)),
        _small(f"{stop['connector_type'].upper()} {stop['power_kw']:.0f} kW · {brl(stop['price_per_kwh'])}/kWh · "
               f"bateria {stop['soc_before']:.0f}% → {stop['soc_after']:.0f}% · ganho que deixa de fazer "
               f"{brl(stop['opportunity_cost'])}"),
        ft.Text(stop['reason'], size=13, color=theme.TEXT_COLOR),
    ]
    if stop.get('amenities'):
        details.append(_small('Comodidades: ' + helpers.amenities_text(stop['amenities'])))
    if stop.get('available_now') is False:
        details.append(_small('Ocupado agora — considere a fila estimada ou outro posto.', theme.AMBER))
    details.append(_station_actions(app, reserve_action, stop, can_reserve=helpers.stop_is_now(plan, stop)))
    return card(details, border=ft.Border.all(1, theme.LIGHT_GRAY))


def plan_view(plan, app, reserve_action):
    window = plan['window']
    source = plan['demand']['source']
    controls = [
        ft.Text(f"Plano {window['start']}–{window['end']} · {window['date'][8:10]}/{window['date'][5:7]}", size=20,
                weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR, font_family='BarlowCondensedBold'),
        _small(f"Demanda: {plan['demand']['label']} ({source}). {plan['stations_considered']} posto(s) compatíveis "
               'considerados.'),
        summary_card(plan),
    ]
    if plan['alerts']:
        controls.append(card([_heading('ALERTAS'), *(_alert_row(alert) for alert in plan['alerts'])]))
    controls.extend([timeline_card(plan), soc_card(plan)])
    if plan['stops']:
        controls.append(ft.Text('Paradas recomendadas', size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR,
                                font_family='BarlowCondensedBold'))
        controls.extend(stop_card(plan, stop, app, reserve_action) for stop in plan['stops'])
    controls.append(ft.ExpansionTile(
        title=ft.Text('Como calculamos', color=theme.TEXT_COLOR),
        controls=[_small('• ' + text) for text in plan.get('assumptions', [])]
        + [_small('• Demanda por horário é uma estimativa de grandes cidades brasileiras; não usamos dados oficiais '
                  'de aplicativos de transporte.')]))
    return controls


def next_stop_view(result, app, reserve_action):
    recommendation, status = result['recommendation'], result['status']
    peak = ' (pico estimado)' if status['in_peak'] else ''
    controls = [
        _heading('PRÓXIMA PARADA AGORA'),
        ft.Text(recommendation['headline'], size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
        ft.Text(recommendation['message'], size=13, color=theme.TEXT_COLOR),
        _small(f"Bateria {status['soc_percent']:.0f}% · ~{status['range_above_reserve_km']} km acima da reserva · "
               f"demanda agora x{status['demand_now']:.2f}{peak}".replace('.', ',')),
    ]
    if recommendation.get('station_id'):
        controls.append(_station_actions(app, reserve_action, recommendation,
                                         can_reserve=recommendation['action'] == 'stop_now'))
    if result.get('alternatives'):
        controls.append(_small('Se parar agora, melhores opções (custo + ganho perdido por kWh):'))
        for item in result['alternatives']:
            distance = f" · {km(item['distance_km'])}" if item.get('distance_km') is not None else ''
            controls.append(ft.Container(ft.Column([
                ft.Text(item['station_name'], size=14, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                _small(f"{brl(item['cost_per_kwh_effective'])}/kWh efetivo · +{kwh(item['kwh'])} em "
                       f"{duration(item['minutes'])} · {brl(item['cost'])}{distance}"),
                _station_actions(app, reserve_action, item, can_reserve=True, emphasize=False),
            ], spacing=4), padding=ft.Padding.symmetric(vertical=6)))
    for alert in result.get('alerts') or ():
        if alert.get('level') in ('warning', 'error') or alert.get('code') == 'rain':
            controls.append(_alert_row(alert))
    return [card(controls, border=ft.Border.all(1, theme.ACCENT))]
