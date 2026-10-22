"""Plano de autonomia compartilhado pelo app e pelo autoatendimento.

Extraído das regras existentes do assistente de recarga, preservando arredondamento,
consumo do carro e limite pelo espaço livre da bateria.
"""
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal


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



MAX_KM = 2000  # mesmo teto de ``parse_km``
CENT = Decimal('0.01')


def charge_maxima(power_kw, price_per_kwh, max_minutes, *, consumption=None, soc=None, usable_kwh=None,
                  discount_percent=0):
    """Máximos de uma recarga em cada modo, para mostrar ANTES de o motorista pedir.

    * ``minutes``: limite do ponto (``max_duration_minutes``; 1..1440);
    * ``energy_kwh``: o menor entre ``potência x tempo máximo`` e o espaço livre da bateria
      (``(100 - SoC)% x bateria útil``, quando o carro é conhecido);
    * ``value``: essa energia x tarifa efetiva (desconto aplicado), arredondada PARA BAIXO no
      centavo: pedir exatamente o máximo cabe no tempo do ponto (a mesma conta de
      ``billing.quote_cap`` no modo valor). ``None`` com tarifa gratuita;
    * ``km``: essa energia / consumo x 100, para baixo (``None`` sem consumo do carro);
    * ``bound``: ``'battery'`` quando a bateria limita antes do tempo, senão ``'time'``.

    O SoC nunca sai daqui: só os máximos derivados dele.
    """
    power = max(Decimal(0), _decimal(power_kw))
    minutes = max(1, min(1440, int(_decimal(max_minutes) or 1440)))
    by_time = power * minutes / 60
    energy, bound = by_time, 'time'
    if soc is not None and usable_kwh is not None:
        level = min(Decimal(100), max(Decimal(0), _decimal(soc)))
        free = (Decimal(100) - level) / 100 * max(Decimal(0), _decimal(usable_kwh))
        if free < by_time:
            energy, bound = free, 'battery'
    energy = energy.quantize(Decimal('0.001'), rounding=ROUND_DOWN)
    price = _decimal(price_per_kwh) * Decimal(100 - int(discount_percent or 0)) / 100
    value = (energy * price).quantize(CENT, rounding=ROUND_DOWN) if price > 0 else None
    km = None
    rate = _decimal(consumption)
    if rate > 0:
        km = min(MAX_KM, int((energy / rate * 100).to_integral_value(rounding=ROUND_DOWN)))
    return {'minutes': minutes, 'energy_kwh': energy, 'value': value, 'km': km, 'bound': bound}


def autonomy_note(result):
    """Aviso gentil quando a bateria não comporta toda a autonomia pedida (nunca mostra o SoC)."""
    if not result or not result.get('capped'):
        return None
    if result['energy_kwh'] <= 0:
        return 'A bateria do carro já está cheia: não há autonomia para adicionar agora.'
    return (f"A bateria comporta cerca de {result['km']} km agora; a recarga vai até encher "
            '(o restante não é cobrado).')

