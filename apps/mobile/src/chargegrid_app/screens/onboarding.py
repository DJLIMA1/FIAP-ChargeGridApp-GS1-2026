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


def _step_header(step):
    labels = ('Localização', 'Ponto e tarifa', 'Revisão')
    return ft.Column([
        ft.Text(f'CONFIGURAÇÃO INICIAL · ETAPA {step} DE 3', size=11,
                weight=ft.FontWeight.BOLD, color=theme.RED),
        ft.Row([
            ft.Container(height=5, expand=True,
                         bgcolor=theme.RED if index <= step else theme.LIGHT_GRAY,
                         border_radius=3)
            for index in range(1, 4)
        ], spacing=5),
        ft.Text(labels[step - 1], size=27, weight=ft.FontWeight.BOLD,
                color=theme.TEXT_COLOR, font_family='BarlowCondensed'),
    ], spacing=9)


def _summary_line(label, value):
    return ft.Row([
        ft.Text(label, color=theme.GRAY_TEXT, size=13, expand=True),
        ft.Text(str(value), color=theme.TEXT_COLOR, size=13,
                weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.RIGHT),
    ], spacing=8)


async def build(app, station_id, point_id=None, step=1):
    station = await app.api.request('GET', f'stations/{station_id}')
    points = station.get('connectors') or []
    point = next((item for item in points if item['id'] == point_id), None) if point_id else None
    if point is None and not point_id:
        point = next((item for item in points if not item.get('active')), None)
    if point is None:
        raise ApiError('O ponto vinculado não foi encontrado neste posto.')

    point_id = point['id']
    step = int(step)
    if step not in (1, 2, 3):
        step = 1

    def destination(next_step):
        return app.link('operator', station_id=station_id, point_id=point_id,
                        onboarding=True, step=next_step)

    intro = ft.Text(
        'O ponto só aparece para consumidores após a publicação. Você pode sair e continuar depois.',
        size=13, color=theme.GRAY_TEXT,
    )
    controls = [_step_header(step), intro]

    if step == 1:
        name = field('Nome da estação', station.get('name', ''))
        name.hint_text = 'Ex.: Estação Centro'
        address = field('Endereço completo', station.get('address', ''))
        address.hint_text = 'Rua, número, bairro, cidade e estado'
        latitude = field('Latitude', str(station.get('latitude', '')))
        longitude = field('Longitude', str(station.get('longitude', '')))
        latitude.keyboard_type = longitude.keyboard_type = ft.KeyboardType.NUMBER

        async def locate():
            _required(address, 'endereço', 300)
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
                'name': _required(name, 'nome da estação', 100),
                'address': _required(address, 'endereço', 300),
                'latitude': _number(latitude, 'Latitude', -90, 90),
                'longitude': _number(longitude, 'Longitude', -180, 180),
            }
            await app.api.request('PATCH', f'stations/{station_id}', body)
            if hasattr(app, 'mark_saved'):
                app.mark_saved()
            await app.go('operator', station_id=station_id, point_id=point_id,
                         onboarding=True, step=2)

        controls += [
            card([ft.Text('Onde seus clientes vão encontrar o ponto?',
                          weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
                  ft.Text('Use um nome reconhecível e o endereço da instalação, não o seu endereço pessoal.',
                          size=12, color=theme.GRAY_TEXT),
                  name, address, button('Buscar coordenadas do endereço', app.action(locate), secondary=True),
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
                         onboarding=True, step=3)

        controls += [
            card([ft.Text('Ponto ' + point['public_code'], weight=ft.FontWeight.BOLD,
                          color=theme.TEXT_COLOR),
                  ft.Text('O código público vem no equipamento e será usado para iniciar recargas.',
                          size=12, color=theme.GRAY_TEXT), kind, power, price, duration]),
            button('Salvar e revisar', app.action(save_point)),
            button('Voltar à localização', destination(1), secondary=True),
        ]

    else:
        connection = 'Online agora' if point.get('online') else 'Offline agora'
        controls += [
            card([ft.Text('Estação', size=16, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
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
            controls.append(ft.Text('O ESP32 ainda não está conectado. Você pode publicar agora, mas o ponto só ficará disponível após a conexão.',
                                    size=13, color=theme.AMBER))

        async def publish():
            # Point first, station second: a failed second request leaves the
            # station unpublished, not a public station with a disabled point.
            await app.api.request('PATCH', f'connectors/{point_id}', {'active': True})
            if not station.get('active'):
                await app.api.request('PATCH', f'stations/{station_id}', {'active': True})
            app.notice('Ponto publicado! Ele aparecerá para os consumidores quando estiver online e disponível.')
            await app.go('operator')

        controls += [
            button('Publicar ponto', app.action(publish)),
            button('Voltar e ajustar tarifa', destination(2), secondary=True),
            button('Deixar como rascunho', app.link('operator'), secondary=True),
        ]

    return ft.Column(controls, spacing=14, scroll=ft.ScrollMode.AUTO)
