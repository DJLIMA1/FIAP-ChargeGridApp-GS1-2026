"""Modo motorista de app: planeja recargas no turno para ganhar mais e parar menos.

Todo cálculo vem da API (``/v1/driver/*``) ou, no modo demo, do mesmo motor
``chargegrid_core.driver`` executado localmente. Demanda é sempre estimativa.

A tela não pergunta a bateria: o planejador usa o SoC escondido do carro
(``services.vehicle_state`` — sorteado por conta no modo oficial, a bateria do celular no modo
apresentação), nunca exibido como número. O carro e o turno vêm do perfil, o modo sai do horário,
o local da busca salva e o clima da API (Open-Meteo).
Layout = referência "Modo motorista" (402 x 874 pt) sem o cartão de bateria: subtítulo com o carro,
turno recolhível, "O APP já considera" (3 linhas que abrem o ajuste) e os botões
"Planejar meu turno" / "Próxima parada agora".
"""
from datetime import datetime

import flet as ft

from chargegrid_core.formatting import brl, duration, km, kwh

from ..api_client import ApiError
from ..demo import DEMO_LOCATIONS
from ..preferences import DriverProfileStore
from ..services import driver as helpers
from ..services import vehicle_state
from ..services.driver_demo import LOCAL_TZ
from ..services.location import geocode_address, geocode_demo_address
from ..services.search_location import SearchLocation
from ..ui import design, motion, theme
from ..ui.vehicle import VehiclePicker

DEMO_REGION = 'Villa Lobos'
RESULTS_KEY = 'driver-results'
DEMAND_SOURCES = {'heuristica': 'horários típicos', 'open-meteo': 'clima', 'informado': 'informado por você'}

# Medidas da referência (pt).
ROW_HEIGHT = 39
ROW_RADIUS = 8
CARD_RADIUS = 10
BUTTON_HEIGHT = 38
BUTTON_RADIUS = 10
ROW_TEXT = 11.5
CHEVRON_COLOR = '#A3A3A3'


def demand_source_text(source):
    """'heuristica+open-meteo' -> 'horários típicos + clima' (keys are API values)."""
    parts = [DEMAND_SOURCES.get(part, part) for part in str(source or '').split('+') if part]
    return ' + '.join(parts) or 'estimativa'


def _colors():
    return {'rodando': theme.GREEN, 'recarga': theme.BLUE, 'refeicao_recarga': theme.AMBER,
            'refeicao': theme.SLATE, 'pausa': theme.ERROR}


def _surface():
    """Cartões/linhas da referência (#191919 sobre o fundo #1F1F1F)."""
    return '#191919' if theme.is_dark() else theme.CARD


def _secondary_bg():
    return '#2E2E2E' if theme.is_dark() else theme.BTN_SECONDARY


def _track_off():
    return '#343434' if theme.is_dark() else theme.SEGMENT_OFF


def _label_style():
    return ft.TextStyle(size=11, font_family=design.FONT_BOLD, color=theme.GRAY_TEXT)


def _input_fill():
    """Campos dentro dos cartões #191919: um tom acima para o campo aparecer."""
    return '#262626' if theme.is_dark() else theme.INPUT_BG


def _rounded():
    return ft.OutlineInputBorder(border_radius=design.RADIUS_BTN + 2, side=ft.BorderSide(0, ft.Colors.TRANSPARENT))


def _dropdown(label, value, options):
    """Campo de escolha escuro (mesmo estilo do seletor de carro)."""
    return ft.Dropdown(
        label=label, value=value, options=[ft.DropdownOption(key=k, text=t) for k, t in options], expand=True,
        color=theme.INPUT_TEXT, bgcolor=theme.CARD, filled=True, fill_color=_input_fill(), border=_rounded(),
        border_radius=design.RADIUS_BTN + 2, label_style=_label_style(),
        text_style=ft.TextStyle(size=12.5, font_family=design.FONT, color=theme.INPUT_TEXT),
        content_padding=ft.Padding(left=13, right=13, top=13, bottom=13))


def _wide(control):
    """Dropdown ocupa a largura toda do cartão (Row + expand)."""
    return ft.Row([control])


def _field(label, value=''):
    """Campo escuro com rótulo cinza dentro (o teste e o leitor de tela usam ``label``)."""
    control = design.input_field('' if value is None else str(value))
    control.label, control.label_style, control.border, control.height = label, _label_style(), _rounded(), None
    control.fill_color = _input_fill()
    return control


