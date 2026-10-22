"""Tela Potência do vendedor, sem Flet: textos e contas sobre ``GET /stations/{id}/power``.

Mesmas regras da API (``chargegrid_core.site_load`` e ``chargegrid_core.power``): limite contratado
efetivo (o do dono ou o padrão do tipo/porte), consumo da loja SIMULADO, disponível para os
carregadores, potência configurada × efetiva de cada carregador e a validação do limite digitado.
"""

from decimal import Decimal, InvalidOperation

from chargegrid_core import power as power_rules
from chargegrid_core import site_load

POLL_SECONDS = 3             # atualização do cartão enquanto a tela está aberta
SITE_MAX_KW = Decimal(10000)
REBALANCE_HELP = 'Divide a potência entre os carros sem passar do limite contratado.'


def number(value):
    """``'28.5'`` -> ``Decimal('28.5')``; vazio/inválido -> ``None``."""
    if value is None or value == '':
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def kw(value, empty='—'):
    """``6 kW``, ``28,5 kW`` (até 1 casa, como a API arredonda) ou ``empty``."""
    amount = number(value)
    if amount is None:
        return empty
    rounded = amount.quantize(Decimal('0.1'))
    text = f'{rounded:.0f}' if rounded == rounded.to_integral_value() else f'{rounded:.1f}'.replace('.', ',')
    return f'{text} kW'


def has_rebalance(station):
    """A API manda as colunas do rebalanceamento no posto (``rebalance_enabled``)."""
    return isinstance((station or {}).get('rebalance_enabled'), bool)


def station_limit(station):
    """``(limite efetivo, é o padrão?)`` pelo posto (``GET stations/{id}``), como a API calcula."""
    station = station or {}
    return site_load.effective_site_limit(number(station.get('site_limit_kw')), station.get('building_profile'),
                                          station.get('building_size'))


def menu_subtitle(station):
    """Subtítulo do menu do posto: ``Limite 75 kW (padrão) · rebalanceamento ligado``."""
    limit, default = station_limit(station)
    head = f"Limite {kw(limit)}{' (padrão)' if default else ''}"
    return f"{head} · rebalanceamento {'ligado' if station.get('rebalance_enabled') else 'desligado'}"


def summary(view):
    """Cartão do topo: disponível, limite, loja (SIMULADO) e carros agora."""
    available = number(view.get('available_kw'))
    used = number(view.get('envelope_kw'))
    if used is None:
        used = number(view.get('allocated_kw')) or Decimal(0)
    exceeded = max(Decimal(0), number(view.get('exceeded_kw')) or Decimal(0))
    count = int(view.get('cars') or 0)
    profile = view.get('building_profile_label') or site_load.profile_label()
    manual = view.get('building_load_mode') == 'manual'
    return {
        'available': kw(available, 'Sem limite'),
        'limit': kw(view.get('site_limit_kw'), 'Sem limite'),
        'limit_detail': 'Padrão para o tipo de estabelecimento' if view.get('site_limit_default') else 'Informado por você',
        'load': kw(view.get('building_load_kw'), '0 kW'),
        'load_detail': 'Valor do simulador (30 min)' if manual else profile.split(' · ')[0],
        'cars': kw(used, '0 kW'),
        'cars_detail': 'Nenhum carro carregando' if not count else f"{count} carro{'s' if count != 1 else ''} carregando",
        'over': (f'Excesso transitório de {kw(exceeded)}: reduções enviadas, aguardando os equipamentos.'
                 if exceeded > 0 else None),
    }


def site_subtitle(view):
    """``75 kW (padrão) · Loja de conveniência`` (o porte fica na subtela)."""
    head = f"{kw(view.get('site_limit_kw'))}{' (padrão)' if view.get('site_limit_default') else ''}"
    return f"{head} · {site_load.PROFILES[site_load.profile_key(view.get('building_profile'))].label}"


def cap_subtitle(station):
    """``Sem teto · aviso desligado`` ou ``80 kW · aviso ligado``."""
    cap = power_rules.to_kw((station or {}).get('max_power_kw'))
    head = 'Sem teto' if cap is None else kw(cap)
    return f"{head} · aviso {'ligado' if station.get('power_limit_notify') else 'desligado'}"


def points(station):
    return [point for point in (station or {}).get('connectors') or [] if not point.get('retired')]


def point_name(point, index):
    """``CCS2 · Carregador 1``: o número é o endereço do carregador (dono) ou a posição no posto."""
    number = point.get('charger_address') or index
    return f"{point.get('connector_type') or 'Carregador'} · Carregador {number}"


def connector_line(point, station, view=None):
    """``60 kW configurados · 47 kW efetivos`` (carregando) ou ``... · até 55 kW efetivos`` (livre)."""
    if point.get('active') is False:
        return 'Inativo: fica fora da divisão do posto'
    configured = power_rules.requested_kw(point.get('power_kw'), point.get('power_limit_kw'))
    head = f'{kw(configured)} configurados'
    session = next(((item.get('session') or {}) for item in (view or {}).get('points') or []
                    if item.get('connector_id') == point.get('id')), {})
    if session:
        effective = number(session.get('applied_kw'))
        effective = number(session.get('target_kw')) if effective is None else effective
        if effective is not None:
            return f'{head} · {kw(effective)} efetivos'
    shared = power_rules.allocate(points(station), station.get('max_power_kw'))['connectors'].get(point.get('id'))
    effective = shared['effective_kw'] if shared else configured
    available = number((view or {}).get('available_kw'))
    if available is not None and available < effective:
        effective = available
    return f"{head} · até {kw(effective)} efetivos"


def limit_input(value):
    """Valor da API -> texto do campo (``75,5``; vazio sem valor)."""
    amount = number(value)
    if amount is None:
        return ''
    rounded = amount.quantize(Decimal('0.1'))
    return f'{rounded:.0f}' if rounded == rounded.to_integral_value() else f'{rounded:.1f}'.replace('.', ',')


def parse_site_limit(text):
    """Limite contratado digitado -> ``(valor da API | None, erro | None)``. Vazio = padrão do tipo/porte."""
    raw = str(text or '').strip()
    if not raw:
        return None, None
    cleaned = raw.replace(',', '.')
    parts = cleaned.split('.')
    if len(parts) > 2 or not parts[0].isdigit() or len(parts[0]) > 5 or \
            (len(parts) == 2 and (not parts[1].isdigit() or len(parts[1]) != 1)):
        return None, 'Use kW com até 1 casa, por exemplo 75,5.'
    amount = Decimal(cleaned)
    if amount <= 0:
        return None, 'Informe um limite maior que zero.'
    if amount > SITE_MAX_KW:
        return None, 'O limite contratado vai até 10.000 kW.'
    return f'{amount:.1f}', None
