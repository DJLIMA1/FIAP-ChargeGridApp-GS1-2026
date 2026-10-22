"""Plano de autonomia compartilhado pelo app e pelo autoatendimento.

Extraído das regras existentes do assistente de recarga, preservando arredondamento,
consumo do carro e limite pelo espaço livre da bateria.
"""
from decimal import ROUND_HALF_UP, Decimal


def _decimal(value):
    try:
        return Decimal(str(value).strip().replace(',', '.'))
    except (ArithmeticError, ValueError):
        return Decimal(0)


def parse_km(text):
    raw = str(text or '').strip().lower().replace('km', '').strip()
    if not raw.isascii() or not raw.isdigit() or not 1 <= int(raw) <= 2000:
        raise ValueError('Informe a autonomia em km inteiros (ex.: 120).')
    return int(raw)


def autonomy_energy(km, consumption_kwh_per_100km, soc_percent, usable_kwh):
    """Energia para ``km`` de autonomia: ``km x consumo / 100``, limitada ao espaço livre da bateria
    (``(100 - SoC)% x bateria útil``). Devolve ``{energy_kwh, wanted_kwh, free_kwh, capped, km}``
    (``km`` = autonomia efetivamente adicionada)."""
    consumption = _decimal(consumption_kwh_per_100km)
    if consumption <= 0:
        raise ValueError('Consumo do carro inválido.')
    wanted = _decimal(km) * consumption / 100
    soc = min(Decimal(100), max(Decimal(0), _decimal(soc_percent)))
    free = (Decimal(100) - soc) / 100 * max(Decimal(0), _decimal(usable_kwh))
    capped = wanted > free
    energy = free if capped else wanted
    return {'energy_kwh': energy.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP),
            'wanted_kwh': wanted.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP),
            'free_kwh': free.quantize(Decimal('0.001'), rounding=ROUND_HALF_UP), 'capped': capped,
            'km': int((energy / consumption * 100).to_integral_value(rounding=ROUND_HALF_UP))}



def autonomy_note(result):
    """Aviso gentil quando a bateria não comporta toda a autonomia pedida (nunca mostra o SoC)."""
    if not result or not result.get('capped'):
        return None
    if result['energy_kwh'] <= 0:
        return 'A bateria do carro já está cheia: não há autonomia para adicionar agora.'
    return (f"A bateria comporta cerca de {result['km']} km agora; a recarga vai até encher "
            '(o restante não é cobrado).')

