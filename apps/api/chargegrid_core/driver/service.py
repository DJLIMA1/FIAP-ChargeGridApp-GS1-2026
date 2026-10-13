"""Fachada usada pela API e pelo modo demo: payload JSON + postos → plano JSON."""

from __future__ import annotations

from datetime import datetime, timedelta

from .demand import (
    BonusWindow,
    CombinedDemand,
    DemandSignal,
    HeuristicDemand,
    ManualContext,
)
from .models import DriverPreferences, options_from_stations
from .planner import SLOT_MINUTES, next_stop, plan_shift
from .vehicles import PRESETS, vehicle_from_dict

MODES = ('auto', 'full_shift')


def default_profile() -> dict:
    return {'vehicle': {'preset': 'byd_dolphin'}, 'preferences': DriverPreferences().to_dict()}


def presets() -> list[dict]:
    return [preset.to_dict() for preset in PRESETS.values()]


def merge_profile(saved: dict | None, overrides: dict | None) -> dict:
    """Perfil salvo + sobrescritas da requisição (rasas, por seção)."""
    base = default_profile()
    for source in (saved or {}, overrides or {}):
        for section in ('vehicle', 'preferences'):
            if isinstance(source.get(section), dict):
                if section == 'vehicle' and source[section].get('preset'):
                    base['vehicle'] = {}
                base[section] = {**base[section], **source[section]}
    return base


def validate_profile(profile: dict) -> dict:
    """Valida e normaliza (levanta ValueError com mensagem em português)."""
    vehicle = vehicle_from_dict(profile.get('vehicle'))
    preferences = DriverPreferences.from_dict(profile.get('preferences'))
    vehicle_data = dict(profile.get('vehicle') or {})
    vehicle_data.setdefault('preset', vehicle.key)
    return {'vehicle': vehicle_data, 'preferences': preferences.to_dict()}


def _floor(now: datetime) -> datetime:
    now = now.replace(second=0, microsecond=0)
    return now - timedelta(minutes=now.minute % SLOT_MINUTES)


def shift_window(preferences: DriverPreferences, now: datetime, mode: str = 'auto') -> tuple[datetime, datetime]:
    """Janela a planejar. ``auto``: do agora até o fim do turno em andamento, ou o próximo turno.
    ``full_shift``: o turno de hoje inteiro (ou o de amanhã, se o de hoje já acabou)."""
    if mode not in MODES:
        raise ValueError('Modo de planejamento inválido')
    day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    length = timedelta(minutes=preferences.shift_minutes)
    today = day + timedelta(minutes=preferences.shift_start)
    for start in (today - timedelta(days=1), today):
        end = start + length
        if start <= now < end and mode == 'auto':
            current = _floor(now)
            if end - current >= timedelta(minutes=SLOT_MINUTES):
                return current, end
        if mode == 'full_shift' and now < end and start.date() == day.date():
            return start, end
    if now < today:
        return today, today + length
    return today + timedelta(days=1), today + timedelta(days=1) + length


def _demand(context: dict, start: datetime, extra: tuple[DemandSignal, ...]):
    holidays = frozenset({start.date()}) if context.get('holiday') else frozenset()
    bonuses = ()
    if context.get('airport'):
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        bonuses = tuple(BonusWindow('Aeroporto', day + timedelta(days=d, hours=h0), day + timedelta(days=d, hours=h1), 1.15)
                        for d in (0, 1) for h0, h1 in ((5, 8), (21, 24)))
    extras = list(extra)
    if context.get('rain') is True and not extra:
        extras.append(ManualContext(rain=True))
    return CombinedDemand(HeuristicDemand(holidays, bonuses), tuple(extras))


def _origin(payload):
    lat, lng = payload.get('lat'), payload.get('lng')
    if lat is None or lng is None:
        return None
    return float(lat), float(lng)


def build_plan(payload: dict, profile: dict, stations: list[dict], now: datetime,
               signals: tuple[DemandSignal, ...] = (), notes: list[dict] | None = None) -> dict:
    """``now`` em horário local (sem fuso). ``profile`` já mesclado e validado."""
    vehicle = vehicle_from_dict(profile.get('vehicle'))
    preferences = DriverPreferences.from_dict(profile.get('preferences'))
    start, end = shift_window(preferences, now, payload.get('mode') or 'auto')
    demand = _demand(payload.get('context') or {}, start, signals)
    options = options_from_stations(stations, vehicle)
    plan = plan_shift(vehicle, preferences, options, start, end, float(payload['soc_percent']), demand,
                      _origin(payload), notes).to_dict()
    plan['mode'] = payload.get('mode') or 'auto'
    return plan


def build_next_stop(payload: dict, profile: dict, stations: list[dict], now: datetime,
                    signals: tuple[DemandSignal, ...] = ()) -> dict:
    vehicle = vehicle_from_dict(profile.get('vehicle'))
    preferences = DriverPreferences.from_dict(profile.get('preferences'))
    start, end = shift_window(preferences, now, 'auto')
    if start > now:  # fora do turno: olha as próximas 4 horas
        end = _floor(now) + timedelta(hours=4)
    demand = _demand(payload.get('context') or {}, _floor(now), signals)
    options = options_from_stations(stations, vehicle)
    return next_stop(vehicle, preferences, options, now, end, float(payload['soc_percent']), demand,
                     _origin(payload))
