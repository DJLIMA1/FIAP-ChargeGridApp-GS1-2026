"""Public point identity shared by selection, reservations and charging."""

from decimal import Decimal, InvalidOperation

import flet as ft

from . import theme
from .components import card, date_time, money


def journey_summary(record, *, reservation=False, demo=False):
    """Describe current facts, never reconstruct an unrecorded event history."""
    status = record.get('status')
    controls = [ft.Text('CONFIRMAÇÃO DA RESERVA' if reservation else 'JORNADA DA RECARGA',
                        size=11, weight=ft.FontWeight.BOLD, color=theme.GRAY_TEXT)]
    source = 'ponto'
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
            'charging': 'Recarga em andamento, confirmada pelo ponto.',
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


def _surge(multiplier):
    """Multiplicador de demanda acima de 1× (``'1.00'``/``None`` não é acréscimo)."""
    try:
        return multiplier is not None and Decimal(str(multiplier)) > 1
    except (InvalidOperation, ValueError):
        return False


def point_context(station, connector):
    """Contexto do ponto para o assistente de início. ``price_per_kwh`` é o preço que o motorista paga
    agora (tarifa base do horário × demanda); ``base_price_per_kwh`` aparece quando o horário ou a
    demanda mudou o preço, e ``demand_multiplier`` só quando a demanda mudou."""
    result = {
        'station_id': station['id'],
        'station_name': station['name'],
        'station_address': station['address'],
        'connector': {key: connector.get(key) for key in (
            'id', 'public_code', 'connector_type', 'power_kw',
            'price_per_kwh', 'max_duration_minutes', 'effective_power_kw', 'speed_prices', 'base_speed_prices',
        ) if connector.get(key) is not None or key != 'effective_power_kw'},
    }
    charged = (connector.get('speed_prices') or {}).get('max',connector.get('dynamic_price_per_kwh'))
    if charged is not None and str(charged) != str(connector.get('price_per_kwh')):
        result['connector'].update(price_per_kwh=charged, base_price_per_kwh=connector.get('price_per_kwh'))
        multiplier = (station.get('demand') or {}).get('multiplier')
        if _surge(multiplier):
            result['demand_multiplier'] = multiplier
    return result


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
        adjusted = connector.get('base_price_per_kwh') is not None
        note = ''
        # O motorista vê só o preço final: o acréscimo por demanda (multiplicador) é do vendedor.
        if adjusted and not _surge(data.get('demand_multiplier')):
            note = ' (tarifa do horário)'  # tarifação por horário do posto, sem acréscimo de demanda
        terms.append(f"{money(connector['price_per_kwh'])}/kWh{note}")
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
