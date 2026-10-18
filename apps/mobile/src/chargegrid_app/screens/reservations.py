"""Aba Recarga: "Minhas recargas" (Próximas / Em andamento) e o detalhe de uma recarga agendada.

``build(app)`` é a lista; ``build(app, detail=True)`` abre a reserva atual ("Recarga Agendada").
``recharge_detail`` (layout carro + indicador + valores) é compartilhado com ``charging.py``
("Recarga em andamento").
"""

from datetime import datetime
from urllib.parse import quote

import flet as ft
import flet.canvas as cv

from ..ui import design as d
from ..ui import theme
from ..ui.components import date_time
from ..ui.point_summary import journey_summary, point_summary

LABELS = {'pending_device':'Aguardando confirmação do posto','confirmed':'Reserva confirmada pelo equipamento','cancelling':'Liberação pendente no equipamento','cancelled':'Reserva cancelada','expired':'Reserva expirada','consumed':'Reserva usada na recarga'}
DEMO_LABELS = {'pending_device':'Aguardando confirmação simulada','confirmed':'Reserva simulada confirmada','cancelling':'Liberação simulada pendente','cancelled':'Reserva simulada cancelada','expired':'Reserva simulada expirada','consumed':'Reserva usada na recarga simulada'}
UPCOMING = ('pending_device', 'confirmed', 'cancelling')
RUNNING = ('starting', 'charging', 'stopping')
DIVIDER = '|'


def when_text(value):
    """``Horário: 12:30 | Data: 31/12/2026`` (hora local) a partir de um ISO; traços se ausente."""
    try:
        moment = datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone()
        return f"Horário: {moment:%H:%M} {DIVIDER} Data: {moment:%d/%m/%Y}"
    except (ValueError, AttributeError, TypeError):
        return f'Horário: -- {DIVIDER} Data: --'


def street_line(address):
    """``Av. X, 123, Bairro, Cidade - UF`` -> ``Av. X, 123`` (a referência mostra só rua e número)."""
    parts = [item.strip() for item in str(address or '').split(',')]
    return ', '.join(parts[:2])


def area_line(address):
    """``Av. X, 123, Pinheiros, São Paulo - SP`` -> ``Pinheiros - São Paulo``; ``None`` se não der para derivar."""
    parts = [item.strip() for item in str(address or '').split(',')]
    if len(parts) < 4:
        return None
    return f"{parts[2]} - {parts[3].split(' - ')[0].strip()}"


def maps_url(address):
    return 'https://www.google.com/maps/dir/?api=1&destination=' + quote(str(address or ''))


# ---------------------------------------------------------------- blocos compartilhados
def btn(text, on_click=None, kind='primary', *, height=54, size=12.8):
    """Botão do design kit (branco / escuro / vermelho) com o texto direto no contêiner."""
    bg, fg = {'primary': (theme.BTN_PRIMARY, theme.BTN_PRIMARY_FG), 'secondary': (theme.BTN_SECONDARY, theme.BTN_SECONDARY_FG),
              'danger': (theme.RED, '#FFFFFF')}[kind]
    return ft.Container(d.txt(text, size, 'bold', fg, text_align=ft.TextAlign.CENTER), bgcolor=bg,
                        border_radius=d.RADIUS_BTN, height=height, alignment=ft.Alignment(0, 0), on_click=on_click,
                        ink=True, padding=ft.Padding(left=16, right=16, top=0, bottom=0))


