"""Perfis de veículo elétrico e curva de carga simplificada.

Os presets são **estimativas** a partir de fichas públicas e testes de rodagem
urbanos; o consumo real varia com ar-condicionado, trânsito, relevo e carga.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from functools import lru_cache

AC_CONNECTORS = frozenset({'type2', 'type1', 'gbtac'})
DC_CONNECTORS = frozenset({'ccs2', 'ccs1', 'chademo', 'gbtdc'})


@lru_cache(maxsize=512)
def _normalize(value: str) -> str:
    """Mesma normalização da descoberta de postos (Tipo 2 → type2, CCS → ccs2)."""
    key = ''.join(character for character in value.casefold() if character.isalnum())
    return {'tipo2': 'type2', 'typeii': 'type2', 'mennekes': 'type2', 'ccs': 'ccs2', 'ccstype2': 'ccs2',
            'combo2': 'ccs2', 'tipo1': 'type1', 'j1772': 'type1', 'gbt': 'gbtac'}.get(key, key)


def normalize_connector(value) -> str:
    """Mesma normalização da descoberta de postos (Tipo 2 → type2, CCS → ccs2)."""
    return _normalize(str(value or ''))


def is_dc(connector_type: str) -> bool:
    return normalize_connector(connector_type) in DC_CONNECTORS


@dataclass(frozen=True)
class VehicleProfile:
    """Veículo do motorista. Energia em kWh, consumo em kWh/100 km, potências em kW."""

    key: str
    name: str
    usable_battery_kwh: float
    consumption_kwh_per_100km: float
    max_ac_kw: float = 7.0
    max_dc_kw: float = 60.0
    connectors: tuple[str, ...] = ('type2', 'ccs2')
    estimate: bool = True

    def __post_init__(self):
        if not 5 <= self.usable_battery_kwh <= 250:
            raise ValueError('Bateria útil deve ficar entre 5 e 250 kWh')
        if not 5 <= self.consumption_kwh_per_100km <= 60:
            raise ValueError('Consumo deve ficar entre 5 e 60 kWh/100 km')
        if not 1 <= self.max_ac_kw <= 43 or not 0 <= self.max_dc_kw <= 400:
            raise ValueError('Potência máxima do veículo fora da faixa')
        object.__setattr__(self, 'connectors', tuple(dict.fromkeys(normalize_connector(c) for c in self.connectors)))

    @property
    def range_km(self) -> float:
        return self.usable_battery_kwh / self.consumption_kwh_per_100km * 100

    def accepts(self, connector_type: str) -> bool:
        kind = normalize_connector(connector_type)
        if kind in DC_CONNECTORS and self.max_dc_kw <= 0:
            return False
        return kind in self.connectors

    def effective_power(self, station_kw: float, connector_type: str) -> float:
        limit = self.max_dc_kw if is_dc(connector_type) else self.max_ac_kw
        return max(0.0, min(float(station_kw), limit))

    def to_dict(self) -> dict:
        data = asdict(self)
        data['connectors'] = list(self.connectors)
        data['range_km'] = round(self.range_km)
        return data


def _preset(key, name, battery, consumption, ac, dc, connectors=('type2', 'ccs2')):
    return VehicleProfile(key, name, battery, consumption, ac, dc, connectors, True)


# Valores aproximados (bateria útil, consumo urbano real de motorista de app,
# AC e DC máximos). Sempre exibidos como "estimativa".
PRESETS: dict[str, VehicleProfile] = {p.key: p for p in (
    _preset('byd_dolphin', 'BYD Dolphin', 44.9, 14.0, 6.6, 60),
    _preset('byd_dolphin_mini', 'BYD Dolphin Mini', 38.0, 12.5, 6.6, 40),
    _preset('byd_seal', 'BYD Seal', 82.5, 16.5, 11.0, 150),
    _preset('byd_yuan_plus', 'BYD Yuan Plus', 60.5, 16.0, 7.0, 88),
    _preset('gwm_ora_03', 'GWM Ora 03', 48.0, 14.5, 6.6, 64),
    _preset('renault_kwid_etech', 'Renault Kwid E-Tech', 26.8, 13.5, 7.0, 30),
    _preset('volvo_ex30', 'Volvo EX30', 51.0, 16.5, 11.0, 134),
    _preset('chevrolet_bolt', 'Chevrolet Bolt EV', 65.0, 16.0, 11.0, 55),
    _preset('chevrolet_spark_euv', 'Chevrolet Spark EUV', 42.0, 14.5, 6.6, 70),
    _preset('jac_ej1', 'JAC E-JS1', 30.0, 13.0, 6.6, 30),
)}
DEFAULT_PRESET = 'byd_dolphin'


def vehicle_from_dict(data: dict | None) -> VehicleProfile:
    """Preset (``{"preset": "byd_dolphin"}``) com sobrescritas opcionais, ou veículo personalizado."""
    data = dict(data or {})
    requested = data.get('preset') or data.get('key')
    if requested and requested != 'custom':
        base = PRESETS.get(str(requested))
        if base is None:
            raise ValueError('Modelo de veículo desconhecido')
    elif requested == 'custom' or data.get('usable_battery_kwh') is not None:
        base = None
        if data.get('usable_battery_kwh') is None:
            raise ValueError('Informe a bateria útil do veículo personalizado')
    else:
        base = PRESETS[DEFAULT_PRESET]
    fields = {}
    for name in ('usable_battery_kwh', 'consumption_kwh_per_100km', 'max_ac_kw', 'max_dc_kw'):
        value = data.get(name)
        if value is not None:
            number = float(value)
            if not math.isfinite(number):
                raise ValueError('Valor numérico inválido para o veículo')
            fields[name] = number
    if base is None:
        return VehicleProfile(
            key='custom', name=str(data.get('name') or 'Meu veículo')[:60],
            usable_battery_kwh=fields['usable_battery_kwh'],
            consumption_kwh_per_100km=fields.get('consumption_kwh_per_100km', 15.0),
            max_ac_kw=fields.get('max_ac_kw', 7.0), max_dc_kw=fields.get('max_dc_kw', 50.0),
            connectors=tuple(data.get('connectors') or ('type2', 'ccs2')), estimate=True)
    return VehicleProfile(
        key=base.key,
        name=str(data.get('name') or base.name)[:60],
        usable_battery_kwh=fields.get('usable_battery_kwh', base.usable_battery_kwh),
        consumption_kwh_per_100km=fields.get('consumption_kwh_per_100km', base.consumption_kwh_per_100km),
        max_ac_kw=fields.get('max_ac_kw', base.max_ac_kw), max_dc_kw=fields.get('max_dc_kw', base.max_dc_kw),
        connectors=tuple(data.get('connectors') or base.connectors), estimate=True)


@dataclass(frozen=True)
class ChargeCurve:
    """Potência constante até ``knee`` (fração de SoC) e queda linear até ``floor``×P em 100%.

    Modelo simplificado: DC costuma cair após ~80%; AC é quase plano até ~90%.
    """

    knee: float = 0.8
    floor: float = 0.25

    @staticmethod
    def for_connector(connector_type: str) -> ChargeCurve:
        return _DC_CURVE if is_dc(connector_type) else _AC_CURVE

    def power_at(self, power_kw: float, soc: float) -> float:
        if soc <= self.knee:
            return power_kw
        return power_kw * (1 - (1 - self.floor) * (min(1.0, soc) - self.knee) / (1 - self.knee))

    def charge(self, battery_kwh: float, power_kw: float, soc_start: float, minutes: float,
               soc_cap: float = 1.0) -> float:
        """SoC (fração) após ``minutes`` de carga, solução analítica do modelo linear por partes."""
        soc, cap = max(0.0, soc_start), min(1.0, soc_cap)
        if power_kw <= 0 or minutes <= 0 or soc >= cap:
            return soc
        hours = minutes / 60
        if soc < self.knee:
            to_knee = (min(self.knee, cap) - soc) * battery_kwh / power_kw
            if hours <= to_knee:
                return min(cap, soc + power_kw * hours / battery_kwh)
            hours -= to_knee
            soc = min(self.knee, cap)
            if soc >= cap:
                return cap
        # Região de queda: dP/ds linear → ds/dt = (a - b·s)/B → exponencial.
        b = power_kw * (1 - self.floor) / (1 - self.knee)
        a = power_kw + b * self.knee
        target = a / b
        soc = target - (target - soc) * math.exp(-b * hours / battery_kwh)
        return min(cap, soc)

    def minutes_to(self, battery_kwh: float, power_kw: float, soc_start: float, soc_end: float) -> float:
        """Inverso de ``charge``: minutos para ir de ``soc_start`` a ``soc_end``."""
        if power_kw <= 0:
            return math.inf
        soc, end, minutes = soc_start, min(1.0, soc_end), 0.0
        if soc >= end:
            return 0.0
        if soc < self.knee:
            stop = min(self.knee, end)
            minutes += (stop - soc) * battery_kwh / power_kw * 60
            soc = stop
            if soc >= end:
                return minutes
        b = power_kw * (1 - self.floor) / (1 - self.knee)
        a = power_kw + b * self.knee
        target = a / b
        if end >= target:
            return math.inf
        return minutes + battery_kwh / b * math.log((target - soc) / (target - end)) * 60


_DC_CURVE = ChargeCurve(0.8, 0.25)
_AC_CURVE = ChargeCurve(0.9, 0.6)
