"""Clima em uma linha para o motorista e o aviso de chuva do plano (puro, sem rede).

A fonte é um ``WeatherSignal`` (Open-Meteo na API; ``simulado`` na demonstração). Só chuva e
temperatura por hora mexem na demanda; condição e temperatura "agora" servem para o resumo.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from .demand import WeatherSignal

RAIN_MM = 0.2
CURRENT_MAX_AGE_MINUTES = 75
SOURCE_LABELS = {'open-meteo': 'Open-Meteo', 'simulado': 'simulado'}
# Códigos de tempo WMO (Open-Meteo) → texto curto em português.
_CONDITIONS = (
    ((0,), 'céu limpo'), ((1,), 'poucas nuvens'), ((2,), 'parcialmente nublado'), ((3,), 'nublado'),
    ((45, 48), 'neblina'), ((51, 53, 55, 56, 57), 'garoa'), ((61, 63, 65, 66, 67), 'chuva'),
    ((71, 73, 75, 77, 85, 86), 'neve'), ((80, 81, 82), 'pancadas de chuva'), ((95, 96, 99), 'tempestade'),
)
RAINY_CODES = frozenset((51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99))


def condition_text(code) -> str | None:
    try:
        code = int(code)
    except (TypeError, ValueError):
        return None
    return next((text for codes, text in _CONDITIONS if code in codes), None)


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _hour(when: datetime) -> datetime:
    return when.replace(minute=0, second=0, microsecond=0, tzinfo=None)


def weather_summary(signal: WeatherSignal, now: datetime, horizon_hours: int = 12) -> dict:
    """``{status, source, temperature_c, condition, rain_now, next_rain_at, label}`` para uma linha da tela."""
    hour = _hour(now)
    current = signal.current if isinstance(signal.current, dict) else {}
    taken = current.get('time')
    if isinstance(taken, datetime) and abs((taken.replace(tzinfo=None) - now.replace(tzinfo=None))
                                           .total_seconds()) > CURRENT_MAX_AGE_MINUTES * 60:
        current = {}  # leitura "agora" velha (cache): vale a previsão daquela hora
    precipitation, temperature = signal.conditions(now) or (None, None)
    temperature = _number(current.get('temperature', temperature))
    precipitation = _number(current.get('precipitation', precipitation))
    code = current.get('weather_code', signal.codes.get(hour))
    condition = condition_text(code)
    rain_now = (precipitation is not None and precipitation >= RAIN_MM) or (
        code is not None and _number(code) in RAINY_CODES)
    upcoming = [when for when in signal.rainy_hours(now, hour + timedelta(hours=horizon_hours)) if when > hour]
    next_rain = None if rain_now or not upcoming else upcoming[0]
    parts = [f'{round(temperature)}°'] if temperature is not None else []
    if rain_now:
        parts += [condition or 'chuva', 'mais corridas agora']
    else:
        if condition:
            parts.append(condition)
        parts.append(f'chuva às {next_rain.hour}h' if next_rain else 'sem chuva prevista')
    simulated = signal.source == 'simulado'
    label = ' · '.join(parts) + (' (simulado)' if simulated else '')
    return {'status': 'simulado' if simulated else 'ok', 'source': signal.source,
            'temperature_c': None if temperature is None else round(temperature, 1), 'condition': condition,
            'rain_now': bool(rain_now), 'next_rain_at': next_rain.strftime('%H:%M') if next_rain else None,
            'label': label}


def rain_note(signal: WeatherSignal, now: datetime, horizon_hours: int = 16) -> dict | None:
    """Alerta informativo do plano quando há chuva prevista (a curva de demanda já a considera)."""
    rainy = signal.rainy_hours(now, _hour(now) + timedelta(hours=horizon_hours))
    if not rainy:
        return None
    source = SOURCE_LABELS.get(signal.source, signal.source)
    return {'level': 'info', 'code': 'rain',
            'message': f'Chuva prevista a partir das {rainy[0].hour}h ({source}): a procura por '
                       'corridas tende a subir — o plano já considera isso.'}


def simulated_weather(now: datetime, rain_hours: tuple[int, ...] = (18, 19)) -> WeatherSignal:
    """Clima fixo da demonstração (rotulado "simulado"): nublado, 23°, chuva das 18h às 20h, hoje e amanhã."""
    day = now.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    hourly, codes = {}, {}
    for offset in range(48):
        when = day + timedelta(hours=offset)
        rain = when.hour in rain_hours
        hourly[when] = (1.5 if rain else 0.0, 21.0 if rain else 23.0)
        codes[when] = 61 if rain else 3
    precipitation, temperature = hourly[_hour(now)]
    current = {'temperature': temperature, 'precipitation': precipitation, 'weather_code': codes[_hour(now)],
               'time': now.replace(tzinfo=None)}
    return WeatherSignal(hourly, source='simulado', codes=codes, current=current)
