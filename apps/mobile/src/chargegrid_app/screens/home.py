import asyncio

import flet as ft

from ..ui import theme
from ..ui.availability import point_status
from ..ui.components import badge, button, card, money
from .charging import LABELS as CHARGING_LABELS
from .charging import SOURCE
from .reservations import LABELS as RESERVATION_LABELS


def _station_status(station):
    connectors = station.get('connectors') or []
    if not connectors:
        return 'Sem pontos', theme.GRAY_TEXT
    if any(point.get('available') for point in connectors):
        return 'Disponível', theme.GREEN
    if connectors and all(not point.get('online') for point in connectors):
        return 'Offline', theme.RED
    online_points = [point for point in connectors if point.get('online')]
    labels = [point_status(point) for point in online_points]
    for label in ('Em recarga', 'Reservado', 'Sincronizando', 'Falha'):
        if any(status[0] == label for status in labels):
            return next(status for status in labels if status[0] == label)
    return labels[0] if labels else ('Indisponível', theme.GRAY_TEXT)


async def build(app):
    async def snapshot():
        return await asyncio.gather(
            app.api.request('GET','reservations/current'),
            app.api.request('GET','charging-sessions/current'),
            app.api.request('GET','stations',params={'limit':5,'offset':0}),
            app.api.request('GET','me/summary'),
        )

    previous = await snapshot()
    reservation, session, stations_result, month_summary = previous
    stations = stations_result['items']
    name = (app.profile.get('name') or 'motorista').strip().split()[0]

    identity = [
        ft.Text(f'Olá, {name}',size=19,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,font_family='BarlowCondensed'),
        ft.Text('Encontre seu próximo ponto de recarga.',size=13,color=theme.GRAY_TEXT),
    ]
    greeting = ft.Row([
        ft.Container(ft.Icon(ft.Icons.PERSON_OUTLINE,color=theme.GRAY_TEXT,size=27),width=52,height=52,bgcolor=theme.LIGHT_GRAY,border_radius=26,alignment=ft.Alignment(0,0)),
        ft.Column(identity,spacing=2,expand=True),
    ],spacing=12)

    estimated_cost = ft.Text(money(month_summary.get('estimated_cost')),size=28,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,font_family='BarlowCondensedSemiBold')
    def summary_text(summary):
        return f"{summary.get('sessions_count',0)} recargas concluídas · {float(summary.get('energy_wh') or 0)/1000:.3f} kWh"
    summary_detail = ft.Text(summary_text(month_summary),size=12,color=theme.GRAY_TEXT)
    summary_card = card([
            ft.Text('GASTO ESTIMADO NESTE MÊS',size=11,color=theme.TEXT_COLOR),
            estimated_cost,
            summary_detail,
        ])
    controls = [greeting]
    if app.profile.get('account_type') == 'vendor':
        controls.append(card([
            ft.Text('Sua conta de vendedor',weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),
            ft.Text('Gerencie seus postos e acompanhe as recargas.' if app.profile.get('operator_enabled') else 'Ligue a tela e escaneie o QR exibido no ESP32 para configurar seu primeiro ponto.',size=13,color=theme.GRAY_TEXT),
            button('Gerenciar postos' if app.profile.get('operator_enabled') else 'Configurar minha primeira tela',app.link('operator'),secondary=True),
        ]))

    def describe_state(reservation, session):
        if session:
            source = SOURCE.get(session.get('source'),'origem não informada')
            battery = '' if session.get('soc_percent') is None else f" · Bateria {float(session['soc_percent']):.0f}%"
            state_text = f"{CHARGING_LABELS.get(session['status'],session['status'])}{battery} · {source}"
            if not session.get('online', True):
                state_text += ' · Equipamento offline, últimos dados recebidos'
            return state_text, app.link('charging',session_id=session['id'])
        if reservation:
            return RESERVATION_LABELS.get(reservation['status'],reservation['status']), app.link('reservations')
        return 'Nenhuma reserva ou recarga ativa. Escolha um posto para começar.', app.link('stations')

    state_text, state_action = describe_state(reservation, session)
    active_state = ft.Text(state_text,size=13,color=theme.TEXT_COLOR,expand=True)
    flow_label = ft.Text('SUA RECARGA' if session else 'SUA RESERVA' if reservation else 'PRÓXIMO PASSO',
                         size=11,weight=ft.FontWeight.BOLD,color=theme.RED)
    flow_icon = ft.Icon(ft.Icons.EV_STATION_OUTLINED if session else ft.Icons.SCHEDULE_OUTLINED if reservation else ft.Icons.EXPLORE_OUTLINED,
                        color=theme.RED,size=25)
    active_card = card([flow_label,ft.Row([
        ft.Container(flow_icon,width=34,height=34,bgcolor=theme.LIGHT_GRAY,border_radius=17,alignment=ft.Alignment(0,0)),
        active_state,
    ],spacing=10)],on_click=state_action,ink=True,border=ft.Border.all(1,theme.LIGHT_GRAY))
    controls.append(active_card)

    def station_rows(items):
        rows = [ft.Text('Explore os postos',weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,size=17,font_family='BarlowCondensed')]
        for station in items:
            status, color = _station_status(station)
            prices = [float(point['price_per_kwh']) for point in station.get('connectors',[]) if point.get('price_per_kwh') is not None]
            detail = station['address']
            if prices:
                detail += f" · a partir de {money(min(prices))}/kWh"
            rows.append(ft.Container(ft.Row([
                ft.Column([ft.Text(station['name'],weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),ft.Text(detail,size=12,color=theme.GRAY_TEXT)],spacing=3,expand=True),
                badge(status,bg=color,width=104),
            ],alignment=ft.MainAxisAlignment.SPACE_BETWEEN),padding=ft.Padding(top=14,bottom=14),border=ft.Border(bottom=ft.BorderSide(1,theme.LIGHT_GRAY)),on_click=app.link('stations',station_id=station['id']),ink=True))
        if not items:
            rows.append(ft.Text('Nenhum posto disponível no momento.',size=13,color=theme.GRAY_TEXT))
        return rows

    listing = ft.Column(station_rows(stations),spacing=0)
    controls.append(listing)
    controls += [
        button('Encontrar um ponto',app.link('stations')),
        button('Tenho o código do ponto',app.link('charging'),secondary=True),
        summary_card,
    ]
    async def update():
        nonlocal previous
        fresh = await snapshot()
        if fresh == previous:
            return
        current_reservation, current_session, current_stations, current_summary = fresh
        if fresh[:2] != previous[:2]:
            active_state.value, active_card.on_click = describe_state(current_reservation, current_session)
            flow_label.value = 'SUA RECARGA' if current_session else 'SUA RESERVA' if current_reservation else 'PRÓXIMO PASSO'
            flow_icon.name = ft.Icons.EV_STATION_OUTLINED if current_session else ft.Icons.SCHEDULE_OUTLINED if current_reservation else ft.Icons.EXPLORE_OUTLINED
        if current_summary != previous[3]:
            estimated_cost.value = money(current_summary.get('estimated_cost'))
            summary_detail.value = summary_text(current_summary)
        if current_stations['items'] != previous[2]['items']:
            listing.controls = station_rows(current_stations['items'])
        previous = fresh
        app.page.update()

    app.set_poll(update, 10)
    return ft.ListView(controls,spacing=16,expand=True)
