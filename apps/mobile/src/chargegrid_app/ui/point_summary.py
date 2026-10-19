"""Public point identity shared by selection, reservations and charging."""

import flet as ft

from ..api_client import ApiError
from . import theme
from .components import button, card, date_time, money

EVENT_LABELS = {
    'start_requested': 'Início solicitado',
    'stop_requested': 'Parada solicitada',
    'command_received': 'Comando recebido pelo ponto',
    'command_failed': 'Falha informada pelo ponto',
    'start_applied': 'Início confirmado pelo ponto',
    'stop_applied': 'Parada confirmada pelo ponto',
    'offline_reconciled': 'Estado conciliado após período offline',
    'ended': 'Fim da sessão observado',
}
EVENT_SOURCES = {'api': 'servidor', 'device_sync': 'sincronização do ponto',
                 'simulator': 'simulador local'}


def event_timeline(events):
    controls = [ft.Text('REGISTRO DA SESSÃO', size=11, weight=ft.FontWeight.BOLD, color=theme.ACCENT)]
    if not events:
        controls.append(ft.Text('Nenhum evento detalhado disponível para esta sessão.',
                                size=13, color=theme.GRAY_TEXT))
    for event in events:
        label = EVENT_LABELS.get(event.get('kind'), 'Evento registrado')
        if event.get('source') == 'simulator':
            label = label.replace('pelo ponto', 'na simulação')
        source = EVENT_SOURCES.get(event.get('source'), 'origem indisponível')
        controls.append(ft.Text(label, size=13, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR))
        controls.append(ft.Text(f"{date_time(event.get('observed_at'))} (horário local) · {source}",
                                size=12, color=theme.GRAY_TEXT))
    controls.append(ft.Text('Horários do servidor ou da simulação; períodos sem conexão não são medidos.',
                            size=12, color=theme.GRAY_TEXT))
    return card(controls)


def event_disclosure(app, session_id):
    panel = ft.Container(visible=False)

    async def toggle():
        if panel.visible:
            panel.visible = False
            trigger.content.value = 'Ver eventos da sessão'
        else:
            try:
                events = await app.api.request('GET', f'charging-sessions/{session_id}/events')
                panel.content = event_timeline(events)
            except ApiError:
                panel.content = card([ft.Text('Registro detalhado indisponível agora.',
                                              size=13, color=theme.GRAY_TEXT)])
            panel.visible = True
            trigger.content.value = 'Ocultar eventos da sessão'
        app.page.update()

    trigger = button('Ver eventos da sessão', app.action(toggle), secondary=True)
    return trigger, panel


def journey_summary(record, *, reservation=False, demo=False):
    """Describe current facts, never reconstruct an unrecorded event history."""
    status = record.get('status')
    controls = [ft.Text('CONFIRMAÇÃO DA RESERVA' if reservation else 'JORNADA DA RECARGA',
                        size=11, weight=ft.FontWeight.BOLD, color=theme.GRAY_TEXT)]
    source = 'simulador' if demo else 'ponto'
    requested = 'Pedido registrado'
    if record.get('created_at'):
        requested += ' · ' + date_time(record['created_at'])
    controls.append(ft.Text(requested, size=13, color=theme.TEXT_COLOR))
    if reservation:
        explanation = {
            'pending_device': f'Aguardando confirmação do {source}. Aguarde antes de se deslocar.',
            'confirmed': f'Confirmada pelo {source}. Ao chegar, confirme sua presença para iniciar.',
            'cancelling': f'Cancelamento solicitado; aguardando liberação pelo {source}.',
            'cancelled': 'Reserva cancelada. Escolha outro ponto quando precisar.',
            'expired': 'Reserva expirada. Consulte a disponibilidade antes de tentar novamente.',
            'consumed': 'Reserva usada no pedido de recarga. Acompanhe a confirmação do início.',
        }.get(status, 'Estado da reserva não informado.')
    else:
        # started_at is the API fact for an applied start. Ending a failed
        # request is not evidence that energy flowed or the point started.
        started = bool(record.get('started_at'))
        if started:
            controls.append(ft.Text(f'Início confirmado pelo {source} · '+date_time(record['started_at']),
                                    size=13, color=theme.TEXT_COLOR))
        explanation = {
            'starting': f'Início solicitado; aguardando confirmação do {source}.',
            'charging': ('Recarga simulada em andamento.' if demo else 'Recarga em andamento, confirmada pelo ponto.'),
            'stopping': f'Parada solicitada; aguardando confirmação do {source}.',
            'completed': 'Sessão encerrada.',
            'failed': 'Sessão encerrada com falha.',
            'interrupted': 'Sessão interrompida.',
        }.get(status, 'Estado da recarga não informado.')
        if status in ('completed', 'failed', 'interrupted') and record.get('ended_at'):
            explanation += ' '+date_time(record['ended_at'])
        if status in ('completed', 'failed', 'interrupted') and not started:
            explanation += ' Sem registro de início confirmado.'
        if status in ('starting', 'charging', 'stopping') and not record.get('online', True):
            explanation += ' Equipamento offline: este é o último estado recebido.'
    controls.append(ft.Text(explanation, size=13, color=theme.TEXT_COLOR))
    return card(controls)


def point_context(station, connector):
    return {
        'station_id': station['id'],
        'station_name': station['name'],
        'station_address': station['address'],
        'connector': {key: connector.get(key) for key in (
            'id', 'public_code', 'connector_type', 'power_kw',
            'price_per_kwh', 'max_duration_minutes', 'effective_power_kw',
        ) if connector.get(key) is not None or key != 'effective_power_kw'},
    }


def point_summary(data, heading='Ponto selecionado'):
    data = data or {}
    connector = data.get('connector') or {}
    session_terms = 'price_per_kwh' in data
    controls = [ft.Text(heading.upper(), size=11, weight=ft.FontWeight.BOLD, color=theme.ACCENT)]
    if data.get('station_name'):
        controls.append(ft.Text(data['station_name'], size=19, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR))
    if data.get('station_address'):
        controls.append(ft.Text(data['station_address'], size=13, color=theme.GRAY_TEXT))
    identity = ' · '.join(str(value) for value in (
        connector.get('public_code'), connector.get('connector_type'),
    ) if value)
    if identity:
        controls.append(ft.Text(identity, color=theme.TEXT_COLOR))
    terms = []
    if connector.get('power_kw') is not None and not session_terms:
        terms.append(f"{float(connector['power_kw']):g}".replace('.', ',') + ' kW nominais')
    if session_terms:
        # A connector may have been repriced after a completed session. Only
        # the immutable session snapshot describes that session's tariff.
        terms.append(f"Tarifa da sessão: {money(data['price_per_kwh'])}/kWh")
    elif connector.get('price_per_kwh') is not None:
        terms.append(f"{money(connector['price_per_kwh'])}/kWh")
    if session_terms and data.get('max_duration_minutes') is not None:
        terms.append(f"limite de {data['max_duration_minutes']} min")
    elif connector.get('max_duration_minutes') is not None:
        terms.append(f"até {connector['max_duration_minutes']} min")
    if terms:
        controls.append(ft.Text(' · '.join(terms), size=13, color=theme.GRAY_TEXT))
    if not identity and not data.get('station_name'):
        message = ('Identificação do ponto indisponível nesta resposta.' if data.get('status') else
                   'O posto será identificado pelo código #F informado.')
        controls.append(ft.Text(message, size=13, color=theme.GRAY_TEXT))
    return card(controls)
