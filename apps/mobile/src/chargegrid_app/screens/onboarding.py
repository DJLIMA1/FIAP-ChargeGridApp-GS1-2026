"""Guided first setup for a QR-claimed charging point.

Each step saves to the API before advancing. Closing the app never leaves an
unsaved, apparently published point behind; an unfinished setup remains a draft.
"""

from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..services.location import geocode_address
from ..ui import design, theme
from ..ui.components import money
from .setup_ui import cta, setup_field, status_card


def _number(control, label, minimum, maximum, *, integer=False):
    try:
        raw = (control.value or '').strip().replace(',', '.')
        result = Decimal(raw)
    except (InvalidOperation, ValueError):
        control.error_text = f'Informe {label.lower()} válido.'
        raise ApiError(control.error_text) from None
    if not result.is_finite() or not minimum <= result <= maximum or (integer and result != int(result)):
        control.error_text = f'{label} deve estar entre {minimum} e {maximum}.'
        raise ApiError(control.error_text)
    control.error_text = None
    return int(result) if integer else str(result)


def _required(control, label, maximum):
    value = (control.value or '').strip()
    if not value or len(value) > maximum:
        control.error_text = f'Informe {label.lower()} (até {maximum} caracteres).'
        raise ApiError(control.error_text)
    control.error_text = None
    return value


def _step_caption(step, existing_station=False):
    labels = ('Posto selecionado' if existing_station else 'Localização', 'Ponto e tarifa', 'Revisão')
    current = max(1, step - 1) if existing_station else step
    total = 2 if existing_station else 3
    return design.txt(f'Etapa {current} de {total} · {labels[step - 1]}', 11, 'regular', theme.GRAY_TEXT,
                      text_align=ft.TextAlign.CENTER)


