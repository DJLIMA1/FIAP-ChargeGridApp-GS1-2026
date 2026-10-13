"""Modo Motorista: planejamento de turno e recarga para motoristas de app com carro elétrico.

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
from .models import (
    AMENITY_KINDS,
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

__all__ = [
    'AMENITY_KINDS', 'Amenity', 'BonusWindow', 'ChargeCurve', 'ChargerOption', 'CombinedDemand', 'DemandSignal',
    'DriverPreferences', 'HeuristicDemand', 'ManualContext', 'Meal', 'PRESETS', 'Plan', 'VehicleProfile',
    'WeatherSignal', 'base_multiplier', 'build_next_stop', 'build_plan', 'default_profile', 'hhmm',
    'merge_profile', 'next_stop', 'normalize_connector', 'options_from_stations', 'parse_hhmm',
    'peak_windows', 'plan_shift', 'presets', 'shift_window', 'validate_profile', 'vehicle_from_dict',
]
