"""Modo motorista de app: planeja recargas no turno para ganhar mais e parar menos.

Todo cálculo vem da API (``/v1/driver/*``) ou, no modo demo, do mesmo motor
``chargegrid_core.driver`` executado localmente. Demanda é sempre estimativa.

Tela enxuta: o motorista não precisa preencher nada.
- Bateria: o SoC escondido do carro (``services.vehicle_state``), nunca exibido como número.
- Carro: o do perfil (ou do cadastro); o seletor só aparece quando não há carro.
- Cartão "Agora" (só leitura): turno e demanda, local, clima e ganho por hora — vindos do perfil, do
  local e de ``GET driver/context`` (clima Open-Meteo; simulado na demo).
- Local: GPS do celular (``services.geolocation``; em segundo plano, só se a permissão já existe — pedir
  só ao tocar "Usar minha localização") → último local salvo (``SearchLocation``) → busca com sugestões.
- Turno nunca informado ("auto") que não cobre agora: planeja de agora até +10 h.
- Ganho: R$ 38/h **estimado** até o motorista informar o dele em Ajustes.
- "Ajustes" (sempre recolhido): turno, ganho, refeições, carregador em casa e "Avançado".
"""
import asyncio
from datetime import datetime

import flet as ft

from chargegrid_core.formatting import brl, duration, km, kwh

from ..api_client import ApiError
from ..demo import DEMO_LOCATIONS
from ..preferences import DriverProfileStore
from ..services import driver as helpers
from ..services import geolocation, vehicle_state
from ..services.driver_demo import LOCAL_TZ
from ..services.location import coordinates_for, geocode_demo_address
from ..services.search_location import SearchLocation
from ..ui import address_autocomplete, design, motion, theme
from ..ui.vehicle import VehiclePicker

DEMO_REGION = 'Villa Lobos'
RESULTS_KEY = 'driver-results'
DEMAND_SOURCES = {'heuristica': 'horários típicos', 'open-meteo': 'clima', 'simulado': 'clima simulado',
                  'informado': 'informado por você'}
DISCLAIMER = 'Estimativa — sem dados oficiais da Uber/99.'
CONTEXT_TIMEOUT = 4.0
SEARCH_RADIUS_KM = 30
CAPTURE_RUNS = ('auto', 'full_shift', 'next')

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
        border_radius=design.RADIUS_BTN + 2, label_style=_label_style(), menu_height=320,
        text_style=ft.TextStyle(size=12.5, font_family=design.FONT, color=theme.INPUT_TEXT),
        content_padding=ft.Padding(left=13, right=13, top=13, bottom=13))


def _field(label, value=''):
    """Campo escuro com rótulo cinza dentro (o teste e o leitor de tela usam ``label``)."""
    control = design.input_field('' if value is None else str(value))
    control.label, control.label_style, control.border, control.height = label, _label_style(), _rounded(), None
    control.fill_color = _input_fill()
    return control


