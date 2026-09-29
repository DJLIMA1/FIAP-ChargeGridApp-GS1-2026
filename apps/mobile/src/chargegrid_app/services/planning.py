"""Temporary charging intentions and shared, explicitly nominal estimates."""
from decimal import Decimal, DecimalException, InvalidOperation


def estimate_charge(connector, minutes, max_cost=None):
    price = Decimal(str(connector.get('price_per_kwh')))
    power = Decimal(str(connector.get('power_kw')))
    duration = Decimal(str(minutes))
    if (not all(v.is_finite() for v in (price, power, duration))
            or not 0 <= price <= 10000 or not 0 < power <= 1000
            or not 1 <= duration <= 1440 or duration != duration.to_integral_value()):
        raise InvalidOperation
    energy = power * duration / 60
    if max_cost is not None:
        budget = Decimal(str(max_cost))
        if not budget.is_finite() or not 0 < budget <= 100000 or price <= 0:
            raise InvalidOperation
        energy = min(energy, budget / price)
    return {'energy_kwh': energy, 'cost': energy * price}


def estimate_text(connector, minutes, max_cost=None):
    try:
        result = estimate_charge(connector, minutes, max_cost)
        energy = f"{result['energy_kwh']:.2f}".replace('.', ',')
        if max_cost is not None:
            return f'Estimativa de até {energy} kWh antes de cupons, considerando a tarifa e o tempo máximo. O consumo real varia.'
        cost = f"R$ {result['cost']:,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.')
        return f'Na potência nominal: cerca de {energy} kWh e {cost} antes de cupons. O consumo real varia.'
    except (DecimalException, TypeError, ValueError):
        return 'A estimativa depende da tarifa, potência e limites do ponto. Nenhuma cobrança real.'


def intent_limits(connector, intent):
    """Clamp an intention against this point; free points always use a time limit."""
    maximum = int(connector.get('max_duration_minutes') or 1440)
    if intent.get('mode') == 'value' and Decimal(str(connector.get('price_per_kwh', 0))) > 0:
        return {'minutes': maximum, 'max_cost': intent['max_cost']}
    return {'minutes': min(maximum, int(intent.get('minutes', 30)))}