def _number_field(label, value):
    control = _field(label, '' if value is None else str(value).replace('.', ','))
    control.keyboard_type = ft.KeyboardType.NUMBER
    return control


def _switch(label, value):
    return ft.Switch(label=label, value=bool(value), active_color=theme.BTN_PRIMARY_FG,
                     active_track_color=theme.BTN_PRIMARY, inactive_thumb_color=theme.GRAY_TEXT,
                     inactive_track_color=_track_off(),
                     label_text_style=ft.TextStyle(size=12.5, font_family=design.FONT, color=theme.TEXT_COLOR))


def _heading(text):
    return design.txt(text, 11, 'bold', theme.GRAY_TEXT)


def _small(text, color=None, **kwargs):
    return design.txt(text, 11.5, 'regular', color or theme.GRAY_TEXT, **kwargs)


def _button(text, on_click, *, primary=True, height=BUTTON_HEIGHT, size=15.5, expand=None):
    """Botão da referência: branco (texto preto) ou escuro, 38 pt, raio 10. ``content`` é o próprio texto."""
    return ft.Container(
        design.txt(text, size, 'medium', theme.BTN_PRIMARY_FG if primary else theme.BTN_SECONDARY_FG,
                   text_align=ft.TextAlign.CENTER),
        height=height, border_radius=BUTTON_RADIUS, alignment=ft.Alignment(0, 0), on_click=on_click, ink=True,
        bgcolor=theme.BTN_PRIMARY if primary else _secondary_bg(), expand=expand)


