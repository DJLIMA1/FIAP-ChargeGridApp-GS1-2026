"""Bateria (SoC) do carro do motorista — valor ESCONDIDO que guia planejador, estimativas e a recarga.

Modo oficial: o app não pergunta a bateria. O SoC é sorteado (uniforme 15–60 %) uma vez por conta e
fica guardado até uma recarga mudá-lo (fim da recarga → SoC final da sessão). Conta real: JSON em
``FLET_APP_STORAGE_DATA`` (como ``preferences.py``); conta demo: em memória na sessão (no cliente demo).
O número nunca é mostrado fora das telas de recarga (lá ele vem da API, o mesmo que o totem mostra).

Modo apresentação (pitch na FIAP; ``presentation_mode``): o celular faz o papel do carro e o SoC é a
bateria real do aparelho, lida pelo serviço ``ft.Battery``. Onde a leitura não existe (desktop, web,
testes sem serviço) cai no valor sorteado, sem avisos.

Carro: o do perfil do motorista (``GET driver/profile``), senão o salvo no aparelho, senão BYD Dolphin.
"""

import asyncio
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path

from chargegrid_core.driver.vehicles import DEFAULT_PRESET, PRESETS

SOC_MIN, SOC_MAX = 15.0, 60.0
BATTERY_TIMEOUT = 2.5
MOBILE = ('android', 'ios')


def _storage():
    return Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')


def _is_demo(app):
    return getattr(getattr(app, 'api', None), 'is_demo', False) is True


def _user_id(app):
    user = getattr(getattr(getattr(app, 'api', None), 'session', None), 'user', None) or {}
    profile = getattr(app, 'profile', None) or {}
    return str(profile.get('id') or (user.get('id') if isinstance(user, dict) else None) or 'anonymous')


def _read(path):
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(path, data):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False))
        return True
    except (OSError, TypeError, ValueError):
        return False


# ------------------------------------------------------------------ modo apresentação (preferência do aparelho)
def _presentation_path():
    return _storage() / 'presentation.json'


def presentation_mode(app=None) -> bool:
    """``True`` quando o celular faz o papel do carro. Preferência do aparelho (vale para qualquer conta)."""
    if app is not None and isinstance(getattr(app, 'presentation_override', None), bool):
        return app.presentation_override
    return _read(_presentation_path()).get('enabled') is True


def set_presentation_mode(app, enabled) -> bool:
    """Liga/desliga e grava no aparelho; se não der para gravar, vale nesta sessão."""
    enabled = bool(enabled)
    saved = _write(_presentation_path(), {'enabled': enabled})
    if app is not None:
        app.presentation_override = None if saved else enabled
    return saved


def presentation_available(app) -> bool:
    """O interruptor aparece no celular (Android/iOS) e na demonstração."""
    return _is_demo(app) or _platform(app) in MOBILE


# ------------------------------------------------------------------ SoC sorteado (escondido)
def _state_path():
    return _storage() / 'vehicle_state.json'


def _entry(app):
    if _is_demo(app):
        entry = getattr(app.api, 'chargegrid_vehicle_state', None)
        return entry if isinstance(entry, dict) else {}
    entry = _read(_state_path()).get(_user_id(app))
    return entry if isinstance(entry, dict) else {}


def _store(app, entry):
    if _is_demo(app):
        try:
            app.api.chargegrid_vehicle_state = entry
        except AttributeError:
            pass
        return
    data = _read(_state_path())
    data[_user_id(app)] = entry
    _write(_state_path(), data)


