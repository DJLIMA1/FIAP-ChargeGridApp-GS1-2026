"""Guided first setup for a QR-claimed charging point.

Each step saves to the API before advancing. Closing the app never leaves an
unsaved, apparently published point behind; an unfinished setup remains a draft.
"""

from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..services.location import geocode_address
from ..ui import theme
from ..ui.components import badge, button, card, field, money


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


def _step_header(step, existing_station=False):
    labels = ('Posto selecionado' if existing_station else 'Localização', 'Ponto e tarifa', 'Revisão')
    current = max(1, step - 1) if existing_station else step
    total = 2 if existing_station else 3
    return ft.Column([
        ft.Text(f'CONFIGURAÇÃO DO PONTO · ETAPA {current} DE {total}', size=11,
                weight=ft.FontWeight.BOLD, color=theme.RED),
        ft.Row([
            ft.Container(height=5, expand=True,
                         bgcolor=theme.RED if index <= current else theme.LIGHT_GRAY,
                         border_radius=3)
            for index in range(1, total + 1)
        ], spacing=5),
        ft.Text(labels[step - 1], size=27, weight=ft.FontWeight.BOLD,
                color=theme.TEXT_COLOR, font_family='BarlowCondensed'),
    ], spacing=9)


def _summary_line(label, value):
    return ft.Column([
        ft.Text(label, color=theme.GRAY_TEXT, size=12),
        ft.Text(str(value), color=theme.TEXT_COLOR, size=13,
                weight=ft.FontWeight.BOLD),
    ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


async def build(app, station_id, point_id=None, step=1, existing_station=False):
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

    intro = ft.Text(
        'O posto é o local com endereço; este ponto é o equipamento de recarga. '
        'Salve cada etapa e publique quando estiver pronto.',
        size=13, color=theme.GRAY_TEXT,
    )
    controls = [_step_header(step, existing_station), intro]
    if is_demo:
        from ..demo import DEMO_PRESENCE_CODE
        controls.append(card([
            ft.Text('PONTO SIMULADO',size=11,weight=ft.FontWeight.BOLD,color=theme.RED),
            ft.Text('Nome, endereço, tarifa e recargas são exemplos locais. Nenhum equipamento físico será acionado.',
                    size=13,color=theme.GRAY_TEXT),
            _summary_line('Código para testar uma recarga após publicar',DEMO_PRESENCE_CODE),
        ]))

    if existing_station:
        controls.append(card([
            ft.Text('POSTO SELECIONADO',size=11,weight=ft.FontWeight.BOLD,color=theme.RED),
            _summary_line('Nome',station['name']),
            _summary_line('Endereço',station['address']),
            ft.Text('Este ponto usará o endereço do posto. Para alterar os dados de todos os pontos, '
                    'abra “Editar posto” na gestão.',size=12,color=theme.GRAY_TEXT),
        ]))

    if step == 1 and existing_station:
        controls += [button('Continuar para ponto e tarifa',destination(2)),
                     button('Voltar ao posto',app.link('operator',station_id=station_id),secondary=True)]
        return ft.Column(controls,spacing=14,scroll=ft.ScrollMode.AUTO)

    if step == 1:
        name = field('Nome do posto', station.get('name', ''))
        name.hint_text = 'Ex.: Posto Centro'
        address = field('Endereço completo', station.get('address', ''))
        address.hint_text = 'Rua, número, bairro, cidade e estado'
        latitude = field('Latitude', str(station.get('latitude', '')))
        longitude = field('Longitude', str(station.get('longitude', '')))
        latitude.keyboard_type = longitude.keyboard_type = ft.KeyboardType.NUMBER

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

        controls += [
            card([ft.Text('Onde seus clientes vão encontrar o ponto?',
                          weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                  ft.Text('Use um nome e endereço fictícios. A localização de exemplo não consulta serviços externos.' if is_demo else
                          'Use um nome reconhecível e o endereço da instalação, não o seu endereço pessoal.',
                          size=12, color=theme.GRAY_TEXT),
                  name, address, button('Usar localização de exemplo' if is_demo else 'Buscar coordenadas do endereço', app.action(locate), secondary=True),
                  ft.Text('Confira as coordenadas. Se necessário, ajuste-as manualmente.',
                          size=12, color=theme.GRAY_TEXT), latitude, longitude]),
            button('Salvar e continuar', app.action(save_location)),
            button('Deixar para depois', app.link('operator'), secondary=True),
        ]

    elif step == 2:
        kind = field('Tipo de conector', point.get('connector_type', 'Tipo 2'))
        power = field('Potência (kW)', str(point.get('power_kw', '')))
        price = field('Tarifa por kWh (R$)', str(point.get('price_per_kwh', '')))
        duration = field('Tempo máximo por recarga (min)', str(point.get('max_duration_minutes', 60)))
        for control in (power, price, duration):
            control.keyboard_type = ft.KeyboardType.NUMBER

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
            card([ft.Text('Ponto ' + point['public_code'], weight=ft.FontWeight.BOLD,
                          color=theme.TEXT_COLOR),
                  ft.Text('O código público identifica este ponto simulado. Para testar a recarga, '
                          f'use {DEMO_PRESENCE_CODE} no modo motorista.' if is_demo else
                          'O código público identifica este ponto. Para iniciar a recarga, o cliente também '
                          'informa o código temporário #F exibido na tela.',
                          size=12, color=theme.GRAY_TEXT), kind, power, price, duration]),
            button('Salvar e revisar', app.action(save_point)),
            button('Voltar ao posto' if existing_station else 'Voltar à localização',
                   app.link('operator',station_id=station_id) if existing_station else destination(1), secondary=True),
        ]

    else:
        connection = ('Online simulado' if point.get('online') else 'Offline simulado') if is_demo else (
            'Online agora' if point.get('online') else 'Offline agora')
        controls += [
            card([ft.Text('Posto', size=16, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                  _summary_line('Nome', station['name']),
                  _summary_line('Local', station['address']),
                  _summary_line('Coordenadas', f"{station['latitude']}, {station['longitude']}")]),
            card([ft.Text('Ponto de recarga', size=16, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                  _summary_line('Código', point['public_code']),
                  _summary_line('Conector', point['connector_type']),
                  _summary_line('Potência', f"{point['power_kw']} kW"),
                  _summary_line('Tarifa', f"{money(point['price_per_kwh'])}/kWh"),
                  _summary_line('Limite', f"{point['max_duration_minutes']} min"),
                  badge(connection, theme.GREEN if point.get('online') else theme.SLATE, width=116)]),
        ]
        if not point.get('online'):
            controls.append(ft.Text('Este equipamento está offline na simulação. Nenhuma conexão com ESP32 físico é necessária.' if is_demo else
                                    'O ESP32 ainda não está conectado. Você pode publicar agora, mas o ponto só ficará disponível após a conexão.',
                                    size=13, color=theme.AMBER))
        if existing_station and not station.get('active'):
            controls.append(ft.Text('Este posto está desativado. Publicar o ponto mantém o posto desativado; '
                                    'reative o posto na gestão quando quiser disponibilizar seus pontos.',
                                    size=13,color=theme.AMBER))

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

        controls += [
            button('Publicar ponto', app.action(publish)),
            button('Voltar e ajustar tarifa', destination(2), secondary=True),
            button('Concluir depois', app.link('operator'), secondary=True),
        ]

    return ft.Column(controls, spacing=14, scroll=ft.ScrollMode.AUTO)