def _number_field(label, value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # 38.0 -> "38"
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


def _pair(left, right):
    return ft.Row([ft.Container(left, expand=1), ft.Container(right, expand=1)], spacing=10,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _button(text, on_click, *, primary=True, height=BUTTON_HEIGHT, size=15.5, expand=None):
    """Botão da referência: branco (texto preto) ou escuro, 38 pt, raio 10. ``content`` é o próprio texto."""
    return ft.Container(
        design.txt(text, size, 'medium', theme.BTN_PRIMARY_FG if primary else theme.BTN_SECONDARY_FG,
                   text_align=ft.TextAlign.CENTER),
        height=height, border_radius=BUTTON_RADIUS, alignment=ft.Alignment(0, 0), on_click=on_click, ink=True,
        bgcolor=theme.BTN_PRIMARY if primary else _secondary_bg(), expand=expand)


def _link(text, on_click):
    """Ação de texto à direita de uma linha ("Alterar", "Ajustar"). ``content`` é o próprio texto."""
    return ft.Container(design.txt(text, 12, 'semibold'), on_click=on_click, ink=False,
                        padding=ft.Padding(left=8, right=2, top=6, bottom=6))


def _card(controls, *, border=None, padding=16, spacing=6):
    return ft.Container(ft.Column(controls, spacing=spacing, tight=True,
                                  horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                        bgcolor=_surface(), border_radius=CARD_RADIUS, padding=padding, border=border)


def _details(title, controls):
    """Seção recolhida ("Ver detalhes", "Outras opções") no estilo das linhas da referência."""
    return ft.Container(ft.ExpansionTile(
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
        title=design.txt(title, 13, 'bold'),
        icon_color=theme.TEXT_COLOR, collapsed_icon_color=theme.TEXT_COLOR,
        shape=ft.RoundedRectangleBorder(radius=ROW_RADIUS),
        collapsed_shape=ft.RoundedRectangleBorder(radius=ROW_RADIUS),
        controls_padding=ft.Padding(left=14, right=14, top=0, bottom=14),
        controls=controls), bgcolor=_surface(), border_radius=ROW_RADIUS)


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


def expandable_row(app, title, controls, *, expanded=False, chevron='right'):
    """Linha escura da referência (título em negrito + chevron) que abre o conteúdo dentro do cartão.

    Retorna ``(container, title_text, body)``; ``container.data`` é a função que abre/fecha.
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
                       bgcolor=_surface(), border_radius=ROW_RADIUS, data=toggle)
    return box, heading, panel


def context_row(icon, text, action=None):
    """Linha do cartão "Agora": ícone, texto (até 2 linhas) e uma ação opcional à direita."""
    items = [ft.Icon(icon, size=17, color=theme.GRAY_TEXT), ft.Container(text, expand=True)]
    if action is not None:
        items.append(action)
    return ft.Row(items, spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)


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


def _without_sources(body):
    """Mesmo pedido sem ``preferences.sources`` (APIs anteriores a este campo respondem 422)."""
    preferences = body.get('preferences')
    if not isinstance(preferences, dict) or 'sources' not in preferences:
        return None
    return {**body, 'preferences': {key: value for key, value in preferences.items() if key != 'sources'}}


async def send(app, state, method, path, body):
    """Pedido ``driver/*`` com ``sources``; numa API antiga (422), repete uma vez sem o campo."""
    if state.get('sources_unsupported'):
        body = _without_sources(body) or body
    try:
        return await app.api.request(method, path, body)
    except ApiError as error:
        legacy = _without_sources(body) if error.status == 422 else None
        if legacy is None:
            raise
        result = await app.api.request(method, path, legacy)
        state['sources_unsupported'] = True
        return result


async def build(app, run=None, soc=None, ajustes=False, **_):
    from chargegrid_core.driver import DISCONTINUED
    if DISCONTINUED:
        # Descontinuado (20/10/2026): links antigos caem aqui, sem chamar a API.
        return design.page(design.txt('O Modo motorista foi descontinuado.', 15, 'bold'),
                           design.txt('Use Recarga para encontrar e reservar um ponto.', 12.5, 'regular',
                                      theme.GRAY_TEXT),
                           design.primary_button('Encontrar um ponto', app.link('stations'), height=48),
                           title='Modo motorista', on_back=app.link('home'))
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
    origin = helpers.sources(prefs)
    edited = {'earnings': False, 'shift': False}
    # A demonstração já vem com o carro padrão (BYD Dolphin): mostra o resumo, sem abrir o seletor.
    has_car = bool(remote.get('saved') or local or (demo and helpers.vehicle_profile(vehicle)))

    # --- carro (do perfil): subtítulo; tocar abre o seletor -------------------------------------
    car_text = design.txt(car_line(vehicle) if has_car else 'Qual é o seu carro?', 13.4, 'regular', expand=True)

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
        content=ft.Container(ft.Row([car_text, design.txt('Trocar', 12, 'semibold', theme.GRAY_TEXT)], spacing=8),
                             on_click=toggle_picker, ink=False, tooltip='Trocar o carro', height=18,
                             padding=ft.Padding(left=5, right=2, top=0, bottom=0)))

    # --- Ajustes (sempre recolhido): só para quem quer mudar o que o app já considera -------------
    start_value, end_value = prefs.get('shift_start', '10:00'), prefs.get('shift_end', '22:00')
    shift_start = _dropdown('Início do turno', start_value, helpers.time_options(start_value))
    shift_end = _dropdown('Fim do turno', end_value, helpers.time_options(end_value))
    shift_note = _small('')
    earnings = _number_field('Ganho médio por hora rodando (R$)', prefs.get('earnings_per_hour', 38))
    earnings_note = _small('')
    speed = _number_field('Km rodados por hora', prefs.get('km_per_hour', 22))
    reserve = _number_field('Reserva mínima (%)', prefs.get('reserve_percent', 15))
    target = _number_field('Carregar até (%)', prefs.get('max_charge_percent', 80))
    home = _switch('Tenho carregador em casa', prefs.get('home_charging', True))
    home_price = _number_field('Tarifa em casa (R$/kWh)', prefs.get('home_price_per_kwh', 0.95))
    home_price.visible = bool(home.value)
    saved_meals = {meal.get('kind'): meal for meal in prefs.get('meals') or [] if isinstance(meal, dict)}
    meal_controls, meal_rows = [], []
    for kind, label, default_start, *_ in helpers.MEALS:
        if kind not in helpers.VISIBLE_MEALS:
            continue
        saved = saved_meals.get(kind)
        value = (saved or {}).get('start', default_start)
        enabled = _switch(label, bool(saved and saved.get('enabled', True)))
        start = _dropdown(f'{label} às', value, helpers.time_options(value))
        meal_controls.append((kind, enabled, start))
        meal_rows.append(_pair(enabled, start))

    advanced, _, _ = expandable_row(app, 'Avançado', [
        _small('Valores padrão do planejador; mude só se precisar.'), speed, _pair(reserve, target)])
    settings, _, settings_panel = expandable_row(app, 'Ajustes', [
        _small('O app já preenche tudo. Mude só o que for diferente para você.'),
        _heading('TURNO'), _pair(shift_start, shift_end), shift_note,
        _heading('GANHO POR HORA'), earnings, earnings_note,
        _heading('REFEIÇÕES'),
        _small('O plano tenta parar para comer num posto com restaurante ou café, recarregando enquanto você come.'),
        *meal_rows,
        _heading('CARREGADOR EM CASA'), home, home_price,
        advanced,
    ])

    def current_sources():
        return {'earnings_per_hour': 'informado' if edited['earnings'] else origin['earnings_per_hour'],
                'shift': 'informado' if edited['shift'] else origin['shift']}

    def form_prefs():
        """Preferências como estão no formulário (sem validar) para as linhas do cartão "Agora"."""
        current = {**prefs, 'shift_start': shift_start.value, 'shift_end': shift_end.value,
                   'sources': current_sources()}
        try:
            current['earnings_per_hour'] = helpers.number(earnings.value, 'o ganho', 0, 500)
        except ApiError:
            pass
        return current

    def effective():
        try:
            return helpers.effective_preferences(form_prefs(), _now(app, demo))
        except (ValueError, TypeError):
            return form_prefs()

    def plan_mode(preferences):
        if demo and run in ('auto', 'full_shift'):
            return run
        return helpers.auto_mode(preferences, _now(app, demo))

    # --- local: último salvo (por conta) ou busca com sugestões --------------------------------
    user = getattr(getattr(app.api, 'session', None), 'user', None) or {}
    account = (getattr(app, 'profile', None) or {}).get('id') or (user.get('id') if isinstance(user, dict) else None)
    searches = None if demo or not account else SearchLocation(account)
    if not state.get('place'):
        saved_search = searches.load() if searches else None
        if saved_search:
            state['place'] = {'label': saved_search['query'] or 'local salvo', 'lat': saved_search['lat'],
                              'lng': saved_search['lng'], 'source': 'saved'}
        elif demo:
            found = geocode_demo_address(DEMO_REGION, _demo_locations())
            if found:
                state['place'] = {'label': DEMO_REGION, 'lat': found[0], 'lng': found[1], 'source': 'demo'}

    region = _field('Bairro ou endereço', '')
    region.hint_text = 'Ex.: Pinheiros, Av. Paulista 1000'

    # --- cartão "Agora" (só leitura) ---------------------------------------------------------------
    shift_text, place_text, weather_text, earnings_text = (
        design.txt('', 12.5, 'regular', max_lines=2) for _ in range(4))
    rain = ft.Checkbox(label='Está chovendo agora', value=bool(state.get('rain')),
                       fill_color={ft.ControlState.SELECTED: theme.BTN_PRIMARY}, check_color=theme.BTN_PRIMARY_FG,
                       label_style=ft.TextStyle(size=12, font_family=design.FONT, color=theme.TEXT_COLOR))

    def weather_icon():
        weather = (state.get('context') or {}).get('weather') or {}
        if weather.get('rain_now') or weather.get('next_rain_at'):
            return ft.Icons.WATER_DROP_OUTLINED
        return ft.Icons.CLOUD_OUTLINED if helpers.weather_live(weather) else ft.Icons.CLOUD_OFF_OUTLINED

    rain_box = ft.Container(rain, margin=ft.Margin(left=20, top=-6, right=0, bottom=0))
    weather_glyph = ft.Icon(ft.Icons.CLOUD_OUTLINED, size=17, color=theme.GRAY_TEXT)

    def refresh_lines():
        current = effective()
        context = state.get('context')
        shift_text.value = helpers.shift_line(current, plan_mode(current), context)
        place = state.get('place')
        place_text.value = ('Perto de você · localização atual' if place and place.get('source') == 'gps' else
                            f"Perto de {place['label']}" if place else
                            'Onde você está? Informe para ver clima e postos perto')
        gps_row.visible = gps and not (place and place.get('source') == 'gps')
        weather = (context or {}).get('weather')
        weather_text.value = helpers.weather_line(weather)
        weather_glyph.icon = weather_icon()
        rain.visible = rain_box.visible = not helpers.weather_live(weather)
        earnings_text.value = helpers.earnings_info(form_prefs())['label']
        sources_now = current_sources()
        earnings_note.value = ('Estimado pelo ChargeGrid (valor de referência, não é o seu histórico). '
                               'Troque pelo seu ganho real, se souber.'
                               if sources_now['earnings_per_hour'] == 'estimativa' else 'Informado por você.')
        shift_note.value = ('Sem turno informado: o plano vai de agora até 10 h depois quando você estiver fora '
                            'deste horário.' if sources_now['shift'] == 'auto' else 'Turno informado por você.')

    async def refresh_context():
        place = state.get('place')
        params = {'lat': place['lat'], 'lng': place['lng']} if place else None
        try:
            state['context'] = await asyncio.wait_for(
                app.api.request('GET', 'driver/context', params=params), CONTEXT_TIMEOUT)
        except (ApiError, asyncio.TimeoutError, OSError, TypeError, ValueError):
            state['context'] = None  # sem rede ou API antiga: o cartão segue com o que o app sabe
        refresh_lines()

    def remember(place):
        state['place'] = {**place, 'source': 'manual'}
        state['region_text'] = place['label']
        if searches:
            searches.save({'lat': place['lat'], 'lng': place['lng'], 'radius': SEARCH_RADIUS_KM,
                           'query': place['label'][:300]})

    async def picked(item):
        if item.get('latitude') is None:
            app.notice('Esse resultado não tem coordenadas; escolha outro endereço.')
            return
        remember({'label': item['label'], 'lat': float(item['latitude']), 'lng': float(item['longitude'])})
        region.value = ''
        editor.visible = False
        await refresh_context()

    suggestions = address_autocomplete.attach(app, region, on_pick=picked)

    async def locate():
        """Local do plano: o texto digitado (se mudou), senão o último local escolhido."""
        text = ' '.join((region.value or '').split())
        place = state.get('place')
        if not text or (place and text == place['label']):
            return (place['lat'], place['lng']) if place else None
        found = geocode_demo_address(text, _demo_locations()) if demo else None
        if found is None:
            found = await coordinates_for(app.api, text)
        if found is None:
            app.notice('Não encontramos esse local; '
                       + ('usando o último local escolhido.' if place else 'planejando com todos os postos ativos.'))
            return (place['lat'], place['lng']) if place else None
        remember({'label': text, 'lat': found[0], 'lng': found[1]})
        region.value = ''
        editor.visible = False
        await refresh_context()
        return found

    async def submit_region(event=None):
        await locate()
        app.page.update()
    region.on_submit = submit_region
    editor = ft.Column([region, suggestions, _small('Escolha uma sugestão; o local fica salvo para a próxima vez.')],
                       spacing=6, visible=not state.get('place'))

    gps = geolocation.available(app)

    def use_position(position):
        state['place'] = {'label': 'Localização atual', 'lat': position[0], 'lng': position[1], 'source': 'gps'}
        editor.visible = False

    async def use_gps(event=None):
        """Toque em "Usar minha localização": aqui (e só aqui) o app pede a permissão."""
        position = await geolocation.current_position(app, ask=True)
        if position is None:
            app.notice('Não deu para usar a localização (permissão negada ou GPS desligado). '
                       'Informe um bairro ou endereço.')
            editor.visible = True
            app.page.update()
            return
        use_position(position)
        await refresh_context()
        app.page.update()

    async def silent_gps():
        """Ao abrir: posição atual só se a permissão já foi dada; nunca segura a tela."""
        position = await geolocation.current_position(app)
        if position is None or (state.get('place') or {}).get('source') == 'manual':
            return
        use_position(position)
        await refresh_context()
        app.page.update()

    gps_row = ft.Row([
        ft.Container(_small('O GPS só serve para achar postos e o clima perto de você.'), expand=True),
        _link('Usar minha localização', use_gps)], spacing=8, visible=gps,
        vertical_alignment=ft.CrossAxisAlignment.CENTER)

    async def toggle_editor(event=None):
        editor.visible = not editor.visible
        app.page.update()

    async def open_settings(event=None):
        if not settings_panel.visible:
            await settings.data()
        else:
            app.page.update()

    async def form_changed(event=None):
        control = getattr(event, 'control', None)
        if control is earnings:
            edited['earnings'] = True
        elif control in (shift_start, shift_end):
            edited['shift'] = True
        refresh_lines()
        app.page.update()

    async def home_changed(event=None):
        home_price.visible = bool(home.value)
        app.page.update()
    earnings.on_change = form_changed
    shift_start.on_select = shift_end.on_select = form_changed
    home.on_change = home_changed

    context_card = _card([
        _heading('O APP JÁ CONSIDERA'),
        context_row(ft.Icons.SCHEDULE, shift_text),
        context_row(ft.Icons.PLACE_OUTLINED, place_text, _link('Alterar', toggle_editor)),
        gps_row,
        editor,
        ft.Row([weather_glyph, ft.Container(weather_text, expand=True)], spacing=10,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        rain_box,
        context_row(ft.Icons.PAYMENTS_OUTLINED, earnings_text, _link('Ajustar', open_settings)),
    ], spacing=10, padding=ft.Padding(left=14, right=12, top=12, bottom=12))
    await refresh_context()
    if gps and (state.get('place') or {}).get('source') != 'manual':
        state['gps_task'] = asyncio.create_task(silent_gps())

    def collect_profile():
        meals = helpers.merge_meals(prefs.get('meals'), {kind: (enabled.value, start.value)
                                                           for kind, enabled, start in meal_controls})
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
            'sources': current_sources(),
        }
        chosen = picker.read(strict=True)
        if chosen is None:
            raise ApiError('Escolha o seu carro para planejar.')
        return {'vehicle': chosen, 'preferences': preferences}

    async def request_body():
        profile = collect_profile()
        # Bateria escondida do carro: sorteio da conta ou, no modo apresentação, a do celular.
        level, _ = await vehicle_state.current_soc(app)
        level = round(max(0.0, min(100.0, float(level))), 1)
        prefs.update(profile['preferences'])
        state.update(rain=bool(rain.value and rain.visible))
        planned = helpers.effective_preferences(profile['preferences'], _now(app, demo))
        body = {'soc_percent': level, 'vehicle': profile['vehicle'], 'preferences': planned,
                'context': {'rain': True} if state['rain'] else {}}
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
            await send(app, state, 'PUT', 'driver/profile', profile)
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
        result = await send(app, state, 'POST', 'driver/plan', {**body, 'mode': plan_mode(body['preferences'])})
        state.update(plan=result, next=None)
        await show()

    async def next_stop():
        body = await request_body()
        result = await send(app, state, 'POST', 'driver/next-stop', body)
        state.update(next=result)
        await show()

    def reserve_action(connector_id):
        async def reserve_point():
            key = state.setdefault('reserve_keys', {}).setdefault(connector_id, app.api.new_key())
            await app.api.request('POST', 'reservations', {'connector_id': connector_id}, key=key)
            state['reserve_keys'].pop(connector_id, None)
            await app.go('reservations', detail=True)
        return app.action(reserve_point)

    def result_controls():
        return [*(next_stop_view(state['next'], app, reserve_action) if state.get('next') else []),
                *(plan_view(state['plan'], app, reserve_action) if state.get('plan') else [])]

    async def show():
        refresh_lines()
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
        context_card,
        _button('Planejar meu turno', app.action(plan_shift)),
        ft.Container(_button('Próxima parada agora', app.action(next_stop), primary=False),
                     margin=ft.Margin(left=0, top=-4, right=0, bottom=0)),
        settings,
        results,
        ft.Container(height=8),
    ], spacing=14, scroll=ft.ScrollMode.AUTO, expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    title = ft.Row([
        ft.Container(ft.Icon(ft.Icons.ARROW_BACK_IOS_NEW, size=14, color=theme.TEXT_COLOR), on_click=back, width=19,
                     height=34, tooltip='Voltar', alignment=ft.Alignment(-1, 0),
                     padding=ft.Padding(left=2, right=0, top=0, bottom=0)),
        design.txt('Modo motorista', 17.6, 'bold', expand=True),
    ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    screen = ft.Column([title, ft.Container(body, expand=True, margin=ft.Margin(left=0, top=0, right=0, bottom=0))],
                       spacing=0, expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    # Capturas de tela (só demonstração): ``run=auto|full_shift|next`` já abre com o resultado;
    # ``ajustes=true`` abre Ajustes.
    if demo and ajustes is True:
        await settings.data()
    if demo and run in CAPTURE_RUNS and not (state.get('plan') or state.get('next')):
        if soc is not None:
            vehicle_state.set_simulated_soc(app, soc)
        await (next_stop() if run == 'next' else plan_shift())
    return screen


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


def _stop_label(stop):
    return f"{stop['meal']} + recarga" if stop['meal'] else 'Recarga'


def first_stop_line(plan):
    """'Primeira parada 14:30 · Almoço + recarga em Shopping Eldorado' (ou nenhuma recarga)."""
    stops = plan.get('stops') or []
    if not stops:
        return 'Nenhuma recarga necessária neste turno.'
    stop = stops[0]
    return f"Primeira parada {stop['start']} · {_stop_label(stop)} em {stop['station_name']}"


def summary_card(plan):
    totals, comparison = plan['totals'], plan['comparison']
    gain = comparison['net_profit_gain']
    gain_text = (f'+{brl(gain)} vs. recarregar só quando a bateria fica baixa' if gain >= 1
                 else 'Empata com recarregar só quando a bateria fica baixa')
    return _card([
        _heading('LUCRO LÍQUIDO ESTIMADO DO TURNO'),
        design.money_text(brl(totals['net_profit']), 32),
        design.txt(gain_text, 12.5, 'semibold', theme.GREEN if gain >= 1 else theme.GRAY_TEXT),
        design.txt(first_stop_line(plan), 12.5, 'regular'),
        _small(f"{totals['stops']} parada(s) · {duration(totals['stop_minutes'])} parado · "
               f"{km(totals['driving_km'])} rodados"),
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
    return _card([
        _heading('LINHA DO TEMPO DO TURNO'),
        ft.Semantics(label=helpers.plan_accessible_summary(plan), container=True,
                     content=ft.Column([bar, peaks, ticks], spacing=4)),
        legend,
    ])


def block_rows(plan):
    colors = _colors()
    return [ft.Row([design.txt(f"{block['start']}–{block['end']}", 12, 'regular', width=92),
                    ft.Container(width=10, height=10, bgcolor=colors[block['kind']], border_radius=2),
                    design.txt(f"{block['label']} · bateria → {block['soc_end']:.0f}%", 12,
                               'regular', expand=True)], spacing=8) for block in plan['blocks']]


def soc_chart(plan):
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
    return [
        _heading('BATERIA PROJETADA (SoC)'),
        ft.Semantics(label=helpers.soc_summary(plan), container=True, content=chart),
        ft.Row([_small(plan['window']['start']), _small(f'Linha vermelha: reserva de {reserve:.0f}%'),
                _small(plan['window']['end'])], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
        _small(helpers.soc_summary(plan)),
    ]


def stop_details(stop):
    """Linha técnica da parada (fica em "Ver detalhes")."""
    return (f"{stop['start']} · {stop['station_name']}: {stop['connector_type'].upper()} {stop['power_kw']:.0f} kW · "
            f"{brl(stop['price_per_kwh'])}/kWh · bateria {stop['soc_before']:.0f}% → {stop['soc_after']:.0f}% · "
            f"{km(stop['detour_km'])} de desvio"
            + (f" · deixa de ganhar {brl(stop['opportunity_cost'])} em corridas"
               if (stop.get('opportunity_cost') or 0) >= 0.01 else ' · sem perder corridas'))


def stop_card(plan, stop, app, reserve_action):
    kind = 'refeicao_recarga' if stop['meal'] else 'recarga'
    details = [
        ft.Row([ft.Container(width=6, height=36, bgcolor=_colors()[kind], border_radius=3),
                ft.Column([design.txt(f"{stop['start']}–{stop['end']} · {_stop_label(stop)}", 14, 'bold'),
                           design.txt(stop['station_name'], 12.5, 'regular')], spacing=2, expand=True)],
               spacing=10),
        _small(f"+{kwh(stop['kwh'])} · {brl(stop['cost'])} · {duration(stop['charge_minutes'])} de carga"),
        design.txt(stop['reason'], 12.5, 'regular'),
    ]
    if stop.get('available_now') is False:
        details.append(_small('Ocupado agora — considere a fila estimada ou outro posto.', theme.WARNING))
    details.append(ft.Container(_station_actions(app, reserve_action, stop, can_reserve=helpers.stop_is_now(plan, stop)),
                                margin=ft.Margin(left=0, top=4, right=0, bottom=0)))
    return _card(details)


def details_section(plan):
    """Tudo o que não é decisão: números, comparação, blocos, bateria, paradas e premissas."""
    totals, comparison, baseline = plan['totals'], plan['comparison'], plan['baseline']['totals']

    def metric(label, value):
        return ft.Column([_small(label), design.txt(value, 15, 'bold')], spacing=2, expand=True)
    controls = [
        ft.Row([metric('Ganho bruto', brl(totals['gross_earnings'])),
                metric('Recargas', brl(totals['charging_cost'])),
                metric('Energia', kwh(totals['energy_kwh']))], spacing=8),
        _small(f"Bateria no fim {totals['end_soc_percent']:.0f}%."),
        _small(f"Sem planejar: {brl(baseline['net_profit'])} líquido, {baseline['stops']} parada(s), "
               f"{duration(baseline['peak_stop_minutes'])} parado no pico."),
        _small(comparison['message']),
        ft.Divider(height=8, color=_track_off()),
        *block_rows(plan),
        ft.Divider(height=8, color=_track_off()),
        *soc_chart(plan),
    ]
    stops = plan.get('stops') or []
    if stops:
        controls += [ft.Divider(height=8, color=_track_off()), _heading('PARADAS')]
        for stop in stops:
            controls.append(_small(stop_details(stop)))
            if stop.get('amenities'):
                controls.append(_small('Comodidades: ' + helpers.amenities_text(stop['amenities'])))
    infos = [alert for alert in plan.get('alerts') or () if alert.get('level') not in ('warning', 'error')]
    if infos:
        controls += [ft.Divider(height=8, color=_track_off()), *(_alert_row(alert) for alert in infos)]
    controls += [
        ft.Divider(height=8, color=_track_off()),
        _heading('COMO CALCULAMOS'),
        _small(f"Demanda: {plan['demand']['label']} ({demand_source_text(plan['demand']['source'])}). "
               f"{plan['stations_considered']} posto(s) compatíveis considerados."),
        *(_small('• ' + text) for text in plan.get('assumptions', [])),
        _small('• Demanda por horário é uma estimativa de grandes cidades brasileiras; não usamos dados oficiais '
               'de aplicativos de transporte.'),
    ]
    return _details('Ver detalhes', controls)


def plan_view(plan, app, reserve_action):
    window = plan['window']
    controls = [
        design.txt(f"Plano {window['start']}–{window['end']} · {window['date'][8:10]}/{window['date'][5:7]}", 15,
                   'bold'),
        _small(DISCLAIMER),
        summary_card(plan),
    ]
    urgent = [alert for alert in plan['alerts'] if alert.get('level') in ('warning', 'error')]
    if urgent:
        controls.append(_card([_heading('ALERTAS'), *(_alert_row(alert) for alert in urgent)]))
    controls.append(timeline_card(plan))
    if plan['stops']:
        controls.append(design.txt('Paradas recomendadas', 15, 'bold'))
        controls.extend(stop_card(plan, stop, app, reserve_action) for stop in plan['stops'])
    controls.append(details_section(plan))
    return controls


def _alternative(item, app, reserve_action):
    distance = f" · {km(item['distance_km'])}" if item.get('distance_km') is not None else ''
    return ft.Container(ft.Column([
        design.txt(item['station_name'], 13, 'semibold'),
        _small(f"{brl(item['cost_per_kwh_effective'])}/kWh efetivo · +{kwh(item['kwh'])} em "
               f"{duration(item['minutes'])} · {brl(item['cost'])}{distance}"),
        _station_actions(app, reserve_action, item, can_reserve=True, emphasize=False),
    ], spacing=6), padding=ft.Padding(left=12, right=12, top=10, bottom=12), border_radius=ROW_RADIUS,
        border=ft.Border.all(1, _track_off()))


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
    for alert in result.get('alerts') or ():
        if alert.get('level') in ('warning', 'error'):
            controls.append(_alert_row(alert))
    alternatives = result.get('alternatives') or []
    if alternatives:
        controls.append(_details(f'Outras opções ({len(alternatives)})', [
            _small('Se parar agora, melhores opções (custo + ganho perdido por kWh):'),
            *(_alternative(item, app, reserve_action) for item in alternatives)]))
    urgent = recommendation.get('action') == 'charge_needed'
    if urgent:
        controls[0] = ft.Row([ft.Icon(ft.Icons.BATTERY_ALERT, size=18, color=theme.ERROR),
                              _heading('RECARGA NECESSÁRIA')], spacing=6)
    return [_card(controls, spacing=8,
                  border=ft.Border.all(2 if urgent else 1, theme.ERROR if urgent else _track_off()))]