def _card(controls, *, border=None, padding=16, spacing=6):
    return ft.Container(ft.Column(controls, spacing=spacing, tight=True,
                                  horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                        bgcolor=_surface(), border_radius=CARD_RADIUS, padding=padding, border=border)


def _demo_locations():
    from ..services.driver_demo import DEMO_DRIVER_NETWORK
    return tuple(DEMO_LOCATIONS) + tuple(DEMO_DRIVER_NETWORK)


def _now(app, demo):
    """Horário local do planejador (o mesmo fuso da API); a demo usa o relógio simulado."""
    clock = getattr(app.api, '_now', None)
    current = clock() if demo and callable(clock) else datetime.now(LOCAL_TZ)
    return current.astimezone(LOCAL_TZ).replace(tzinfo=None)


def car_line(vehicle):
    """'BYD Dolphin - 321 km de autonomia' (subtítulo da referência)."""
    profile = helpers.vehicle_profile(vehicle)
    return f'{profile.name} - {round(profile.range_km)} km de autonomia' if profile else 'Qual é o seu carro?'


def mode_title(mode):
    """Título da linha do modo: reflete a escolha automática (ou manual)."""
    return 'Resto do turno' if mode == 'auto' else 'Turno completo'


def expandable_row(app, title, controls, *, expanded=False, chevron='right'):
    """Linha escura da referência (título em negrito + chevron) que abre o ajuste dentro do cartão.

    ``chevron='up'``: seção recolhível "Turno, ganhos e refeições" (como na referência).
    Retorna ``(container, title_text, body)``.
    """
    closed, opened = ((ft.Icons.KEYBOARD_ARROW_UP, ft.Icons.KEYBOARD_ARROW_DOWN) if chevron == 'up'
                      else (ft.Icons.CHEVRON_RIGHT, ft.Icons.KEYBOARD_ARROW_DOWN))
    icon = ft.Icon(opened if expanded else closed, size=20 if chevron == 'up' else 22, color=CHEVRON_COLOR
                   if theme.is_dark() else theme.GRAY_TEXT)
    heading = design.txt(title, ROW_TEXT, 'bold', expand=True)
    body = ft.Column(controls, spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    panel = ft.Container(body, padding=ft.Padding(left=14, right=14, top=0, bottom=14), visible=expanded)
    semantics = ft.Semantics(expanded=expanded, button=True, label=title)

    async def toggle(event=None):
        panel.visible = not panel.visible
        icon.icon = opened if panel.visible else closed
        semantics.expanded = panel.visible
        app.page.update()
    semantics.content = ft.Container(
        ft.Row([heading, icon], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=ROW_HEIGHT, padding=ft.Padding(left=14, right=11, top=0, bottom=0), on_click=toggle, ink=False,
        border_radius=ROW_RADIUS)
    box = ft.Container(ft.Column([semantics, panel], spacing=0, tight=True,
                                 horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                       bgcolor=_surface(), border_radius=ROW_RADIUS)
    return box, heading, panel


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


async def build(app, **_):
    demo = getattr(app.api, 'is_demo', False) is True
    state = getattr(app, 'driver_state', None)
    if not isinstance(state, dict):
        state = {}
        app.driver_state = state
    store = DriverProfileStore()
    local = None if demo else store.load()
    remote = await _remote_profile(app, demo)
    profile = remote if remote.get('saved') or not local else {**remote, **local}
    vehicle = dict(profile.get('vehicle') or {})
    prefs = dict(profile.get('preferences') or {})
    # A demonstração já vem com o carro padrão (BYD Dolphin): mostra o resumo, sem abrir o seletor.
    has_car = bool(remote.get('saved') or local or (demo and helpers.vehicle_profile(vehicle)))
    # Primeira vez: o turno ainda é o padrão e nunca foi planejado neste aparelho.
    first_time = not demo and not local and (not remote.get('saved') or prefs == helpers.default_preferences())

    # --- carro (do perfil): subtítulo; tocar abre o seletor -------------------------------------
    car_text = design.txt(car_line(vehicle) if has_car else 'Qual é o seu carro?', 13.4, 'regular')
    def car_changed(chosen):
        if chosen:
            car_text.value = car_line(chosen)
        app.page.update()

    picker = VehiclePicker(vehicle, remote.get('presets'), on_change=car_changed)
    picker_box = ft.Column([picker.control], visible=not has_car)

    async def toggle_picker(event=None):
        picker_box.visible = not picker_box.visible
        app.page.update()
    car_row = ft.Semantics(
        button=True, label='Trocar o carro',
        content=ft.Container(car_text, on_click=toggle_picker, ink=False, tooltip='Trocar o carro', height=16,
                             alignment=ft.Alignment(-1, 0), padding=ft.Padding(left=5, right=0, top=0, bottom=0)))

    # --- turno, ganhos e refeições (do perfil; aberto só na primeira vez) -------------------------
    shift_start = _field('Início do turno (HH:MM)', prefs.get('shift_start', '10:00'))
    shift_end = _field('Fim do turno (HH:MM)', prefs.get('shift_end', '22:00'))
    earnings = _number_field('Ganho médio por hora rodando (R$)', prefs.get('earnings_per_hour', 38))
    speed = _number_field('Km rodados por hora', prefs.get('km_per_hour', 22))
    reserve = _number_field('Reserva mínima (%)', prefs.get('reserve_percent', 15))
    target = _number_field('Carregar até (%)', prefs.get('max_charge_percent', 80))
    home = _switch('Tenho carregador em casa', prefs.get('home_charging', True))
    home_price = _number_field('Tarifa em casa (R$/kWh)', prefs.get('home_price_per_kwh', 0.95))
    saved_meals = {meal.get('kind'): meal for meal in prefs.get('meals') or []}
    meal_controls = []
    meal_rows = []
    for kind, label, default_start, default_duration, default_flex in helpers.MEALS:
        saved = saved_meals.get(kind)
        enabled = _switch(label, bool(saved and saved.get('enabled', True)))
        start = _field(f'{label} às (HH:MM)', (saved or {}).get('start', default_start))
        length = _number_field(f'Duração do {label.lower()} (min)', (saved or {}).get('duration_minutes', default_duration))
        flex = _dropdown('Flexibilidade', helpers.meal_flex(saved) if saved else default_flex, helpers.FLEX_CHOICES)
        meal_controls.append((kind, enabled, start, length, flex))
        meal_rows.append(ft.Column([enabled, ft.Row([ft.Container(start, expand=1), ft.Container(length, expand=1)]),
                                    _wide(flex)], spacing=10))

    shift_summary = _small(helpers.shift_summary(prefs) + ('' if first_time else ' · do seu perfil'))
    shift_section, _, _ = expandable_row(app, 'Turno, ganhos e refeições', [
        shift_summary,
        ft.Row([ft.Container(shift_start, expand=1), ft.Container(shift_end, expand=1)]), earnings, speed,
        ft.Row([ft.Container(reserve, expand=1), ft.Container(target, expand=1)]), home, home_price,
        _small('Refeições: o planejador tenta parar para comer num posto com restaurante ou café, '
               'recarregando enquanto você come.'), *meal_rows,
    ], expanded=first_time, chevron='up')

    # --- o que o app já considera (modo, local, clima), cada um com um ajuste opcional ----------
    now = _now(app, demo)
    mode = _dropdown('O que planejar', state.get('mode') if state.get('mode_manual') else
                     helpers.auto_mode(prefs, now), helpers.MODES)
    user = getattr(getattr(app.api, 'session', None), 'user', None) or {}
    account = (getattr(app, 'profile', None) or {}).get('id') or (user.get('id') if isinstance(user, dict) else None)
    saved_search = None if demo or not account else SearchLocation(account).load()
    region = _field('Bairro ou endereço', state.get('region', DEMO_REGION if demo else ''))
    rain = ft.Checkbox(label='Está chovendo agora (usar se a previsão errar)', value=bool(state.get('rain')),
                       fill_color={ft.ControlState.SELECTED: theme.BTN_PRIMARY}, check_color=theme.BTN_PRIMARY_FG,
                       label_style=ft.TextStyle(size=12.5, font_family=design.FONT, color=theme.TEXT_COLOR))
    mode_text, place_text, weather_text = (_small('') for _ in range(3))

    def place():
        text = (region.value or '').strip()
        if text:
            return f'Perto de {text}'
        if saved_search:
            return f"Perto de {saved_search['query'] or 'sua busca salva'} (busca salva)"
        return 'Sem local: considera todos os postos ativos'

    def refresh_context():
        mode_text.value = helpers.mode_line(mode.value, prefs)
        mode_heading.value = mode_title(mode.value)
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

    mode_row, mode_heading, _ = expandable_row(app, 'Turno completo', [mode_text, _wide(mode)])
    place_row, _, _ = expandable_row(app, 'Postos ativos por local', [
        place_text, region, _small('Sem GPS: use um bairro, endereço ou a busca salva em Postos.')])
    weather_row, _, _ = expandable_row(app, 'Situação climática', [weather_text, rain])
    refresh_context()

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
        # Bateria escondida do carro: sorteio da conta ou, no modo apresentação, a do celular.
        level, _ = await vehicle_state.current_soc(app)
        level = round(max(0.0, min(100.0, float(level))), 1)
        prefs.update(profile['preferences'])
        if not state.get('mode_manual'):
            # O turno pode ter mudado no formulário: o modo segue o horário.
            mode.value = helpers.auto_mode(profile['preferences'], _now(app, demo))
        state.update(rain=bool(rain.value))
        body = {'soc_percent': level, **profile, 'context': {'rain': True} if rain.value else {}}
        position = await locate()
        if position:
            body.update(lat=position[0], lng=position[1])
        await persist(profile)
        return body

    async def persist(profile):
        if not demo:
            store.save(profile)
        vehicle_state.remember_vehicle(app, profile['vehicle'])
        try:
            await app.api.request('PUT', 'driver/profile', profile)
        except ApiError as error:
            if error.status == 422:
                raise
            # Sem rede: o perfil fica no aparelho e o plano usa os dados enviados.
        # O carro agora está no perfil: some o seletor, fica o resumo.
        car_text.value = car_line(profile['vehicle'])
        picker_box.visible = False

    results = ft.Column(spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
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
            await body.scroll_to(scroll_key=RESULTS_KEY, duration=motion.duration(350))
        except (AttributeError, RuntimeError, AssertionError):
            pass  # Not mounted (tests) or no client: the results are still rendered.

    if state.get('plan') or state.get('next'):
        results.controls = result_controls()

    back = getattr(app, 'back', None) or app.link('home')
    body = ft.Column([
        ft.Container(car_row, margin=ft.Margin(left=0, top=0, right=0, bottom=1)),
        picker_box,
        shift_section,
        ft.Container(design.txt('O APP já considera', 11.5, 'bold'), height=20, alignment=ft.Alignment(-1, 0),
                     padding=ft.Padding(left=3, right=0, top=0, bottom=4)),
        mode_row, place_row, weather_row,
        _button('Planejar meu turno', app.action(plan_shift)),
        ft.Container(_button('Próxima parada agora', app.action(next_stop), primary=False),
                     margin=ft.Margin(left=0, top=1, right=0, bottom=0)),
        results,
        ft.Container(height=8),
    ], spacing=16, scroll=ft.ScrollMode.AUTO, expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    title = ft.Row([
        ft.Container(ft.Icon(ft.Icons.ARROW_BACK_IOS_NEW, size=14, color=theme.TEXT_COLOR), on_click=back, width=19,
                     height=34, tooltip='Voltar', alignment=ft.Alignment(-1, 0),
                     padding=ft.Padding(left=2, right=0, top=0, bottom=0)),
        design.txt('Modo motorista', 17.6, 'bold', expand=True),
    ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Column([title, ft.Container(body, expand=True, margin=ft.Margin(left=0, top=0, right=0, bottom=0))],
                     spacing=0, expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


# --- resultados ------------------------------------------------------------------------------

def _alert_row(alert):
    icon, color = {'error': (ft.Icons.ERROR_OUTLINE, theme.ERROR),
                   'warning': (ft.Icons.WARNING_AMBER_ROUNDED, theme.WARNING)}.get(
        alert.get('level'), (ft.Icons.INFO_OUTLINE, theme.GRAY_TEXT))
    return ft.Row([ft.Icon(icon, size=18, color=color),
                   design.txt(alert['message'], 12, 'regular', expand=True)],
                  spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)


def _station_actions(app, reserve_action, item, *, can_reserve, emphasize=True):
    row = [_button('Ver posto', app.link('stations', station_id=item['station_id']), primary=False, size=14)]
    if can_reserve and item.get('connector_id') and item.get('available_now') is not False:
        row.append(_button('Reservar', reserve_action(item['connector_id']), primary=emphasize, size=14))
    return ft.Row([ft.Container(control, expand=1) for control in row], spacing=8)


def summary_card(plan):
    totals, comparison, baseline = plan['totals'], plan['comparison'], plan['baseline']['totals']
    gain = comparison['net_profit_gain']
    gain_text = (f'+{brl(gain)} vs. recarregar só quando a bateria fica baixa' if gain >= 1
                 else 'Empata com recarregar só quando a bateria fica baixa')

    def metric(label, value):
        return ft.Column([_small(label), design.txt(value, 15, 'bold')], spacing=2, expand=True)
    return _card([
        _heading('LUCRO LÍQUIDO ESTIMADO DO TURNO'),
        design.money_text(brl(totals['net_profit']), 32),
        design.txt(gain_text, 12.5, 'semibold', theme.GREEN if gain >= 1 else theme.GRAY_TEXT),
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
    peaks = ft.Row([ft.Container(expand=1, height=6, bgcolor=theme.RED if (row['demand'] or 0) >= 1.3 else _track_off())
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
    rows = [ft.Row([design.txt(f"{block['start']}–{block['end']}", 12, 'regular', width=92),
                    ft.Container(width=10, height=10, bgcolor=colors[block['kind']], border_radius=2),
                    design.txt(f"{block['label']} · bateria → {block['soc_end']:.0f}%", 12,
                               'regular', expand=True)], spacing=8) for block in blocks]
    return _card([
        _heading('LINHA DO TEMPO DO TURNO'),
        ft.Semantics(label=helpers.plan_accessible_summary(plan), container=True,
                     content=ft.Column([bar, peaks, ticks], spacing=4)),
        legend, ft.Divider(height=8, color=_track_off()), *rows,
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
    return _card([
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
        ft.Row([ft.Container(width=6, height=36, bgcolor=_colors()[kind], border_radius=3),
                ft.Column([design.txt(f"{stop['start']}–{stop['end']} · {label}", 14, 'bold'),
                           design.txt(stop['station_name'], 12.5, 'regular')], spacing=2, expand=True)],
               spacing=10),
        _small(helpers.stop_line(stop)),
        _small(f"{stop['connector_type'].upper()} {stop['power_kw']:.0f} kW · {brl(stop['price_per_kwh'])}/kWh · "
               f"bateria {stop['soc_before']:.0f}% → {stop['soc_after']:.0f}%"
               + (f" · deixa de ganhar {brl(stop['opportunity_cost'])} em corridas"
                  if (stop.get('opportunity_cost') or 0) >= 0.01 else ' · sem perder corridas')),
        design.txt(stop['reason'], 12.5, 'regular'),
    ]
    if stop.get('amenities'):
        details.append(_small('Comodidades: ' + helpers.amenities_text(stop['amenities'])))
    if stop.get('available_now') is False:
        details.append(_small('Ocupado agora — considere a fila estimada ou outro posto.', theme.WARNING))
    details.append(ft.Container(_station_actions(app, reserve_action, stop, can_reserve=helpers.stop_is_now(plan, stop)),
                                margin=ft.Margin(left=0, top=4, right=0, bottom=0)))
    return _card(details)


def plan_view(plan, app, reserve_action):
    window = plan['window']
    source = plan['demand']['source']
    controls = [
        design.txt(f"Plano {window['start']}–{window['end']} · {window['date'][8:10]}/{window['date'][5:7]}", 15,
                   'bold'),
        _small(f"Estimativa, sem dados oficiais da Uber/99. Demanda: {plan['demand']['label']} "
               f"({demand_source_text(source)}). {plan['stations_considered']} posto(s) compatíveis considerados."),
        summary_card(plan),
    ]
    if plan['alerts']:
        controls.append(_card([_heading('ALERTAS'), *(_alert_row(alert) for alert in plan['alerts'])]))
    controls.extend([timeline_card(plan), soc_card(plan)])
    if plan['stops']:
        controls.append(design.txt('Paradas recomendadas', 15, 'bold'))
        controls.extend(stop_card(plan, stop, app, reserve_action) for stop in plan['stops'])
    controls.append(ft.Container(ft.ExpansionTile(
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.START,
        title=design.txt('Como calculamos', 13, 'bold'),
        icon_color=theme.TEXT_COLOR, collapsed_icon_color=theme.TEXT_COLOR,
        shape=ft.RoundedRectangleBorder(radius=ROW_RADIUS),
        collapsed_shape=ft.RoundedRectangleBorder(radius=ROW_RADIUS),
        controls=[_small('• ' + text) for text in plan.get('assumptions', [])]
        + [_small('• Demanda por horário é uma estimativa de grandes cidades brasileiras; não usamos dados oficiais '
                  'de aplicativos de transporte.')]), bgcolor=_surface(), border_radius=ROW_RADIUS))
    return controls


def next_stop_view(result, app, reserve_action):
    recommendation, status = result['recommendation'], result['status']
    peak = ' (pico estimado)' if status['in_peak'] else ''
    controls = [
        _heading('PRÓXIMA PARADA AGORA'),
        design.txt(recommendation['headline'], 16, 'bold'),
        design.txt(recommendation['message'], 12.5, 'regular'),
        # O SoC atual é escondido (services.vehicle_state): só a autonomia acima da reserva aparece.
        _small(f"~{max(0, round(status['range_above_reserve_km'] or 0))} km acima da reserva · "
               f"demanda agora {status['demand_now']:.2f}× a média{peak}".replace('.', ',')),
    ]
    if recommendation.get('station_id'):
        controls.append(ft.Container(_station_actions(app, reserve_action, recommendation,
                                                      can_reserve=recommendation['action'] in ('stop_now', 'charge_needed')),
                                     margin=ft.Margin(left=0, top=4, right=0, bottom=0)))
    if result.get('alternatives'):
        controls.append(_small('Se parar agora, melhores opções (custo + ganho perdido por kWh):'))
        for item in result['alternatives']:
            distance = f" · {km(item['distance_km'])}" if item.get('distance_km') is not None else ''
            controls.append(ft.Container(ft.Column([
                design.txt(item['station_name'], 13, 'semibold'),
                _small(f"{brl(item['cost_per_kwh_effective'])}/kWh efetivo · +{kwh(item['kwh'])} em "
                       f"{duration(item['minutes'])} · {brl(item['cost'])}{distance}"),
                _station_actions(app, reserve_action, item, can_reserve=True, emphasize=False),
            ], spacing=6), padding=ft.Padding(left=12, right=12, top=10, bottom=12), border_radius=ROW_RADIUS,
                border=ft.Border.all(1, _track_off())))
    for alert in result.get('alerts') or ():
        if alert.get('level') in ('warning', 'error') or alert.get('code') == 'rain':
            controls.append(_alert_row(alert))
    urgent = recommendation.get('action') == 'charge_needed'
    if urgent:
        controls[0] = ft.Row([ft.Icon(ft.Icons.BATTERY_ALERT, size=18, color=theme.ERROR),
                              _heading('RECARGA NECESSÁRIA')], spacing=6)
    return [_card(controls, spacing=8,
                  border=ft.Border.all(2 if urgent else 1, theme.ERROR if urgent else _track_off()))]
