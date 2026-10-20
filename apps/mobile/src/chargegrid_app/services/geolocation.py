"""Localização do celular (GPS) para o Modo motorista — só Android/iOS, nunca trava a tela.

Usa a extensão oficial ``flet-geolocator`` (serviço ``Geolocator``), importada só quando a plataforma
é Android/iOS: desktop, web e testes seguem sem GPS (os testes injetam ``app.geolocator`` falso).

- ``current_position(app)``: só lê se a permissão **já** foi dada (sem pedir nada).
- ``current_position(app, ask=True)``: pede a permissão (toque em "Usar minha localização").
Toda chamada tem tempo-limite; qualquer falha devolve ``None`` e o app cai no último local salvo
ou na busca por endereço. A posição não é gravada pelo app; só vai à API junto do pedido de plano.
"""

import asyncio
from datetime import datetime, timezone

MOBILE = ('android', 'ios')
TIMEOUT = 5.0
PERMISSION_TIMEOUT = 60.0  # o motorista lê o diálogo do sistema
MAX_AGE_MINUTES = 10
GRANTED = ('whileInUse', 'always')
DENIED_FOREVER = 'deniedForever'


def _platform(app):
    platform = getattr(getattr(app, 'page', None), 'platform', None)
    value = getattr(platform, 'value', platform)
    return str(value or '').lower()


def available(app) -> bool:
    """GPS só no celular (ou com um serviço injetado nos testes)."""
    if getattr(app, 'geolocator', None) is not None:
        return True
    return not getattr(app, 'geolocator_unavailable', False) and _platform(app) in MOBILE


def _service(app):
    service = getattr(app, 'geolocator', None)
    if service is not None or not available(app):
        return service
    try:
        import flet_geolocator as geo
        service = geo.Geolocator(configuration=geo.GeolocatorConfiguration(
            accuracy=geo.GeolocatorPositionAccuracy.MEDIUM))
        services = getattr(app.page, 'services', None)
        if isinstance(services, list) and service not in services:
            services.append(service)  # versões do Flet com page.services; nas outras o serviço se registra só
        app.geolocator = service  # referência forte: o Flet descarta serviços sem referência
    except Exception:  # noqa: BLE001 - extensão ausente (build antigo) ou plataforma sem GPS
        app.geolocator_unavailable = True
        return None
    return service


def _value(status):
    return getattr(status, 'value', status)


def _fresh(position) -> bool:
    stamp = getattr(position, 'timestamp', None)
    if not isinstance(stamp, datetime):
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() <= MAX_AGE_MINUTES * 60


def _coordinates(position):
    try:
        lat, lng = float(position.latitude), float(position.longitude)
    except (AttributeError, TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    return lat, lng


async def permission(app):
    """Status da permissão (``'whileInUse'``, ``'denied'``, ...) ou ``None`` sem GPS."""
    service = _service(app)
    if service is None:
        return None
    try:
        return _value(await asyncio.wait_for(service.get_permission_status(), TIMEOUT))
    except Exception:  # noqa: BLE001
        return None


async def current_position(app, *, ask=False):
    """``(lat, lng)`` do celular ou ``None``. Sem ``ask`` nunca abre o diálogo de permissão."""
    service = _service(app)
    if service is None:
        return None
    try:
        status = _value(await asyncio.wait_for(service.get_permission_status(), TIMEOUT))
        if status not in GRANTED:
            if not ask or status == DENIED_FOREVER:
                return None
            status = _value(await asyncio.wait_for(service.request_permission(), PERMISSION_TIMEOUT))
            if status not in GRANTED:
                return None
        try:
            last = await asyncio.wait_for(service.get_last_known_position(), TIMEOUT)
        except Exception:  # noqa: BLE001 - web/sem cache: pede uma leitura nova
            last = None
        if last is not None and _fresh(last) and _coordinates(last):
            return _coordinates(last)
        return _coordinates(await asyncio.wait_for(service.get_current_position(), TIMEOUT))
    except Exception:  # noqa: BLE001 - tempo esgotado, GPS desligado ou serviço indisponível
        return None