def _stage(percent, live=None):
    """Carro com os dois arcos vermelhos + indicador circular (valor ``percent`` já formatado)."""
    red = '#D72B32'
    arcs = cv.Canvas([
        # brilho sob o carro (meia elipse preenchida)
        cv.Arc(55, 100, 245, 70, 0, 3.14159, True, ft.Paint(
            style=ft.PaintingStyle.FILL,
            gradient=ft.PaintLinearGradient((0, 135), (0, 170), [ft.Colors.with_opacity(0.0, red),
                                                                 ft.Colors.with_opacity(0.30, red)]))),
        cv.Arc(55, 100, 245, 70, 0, 3.14159, False, ft.Paint(color=ft.Colors.with_opacity(0.16, red), stroke_width=7,
                                                           style=ft.PaintingStyle.STROKE)),
        cv.Arc(55, 100, 245, 70, 0, 3.14159, False, ft.Paint(color=red, stroke_width=2.4,
                                                           style=ft.PaintingStyle.STROKE)),
        cv.Arc(1, 76, 360, 123, 0, 3.14159, False, ft.Paint(color=ft.Colors.with_opacity(0.78, red),
                                                           stroke_width=2.4, style=ft.PaintingStyle.STROKE)),
    ], width=362, height=200)
    car = ft.Container(d.car_image(width=236), left=58.5, top=19)
    stage = ft.Container(ft.Stack([arcs, car], width=362, height=200), margin=ft.Margin(0, 0, 0, -3.5))
    shown = d.txt(percent, 25, 'semibold', text_align=ft.TextAlign.CENTER)
    if live is not None:
        live['percent'] = shown
    gauge = ft.Container(
        ft.Container(shown, width=80, height=80,
                     border_radius=40, bgcolor='#232323', alignment=ft.Alignment(0, 0)),
        width=86, height=86, border_radius=43, border=ft.Border.all(3, red), alignment=ft.Alignment(0, 0))
    return [stage, ft.Row([gauge], alignment=ft.MainAxisAlignment.CENTER)]


