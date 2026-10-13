"""Sinal ao vivo opcional: clima por hora da Open-Meteo (gratuita, sem chave).

Timeout curto, cache em memória por região e falha silenciosa — sem clima, o
planejador usa só a heurística e a resposta diz isso.
"""
import logging
import threading
import time
from datetime import datetime

import httpx

from chargegrid_core.driver import WeatherSignal

URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_SECONDS = 2.0
TTL_SECONDS = 30 * 60
FAILURE_TTL_SECONDS = 5 * 60
_cache: dict[tuple[float, float], tuple[float, WeatherSignal | None]] = {}
_lock = threading.Lock()
log = logging.getLogger(__name__)


def _request(lat: float, lng: float) -> dict:
    response = httpx.get(URL, timeout=TIMEOUT_SECONDS, params={
        "latitude": round(lat, 2), "longitude": round(lng, 2),
        "hourly": "precipitation,temperature_2m", "timezone": "America/Sao_Paulo", "forecast_days": 2,
    })
    response.raise_for_status()
    return response.json()


def _parse(data: dict) -> WeatherSignal:
    hourly = data["hourly"]
    rows = zip(hourly["time"], hourly["precipitation"], hourly["temperature_2m"], strict=True)
    return WeatherSignal({datetime.fromisoformat(stamp): (rain, temperature) for stamp, rain, temperature in rows})


def weather_signal(lat: float, lng: float) -> WeatherSignal | None:
    key = (round(lat, 1), round(lng, 1))
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < (TTL_SECONDS if hit[1] is not None else FAILURE_TTL_SECONDS):
            return hit[1]
    try:
        signal = _parse(_request(lat, lng))
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        log.info("Open-Meteo indisponível; usando heurística: %s", type(error).__name__)
        signal = None
    with _lock:
        if len(_cache) > 256:
            _cache.clear()
        _cache[key] = (now, signal)
    return signal


def clear_cache():
    with _lock:
        _cache.clear()
