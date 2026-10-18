"""Notificações do app, montadas a partir dos dados da conta (sem backend próprio).

Consumidor: meta de bateria atingida (sessão atual ou última recarga concluída).
Vendedor: estações/pontos sem comunicação (``operator/stations``).
Na demonstração, quando nada gera aviso, mostra os exemplos da referência.
"""

from datetime import datetime

BATTERY_TARGET = 80

KIND_BATTERY = 'battery'
KIND_OFFLINE = 'offline'


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
            items += offline_items(result.get('items') or [])
        else:
            current = await api.request('GET', 'charging-sessions/current')
            item = battery_item(current) if current else None
            if item:
                items.append(item)
    except Exception:  # noqa: BLE001 - aviso é opcional; a tela segue sem ele
        pass
    return items or (sample_items() if demo else [])