def _value_row(name, value, live=None, key=None):
    shown = d.txt(value, 11.8, 'bold', text_align=ft.TextAlign.RIGHT)
    if live is not None:
        live[key] = shown
    return ft.Container(ft.Row([d.txt(name, 11.8, 'regular', theme.GRAY_TEXT), shown],
                               alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                        padding=ft.Padding(left=16, right=16, top=0, bottom=0))


def _route_icon(size=19):
    """Ícone "rota" da referência (dois pontos ligados por uma curva), desenhado em canvas."""
    line = ft.Paint(color=theme.TEXT_COLOR, stroke_width=2, style=ft.PaintingStyle.STROKE,
                    stroke_cap=ft.StrokeCap.ROUND)
    k = size / 24
    path = cv.Path([cv.Path.MoveTo(8.2 * k, 6.2 * k), cv.Path.CubicTo(15.5 * k, 5.5 * k, 15.5 * k, 9.5 * k, 11.5 * k, 11.5 * k),
                    cv.Path.CubicTo(7.5 * k, 13.5 * k, 8 * k, 18.5 * k, 16.4 * k, 18.4 * k)], paint=line)
    return cv.Canvas([cv.Circle(5 * k, 5.5 * k, 2.4 * k, line), cv.Circle(19 * k, 18.5 * k, 2.4 * k, line), path],
                     width=size, height=size)


def _maps_row(app, address):
    async def open_maps(event=None):
        launcher = ft.UrlLauncher()
        await launcher.launch_url(maps_url(address))
    return ft.Container(
        ft.Row([_route_icon(),
                d.txt('Abrir rota no Google Maps', 12.7, 'semibold', expand=True),
                ft.Icon(ft.Icons.OPEN_IN_NEW, size=20, color=theme.GRAY_TEXT)], spacing=12,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor='#272727', border_radius=d.RADIUS_BTN, height=43, padding=ft.Padding(left=17, right=13, top=0, bottom=0),
        margin=ft.Margin(6, 0, 6, 0), on_click=open_maps, ink=True,
        data='maps')


def recharge_detail(app, title, *, when, address, percent, cost, power, remaining, action, on_back,
                    status=None, extra=(), secondary=(), live=None):
    """Layout de "Recarga Agendada" / "Recarga em andamento" (estacao_16.1 / 16.2)."""
    head = ft.Column([d.page_title(title, on_back, size=17.6),
                      ft.Container(d.txt(when, 14.3, 'regular'), padding=ft.Padding(6, 0, 0, 0)),
                      ft.Container(d.txt(street_line(address), 14.3, 'regular'), padding=ft.Padding(7, 0, 0, 5))],
                     spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    left = d.txt(remaining, 11.6, 'bold')
    if live is not None:
        live['remaining'] = left
    track = ft.Container(ft.Row([d.txt('Tempo restante', 11.6, 'regular', theme.GRAY_TEXT), left], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                         bgcolor=theme.CARD, border_radius=6, height=29, padding=ft.Padding(left=7, right=7, top=0, bottom=0),
                         margin=ft.Margin(6, 0, 6, 0), alignment=ft.Alignment(0, 0))
    notes = [d.txt(status, 11, 'regular', theme.GRAY_TEXT)] if status else []
    rows = ft.Column([_value_row('Custo estimado', cost, live, 'cost'), _value_row('Potência atual', power, live, 'power')],
                     spacing=16.5)
    body = [head, *_stage(percent, live), ft.Container(height=1.5), ft.Container(rows, margin=ft.Margin(0, -2, 0, 0)), ft.Container(height=7),
            track, _maps_row(app, address),
            ft.Container(action, margin=ft.Margin(6, 0, 6, 0)),
            *[ft.Container(item, margin=ft.Margin(6, 0, 6, 0)) for item in secondary],
            *notes, *extra]
    return ft.Column(body, spacing=16.5, scroll=ft.ScrollMode.AUTO, expand=True,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def station_tile_row(name, subtitle, on_click):
    return ft.Row([d.icon_tile(None, size=46),
                   ft.Column([d.txt(name, 13.6, 'semibold'), d.txt(subtitle, 10.2, 'regular', theme.GRAY_TEXT)],
                             spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                   ft.Container(ft.Icon(ft.Icons.CHEVRON_RIGHT, size=26, color=theme.TEXT_COLOR), height=46,
                                alignment=ft.Alignment(0, -1), margin=ft.Margin(0, -8, -4, 0))],
                  spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _recharge_card(when, address, name, subtitle, on_click):
    return ft.Container(
        ft.Column([d.txt(when, 9.3, 'regular'), d.txt(street_line(address), 9.3, 'regular'),
                   ft.Container(station_tile_row(name, subtitle, on_click), margin=ft.Margin(0, 11.5, 0, 0))],
                  spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        bgcolor=theme.CARD, border_radius=24, padding=ft.Padding(left=15, right=15, top=12.5, bottom=17.5),
        on_click=on_click, ink=True, margin=ft.Margin(0, 0, -2, -2))


async def seed_demo(app, kind):
    """Capture/demo helper: ``demo_seed='res'|'session'`` creates a simulated reservation (and session) once.

    Only honoured for the demo backend; harmless (no-op) everywhere else and when the param is absent.
    """
    if kind not in ('res', 'session') or getattr(app.api, 'is_demo', False) is not True:
        return
    import asyncio
    current = await app.api.request('GET', 'reservations/current')
    if not current or current.get('status') not in ('pending_device', 'confirmed'):
        stations = await app.api.request('GET', 'stations', params={'limit': 5, 'offset': 0})
        point = next((c for s in stations['items'] for c in s['connectors'] if c.get('available')), None)
        if not point:
            return
        await app.api.request('POST', 'reservations', {'connector_id': point['id']}, key='seed-res')
        await asyncio.sleep(2)
        current = await app.api.request('GET', 'reservations/current')
    if kind == 'session' and not await app.api.request('GET', 'charging-sessions/current'):
        point = (current or {}).get('connector') or {}
        await app.api.request('POST', 'charging-sessions', {
            'presence_code': '#F12345', 'public_code': point.get('public_code') or (current or {}).get('public_code'),
            'reservation_id': current['id'], 'max_duration_minutes': 30}, key='seed-ses')
        await asyncio.sleep(4)


# ---------------------------------------------------------------- telas
async def build(app, detail=False, demo_seed=None, **_):
    demo = getattr(app.api, 'is_demo', False) is True
    await seed_demo(app, demo_seed)
    if detail:
        return await _detail(app, demo)
    reservation = await app.api.request('GET', 'reservations/current')
    if reservation and reservation.get('status') not in UPCOMING:
        reservation = None
    session = await app.api.request('GET', 'charging-sessions/current')
    if session and session.get('status') not in RUNNING:
        session = None

    def snapshot(res, ses):
        return (res or {}).get('id'), (res or {}).get('status'), (ses or {}).get('id'), (ses or {}).get('status')
    shown = snapshot(reservation, session)

    async def update():
        current_res = await app.api.request('GET', 'reservations/current')
        if current_res and current_res.get('status') not in UPCOMING:
            current_res = None
        current_ses = await app.api.request('GET', 'charging-sessions/current')
        if current_ses and current_ses.get('status') not in RUNNING:
            current_ses = None
        if snapshot(current_res, current_ses) != shown:
            await app.go('reservations')
    if reservation or session:
        app.set_poll(update, 5)

    labels = DEMO_LABELS if demo else LABELS
    upcoming, running = [], []
    if reservation:
        upcoming.append(_recharge_card(
            when_text(reservation.get('expires_at') or reservation.get('created_at')),
            reservation.get('station_address'), reservation.get('station_name') or 'Posto reservado',
            area_line(reservation.get('station_address')) or labels.get(reservation['status'], reservation['status']),
            app.link('reservations', detail=True)))
    if session:
        from .charging import DEMO_LABELS as SESSION_DEMO
        from .charging import LABELS as SESSION_LABELS
        session_labels = SESSION_DEMO if demo else SESSION_LABELS
        running.append(_recharge_card(
            when_text(session.get('started_at') or session.get('created_at')),
            session.get('station_address'), session.get('station_name') or 'Posto',
            area_line(session.get('station_address')) or session_labels.get(session['status'], session['status']),
            app.link('charging', session_id=session['id'])))
    body = [d.txt('Minhas recargas', 18.5, 'bold'), ft.Container(height=3.5),
            d.txt('Próximas', 14.6, 'bold'), *upcoming,
            d.txt('Em andamento', 14.6, 'bold'), *running]
    search = ft.Container(btn('Buscar mais estações', app.link('stations'), 'danger'), margin=ft.Margin(8, 0, 3, -6))
    if upcoming or running:
        # Com recargas listadas a referência não prende o botão à barra: ele segue o conteúdo.
        return d.page(*body, ft.Container(height=234), search, gap=14.5)
    return d.page(*body, footer=ft.Container(search.content, margin=ft.Margin(8, 0, 8, -6)), gap=14.5)


async def _detail(app, demo):
    reservation = await app.api.request('GET', 'reservations/current')
    if not reservation:
        return d.page(d.txt('Nenhuma reserva ativa.', 14, 'regular', theme.GRAY_TEXT),
                      title='Recarga Agendada', on_back=app.link('reservations'),
                      footer=btn('Buscar um ponto', app.link('stations')))

    async def update():
        current = await app.api.request('GET', 'reservations/current')
        if current != reservation:
            await app.go('reservations', detail=True)
    app.set_poll(update, 5)

    async def cancel():
        await app.api.request('POST', f"reservations/{reservation['id']}/cancel")
        app.planning_intent = None
        await app.go('reservations')
    labels = DEMO_LABELS if demo else LABELS
    status = reservation['status']
    connector = reservation.get('connector') or {}
    extra = []
    if status != 'confirmed':
        extra.append(journey_summary(reservation, reservation=True, demo=demo))
    heading = {'pending_device': 'Ponto solicitado', 'confirmed': 'Ponto reservado',
               'cancelling': 'Ponto em liberação'}.get(status, 'Ponto da reserva')
    extra.append(point_summary(reservation, heading))
    if status == 'confirmed':
        extra.append(ft.ExpansionTile(
            expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            title=ft.Text('Sobre esta confirmação', size=13, color=theme.GRAY_TEXT),
            controls=[journey_summary(reservation, reservation=True, demo=demo)]))
    if demo:
        extra.append(d.txt('Reserva simulada. Ao chegar ao ponto de exemplo, use #F12345 para testar.', 12, 'regular',
                           theme.GRAY_TEXT))
    if reservation.get('station_id'):
        extra.append(btn('Ver posto e endereço', app.link('stations', station_id=reservation['station_id']), 'secondary', height=48))
    extra.append(d.txt('O estado é atualizado a cada 5 segundos.', 12, 'regular', theme.GRAY_TEXT))
    status_line = labels.get(status, status)
    if reservation.get('expires_at') and status == 'confirmed':
        status_line += ' · Chegue até: ' + date_time(reservation['expires_at'])
    arrive = (btn('Cheguei: informar código',
                              app.link('charging', reservation_id=reservation['id'], point_context=reservation,
                                       max_duration=min(30, connector.get('max_duration_minutes') or 30)),
                              'danger') if status == 'confirmed' else None)
    cancel_button = (btn('Cancelar Recarga', app.action(cancel))
                     if status in ('confirmed', 'pending_device') else None)
    return recharge_detail(
        app, 'Recarga Agendada', when=when_text(reservation.get('expires_at') or reservation.get('created_at')),
        address=reservation.get('station_address'), percent='-%', cost='-', power='- kW', remaining='- minutos',
        action=cancel_button or arrive or ft.Container(), on_back=app.link('reservations'), status=status_line,
        secondary=[arrive] if arrive and cancel_button else (), extra=extra)
