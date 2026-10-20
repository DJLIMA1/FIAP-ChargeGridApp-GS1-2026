"""Busca antecipada das telas que a pessoa provavelmente abre em seguida.

Só com o cliente real (``api.prefetch``); a demonstração responde no próprio aparelho. Cada pedido
usa exatamente a rota e os parâmetros da tela de destino, então ela abre direto do cache. Nada aqui
bloqueia a tela atual nem mostra erro: se a busca falhar, a tela consulta normalmente.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone

_log = logging.getLogger(__name__)

# Parâmetros idênticos aos das telas (a chave do cache inclui os parâmetros).
STATIONS_TAB = ('stations', {'limit': 20, 'offset': 0, 'sort': 'default', 'available_only': False})
HOME_STATIONS = ('stations', {'limit': 3, 'offset': 0})
HISTORY_TAB = ('me/charging-sessions', {'limit': 20, 'offset': 0})
OWNER_HISTORY = ('operator/charging-sessions', {'limit': 20, 'offset': 0})
OWNER_STATIONS = ('operator/stations', {'limit': 100, 'offset': 0})
ACTIVE = (('reservations/current', None), ('charging-sessions/current', None))


def supported(app):
    from ..api_cache import ResponseCache
    api = getattr(app, 'api', None)
    return isinstance(getattr(api, 'cache', None), ResponseCache) and not getattr(app, 'closed', False)


def fetch(app, targets):
    """Dispara as buscas; devolve as tarefas (já em andamento) para quem quiser encadear algo depois."""
    if not supported(app):
        return []
    tasks = []
    for path, params in targets:
        try:
            task = app.api.prefetch(path, params)
        except Exception:  # noqa: BLE001 - busca antecipada nunca derruba a tela
            task = None
        if task is not None:
            tasks.append(task)
    return tasks


def consumer_home():
    return [*ACTIVE, HOME_STATIONS]


def owner_dashboard(days=7):
    from ..screens.history_owner import _window
    window = _window(days)
    return [('owner/overview', window), ('owner/margin', {**window, 'limit': 1}),
            ('owner/timeseries', {**window, 'granularity': 'day'})]


def owner_net():
    from . import payout
    return [('owner/margin', payout.net_params())]


def cached(app, path, params=None):
    """Resposta guardada (sem rede), ou ``None``."""
    from ..api_cache import key
    entry = app.api.cache.entries.get(key(path, params))
    return entry[1] if entry else None


_background = set()


def _then(app, path, params, follow):
    """Busca (ou reaproveita) ``path`` e, em segundo plano, chama ``follow(resposta)``; erros ignorados."""
    if not supported(app):
        return None
    task = app.api.prefetch(path, params)

    async def run():
        try:
            result = await asyncio.shield(task) if task is not None else cached(app, path, params)
            await follow(result)
        except Exception:  # noqa: BLE001 - só aquece caches
            _log.debug('Preparação em segundo plano falhou', exc_info=True)
    background = asyncio.ensure_future(run())
    _background.add(background)
    background.add_done_callback(_background.discard)
    return background


def after_render(app, route, data):
    """Depois que a tela aparece: as abas vizinhas e o próximo toque provável."""
    if not supported(app):
        return
    vendor = getattr(app, 'browsing_mode', 'consumer') == 'vendor'
    if route == 'home' and not vendor:
        fetch(app, [HISTORY_TAB, ('me', None), ('driver/profile', None)])
        _then(app, *STATIONS_TAB, lambda result: _warm_list_map(app, result))
    elif route == 'home' and vendor:
        fetch(app, [OWNER_HISTORY, *owner_dashboard(), ('me', None), ('driver/profile', None), *owner_net()])
    elif route == 'stations' and data.get('station_id'):
        # Próximo passo provável: o assistente de reserva (configuração do pagamento de teste). No modo
        # apresentação a Stripe fica de fora e o app nunca consulta ``payments/config``.
        from . import payments
        if payments.enabled(app):
            fetch(app, [('payments/config', None)])
    elif route == 'stations' and not vendor:
        fetch(app, [HISTORY_TAB])
        listing = cached(app, *STATIONS_TAB) or {}
        _warm_details(app, (listing.get('items') or [])[:2])
    elif route == 'history' and not vendor and not data:
        listing = cached(app, *HISTORY_TAB) or {}
        first = next(iter(listing.get('items') or []), None)
        if isinstance(first, dict) and first.get('id'):
            fetch(app, [(f"charging-sessions/{first['id']}/receipt", None)])  # "Ver recibo" da última recarga
    elif route == 'history' and vendor and data.get('manage') and not data.get('page'):
        from ..screens.history_owner import _window
        fetch(app, [('owner/overview', _window(7, shift=7))])  # página "Consumo de energia"
        owned = (cached(app, *OWNER_STATIONS) or {}).get('items') or []
        if owned:
            fetch(app, [('owner/forecast', {'station_id': owned[0]['id'], 'horizon_hours': 36})])
    elif route == 'operator' and not data:
        fetch(app, [OWNER_HISTORY, *owner_dashboard()])
    elif route == 'station_admin' and data.get('station_id') and not data.get('page'):
        sid = data['station_id']
        fetch(app, [(f'stations/{sid}/power', None), ('owner/live', {'station_id': sid}),
                    ('owner/alerts', {'station_id': sid})])


async def _warm_list_map(app, result):
    """Mapa da aba Recarga composto (tiles + Pillow numa thread) antes de a pessoa abrir a aba."""
    from ..screens.stations import warm_list_map
    await warm_list_map(app, (result or {}).get('items') or [])


def _warm_details(app, stations):
    """O primeiro posto da lista: o mapa do detalhe já pronto ao tocar."""
    stations = [station for station in stations if isinstance(station, dict) and station.get('id')]
    if stations:
        from ..screens.stations import warm_detail_map

        async def warm():
            try:
                await warm_detail_map(app, stations[0])
            except Exception:  # noqa: BLE001 - só aquece o cache do mapa
                _log.debug('Mapa do detalhe não pôde ser preparado', exc_info=True)
        task = asyncio.ensure_future(warm())
        _background.add(task)
        task.add_done_callback(_background.discard)


PERIOD_STEP_MINUTES = 5


def period_end(now=None):
    """Fim de um período "até agora" arredondado para cima (próximos 5 min cheios).

    Não deixa nenhuma recarga de fora e repete os mesmos parâmetros por alguns minutos, então as
    telas reaproveitam a mesma consulta (cache) em vez de pedir de novo a cada segundo."""
    moment = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    return moment + timedelta(minutes=PERIOD_STEP_MINUTES - moment.minute % PERIOD_STEP_MINUTES)
