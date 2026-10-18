"""Modo motorista de app: planeja recargas no turno para ganhar mais e parar menos.

Todo cálculo vem da API (``/v1/driver/*``) ou, no modo demo, do mesmo motor
``chargegrid_core.driver`` executado localmente. Demanda é sempre estimativa.

A tela pergunta só o que muda a cada turno (a bateria agora). O carro e o turno vêm do
perfil, o modo sai do horário, o local da busca salva e o clima da API (Open-Meteo).
"""
import asyncio
from datetime import datetime

import flet as ft

from chargegrid_core.formatting import brl, duration, km, kwh

from ..api_client import ApiError
from ..demo import DEMO_LOCATIONS
from ..preferences import DriverProfileStore
from ..services import driver as helpers
from ..services.driver_demo import LOCAL_TZ
from ..services.location import geocode_address, geocode_demo_address
from ..services.search_location import SearchLocation
from ..ui import motion, theme
from ..ui.components import button, card, disclosure_field, field, pill
from ..ui.vehicle import VehiclePicker

DEMO_REGION = 'Villa Lobos'
RESULTS_KEY = 'driver-results'
DEMAND_SOURCES = {'heuristica': 'horários típicos', 'open-meteo': 'clima', 'informado': 'informado por você'}
HERO_COLORS = ('#D72B32', '#7E1419')


def demand_source_text(source):
    """'heuristica+open-meteo' -> 'horários típicos + clima' (keys are API values)."""
    parts = [DEMAND_SOURCES.get(part, part) for part in str(source or '').split('+') if part]
    return ' + '.join(parts) or 'estimativa'


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


def _now(app, demo):
    """Horário local do planejador (o mesmo fuso da API); a demo usa o relógio simulado."""
    clock = getattr(app.api, '_now', None)
    current = clock() if demo and callable(clock) else datetime.now(LOCAL_TZ)
    return current.astimezone(LOCAL_TZ).replace(tzinfo=None)


def _link(text, on_click):
    return ft.TextButton(content=ft.Text(text, size=13, weight=ft.FontWeight.BOLD, color=theme.ACCENT),
                         on_click=on_click, style=ft.ButtonStyle(padding=ft.Padding(left=8, right=8, top=6, bottom=6)))


def _battery_color(level, reserve):
    return theme.ERROR if level < reserve else theme.WARNING if level < reserve + 15 else theme.GREEN