def _valid(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0 <= number <= 100 else None


def simulated_soc(app, rng=None) -> float:
    """SoC escondido da conta: sorteado uma vez (15–60 %), depois o valor guardado."""
    entry = _entry(app)
    value = _valid(entry.get('soc'))
    if value is None:
        value = round((rng or random).uniform(SOC_MIN, SOC_MAX), 1)
        _store(app, {**entry, 'soc': value, 'drawn_at': datetime.now(timezone.utc).isoformat()})
    return value


def set_simulated_soc(app, value) -> None:
    """Substitui o SoC escondido (testes e fim de recarga)."""
    number = _valid(value)
    if number is not None:
        _store(app, {**_entry(app), 'soc': round(number, 1)})


def record_session_end(app, session) -> bool:
    """Após uma recarga terminar, o carro fica com o SoC final dela (uma vez por sessão, nunca regride
    para uma sessão mais antiga vista no histórico)."""
    if not isinstance(session, dict) or session.get('status') in ('starting', 'charging', 'stopping'):
        return False
    final = _valid(session.get('soc_percent'))
    if final is None:
        return False
    entry = _entry(app)
    ended = str(session.get('ended_at') or session.get('last_measurement_at') or '')
    if entry.get('session_id') == session.get('id') or (ended and str(entry.get('ended_at') or '') > ended):
        return False
    _store(app, {**entry, 'soc': round(final, 1), 'session_id': session.get('id'), 'ended_at': ended})
    return True


# ------------------------------------------------------------------ bateria do celular (ft.Battery)
def _platform(app):
    platform = getattr(getattr(app, 'page', None), 'platform', None)
    value = getattr(platform, 'value', platform)
    return str(value or '').lower()


def _battery(app):
    service = getattr(app, 'battery_service', None)
    if service is not None:
        return service
    if getattr(app, 'battery_unavailable', False) or _platform(app) not in MOBILE:
        return None
    try:
        import flet as ft
        service = ft.Battery()
        services = getattr(app.page, 'services', None)
        if isinstance(services, list) and service not in services:
            services.append(service)  # versões do Flet com page.services; nas outras o serviço se registra só
        app.battery_service = service  # referência forte: o Flet descarta serviços sem referência
    except Exception:  # noqa: BLE001 - sem serviço de bateria neste ambiente
        app.battery_unavailable = True
        return None
    return service


async def phone_battery(app):
    """Nível da bateria do celular (0–100) ou ``None`` se indisponível."""
    service = _battery(app)
    if service is None:
        return None
    try:
        level = await asyncio.wait_for(service.get_battery_level(), BATTERY_TIMEOUT)
    except Exception:  # noqa: BLE001 - plataforma sem leitura: segue com o valor simulado
        return None
    return _valid(level)


async def current_soc(app):
    """``(soc, fonte)``: bateria do celular no modo apresentação (``phone``), senão o sorteio (``simulated``)."""
    if presentation_mode(app):
        level = await phone_battery(app)
        if level is not None:
            return float(level), 'phone'
    return simulated_soc(app), 'simulated'


# ------------------------------------------------------------------ carro
def _vehicle_dict(app, vehicle):
    if isinstance(vehicle, dict) and vehicle:
        app.vehicle_cache = dict(vehicle)


def remember_vehicle(app, vehicle):
    """Telas que salvam o carro (Modo motorista, Perfil) atualizam o cache desta sessão."""
    _vehicle_dict(app, vehicle)


async def vehicle(app):
    """Carro do motorista (dict do perfil). Nunca levanta erro: cai no BYD Dolphin."""
    cached = getattr(app, 'vehicle_cache', None)
    if isinstance(cached, dict) and cached:
        return cached
    found = None
    try:
        data = await app.api.request('GET', 'driver/profile')
        if isinstance(data, dict) and isinstance(data.get('vehicle'), dict) and data['vehicle']:
            found = data['vehicle']
    except Exception:  # noqa: BLE001 - perfil indisponível: usa o carro do aparelho ou o padrão
        found = None
    if found is None and not _is_demo(app):
        from ..preferences import DriverProfileStore
        local = DriverProfileStore().load()
        found = (local or {}).get('vehicle')
    found = found if isinstance(found, dict) and found else {'preset': DEFAULT_PRESET}
    _vehicle_dict(app, found)
    return found


def car_specs(vehicle_data):
    """``{'name', 'usable_kwh', 'consumption'}`` do carro (preset + sobrescritas); padrão BYD Dolphin."""
    from .driver import vehicle_profile
    profile = vehicle_profile(vehicle_data) or PRESETS[DEFAULT_PRESET]
    return {'name': profile.name, 'usable_kwh': float(profile.usable_battery_kwh),
            'consumption': float(profile.consumption_kwh_per_100km)}


async def snapshot(app):
    """Carro + SoC escondido para as contas do app (autonomia, início da recarga)."""
    soc, source = await current_soc(app)
    return {**car_specs(await vehicle(app)), 'soc': soc, 'source': source}


async def start_fields(app, car=None):
    """Campos enviados no ``POST charging-sessions`` (contrato SoC)."""
    car = car or await snapshot(app)
    usable = max(5.0, min(250.0, float(car['usable_kwh'])))
    return {'soc_percent': round(float(car['soc']), 1), 'battery_kwh': round(usable, 1),
            'soc_source': 'phone' if car.get('source') == 'phone' else 'simulated'}

# Campos de início de recarga ligados à bateria do carro (omitidos se a API ainda não os aceita).
START_KEYS = ('soc_percent', 'battery_kwh', 'soc_source')
