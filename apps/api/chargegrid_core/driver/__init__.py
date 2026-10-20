"""Modo Motorista: planejamento de turno e recarga para motoristas de app com carro elétrico.

**DESCONTINUADO em 20/10/2026** (``DISCONTINUED``): desligado em produção. A API responde 410 em
``/v1/driver/*``, o assistente de IA não oferece mais o planejamento e o app não mostra a entrada.
O código fica no repositório como referência; nada aqui é chamado em produção.

Lógica pura (stdlib, determinística). Demanda é sempre **estimativa** — não há API
oficial pública de demanda da Uber/99.
"""

from .demand import (
    BonusWindow,
    CombinedDemand,
    DemandSignal,
    HeuristicDemand,
    ManualContext,
    WeatherSignal,
    base_multiplier,
    peak_windows,
)
from .earnings import EarningsSource, Trip, TripHistory, resolve_earnings
from .models import (
    AMENITY_KINDS,
    SOURCE_CHOICES,
    Amenity,
    ChargerOption,
    DriverPreferences,
    Meal,
    hhmm,
    options_from_stations,
    parse_hhmm,
)
from .planner import Plan, next_stop, plan_shift
from .service import (
    build_context,
    build_next_stop,
    build_plan,
    default_profile,
    merge_profile,
    presets,
    shift_window,
    validate_profile,
)
from .vehicles import (
    PRESETS,
    ChargeCurve,
    VehicleProfile,
    normalize_connector,
    vehicle_from_dict,
)
from .weather import condition_text, rain_note, simulated_weather, weather_summary

__all__ = [
    'AMENITY_KINDS', 'Amenity', 'BonusWindow', 'ChargeCurve', 'ChargerOption', 'CombinedDemand', 'DemandSignal',
    'DriverPreferences', 'EarningsSource', 'HeuristicDemand', 'ManualContext', 'Meal', 'PRESETS', 'Plan',
    'SOURCE_CHOICES', 'Trip', 'TripHistory', 'VehicleProfile', 'WeatherSignal', 'base_multiplier',
    'build_context', 'build_next_stop', 'build_plan', 'condition_text', 'default_profile', 'hhmm',
    'merge_profile', 'next_stop', 'normalize_connector', 'options_from_stations', 'parse_hhmm',
    'peak_windows', 'plan_shift', 'presets', 'rain_note', 'resolve_earnings', 'shift_window',
    'simulated_weather', 'validate_profile', 'vehicle_from_dict', 'weather_summary',
]

# Descontinuado em 20/10/2026: API (410), assistente e app não usam mais este módulo.
DISCONTINUED = True