def _battery_icon(level):
    steps = (ft.Icons.BATTERY_ALERT, ft.Icons.BATTERY_1_BAR, ft.Icons.BATTERY_2_BAR, ft.Icons.BATTERY_3_BAR,
             ft.Icons.BATTERY_4_BAR, ft.Icons.BATTERY_5_BAR, ft.Icons.BATTERY_6_BAR, ft.Icons.BATTERY_FULL)
    return steps[min(len(steps) - 1, int(level // (100 / len(steps))))]


def hero(app):
    demo = getattr(app.api, 'is_demo', False) is True
    name = '' if demo else str((getattr(app, 'profile', None) or {}).get('name') or '').split(' ')[0]
    white = '#FFFFFF'
    tags = [pill(text, bg=ft.Colors.with_opacity(0.18, white), fg=white)
            for text in ('Estimativas', 'Sem dados oficiais da Uber/99')]
    return ft.Container(
        ft.Column([
            ft.Row([ft.Column([
                ft.Text(f'Bom turno, {name}' if name else 'Bom turno', size=13, color=white),
                ft.Text('Modo motorista', size=30, weight=ft.FontWeight.BOLD, color=white,
                        font_family='BarlowCondensedBold'),
                ft.Text('Rode nos picos, carregue nas horas fracas e junte a refeição com a recarga.',
                        size=13, color=white),
            ], spacing=2, expand=True), ft.Icon(ft.Icons.LOCAL_TAXI_OUTLINED, size=40, color=white)],
                vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Row(tags, wrap=True, spacing=6, run_spacing=6),
        ], spacing=10),
        gradient=ft.LinearGradient(begin=ft.Alignment(-1, -1), end=ft.Alignment(1, 1), colors=list(HERO_COLORS)),
        border_radius=16, padding=18)


async def _remote_profile(app, demo):
    try:
        return await app.api.request('GET', 'driver/profile')
    except ApiError as error:
        # Without network the screen still opens from the profile saved on
        # this device; only planning itself needs the API.
        if error.status != 0 or demo:
            raise
        app.notice('Sem conexão: usando o perfil salvo neste aparelho.')
        return {'saved': False}


async def _live_soc(app):
    """Bateria lida da recarga em andamento (quando o ponto informa o SoC)."""
    try:
        session = await app.api.request('GET', 'charging-sessions/current')
    except Exception:  # noqa: BLE001 - leitura opcional: o motorista ajusta a bateria
        return None
    soc = session.get('soc_percent') if isinstance(session, dict) else None
    return float(soc) if isinstance(soc, (int, float)) and 0 <= soc <= 100 else None


async def build(app):
    demo = getattr(app.api, 'is_demo', False) is True
    state = getattr(app, 'driver_state', None)
    if not isinstance(state, dict):
        state = {}
        app.driver_state = state
    store = DriverProfileStore()
    local = None if demo else store.load()
    remote, live_soc = await asyncio.gather(_remote_profile(app, demo), _live_soc(app))
    profile = remote if remote.get('saved') or not local else {**remote, **local}
    vehicle = dict(profile.get('vehicle') or {})
    prefs = dict(profile.get('preferences') or {})
    has_car = bool(remote.get('saved') or local)
    # Primeira vez: o turno ainda é o padrão e nunca foi planejado neste aparelho.
    first_time = not demo and not local and (not remote.get('saved') or prefs == helpers.default_preferences())

    # --- carro (do perfil) -----------------------------------------------------------------
    car_title = ft.Text(helpers.vehicle_headline(vehicle) if has_car else 'Qual é o seu carro?', size=16,
                        weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR)
    car_note = _small('Do seu perfil · usado em todos os planos' if has_car else
                      'Escolha uma vez: fica salvo no seu perfil.')

    def car_changed(chosen):
        if chosen:
            car_title.value = helpers.vehicle_headline(chosen)
        refresh_battery()
        app.page.update()

    picker = VehiclePicker(vehicle, remote.get('presets'), on_change=car_changed)
    picker_box = ft.Column([picker.control], visible=not has_car)

    async def toggle_picker(event=None):
        picker_box.visible = not picker_box.visible
        swap.content.value = 'Fechar' if picker_box.visible else 'Trocar'
        app.page.update()
    swap = _link('Trocar', toggle_picker)
    swap.visible = has_car
    car_card = card([
        ft.Row([ft.Container(ft.Icon(ft.Icons.ELECTRIC_CAR_OUTLINED, size=24, color=theme.ACCENT),
                             bgcolor=theme.LIGHT_GRAY, border_radius=10, padding=8),
                ft.Column([car_title, car_note], spacing=1, expand=True), swap],
               spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        picker_box,
    ], border=ft.Border.all(1, theme.LIGHT_GRAY))

    # --- bateria agora: a única pergunta de cada turno -------------------------------------
    # 0 % is a real reading: only a missing value falls back to the next source.
    soc_value = next((value for value in (state.get('soc'), live_soc, (local or {}).get('soc_percent'))
                      if value is not None), 60)
    soc_value = round(max(0, min(100, float(soc_value))))
    soc = ft.Slider(value=soc_value, min=0, max=100, divisions=100, data='soc',
                    active_color=theme.RED, inactive_color=theme.LIGHT_GRAY, thumb_color=theme.RED)
    readout = ft.Text(f'{soc_value}%', size=44, weight=ft.FontWeight.BOLD, font_family='BarlowCondensedBold')
    battery_icon = ft.Icon(_battery_icon(soc_value), size=34)
    range_text = ft.Text('', size=13, color=theme.TEXT_COLOR)
    soc_source = _small('Lida da sua recarga em andamento.' if live_soc is not None and state.get('soc') is None
                        else 'Arraste para a carga que o painel do carro mostra agora.')

    def reserve_level():
        try:
            return helpers.number(reserve.value, 'a reserva', 5, 50)
        except ApiError:
            return float(prefs.get('reserve_percent', 15))

    def refresh_battery():
        level = round(float(soc.value or 0))
        color = _battery_color(level, reserve_level())
        readout.value, readout.color = f'{level}%', color
        battery_icon.icon, battery_icon.color = _battery_icon(level), color
        range_text.value = helpers.battery_line(picker.read(strict=False), level, reserve_level())

    async def soc_changed(event=None):
        state['soc'] = round(float(soc.value or 0))
        refresh_battery()
        app.page.update()

    async def step(delta):
        soc.value = max(0, min(100, round(float(soc.value or 0)) + delta))
        await soc_changed()
    soc.on_change = soc_changed

    def stepper(icon, delta, label):
        async def clicked(event=None):
            await step(delta)
        return ft.IconButton(icon=icon, on_click=clicked, tooltip=label, icon_color=theme.TEXT_COLOR,
                             style=ft.ButtonStyle(bgcolor=theme.LIGHT_GRAY))

    battery_card = card([
        _heading('BATERIA AGORA'),
        ft.Row([battery_icon, readout, ft.Container(expand=True),
                stepper(ft.Icons.REMOVE, -1, 'Menos 1%'), stepper(ft.Icons.ADD, 1, 'Mais 1%')],
               spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Semantics(label='Bateria agora (%)', content=soc),
        range_text, soc_source,
    ], border=ft.Border.all(1, theme.LIGHT_GRAY))

    # --- turno, ganhos e refeições (do perfil; aberto só na primeira vez) --------------------
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

    shift_section, _ = disclosure_field(
        'Turno, ganhos e refeições',
        helpers.shift_summary(prefs) + ('' if first_time else ' · do seu perfil'),
        [ft.Row([ft.Container(shift_start, expand=1), ft.Container(shift_end, expand=1)]), earnings, speed,
         ft.Row([ft.Container(reserve, expand=1), ft.Container(target, expand=1)]), home, home_price,
         _small('Refeições: o planejador tenta parar para comer num posto com restaurante ou café, '
                'recarregando enquanto você come.'), *meal_rows],
        expanded=first_time, on_update=lambda: app.page.update())
    reserve.on_change = soc_changed

    # --- o que o app já sabe (modo, local, clima), cada um com um ajuste opcional ----------------
    now = _now(app, demo)
    mode = _dropdown('O que planejar', state.get('mode') if state.get('mode_manual') else
                     helpers.auto_mode(prefs, now), helpers.MODES)
    user = getattr(getattr(app.api, 'session', None), 'user', None) or {}
    account = (getattr(app, 'profile', None) or {}).get('id') or (user.get('id') if isinstance(user, dict) else None)
    saved_search = None if demo or not account else SearchLocation(account).load()
    region = field('Bairro ou endereço', state.get('region', DEMO_REGION if demo else ''))
    rain = ft.Checkbox(label='Está chovendo agora (usar se a previsão errar)', value=bool(state.get('rain')))
    mode_text, place_text, weather_text = (ft.Text('', size=13, color=theme.TEXT_COLOR, expand=True) for _ in range(3))

    def place():
        text = (region.value or '').strip()
        if text:
            return f'Perto de {text}'
        if saved_search:
            return f"Perto de {saved_search['query'] or 'sua busca salva'} (busca salva)"
        return 'Sem local: considera todos os postos ativos'

    def refresh_context():
        mode_text.value = helpers.mode_line(mode.value, prefs)
        place_text.value = place()
        located = bool((region.value or '').strip() or saved_search)
        weather_text.value = ('Chuva informada por você' if rain.value else
                              'Demonstração: clima não consultado' if demo else
                              'Clima ao vivo (Open-Meteo) entra no plano' if located else
                              'Sem local, sem clima: usa horários típicos')

    async def context_changed(event=None):
        if event is not None and event.control is mode:
            state.update(mode=mode.value, mode_manual=True)
        refresh_context()
        app.page.update()
    mode.on_select = context_changed
    region.on_change = rain.on_change = context_changed

    def context_row(icon, text, action, controls):
        box = ft.Column(controls, spacing=8, visible=False)

        async def toggle(event=None):
            box.visible = not box.visible
            app.page.update()
        return ft.Column([ft.Row([ft.Icon(icon, size=20, color=theme.GRAY_TEXT), text, _link(action, toggle)],
                                 spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER), box], spacing=4)

    context_card = card([
        _heading('O APP JÁ CONSIDERA'),
        context_row(ft.Icons.SCHEDULE, mode_text, 'Mudar', [_wide(mode)]),
        context_row(ft.Icons.PLACE_OUTLINED, place_text, 'Mudar local',
                    [region, _small('Sem GPS: use um bairro, endereço ou a busca salva em Postos.')]),
        context_row(ft.Icons.CLOUD_OUTLINED, weather_text, 'Ajustar', [rain]),
    ], border=ft.Border.all(1, theme.LIGHT_GRAY))
    refresh_context()
    refresh_battery()

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
        chosen = picker.read(strict=True)
        if chosen is None:
            raise ApiError('Escolha o seu carro para planejar.')
        return {'vehicle': chosen, 'preferences': preferences}

    async def locate():
        text = (region.value or '').strip()
        state['region'] = text
        if not text:
            return (saved_search['lat'], saved_search['lng']) if saved_search else None
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
        prefs.update(profile['preferences'])
        if not state.get('mode_manual'):
            # O turno pode ter mudado no formulário: o modo segue o horário.
            mode.value = helpers.auto_mode(profile['preferences'], _now(app, demo))
        state.update(soc=level, rain=bool(rain.value))
        body = {'soc_percent': level, **profile, 'context': {'rain': True} if rain.value else {}}
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
        # O carro agora está no perfil: some o seletor, fica o resumo.
        car_title.value = helpers.vehicle_headline(profile['vehicle'])
        car_note.value = 'Do seu perfil · usado em todos os planos'
        picker_box.visible, swap.visible, swap.content.value = False, True, 'Trocar'

    results = ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                        key=ft.ScrollKey(RESULTS_KEY))

    async def plan_shift():
        body = await request_body()
        result = await app.api.request('POST', 'driver/plan', {**body, 'mode': mode.value})
        state.update(plan=result, next=None)
        await show()

    async def next_stop():
        body = await request_body()
        result = await app.api.request('POST', 'driver/next-stop', body)
        state.update(next=result)
        await show()

    def reserve_action(connector_id):
        async def reserve_point():
            key = state.setdefault('reserve_keys', {}).setdefault(connector_id, app.api.new_key())
            await app.api.request('POST', 'reservations', {'connector_id': connector_id}, key=key)
            state['reserve_keys'].pop(connector_id, None)
            await app.go('reservations')
        return app.action(reserve_point)

    def result_controls():
        return [*(next_stop_view(state['next'], app, reserve_action) if state.get('next') else []),
                *(plan_view(state['plan'], app, reserve_action) if state.get('plan') else [])]

    async def show():
        refresh_context()
        results.controls = result_controls()
        app.page.update()
        # The answer appears below the form: bring it into view instead of
        # leaving the user wondering whether the button worked.
        try:
            await screen.scroll_to(scroll_key=RESULTS_KEY, duration=motion.duration(350))
        except (AttributeError, RuntimeError, AssertionError):
            pass  # Not mounted (tests) or no client: the results are still rendered.

    if state.get('plan') or state.get('next'):
        results.controls = result_controls()

    actions = ft.Column([
        button('Planejar meu turno', app.action(plan_shift)),
        button('Próxima parada agora', app.action(next_stop), secondary=True),
        _small('Consideramos consumo, autonomia, picos estimados, refeições, potência, tarifa e ocupação dos postos.',
               text_align=ft.TextAlign.CENTER),
    ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    screen = ft.Column([hero(app), car_card, battery_card, context_card, shift_section, actions, results],
                       spacing=12, expand=True, scroll=ft.ScrollMode.AUTO,
                       horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    return screen


# --- resultados ------------------------------------------------------------------------------

def _alert_row(alert):
    icon, color = {'error': (ft.Icons.ERROR_OUTLINE, theme.ERROR),
                   'warning': (ft.Icons.WARNING_AMBER_ROUNDED, theme.WARNING)}.get(
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
        _small(f"Sem planejar: {brl(baseline['net_profit'])} líquido, {baseline['stops']} parada(s), "
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
               f"bateria {stop['soc_before']:.0f}% → {stop['soc_after']:.0f}%"
               + (f" · deixa de ganhar {brl(stop['opportunity_cost'])} em corridas"
                  if (stop.get('opportunity_cost') or 0) >= 0.01 else ' · sem perder corridas')),
        ft.Text(stop['reason'], size=13, color=theme.TEXT_COLOR),
    ]
    if stop.get('amenities'):
        details.append(_small('Comodidades: ' + helpers.amenities_text(stop['amenities'])))
    if stop.get('available_now') is False:
        details.append(_small('Ocupado agora — considere a fila estimada ou outro posto.', theme.WARNING))
    details.append(_station_actions(app, reserve_action, stop, can_reserve=helpers.stop_is_now(plan, stop)))
    return card(details, border=ft.Border.all(1, theme.LIGHT_GRAY))


def plan_view(plan, app, reserve_action):
    window = plan['window']
    source = plan['demand']['source']
    controls = [
        ft.Text(f"Plano {window['start']}–{window['end']} · {window['date'][8:10]}/{window['date'][5:7]}", size=20,
                weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR, font_family='BarlowCondensedBold'),
        _small(f"Demanda: {plan['demand']['label']} ({demand_source_text(source)}). "
               f"{plan['stations_considered']} posto(s) compatíveis considerados."),
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
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.START,
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
        _small(f"Bateria {status['soc_percent']:.0f}% · ~{max(0, round(status['range_above_reserve_km'] or 0))} km acima da reserva · "
               f"demanda agora {status['demand_now']:.2f}× a média{peak}".replace('.', ',')),
    ]
    if recommendation.get('station_id'):
        controls.append(_station_actions(app, reserve_action, recommendation,
                                         can_reserve=recommendation['action'] in ('stop_now', 'charge_needed')))
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
    urgent = recommendation.get('action') == 'charge_needed'
    if urgent:
        controls[0] = ft.Row([ft.Icon(ft.Icons.BATTERY_ALERT, size=18, color=theme.ERROR),
                              _heading('RECARGA NECESSÁRIA')], spacing=6)
    return [card(controls, border=ft.Border.all(2 if urgent else 1, theme.ERROR if urgent else theme.ACCENT))]
