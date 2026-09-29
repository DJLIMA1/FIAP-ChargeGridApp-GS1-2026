import asyncio
from copy import deepcopy
from math import isfinite

import flet as ft

from ..services.maps import station_map_widget
from ..ui import theme
from ..ui.availability import point_status
from ..ui.components import BRAND_PROMISE, button, card, date_time, money
from .charging import DEMO_LABELS as DEMO_CHARGING_LABELS
from .charging import LABELS as CHARGING_LABELS
from .charging import SOURCE
from .reservations import DEMO_LABELS as DEMO_RESERVATION_LABELS
from .reservations import LABELS as RESERVATION_LABELS


def _enabled_points(station):
    if station.get('active') is False:
        return []
    return [point for point in station.get('connectors') or []
            if point.get('active') is not False and not point.get('retired')
            and point.get('availability_status') != 'disabled']


def _available_points(station):
    # Older APIs omit availability_status/active; explicit negative signals
    # always win over an inconsistent or stale available flag.
    return [point for point in _enabled_points(station)
            if point.get('available') is True and point.get('online') is True
            and point.get('availability_status') in (None, 'available')]


def _station_price(station):
    prices = []
    for point in _available_points(station):
        try:
            price = float(point.get('price_per_kwh'))
        except (TypeError, ValueError):
            continue
        if isfinite(price) and price >= 0:
            prices.append(price)
    return min(prices) if prices else None


def _station_status(station):
    connectors = station.get('connectors') or []
    if station.get('active') is False:
        return 'Desativado', theme.SLATE
    if not connectors:
        return 'Sem pontos', theme.GRAY_TEXT
    if _available_points(station):
        return 'Disponível', theme.GREEN
    enabled = _enabled_points(station)
    if not enabled:
        return 'Desativado', theme.SLATE
    online_points = [point for point in enabled if point.get('online') is True]
    if not online_points:
        return 'Offline', theme.SLATE
    labels = [point_status(point) for point in online_points
              if point_status(point)[0] != 'Disponível']
    for label in ('Em recarga', 'Reservado', 'Sincronizando', 'Falha'):
        if any(status[0] == label for status in labels):
            return next(status for status in labels if status[0] == label)
    return labels[0] if labels else ('Indisponível', theme.GRAY_TEXT)


