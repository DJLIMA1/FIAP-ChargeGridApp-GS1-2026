"""Carro do motorista no perfil da API (``/v1/driver/profile``): cadastro, perfil e Modo motorista.

O PUT recebe o perfil completo; trocar só o carro preserva as preferências já salvas.
"""
from ..api_client import ApiError
from ..preferences import PendingVehicleStore


async def save_vehicle(api, vehicle, current=None):
    """Grava ``vehicle`` mantendo as preferências do perfil (``current`` evita um GET repetido)."""
    if current is None:
        current = await api.request('GET', 'driver/profile')
    preferences = dict((current or {}).get('preferences') or {})
    return await api.request('PUT', 'driver/profile', {'vehicle': vehicle, 'preferences': preferences})


async def apply_pending_vehicle(api, email, store=None):
    """Aplica o carro escolhido no cadastro no primeiro login desta conta. Nunca levanta erro."""
    store = store or PendingVehicleStore()
    vehicle = store.load(email)
    if not vehicle:
        return False
    try:
        current = await api.request('GET', 'driver/profile')
        applied = not (current or {}).get('saved')
        if applied:
            await save_vehicle(api, vehicle, current)
        # Perfil já salvo (outro aparelho ou conta existente): o cadastro não sobrescreve o carro.
    except ApiError as error:
        if error.status in (400, 422):
            store.clear(email)  # Carro recusado pela API: não insistir a cada login.
        return False  # Sem rede ou falha temporária: tenta de novo no próximo login.
    except (OSError, TypeError, ValueError, KeyError):
        return False
    store.clear(email)
    return applied


async def apply_signup_vehicle(api, profile=None):
    """Chamado em todo login: se houver carro pendente para este e-mail, grava no perfil."""
    if getattr(api, 'is_demo', False) is True:
        return False
    user = getattr(getattr(api, 'session', None), 'user', None) or {}
    email = (user.get('email') if isinstance(user, dict) else None) or (profile.get('email') if isinstance(profile, dict) else None)
    if not isinstance(email, str) or not email:
        return False
    try:
        return await apply_pending_vehicle(api, email)
    except Exception:  # noqa: BLE001 - o login nunca depende do carro pendente
        return False
