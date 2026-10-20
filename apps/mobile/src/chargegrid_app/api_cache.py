"""Cache em memória das respostas GET da API, com regras de frescor e de invalidação.

Só o ``ApiClient`` real usa este módulo (a demonstração responde no próprio aparelho).

* **Política por rota** (``POLICIES``): ``fresh`` = segundos em que a resposta é servida sem rede;
  ``stale`` = idade máxima para mostrar a última resposta na hora e revalidar em segundo plano
  (stale-while-revalidate). Rotas sem política nunca são guardadas (ex.: ``charging-sessions/{id}``,
  pagamentos, dispositivos).
* **Leitura do cache só na montagem das telas**: ``reading()`` (usado por ``app.go``) libera o cache
  dentro daquele contexto. Polls, ações e consultas em segundo plano sempre vão à rede e atualizam o
  cache (escrita direta), então o que a tela mostra nunca fica mais velho que o último poll.
* **Invalidação**: toda escrita (POST/PUT/PATCH/DELETE) descarta antes e depois de enviar as
  respostas que ela pode mudar (``invalidation``). Uma consulta que começou antes da escrita não é
  guardada quando termina depois dela (``epoch``).
"""
import re
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from time import monotonic

clock = monotonic  # trocável nos testes (simula o tempo passado numa aba)
MAX_ENTRIES = 300  # consultas com período que muda a cada minuto não crescem sem limite

# (rota, fresco em segundos, idade máxima para servir e revalidar)
POLICIES = tuple((re.compile(pattern), fresh, stale) for pattern, fresh, stale in (
    (r'me', 60, 3600),
    (r'driver/profile', 60, 3600),
    (r'payments/config', 300, 86400),
    (r'stations', 10, 900),
    (r'stations/[^/]+', 10, 900),
    (r'stations/[^/]+/best-times', 60, 900),
    (r'stations/[^/]+/(pricing|economics)', 30, 900),
    (r'stations/[^/]+/power', 2, 120),
    (r'stations/[^/]+/charging-sessions', 15, 900),
    (r'operator/stations', 10, 900),
    (r'operator/charging-sessions', 15, 900),
    (r'me/charging-sessions', 15, 900),
    (r'charging-sessions/[^/]+/receipt', 30, 900),
    (r'owner/(overview|timeseries|heatmap|margin|forecast|occupancy-history|sessions|reservations)', 30, 900),
    (r'owner/(alerts|live)', 2, 120),
    (r'reservations/current', 3, 120),
    (r'charging-sessions/current', 3, 120),
    (r'overstays/current', 20, 120),  # só o aviso do sino: muda devagar (prazo de tolerância)
    (r'coupons', 15, 900),
))

_EVERYTHING = re.compile(r'.*')
_ACCOUNT = re.compile(r'me|driver/profile')
# Escritas comuns preservam só a configuração de pagamento e o carro do perfil (nada que elas mudem).
_ALL_BUT_STABLE = re.compile(r'(?!(?:payments/config|driver/profile)$).*')
_SOC = re.compile(r'charging-sessions/[^/]+/soc')


def policy(path):
    """``(fresh, stale)`` da rota ou ``None`` quando ela não é guardada."""
    for pattern, fresh, stale in POLICIES:
        if pattern.fullmatch(path):
            return fresh, stale
    return None


def invalidation(path):
    """Padrão das rotas guardadas que uma escrita em ``path`` pode mudar (``None``: nenhuma)."""
    if path.startswith(('ai/', 'geo/')):
        return None  # perguntas à IA e sugestões de endereço não mudam dados da conta
    if path.startswith('auth/'):
        return _EVERYTHING  # troca de conta, senha ou sessão
    if path in ('me', 'driver/profile'):
        return _ACCOUNT
    if _SOC.fullmatch(path):
        return re.compile(r'charging-sessions/current')  # bateria informada pelo celular durante a recarga
    # Reservas, recargas, pagamentos, postos, pontos, tarifas, cupons, vínculos, energia: mudam
    # disponibilidade, histórico, painel do dono e até o perfil (o primeiro vínculo libera o operador).
    return _ALL_BUT_STABLE


def _param(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)


def key(path, params=None):
    return path, tuple(sorted((str(name), _param(value)) for name, value in (params or {}).items()))


@dataclass
class StaleRead:
    key: tuple
    path: str
    params: dict
    value: object


@dataclass
class ReadMode:
    """Leituras liberadas para o cache numa montagem de tela."""
    stale_ok: bool = False
    served: list = field(default_factory=list)  # StaleRead servidos fora do frescor
    seen: set = field(default_factory=set)  # chaves lidas (cache ou rede) neste contexto


_mode = ContextVar('chargegrid_api_read_mode', default=None)


def current_mode():
    return _mode.get()


@contextmanager
def reading(stale_ok=False):
    """Libera o cache no contexto atual (``stale_ok``: também respostas velhas, para revalidar)."""
    mode = ReadMode(stale_ok=stale_ok)
    token = _mode.set(mode)
    try:
        yield mode
    finally:
        _mode.reset(token)


@contextmanager
def network_only():
    """Ignora o cache (consulta sempre à rede) mesmo dentro de uma montagem de tela."""
    token = _mode.set(None)
    try:
        yield
    finally:
        _mode.reset(token)


class ResponseCache:
    def __init__(self):
        self.entries = {}  # chave -> (instante, valor)
        self.inflight = {}  # chave -> Task da consulta em andamento
        self.epoch = 0

    def read(self, cache_key, rule, stale_ok):
        """``(valor, velho)`` quando a entrada pode ser servida; ``None`` quando é preciso ir à rede."""
        entry = self.entries.get(cache_key)
        if entry is None:
            return None
        age = clock() - entry[0]
        fresh, stale = rule
        if age < fresh:
            return entry[1], False
        if stale_ok and age < stale:
            return entry[1], True
        return None

    def fresh(self, cache_key, rule):
        hit = self.read(cache_key, rule, False)
        return hit is not None

    def store(self, cache_key, value, epoch, at=None):
        """Guarda a resposta, a menos que uma escrita tenha acontecido depois que a consulta começou."""
        if epoch != self.epoch:
            return False
        at = clock() if at is None else at
        current = self.entries.get(cache_key)
        if current is not None and current[0] > at:
            return False
        self.entries[cache_key] = (at, value)
        if len(self.entries) > MAX_ENTRIES:
            oldest = sorted(self.entries, key=lambda item: self.entries[item][0])
            for item in oldest[:len(self.entries) - MAX_ENTRIES]:
                del self.entries[item]
        return True

    def invalidate(self, pattern):
        if pattern is None:
            return
        self.epoch += 1
        for cache_key in [k for k in self.entries if pattern.fullmatch(k[0])]:
            del self.entries[cache_key]
        # Consultas que começaram antes da escrita não podem ser reaproveitadas por quem chega depois.
        for cache_key in [k for k in self.inflight if pattern.fullmatch(k[0])]:
            del self.inflight[cache_key]

    def clear(self):
        self.epoch += 1
        self.entries.clear()
        tasks, self.inflight = list(self.inflight.values()), {}
        return tasks