def _summary_line(label, value):
    return ft.Column([
        design.txt(label, 11, 'bold', theme.GRAY_TEXT),
        design.txt(str(value), 13, 'semibold'),
    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def _group(*controls):
    """Cartão escuro com linhas de resumo."""
    return design.card_box(ft.Column(list(controls), spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                           padding=16)


def _note(text, color=None):
    return design.txt(text, 11.5, 'regular', color or theme.GRAY_TEXT)


def _form(controls):
    return ft.Column(controls, spacing=15, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


async def build(app, station_id, point_id=None, step=1, existing_station=False, **_):
    is_demo = bool(getattr(app.api,'is_demo',False))
    station = await app.api.request('GET', f'stations/{station_id}')
    points = station.get('connectors') or []
    point = next((item for item in points if item['id'] == point_id), None) if point_id else None
    if point is None and not point_id:
        point = next((item for item in points if not item.get('active') and not item.get('retired')), None)
    if point is None:
        raise ApiError('O ponto vinculado não foi encontrado neste posto.')
    if point.get('retired'):
        raise ApiError('Este ponto simulado foi desvinculado. Adicione outro equipamento na gestão.' if is_demo else
                       'Este ponto foi desvinculado. Escaneie o novo QR da tela para configurar outro ponto.')

    point_id = point['id']
    step = int(step)
    if step not in (1, 2, 3):
        step = 1

    context = {'existing_station':True} if existing_station else {}

    def destination(next_step):
        return app.link('operator', station_id=station_id, point_id=point_id,
                        onboarding=True, step=next_step, **context)

    controls = []
    tail = []
    if is_demo:
        from ..demo import DEMO_PRESENCE_CODE
        tail.append(status_card(
            design.txt('PONTO SIMULADO', 11, 'bold', theme.ACCENT),
            _note('Nome, endereço, tarifa e recargas são exemplos locais. Nenhum equipamento físico será acionado.'),
            _summary_line('Código para testar uma recarga após publicar', DEMO_PRESENCE_CODE), padding=16))

    if existing_station:
        controls.append(_group(
            design.txt('POSTO SELECIONADO', 11, 'bold', theme.ACCENT),
            _summary_line('Nome', station['name']),
            _summary_line('Endereço', station['address']),
            _note('Este ponto usará o endereço do posto. Para alterar os dados de todos os pontos, '
                  'abra “Editar posto” na gestão.')))

    def finish(items):
        items.extend(tail)
        items.append(_step_caption(step, existing_station))
        items.append(design.txt('O posto é o local com endereço; este ponto é o equipamento de recarga. '
                                'Salve cada etapa e publique quando estiver pronto.', 11, 'regular',
                                theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER))
        screen = design.page(*items, title='Configurar Estação', on_back=getattr(app, "back", None), center_title=True, gap=16)
        return screen

    if step == 1 and existing_station:
        controls += [cta('Continuar para ponto e tarifa', destination(2), weight='semibold'),
                     cta('Voltar ao posto', app.link('operator', station_id=station_id), primary=False,
                         weight='semibold')]
        return finish(controls)

    if step == 1:
        name_box = setup_field('Nome da estação', station.get('name', ''), 'Ex.: Posto Centro')
        address_box = setup_field('Endereço', station.get('address', ''), 'Rua, número, bairro, cidade e estado')
        latitude_box = setup_field('Latitude', str(station.get('latitude', '')), keyboard=ft.KeyboardType.NUMBER)
        longitude_box = setup_field('Longitude', str(station.get('longitude', '')), keyboard=ft.KeyboardType.NUMBER)
        ident_box = setup_field('Identificador', point.get('public_code', ''), read_only=True)
        name, address, latitude, longitude = (box.controls[1] for box in
                                              (name_box, address_box, latitude_box, longitude_box))

        async def locate():
            _required(address, 'endereço', 300)
            if is_demo:
                latitude.value,longitude.value = '-23.55','-46.63'
                latitude.error_text = longitude.error_text = None
                app.page.update()
                return
            try:
                coordinates = await geocode_address(address.value.strip())
            except Exception as exc:
                raise ApiError('Não foi possível consultar este endereço. Informe as coordenadas manualmente.') from exc
            if not coordinates:
                raise ApiError('Endereço não encontrado. Confira o texto ou informe as coordenadas.')
            latitude.value, longitude.value = map(str, coordinates)
            latitude.error_text = longitude.error_text = None
            app.page.update()

        async def save_location():
            body = {
                'name': _required(name, 'nome do posto', 100),
                'address': _required(address, 'endereço', 300),
                'latitude': _number(latitude, 'Latitude', -90, 90),
                'longitude': _number(longitude, 'Longitude', -180, 180),
            }
            await app.api.request('PATCH', f'stations/{station_id}', body)
            if hasattr(app, 'mark_saved'):
                app.mark_saved()
            await app.go('operator', station_id=station_id, point_id=point_id,
                         onboarding=True, step=2, **context)

        tail.insert(0, _note('Use um nome e endereço fictícios. A localização de exemplo não consulta serviços externos.' if is_demo else
                             'Use um nome reconhecível e o endereço da instalação, não o seu endereço pessoal.'))
        controls += [
            _form([name_box, address_box, ident_box,
                   cta('Usar localização de exemplo' if is_demo else 'Buscar coordenadas do endereço',
                       app.action(locate), primary=False, weight='semibold'),
                   latitude_box, longitude_box,
                   _note('Confira as coordenadas. Se necessário, ajuste-as manualmente.')]),
            cta('Salvar e continuar', app.action(save_location), weight='bold', size=15),
            cta('Deixar para depois', app.link('operator'), primary=False, weight='semibold'),
        ]

    elif step == 2:
        kind_box = setup_field('Tipo de conector', point.get('connector_type', 'Tipo 2'))
        power_box = setup_field('Potência (kW)', str(point.get('power_kw', '')), keyboard=ft.KeyboardType.NUMBER)
        price_box = setup_field('Tarifa por kWh (R$)', str(point.get('price_per_kwh', '')),
                                keyboard=ft.KeyboardType.NUMBER)
        duration_box = setup_field('Tempo máximo por recarga (min)', str(point.get('max_duration_minutes', 60)),
                                   keyboard=ft.KeyboardType.NUMBER)
        kind, power, price, duration = (box.controls[1] for box in (kind_box, power_box, price_box, duration_box))

        async def save_point():
            body = {
                'connector_type': _required(kind, 'tipo de conector', 50),
                'power_kw': _number(power, 'Potência', Decimal('0.001'), 1000),
                'price_per_kwh': _number(price, 'Tarifa', 0, 10000),
                'max_duration_minutes': _number(duration, 'Tempo máximo', 1, 1440, integer=True),
            }
            if Decimal(body['power_kw']) <= 0:
                power.error_text = 'A potência deve ser maior que zero.'
                raise ApiError(power.error_text)
            await app.api.request('PATCH', f'connectors/{point_id}', body)
            if hasattr(app, 'mark_saved'):
                app.mark_saved()
            await app.go('operator', station_id=station_id, point_id=point_id,
                         onboarding=True, step=3, **context)

        controls += [
            design.txt('Ponto ' + point['public_code'], 13, 'semibold'),
            _note('O código público identifica este ponto simulado. Para testar a recarga, '
                  f'use {DEMO_PRESENCE_CODE} no modo motorista.' if is_demo else
                  'O código público identifica este ponto. Para iniciar a recarga, o cliente também '
                  'informa o código temporário #F exibido na tela.'),
            _form([kind_box, power_box, price_box, duration_box]),
            cta('Salvar e revisar', app.action(save_point), weight='bold', size=15),
            cta('Voltar ao posto' if existing_station else 'Voltar à localização',
                app.link('operator', station_id=station_id) if existing_station else destination(1),
                primary=False, weight='semibold'),
        ]

    else:
        connection = ('Online simulado' if point.get('online') else 'Offline simulado') if is_demo else (
            'Online agora' if point.get('online') else 'Offline agora')
        controls += [
            _group(design.section_label('Posto'),
                   _summary_line('Nome', station['name']),
                   _summary_line('Local', station['address']),
                   _summary_line('Coordenadas', f"{station['latitude']}, {station['longitude']}")),
            _group(design.section_label('Ponto de recarga'),
                   _summary_line('Código', point['public_code']),
                   _summary_line('Conector', point['connector_type']),
                   _summary_line('Potência', f"{point['power_kw']} kW"),
                   _summary_line('Tarifa', f"{money(point['price_per_kwh'])}/kWh"),
                   _summary_line('Limite', f"{point['max_duration_minutes']} min"),
                   design.txt(connection, 12, 'semibold', theme.SUCCESS if point.get('online') else theme.GRAY_TEXT)),
        ]
        if not point.get('online'):
            controls.append(_note('Este equipamento está offline na simulação. Nenhum equipamento físico precisa estar conectado.' if is_demo else
                                  'O equipamento ainda não está conectado. Você pode publicar agora, mas o ponto só ficará disponível após a conexão.',
                                  theme.WARNING))
        if existing_station and not station.get('active'):
            controls.append(_note('Este posto está desativado. Publicar o ponto mantém o posto desativado; '
                                  'reative o posto na gestão quando quiser disponibilizar seus pontos.', theme.WARNING))

        controls.append(_group(
            design.txt('DEPOIS DE PUBLICAR', 11, 'bold', theme.ACCENT),
            _note('Motoristas encontram o ponto na busca, no Modo Motorista e no assistente com IA. '
                  'Acompanhe receita, ocupação e alertas em Postos ou no painel web do proprietário, '
                  'com a mesma conta.')))

        async def publish():
            # Point first, station second: a failed second request leaves the
            # station unpublished, not a public station with a disabled point.
            await app.api.request('PATCH', f'connectors/{point_id}', {'active': True})
            if not station.get('active') and not existing_station:
                await app.api.request('PATCH', f'stations/{station_id}', {'active': True})
            app.notice('Ponto configurado. O posto continua desativado; reative-o na gestão quando estiver pronto.'
                       if existing_station and not station.get('active') else
                       f'Ponto simulado publicado! Teste uma recarga no modo motorista com {DEMO_PRESENCE_CODE}.' if is_demo else
                       'Ponto publicado! Ele estará disponível para recarga quando estiver online e livre.')
            await app.go('operator')

        async def keep_inactive():
            app.notice('Ponto salvo como inativo. Publique quando estiver pronto.')
            await app.go('operator')

        status = {'value': 'active'}
        selector = ft.Container()
        publish_label = design.txt('Publicar ponto', 15, 'bold', theme.BTN_PRIMARY_FG, text_align=ft.TextAlign.CENTER)
        publish_button = cta('Publicar ponto', app.action(publish), weight='bold', size=15)
        publish_button.content = publish_label

        def draw_status():
            selector.content = design.segmented([('active', 'Ativa'), ('inactive', 'Inativa')], status['value'],
                                                change_status, height=37)

        async def change_status(value):
            status['value'] = value
            publish_label.value = 'Publicar ponto' if value == 'active' else 'Salvar sem publicar'
            publish_button.on_click = app.action(publish if value == 'active' else keep_inactive)
            draw_status()
            app.page.update()

        draw_status()
        controls += [
            ft.Column([design.label('Status', strong=False), selector], spacing=6,
                      horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            publish_button,
            cta('Voltar e ajustar tarifa', destination(2), primary=False, weight='semibold'),
            cta('Concluir depois', app.link('operator'), primary=False, weight='semibold'),
        ]

    return finish(controls)
