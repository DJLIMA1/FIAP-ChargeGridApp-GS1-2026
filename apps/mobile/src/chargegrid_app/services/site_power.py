"""Energia do estabelecimento (rebalanceamento ao vivo) vista pelo vendedor, sem Flet.

Mesmas regras do painel web (``apps/owner-web/src/lib/power.ts``) sobre ``GET /stations/{id}/power``:
rótulos do estado e do gatilho, kW com até 1 casa, soma da potência dos pontos contra o disponível,
texto "30 kW contratados − 12 kW da loja = 18 kW para recarga", faixa do controle do consumo da loja
(SIMULADO), validação do limite contratado e o debounce do controle deslizante.
"""

import asyncio
from decimal import ROUND_CEILING, Decimal, InvalidOperation

POLL_SECONDS = 1.5           # atualização do cartão enquanto a página está aberta
DEBOUNCE_SECONDS = 0.35      # espera sem mexer no controle antes de gravar o consumo simulado
SITE_MAX_KW = Decimal(10000)

# Estado da potência do ponto (``power_state``): rótulo e tom (``theme``).
POWER_STATE = {
    'applied': ('Aplicada', 'GREEN'),
    'reducing': ('Reduzindo', 'AMBER'),
    'raising': ('Aumentando', 'BLUE'),
    'waiting': ('Aguardando', 'AMBER'),
    'paused': ('Pausada', 'RED'),
    'fixed': ('Fixa', 'SLATE'),
}

POWER_TRIGGER = {
    'initial': 'Início',
    'building_load_changed': 'Consumo da loja',
    'site_limit_changed': 'Limite contratado',
    'station_cap_changed': 'Teto do posto',
    'session_started': 'Recarga iniciada',
    'session_ended': 'Recarga encerrada',
    'request_changed': 'Pedido alterado',
    'power_confirmed': 'Confirmação do equipamento',
}


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


def usage(view):
    """Soma das potências reservadas aos pontos contra o disponível.

    ``{used, available, fraction (0–1, para a barra), exceeded, over}``."""
    used = number(view.get('envelope_kw'))
    if used is None:
        used = number(view.get('allocated_kw')) or Decimal(0)
    available = number(view.get('available_kw'))
    exceeded = max(Decimal(0), number(view.get('exceeded_kw')) or Decimal(0))
    if available is not None and available > 0:
        fraction = min(Decimal(1), used / available)
    else:
        fraction = Decimal(1) if used > 0 else Decimal(0)
    over = exceeded > 0 or (available is not None and used > available)
    return {'used': used, 'available': available, 'fraction': float(fraction), 'exceeded': exceeded, 'over': over}


def availability_text(view):
    """``30 kW contratados − 12 kW da loja = 18 kW para recarga`` (ou o texto sem limite)."""
    limit = number(view.get('site_limit_kw'))
    load = number(view.get('building_load_kw')) or Decimal(0)
    if limit is None:
        return f"Sem limite contratado: vale o teto do posto ({kw(view.get('station_cap_kw'), 'potência nominal')})."
    return f"{kw(limit)} contratados − {kw(load)} da loja = {kw(view.get('available_kw'))} para recarga"


def load_max(view):
    """Fim do controle do consumo da loja: o limite contratado (ou 100 kW sem limite), no mínimo 10."""
    limit = number(view.get('site_limit_kw'))
    load = number(view.get('building_load_kw')) or Decimal(0)
    top = max(limit if limit is not None else Decimal(100), load)
    return max(10, int(top.to_integral_value(rounding=ROUND_CEILING)))


def limit_input(value):
    """Valor da API -> texto do campo (``75,5``; vazio sem limite)."""
    amount = number(value)
    if amount is None:
        return ''
    rounded = amount.quantize(Decimal('0.1'))
    return f'{rounded:.0f}' if rounded == rounded.to_integral_value() else f'{rounded:.1f}'.replace('.', ',')


def parse_site_limit(text):
    """Limite contratado digitado -> ``(valor da API | None, erro | None)``. Vazio remove o limite."""
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


def state_label(session):
    """(rótulo, tom) do estado do ponto; ``Livre`` sem sessão, ``Em recarga`` sem rebalanceamento."""
    if not session:
        return 'Livre', 'SLATE'
    state = session.get('power_state')
    if not state:
        return 'Em recarga', 'BLUE'
    return POWER_STATE.get(state, (str(state), 'SLATE'))


def point_detail(point):
    """``60 kW nominal · carga fixa · offline``."""
    parts = [f"{kw(point.get('power_kw'))} nominal"]
    if point.get('adjustable') is False:
        parts.append('carga fixa')
    if point.get('online') is False:
        parts.append('offline')
    return ' · '.join(parts)


def decision_detail(decision):
    """``Consumo da loja · 18 kW disponíveis · excesso 3 kW``."""
    trigger = decision.get('trigger')
    parts = [POWER_TRIGGER.get(trigger, str(trigger or 'Decisão')),
             f"{kw(decision.get('available_kw'), 'sem limite')} disponíveis"]
    if (number(decision.get('exceeded_kw')) or 0) > 0:
        parts.append(f"excesso {kw(decision.get('exceeded_kw'))}")
    return ' · '.join(parts)


def over_text(view, info):
    """Aviso quando a soma passa do disponível (redução em andamento ou rebalanceamento desligado)."""
    if not info['over']:
        return None
    amount = info['exceeded'] if info['exceeded'] > 0 else info['used'] - (info['available'] or 0)
    if view.get('rebalance_enabled'):
        return (f'Excesso transitório de {kw(amount)}: as reduções já foram enviadas e aguardam a confirmação '
                'dos equipamentos.')
    return f'{kw(amount)} acima do disponível: ligue o rebalanceamento para reduzir os pontos em recarga.'


class Debouncer:
    """Último valor vence: ``call(valor)`` agenda o envio; ``flush()`` envia já (ao soltar o controle).

    Os envios são em fila (um de cada vez) para a resposta mais nova ser a última aplicada."""

    def __init__(self, send, wait=DEBOUNCE_SECONDS):
        self.send, self.wait = send, wait
        self._task = None
        self._last = None
        self._lock = None
        self._sending = 0

    @property
    def pending(self):
        """Há valor aguardando a pausa ou um envio em andamento (o controle fica com o valor local)."""
        return self._last is not None or self._sending > 0

    def __call__(self, *args):
        self._last = args
        if self._task is not None:
            self._task.cancel()
        self._task = asyncio.ensure_future(self._later())

    async def _later(self):
        try:
            await asyncio.sleep(self.wait)
        except asyncio.CancelledError:
            return
        self._task = None
        await self._run()

    async def flush(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None
        await self._run()

    def cancel(self):
        if self._task is not None:
            self._task.cancel()
        self._task = None
        self._last = None

    async def _run(self):
        if self._last is None:
            return
        if self._lock is None:
            self._lock = asyncio.Lock()
        self._sending += 1
        try:
            async with self._lock:
                args, self._last = self._last, None
                if args is not None:
                    await self.send(*args)
        finally:
            self._sending -= 1
