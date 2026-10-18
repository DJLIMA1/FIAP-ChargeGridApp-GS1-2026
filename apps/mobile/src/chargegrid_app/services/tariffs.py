"""Tarifas dinâmicas do vendedor (simulado, só no aparelho).

A API não tem tarifas dinâmicas: as regras ficam no cliente. Na conta demo, em memória;
na conta real, em JSON sob ``FLET_APP_STORAGE_DATA`` (como ``preferences.py``). Nenhum valor
é cobrado de verdade. ``effective_price`` é função pura e testada.
"""

import json
import os
from copy import deepcopy
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

DAY_LABELS = ('Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom')  # datetime.weekday(): 0 = segunda

DEFAULT_RULES = {
    'rotation': {'enabled': True, 'start_after_min': 30, 'interval_min': 10, 'amount': '0.20'},
    'demand': {'enabled': True, 'min_stations': 2, 'extra': '0.30'},
    'peak': {'enabled': True, 'start': '18:00', 'end': '21:00', 'extra': '0.25', 'days': [0, 1, 2, 3, 4, 5, 6]},
}

_DEMO_MEMORY = {}
_CENT = Decimal('0.01')


# ---------------------------------------------------------------- números pt-BR
def parse_decimal(text, *, minimum=Decimal('0'), maximum=Decimal('9999')):
    """Lê ``R$ 0,20``, ``+ R$ 0,30 por kWh``, ``1.234,50`` ou ``0.2``. ``None`` se inválido/fora da faixa."""
    if isinstance(text, (int, float, Decimal)):
        raw = str(text)
    else:
        raw = ''.join(ch for ch in str(text or '') if ch.isdigit() or ch in ',.')
    if not raw or not any(ch.isdigit() for ch in raw):
        return None
    if ',' in raw:
        raw = raw.replace('.', '').replace(',', '.')
    elif raw.count('.') > 1:
        raw = raw.replace('.', '')
    try:
        value = Decimal(raw)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < minimum or value > maximum:
        return None
    return value.quantize(Decimal('0.0001'))


def parse_minutes(text, *, minimum=1, maximum=1440):
    """Inteiro de minutos a partir de ``30 minutos`` / ``30``. ``None`` se inválido."""
    digits = ''.join(ch for ch in str(text or '') if ch.isdigit())
    if not digits or any(ch in str(text) for ch in ',.-'):
        return None
    value = int(digits)
    return value if minimum <= value <= maximum else None


def parse_time(text):
    """``18:00`` (ou ``18``, ``18h30``) -> ``'18:00'``; ``None`` se inválido."""
    raw = str(text or '').strip().lower().replace('h', ':')
    parts = raw.split(':')
    if len(parts) > 2 or not parts[0].isdigit() or (len(parts) == 2 and parts[1] not in ('',) and not parts[1].isdigit()):
        return None
    hour = int(parts[0])
    minute = int(parts[1]) if len(parts) == 2 and parts[1] else 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return f'{hour:02d}:{minute:02d}'


def fmt_money(value):
    """``Decimal`` -> ``R$ 0,20`` (2 casas, meio para cima)."""
    amount = Decimal(str(value)).quantize(_CENT, rounding=ROUND_HALF_UP)
    return f"R$ {str(amount).replace('.', ',')}"


def fmt_rate(value):
    """``R$ 1,89``."""
    return fmt_money(value)


def days_label(days):
    names = [DAY_LABELS[d] for d in sorted(set(days)) if 0 <= d < 7]
    if not names:
        return 'Nenhum dia'
    return names[0] if len(names) == 1 else ', '.join(names[:-1]) + ' e ' + names[-1]


# ---------------------------------------------------------------- cálculo
def _minutes_of_day(hhmm):
    hour, minute = hhmm.split(':')
    return int(hour) * 60 + int(minute)


def rotation_intervals(rule, minutes):
    """Quantos intervalos de rotatividade foram cobrados após ``minutes`` de ocupação."""
    if not rule or not rule.get('enabled') or minutes is None:
        return 0
    start, step = int(rule['start_after_min']), int(rule['interval_min'])
    if minutes <= start or step <= 0:
        return 0
    return int((minutes - start) // step)


def rotation_fee(rules, minutes):
    """Valor adicional de rotatividade (R$) para ``minutes`` de ocupação."""
    rule = (rules or {}).get('rotation')
    return Decimal(str(rule['amount'])) * rotation_intervals(rule, minutes) if rule else Decimal('0')


def in_peak(rule, now):
    if not rule or not rule.get('enabled') or now is None:
        return False
    if now.weekday() not in rule.get('days', []):
        return False
    start, end, current = _minutes_of_day(rule['start']), _minutes_of_day(rule['end']), now.hour * 60 + now.minute
    if start == end:
        return False
    return start <= current < end if start < end else (current >= start or current < end)


def effective_price(base, rules, now=None, occupancy=0, minutes=None):
    """Preço por kWh (``Decimal``) = base + adicional de demanda + adicional de pico.

    ``occupancy``: estações do vendedor em uso agora; ``minutes`` é aceito por compatibilidade
    (a rotatividade é cobrada à parte, ver ``rotation_fee``). Regras inativas/ausentes não somam.
    """
    price = Decimal(str(base))
    rules = rules or {}
    demand = rules.get('demand')
    if demand and demand.get('enabled') and int(occupancy or 0) >= int(demand['min_stations']):
        price += Decimal(str(demand['extra']))
    if in_peak(rules.get('peak'), now or datetime.now()):
        price += Decimal(str(rules['peak']['extra']))
    return price


def base_price(connectors):
    """Tarifa base da estação = menor ``price_per_kwh`` entre os conectores ativos (``None`` sem conectores)."""
    prices = []
    for connector in connectors or []:
        if connector.get('retired') or connector.get('active') is False:
            continue
        try:
            prices.append(Decimal(str(connector['price_per_kwh'])))
        except (KeyError, InvalidOperation):
            continue
    return min(prices) if prices else None


# ---------------------------------------------------------------- armazenamento
def _clean(raw):
    rules = deepcopy(DEFAULT_RULES)
    if not isinstance(raw, dict):
        return rules
    for key, default in DEFAULT_RULES.items():
        saved = raw.get(key)
        if isinstance(saved, dict):
            for field in default:
                if field in saved and type(saved[field]) is type(default[field]):
                    rules[key][field] = saved[field]
    return rules


class TariffStore:
    """Regras por estação. ``demo=True`` guarda só em memória."""

    def __init__(self, demo=False, path=None):
        self.demo = demo
        storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
        self.path = Path(path or storage / 'tariffs.json')

    def _read_all(self):
        if self.demo:
            return _DEMO_MEMORY
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def load(self, station_id):
        return _clean(self._read_all().get(str(station_id)))

    def save(self, station_id, rules):
        data = self._read_all()
        data[str(station_id)] = _clean(rules)
        if self.demo:
            return True
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data, ensure_ascii=False))
            return True
        except (OSError, TypeError, ValueError):
            return False

    def save_rule(self, station_id, key, rule):
        rules = self.load(station_id)
        rules[key] = rule
        return self.save(station_id, rules)


def reset_demo():
    _DEMO_MEMORY.clear()
