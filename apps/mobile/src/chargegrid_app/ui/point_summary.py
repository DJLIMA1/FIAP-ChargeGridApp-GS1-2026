"""Public point identity shared by selection, reservations and charging."""

import flet as ft

from . import theme
from .components import card, money


def point_context(station, connector):
    return {
        'station_id': station['id'],
        'station_name': station['name'],
        'station_address': station['address'],
        'connector': {key: connector.get(key) for key in (
            'id', 'public_code', 'connector_type', 'power_kw',
            'price_per_kwh', 'max_duration_minutes',
        )},
    }


def point_summary(data, heading='Ponto selecionado'):
    data = data or {}
    connector = data.get('connector') or {}
    session_terms = 'price_per_kwh' in data
    controls = [ft.Text(heading.upper(), size=11, weight=ft.FontWeight.BOLD, color=theme.RED)]
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
        terms.append(f"{connector['power_kw']} kW")
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
