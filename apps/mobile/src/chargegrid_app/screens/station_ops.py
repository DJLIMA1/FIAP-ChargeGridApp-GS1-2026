"""Totem de autoatendimento do posto (vendedor), mostrado em Dados da estação.

``kiosk_mode`` liga/desliga o totem (``PATCH stations``, padrão desligado; muda só com a resposta do
servidor). O status cabe numa linha e segue o Modo apresentação da CONTA do dono (``presentation_mode``
de ``/me``): "Pagamento: Stripe (teste)", "Pagamento simulado (Modo apresentação)" ou o motivo de
indisponível (Stripe não configurada no servidor, estação inativa). A API com ``kiosk_status`` no posto
já decide, pela mesma regra do ``connector.kiosk`` do sync; a antiga é deduzida aqui.

Sem a página de Pagamentos: o pagamento do app é Stripe por padrão (simulado em Modo apresentação) e os
antigos ``prepay_required``/``kiosk_payments`` ficam desligados no servidor, sem interruptor no app.
"""

import flet as ft

from ..api_client import ApiError
from ..ui import design, theme

KIOSK_TITLE = 'Totem de autoatendimento'
KIOSK_TEXTS = {'stripe': 'Pagamento: Stripe', 'simulated': 'Pagamento: sem cobrança'}
KIOSK_REASONS = {
    'payments_unavailable': 'Indisponível: pagamentos Stripe não configurados no servidor',
    'point_disabled': 'Indisponível: estação inativa',
}


def has_kiosk(station):
    """A API manda ``kiosk_mode`` no posto (totem 0.8.0)."""
    return isinstance((station or {}).get('kiosk_mode'), bool)


def account_presentation(app):
    """Modo apresentação da conta (``/me``); API antiga sem o campo: o do aparelho."""
    from ..services import account_mode, vehicle_state
    value = account_mode.account_value(getattr(app, 'profile', None))
    return value if value is not None else vehicle_state.presentation_mode(app)


def server_kiosk_status(station, presentation):
    """``(método, motivo)`` do ``kiosk_status`` que a API manda no posto do dono, ou ``None``.

    Vale o bloco do servidor (mesma regra do ``connector.kiosk`` do sync, inclusive a Stripe configurada),
    exceto quando o Modo apresentação da conta mudou depois que o posto foi lido (posto em cache): aí o
    bloco não bate com ``presentation`` e o app volta ao cálculo local."""
    server = (station or {}).get('kiosk_status')
    if not isinstance(server, dict):
        return None
    method, reason = server.get('method'), server.get('reason')
    if reason == 'point_disabled' and method is None:
        return method, reason
    if presentation and method == 'simulated' and reason is None:
        return method, reason
    if not presentation and ((method == 'stripe' and reason is None)
                             or (method is None and reason == 'payments_unavailable')):
        return method, reason
    return None


def kiosk_status(station, presentation, payments_config=None):
    """``{enabled, method, label, reason, text}`` como o ``connector.kiosk`` do sync (decidido pela API).

    Usa o ``kiosk_status`` do posto (API com o campo); sem ele, deduz: ``payments_config`` é
    ``GET payments/config`` (``None`` = ainda não consultado: supõe a Stripe ligada)."""
    station = station or {}
    decided = server_kiosk_status(station, presentation)
    if decided is not None:
        method, reason = decided
    elif station.get('active') is False:
        method, reason = None, 'point_disabled'
    elif presentation:
        method, reason = 'simulated', None
    elif payments_config is None or payments_config.get('enabled') is True:
        method, reason = 'stripe', None
    else:
        method, reason = None, 'payments_unavailable'
    label = {'simulated': 'SIMULADO', 'stripe': 'TESTE'}.get(method)
    text = KIOSK_TEXTS[method] if method else KIOSK_REASONS[reason]
    return {'enabled': method is not None, 'method': method, 'label': label, 'reason': reason, 'text': text}


def kiosk_control(app, station, payments_config=None):
    """Ligado/Desligado do totem + status numa linha. ``(controle, redesenhar)``; ``(None, None)`` sem o campo."""
    if not has_kiosk(station):
        return None, None
    sid = station['id']
    state = {'busy': False}
    holder = ft.Container(data='kiosk_mode')
    status = design.txt('', 11, 'regular', theme.GRAY_TEXT, data='kiosk-status')

    async def choose(key):
        value = key == 'on'
        if state['busy'] or value == bool(station.get('kiosk_mode')):
            return
        state['busy'] = True
        try:
            saved = await app.api.request('PATCH', f'stations/{sid}', {'kiosk_mode': value})
        except ApiError as exc:
            app.notice(f'Totem não alterado: {exc}')  # sem atualização otimista: fica o valor do servidor
        else:
            station['kiosk_mode'] = bool((saved or {}).get('kiosk_mode', value))
            if isinstance((saved or {}).get('kiosk_status'), dict):
                station['kiosk_status'] = saved['kiosk_status']
            app.notice('Totem de autoatendimento ligado' if station['kiosk_mode']
                       else 'Totem de autoatendimento desligado')
        finally:
            state['busy'] = False
            draw()
            app.page.update()

    def draw():
        info = kiosk_status(station, account_presentation(app), payments_config)
        holder.content = design.segmented([('on', 'Ligado'), ('off', 'Desligado')],
                                          'on' if station.get('kiosk_mode') else 'off', choose, height=37.5)
        status.value = info['text']
        status.color = theme.ERROR if info['reason'] else theme.GRAY_TEXT
    draw()
    control = ft.Column([design.labeled(KIOSK_TITLE, holder, gap=5, strong=False), status], spacing=6,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH, data='kiosk')
    return control, draw