async def build(app):
    demo = getattr(app.api,'is_demo',False) is True
    async def snapshot():
        return deepcopy(await asyncio.gather(
            app.api.request('GET','reservations/current'),
            app.api.request('GET','charging-sessions/current'),
            app.api.request('GET','stations',params={'limit':3,'offset':0}),
            app.api.request('GET','me/summary'),
        ))

    previous = await snapshot()
    reservation, session, stations_result, month_summary = previous
    stations = stations_result['items']
    name = ((app.profile.get('name') or '').strip().split() or ['motorista'])[0]

    identity = [
        ft.Text(f'Olá, {name}',size=22,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,font_family='BarlowCondensedBold'),
        ft.Text(BRAND_PROMISE,size=13,color=theme.GRAY_TEXT),
    ]
    greeting = ft.Row([
        ft.Container(ft.Icon(ft.Icons.PERSON_OUTLINE,color=theme.GRAY_TEXT,size=27),width=52,height=52,bgcolor=theme.LIGHT_GRAY,border_radius=26,alignment=ft.Alignment(0,0)),
        ft.Column(identity,spacing=2,expand=True),
    ],spacing=12)

    estimated_cost = ft.Text(money(month_summary.get('estimated_cost')),size=32,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,font_family='BarlowCondensedBold')
    def summary_text(summary):
        count = summary.get('sessions_count',0)
        energy = f"{float(summary.get('energy_wh') or 0)/1000:.3f}".replace('.',',')
        return f"{count} {'recarga concluída' if count == 1 else 'recargas concluídas'} · {energy} kWh"
    summary_detail = ft.Text(summary_text(month_summary),size=12,color=theme.GRAY_TEXT)
    summary_card = card([
            ft.Text('GASTO ESTIMADO NESTE MÊS',size=11,color=theme.TEXT_COLOR),
            estimated_cost,
            summary_detail,
        ])
    def describe_state(reservation, session):
        if session:
            source = 'Simulação local' if demo else SOURCE.get(session.get('source'),'origem não informada')
            battery_label = 'Bateria simulada' if demo else 'Bateria'
            battery = '' if session.get('soc_percent') is None else f" · {battery_label} {float(session['soc_percent']):.0f}%"
            labels = DEMO_CHARGING_LABELS if demo else CHARGING_LABELS
            state_text = f"{labels.get(session['status'],session['status'])}{battery} · {source}"
            if not session.get('online', True):
                state_text += ' · Equipamento offline, últimos dados recebidos'
            if session.get('station_name'):
                state_text = session['station_name'] + ' · ' + state_text
            return state_text, 'Acompanhar recarga', app.link('charging',session_id=session['id'])
        if reservation:
            labels = DEMO_RESERVATION_LABELS if demo else RESERVATION_LABELS
            state_text = labels.get(reservation['status'],reservation['status'])
            if reservation.get('station_name'):
                state_text = reservation['station_name'] + ' · ' + state_text
            if reservation['status'] == 'confirmed':
                if reservation.get('expires_at'):
                    state_text += ' · Chegue até ' + date_time(reservation['expires_at'])
                connector = reservation.get('connector') or {}
                return state_text, 'Cheguei: informar código', app.link(
                    'charging',reservation_id=reservation['id'],point_context=reservation,
                    max_duration=min(30,connector.get('max_duration_minutes') or 30))
            label = 'Acompanhar liberação' if reservation['status'] == 'cancelling' else 'Acompanhar reserva'
            return state_text, label, app.link('reservations')
        return 'Nenhuma reserva ou recarga ativa. Escolha um posto para começar.', 'Recarregar agora', app.link('stations')

    state_text, action_label, state_action = describe_state(reservation, session)
    active_state = ft.Text(state_text,size=13,color=theme.TEXT_COLOR,expand=True)
    flow_label = ft.Text('SUA RECARGA' if session else 'SUA RESERVA' if reservation else 'ENCONTRE SEU PONTO',
                         size=11,weight=ft.FontWeight.BOLD,color=theme.ACCENT)
    flow_icon = ft.Icon(ft.Icons.EV_STATION_OUTLINED if session else ft.Icons.SCHEDULE_OUTLINED if reservation else ft.Icons.EXPLORE_OUTLINED,
                        color=theme.ACCENT,size=25)
    active_button = button(action_label,state_action)
    active_card = card([flow_label,ft.Row([
        ft.Container(flow_icon,width=34,height=34,bgcolor=theme.LIGHT_GRAY,border_radius=17,alignment=ft.Alignment(0,0)),
        active_state,
    ],spacing=10),active_button],on_click=state_action,ink=True,
        border=ft.Border.all(1,theme.LIGHT_GRAY))
    map_width = max(200,min(getattr(app.page,'width',None) or 400,600)-40)

    async def make_map(items):
        records = [{**station,'free_points':len(_available_points(station)),
                    'status':_station_status(station)[0],'price':_station_price(station)} for station in items[:3]]
        return await station_map_widget(records,lambda station_id:app.link('stations',station_id=station_id),offline=demo,width=map_width)

    map_preview = ft.Container(await make_map(stations))
    map_heading = ft.Text('Postos no mapa',weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,size=20,font_family='BarlowCondensedBold')
    map_section = ft.Column([map_heading,map_preview],spacing=16,
                            horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    async def resize_map_section(event):
        nonlocal map_width
        if event.width <= 0 or abs(event.width-map_width) < .5:
            return
        map_width = event.width
    map_section.on_size_change = resize_map_section
    controls = [
        greeting,active_card,map_section,summary_card,
    ]
    async def update():
        nonlocal previous
        fresh = await snapshot()
        if fresh == previous:
            return
        current_reservation, current_session, current_stations, current_summary = fresh
        if fresh[:2] != previous[:2]:
            active_state.value, active_button.content.value, action = describe_state(current_reservation, current_session)
            active_card.on_click = active_button.on_click = action
            flow_label.value = 'SUA RECARGA' if current_session else 'SUA RESERVA' if current_reservation else 'ENCONTRE SEU PONTO'
            flow_icon.icon = ft.Icons.EV_STATION_OUTLINED if current_session else ft.Icons.SCHEDULE_OUTLINED if current_reservation else ft.Icons.EXPLORE_OUTLINED
        if current_summary != previous[3]:
            estimated_cost.value = money(current_summary.get('estimated_cost'))
            summary_detail.value = summary_text(current_summary)
        if current_stations['items'] != previous[2]['items']:
            map_preview.content = await make_map(current_stations['items'])
        previous = fresh
        app.page.update()

    app.set_poll(update, 10)
    return ft.ListView(controls,spacing=10,expand=True)
