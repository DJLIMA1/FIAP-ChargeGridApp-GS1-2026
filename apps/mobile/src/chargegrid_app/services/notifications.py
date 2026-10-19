"""Notificações do app, montadas a partir dos dados da conta (sem backend próprio).

Consumidor: meta de bateria atingida (sessão atual ou última recarga concluída).
Vendedor: estações/pontos sem comunicação e, com o aviso ligado no posto (``power_limit_notify``),
recargas rodando com potência limitada (``operator/stations``: ``power_limited``/``effective_power_kw``).
Um aviso por conector por dia; lidas/não lidas usam o mesmo mecanismo dos demais.
Na demonstração, quando nada gera aviso, mostra os exemplos da referência.
"""

import json
import os
from datetime import datetime
from pathlib import Path

BATTERY_TARGET = 80

KIND_BATTERY = 'battery'
KIND_OFFLINE = 'offline'
KIND_POWER = 'power'
_IN_USE = ('charging', 'reconciling')


def _parse(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone()
    except (TypeError, ValueError):
        return None


def battery_item(session, now=None):
    """Aviso de meta de bateria para uma sessão com ``soc_percent`` >= meta; ``None`` caso contrário."""
    try:
        soc = float(session.get('soc_percent'))
    except (TypeError, ValueError):
        return None
    if soc < BATTERY_TARGET:
        return None
    when = _parse(session.get('last_measurement_at') or session.get('ended_at') or session.get('started_at'))
    when = when or now or datetime.now().astimezone()
    return {'id': f"battery-{session.get('id')}", 'kind': KIND_BATTERY, 'title': 'Meta de bateria atingida',
            'subtitle': 'Estação ' + str(session.get('station_name') or 'ChargeGrid'),
            'detail': f"Bateria atingiu {BATTERY_TARGET}% - {when.strftime('%H:%M')}", 'at': when}


def offline_items(stations, now=None):
    """Um aviso por estação ativa que tem pontos habilitados e nenhum deles online."""
    items = []
    for station in stations or []:
        if station.get('active') is False:
            continue
        points = [p for p in station.get('connectors') or [] if p.get('active') is not False and not p.get('retired')]
        if points and not any(p.get('online') is True for p in points):
            items.append({'id': f"offline-{station.get('id')}", 'kind': KIND_OFFLINE, 'title': 'Estação sem comunicação',
                          'subtitle': 'Estação ' + str(station.get('name') or ''),
                          'detail': 'Verifique o status do dispositivo.', 'at': now or datetime.now().astimezone()})
    return items


def _kw(value):
    from chargegrid_core.power import kw_text
    return kw_text(value)


def power_items(stations, now=None):
    """``Limite de potência em uso · Estação X: CCS2 a 40 kW de 60 kW`` (postos com o aviso ligado)."""
    now = now or datetime.now().astimezone()
    items = []
    for station in stations or []:
        if not station.get('power_limit_notify'):
            continue
        for point in station.get('connectors') or []:
            if not point.get('power_limited') or point.get('availability_status') not in _IN_USE:
                continue
            kind = point.get('connector_type') or 'Conector'
            items.append({'id': f"power-{point.get('id')}-{now.strftime('%Y%m%d')}", 'kind': KIND_POWER,
                          'title': 'Limite de potência em uso',
                          'subtitle': 'Estação ' + str(station.get('name') or ''),
                          'detail': f"{kind} a {_kw(point.get('effective_power_kw'))} kW de "
                                    f"{_kw(point.get('power_kw'))} kW", 'at': now})
    return items


def sample_items(now=None):
    """Exemplos da referência (somente demonstração)."""
    now = (now or datetime.now().astimezone()).replace(hour=12, minute=42)
    return [
        {'id': 'sample-battery', 'kind': KIND_BATTERY, 'title': 'Meta de bateria atingida',
         'subtitle': 'Estação Marginal Pinheiros', 'detail': 'Bateria atingiu 80% - 12:42', 'at': now},
        {'id': 'sample-offline', 'kind': KIND_OFFLINE, 'title': 'Estação sem comunicação',
         'subtitle': 'Estação Marginal Pinheiros', 'detail': 'Verifique o status do dispositivo.', 'at': now},
    ]


def group_label(moment, now=None):
    today = (now or datetime.now().astimezone()).date()
    days = (today - moment.date()).days
    return 'Hoje' if days <= 0 else 'Ontem' if days == 1 else moment.strftime('%d/%m/%Y')


def grouped(items, now=None):
    """[(rótulo, [itens])] do mais recente ao mais antigo."""
    groups = {}
    for item in sorted(items, key=lambda i: i['at'], reverse=True):
        groups.setdefault(group_label(item['at'], now), []).append(item)
    return list(groups.items())


async def collect(app):
    """Lista de notificações da conta atual; nunca levanta erro de rede."""
    api = app.api
    demo = getattr(api, 'is_demo', False) is True
    vendor = getattr(app, 'browsing_mode', 'consumer') == 'vendor'
    items = []
    try:
        if vendor:
            result = await api.request('GET', 'operator/stations', params={'limit': 100, 'offset': 0})
            stations = result.get('items') or []
            items += offline_items(stations)
            items += power_items(stations)
        else:
            current = await api.request('GET', 'charging-sessions/current')
            item = battery_item(current) if current else None
            if item:
                items.append(item)
    except Exception:  # noqa: BLE001 - aviso é opcional; a tela segue sem ele
        pass
    return items or (sample_items() if demo else [])


# --------------------------------------------------------------- lidas / não lidas
def _store_path():
    storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
    return storage / 'notifications_read.json'


def _account(app):
    return str(((getattr(app.api, 'session', None) and app.api.session.user) or {}).get('id')
               or (getattr(app, 'profile', None) or {}).get('id') or 'local')


def read_ids(app):
    """Ids já lidos da conta atual (demo: só na memória da sessão)."""
    cache = getattr(app, 'notifications_read', None)
    if cache is None:
        cache = set()
        if getattr(app.api, 'is_demo', False) is not True:
            try:
                data = json.loads(_store_path().read_text())
                cache = set((data or {}).get(_account(app)) or [])
            except (OSError, ValueError, TypeError, AttributeError):
                cache = set()
        app.notifications_read = cache
    return cache


def mark_read(app, ids):
    """Marca avisos como lidos; nunca falha (sem disco, vale só nesta sessão)."""
    cache = read_ids(app)
    cache.update(ids)
    if getattr(app.api, 'is_demo', False) is True:
        return
    try:
        path = _store_path()
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data[_account(app)] = sorted(cache)[-200:]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except (OSError, TypeError, ValueError):
        pass


def unread(app, items):
    seen = read_ids(app)
    return [item for item in items if item['id'] not in seen]
