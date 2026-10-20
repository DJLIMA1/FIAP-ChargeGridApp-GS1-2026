"""Modo apresentação da CONTA (``profiles.presentation_mode`` em ``GET/PATCH /me``).

O interruptor continua sendo uma preferência do aparelho (``vehicle_state.presentation_mode``: bateria
do celular e pagamento simulado do motorista), e passa a ser também um atributo da conta no servidor,
onde ele só decide o pagamento do totem dos postos dessa conta (simulado × Stripe teste).

Regra (a mais simples que mantém uma única verdade para o totem):

* **Ao alternar**: grava no aparelho (como antes) e manda ``PATCH /me {presentation_mode}``. O cache
  de ``me`` é descartado pela própria escrita (``api_cache.invalidation``) e ``app.profile`` recebe a
  resposta. Conta de dono numa API com o campo: se o PATCH falhar, o aparelho volta ao valor anterior
  (o totem continuaria no modo antigo). Motorista ou API antiga (sem o campo): vale o aparelho, como na 0.7.
* **Ao entrar**: conta de dono com o campo e valor diferente do aparelho → **o servidor manda** (o
  aparelho adota o modo da conta, que é o que o totem usa). Motorista: nada muda (o campo não tem efeito
  para ele). Conta demo: não há servidor; a conta em memória recebe o modo do aparelho.
"""

from ..api_client import ApiError
from . import vehicle_state

TOTEM_SIMULATED = 'Totem: pagamento simulado'
TOTEM_STRIPE = 'Totem: Stripe (teste)'
SAVE_FAILED = ('Não foi possível salvar o Modo apresentação na sua conta. Nada mudou; '
               'o totem continua no modo anterior.')


def _demo(app):
    return getattr(getattr(app, 'api', None), 'is_demo', False) is True


def _profile(app):
    profile = getattr(app, 'profile', None)
    return profile if isinstance(profile, dict) else {}


def account_value(profile):
    """``True``/``False`` da conta, ou ``None`` quando a API ainda não manda o campo."""
    value = (profile or {}).get('presentation_mode')
    return value if isinstance(value, bool) else None


def is_owner(app, profile=None):
    """Conta que pode ter postos (mesma regra de ``navigation.can_manage``)."""
    profile = profile if profile is not None else _profile(app)
    return bool(profile.get('operator_enabled') or profile.get('account_type') == 'vendor')


def totem_caption(app):
    """Método que o totem dos postos desta conta usa (segue o Modo apresentação)."""
    return TOTEM_SIMULATED if vehicle_state.presentation_mode(app) else TOTEM_STRIPE


def _keep(app, profile):
    if isinstance(profile, dict) and profile:
        try:
            app.profile = {**_profile(app), **profile}
        except AttributeError:
            pass


async def toggle(app, enabled):
    """Interruptor da Conta: grava no aparelho e na conta.

    ``(saved_on_device, synced)``: ``synced`` é ``True`` (conta atualizada), ``None`` (só no aparelho:
    motorista, demo sem o campo ou API antiga) ou ``False`` (dono com o campo e o PATCH falhou: o aparelho
    voltou ao valor anterior)."""
    enabled = bool(enabled)
    previous = vehicle_state.presentation_mode(app)
    saved = vehicle_state.set_presentation_mode(app, enabled)
    authoritative = is_owner(app) and account_value(_profile(app)) is not None
    try:
        profile = await app.api.request('PATCH', 'me', {'presentation_mode': enabled})
    except ApiError:
        if authoritative:
            vehicle_state.set_presentation_mode(app, previous)
            return saved, False
        return saved, None
    _keep(app, profile)
    return saved, True if account_value(profile) == enabled else None


async def adopt(app, profile=None):
    """Ao entrar: alinha o aparelho e a conta. Devolve ``True`` quando o modo do aparelho mudou."""
    profile = profile if isinstance(profile, dict) else _profile(app)
    server = account_value(profile)
    local = vehicle_state.presentation_mode(app)
    if server is None or server == local:
        return False
    if _demo(app):
        # Sem servidor real: a conta em memória acompanha o aparelho.
        try:
            _keep(app, await app.api.request('PATCH', 'me', {'presentation_mode': local}))
        except ApiError:
            pass
        return False
    if not is_owner(app, profile):
        return False
    vehicle_state.set_presentation_mode(app, server)
    return True
