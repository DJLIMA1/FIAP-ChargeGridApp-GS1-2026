"""Detalhes da recarga: a única tela de uma recarga encerrada (subpágina do histórico).

Rota ``history?session=<id>`` (``receipt=<id>`` é o nome antigo e abre a mesma tela). Usada pelo cartão
do histórico do motorista e do vendedor (``manage``/``station_id``) e pelo atalho do fim da recarga.

Motorista: lê o recibo explicável (``GET /v1/charging-sessions/{id}/receipt``, contrato
``chargegrid.receipt``; na conta demo o mesmo núcleo roda localmente) e a sessão
(``GET /v1/charging-sessions/{id}``, opcional: capacidade da bateria, velocidade, limites e o posto).
"Exportar recibo" baixa ``/receipt.pdf`` com autenticação e entrega pela folha de compartilhamento
(celular) ou pelo "Salvar como" (navegador/desktop); na conta demo o PDF é gerado no aparelho.
O motorista vê só o preço travado por kWh: base, horário e ajuste por demanda são dados do vendedor.

Vendedor: o recibo é documento do motorista (a API devolve 404), então a tela usa o item da listagem
(``app.history_sessions``, guardado pelo histórico; sem ele, busca uma página da listagem) montado
pelo mesmo núcleo ``chargegrid_core.receipt``. Sem "Exportar recibo".
"""

import asyncio
from datetime import datetime
from decimal import Decimal, InvalidOperation

import flet as ft

from chargegrid_core import receipt as core_receipt
from chargegrid_core.formatting import brl, duration, kwh
from chargegrid_core.pricing import multiplier_label

from ..api_client import ApiError
from ..services import files, owner_sessions
from ..ui import theme
from ..ui.design import (
    card_box,
    icon_tile,
    num,
    page,
    primary_button,
    secondary_button,
    section_label,
    txt,
)
from ..ui.states import SESSION_TONES, empty_state, status_chip
from .history_owner import BLUE, BLUE_FILL, line_chart

TITLE = 'Detalhes da recarga'
EXPORT_LABEL = 'Exportar recibo'
EXPORT_DEMO_NOTE = 'Conta demo: PDF de exemplo gerado no aparelho, sem valor fiscal.'
NOT_FOUND = 'Recarga não encontrada'
SELLER_PAGE = 100
PAYMENT_STATUS = {
    'awaiting_payment': 'Aguardando pagamento', 'authorized': 'Autorizado', 'paid': 'Pago', 'in_use': 'Em uso',
    'captured': 'Capturado', 'settled': 'Acertado', 'refunded': 'Devolvido', 'canceled': 'Cancelado',
    'cancelled': 'Cancelado', 'expired': 'Expirado', 'declined': 'Recusado', 'completed': 'Concluído',
}
# Fase da permanência (``phase``: o recibo usa ``status`` para dizer que a seção está disponível).
OVERSTAY_PHASES = {'grace': 'Em tolerância (carro conectado)', 'billing': 'Em cobrança (carro conectado)',
                   'capped': 'Teto atingido (carro conectado)', 'closed': 'Encerrada', 'no_fee': 'Sem taxa aceita'}
REFUND_STATUS = {'refunded': 'Valor devolvido', 'released': 'Sobra da pré-autorização liberada',
                 'pending': 'Acerto pendente', 'none': 'Sem devolução'}
PAYMENT_METHODS = {'card': 'Cartão', 'pix': 'Pix', 'wallet': 'Saldo', 'balance': 'Saldo'}
PAYMENT_ENVIRONMENTS = {'mock': 'Pagamento simulado (nenhum dinheiro real)',
                        'sandbox': 'Pagamento de teste (sandbox)', 'production': 'Pagamento real'}
POWER_STATUS = {'applied': 'Aplicada', 'requested': 'Pedida, sem confirmação', 'failed': 'Não aplicada'}
TEST_BADGES = {'mock': 'SIMULADO', 'sandbox': 'TESTE'}
SPEEDS = {'reduced': 'Reduzida · mais econômica', 'max': 'Máxima · mais rápida'}
SECTION_STATES = ('available', 'pending', 'not_applicable', 'unavailable')
BADGE_AMBER = '#F5B73A'  # selo fixo (preto sobre âmbar é legível nos temas claro e escuro)
BADGE_DEMO = '#FF858A'


# ----------------------------------------------------------------- formatação

def _dec(value):
    if value is None or value == '':
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _local(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone()
    except (TypeError, ValueError):
        return None


def _hour(value):
    moment = _local(value)
    return moment.strftime('%H:%M') if moment else '—'


def _day(value):
    moment = _local(value)
    return moment.strftime('%d/%m/%Y') if moment else '—'


def _stamp(value):
    moment = _local(value)
    return moment.strftime('%d/%m/%Y %H:%M') if moment else '—'


def _money(value):
    number = _dec(value)
    return brl(number) if number is not None else '—'


def price_text(value):
    """``R$ 1,89`` ou, com frações de centavo, ``R$ 2,4570`` (o preço travado tem 4 casas)."""
    number = _dec(value)
    if number is None:
        return '—'
    if number == number.quantize(Decimal('0.01')):
        return brl(number)
    text = f'{number.quantize(Decimal("0.0001")):,.4f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
    return 'R$ ' + text


def _kw(value):
    number = _dec(value)
    if number is None:
        return '—'
    return f'{number.quantize(Decimal("0.1")):f}'.replace('.', ',') + ' kW'


def _pct(value):
    number = _dec(value)
    return '—' if number is None else f'{number.quantize(Decimal("1"))}%'


def _line_value(line):
    unit = line.get('unit')
    if unit == 'R$/kWh':
        return price_text(line.get('value')) + '/kWh'
    if unit == '×':
        return multiplier_label(line.get('value') or 1)
    if unit == '%':
        return f"−{line.get('value')}%"
    return str(line.get('value') or '—')


def area(address):
    """'Av. X, 10, Pinheiros, São Paulo - SP' -> 'Pinheiros - São Paulo'."""
    text = str(address or '').strip()
    head, _, uf = text.rpartition(' - ')
    if head and len(uf.strip()) == 2:
        text = head
    parts = [part.strip() for part in text.split(',') if part.strip()]
    return f'{parts[-2]} - {parts[-1]}' if len(parts) >= 3 else text


def pdf_filename(receipt):
    return f"chargegrid-recibo-{str(receipt.get('number') or receipt.get('session_id') or 'sessao').lower()}.pdf"


def is_demo(app):
    return getattr(getattr(app, 'api', None), 'is_demo', False) is True


# ------------------------------------------------------------------- blocos

def badge(text, *, bgcolor=None, color='#000000'):
    return ft.Container(txt(text, 9.5, 'bold', color), bgcolor=bgcolor or BADGE_AMBER, border_radius=6,
                        padding=ft.Padding(left=7, right=7, top=3, bottom=3))


LONG_VALUE = 26  # valores maiores (endereço, motivo) vão abaixo do rótulo, em vez de espremidos à direita


def _row(label, value, *, strong=False, color=None, caption=None):
    left = [txt(label, 12, 'semibold' if strong else 'regular', None if strong else theme.GRAY_TEXT)]
    if caption:
        left.append(txt(caption, 10.5, 'regular', theme.GRAY_TEXT))
    if len(str(value)) > LONG_VALUE:
        return ft.Column([*left, txt(value, 12.5, 'semibold', color)], spacing=3,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    return ft.Row([ft.Column(left, spacing=2, expand=True),
                   txt(value, 13.5 if strong else 12.5, 'bold' if strong else 'semibold', color,
                       text_align=ft.TextAlign.END)],
                  alignment=ft.MainAxisAlignment.SPACE_BETWEEN, vertical_alignment=ft.CrossAxisAlignment.START,
                  spacing=12)


def _note(text, *, icon=ft.Icons.INFO_OUTLINE, color=None):
    return ft.Row([ft.Icon(icon, size=16, color=color or theme.GRAY_TEXT),
                   txt(text, 11, 'regular', color or theme.GRAY_TEXT, expand=True)],
                  spacing=8, vertical_alignment=ft.CrossAxisAlignment.START)


def _divider():
    return ft.Container(height=1, bgcolor=theme.BORDER_SOFT)


def _section(title, controls, *, key, badges=()):
    head = ft.Row([section_label(title, expand=True), *badges], spacing=8,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Column([head, card_box(ft.Column(list(controls), spacing=11,
                                               horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                                     padding=ft.Padding(left=16, right=16, top=16, bottom=16))],
                     spacing=12, data=f'detail-{key}')


def disclosure(title, controls, *, data=None):
    """Linha "título  ˅" que mostra/esconde ``controls`` (detalhes que não precisam estar abertos)."""
    body = ft.Column(list(controls), spacing=8, visible=False,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    arrow = ft.Icon(ft.Icons.KEYBOARD_ARROW_DOWN, size=20, color=theme.GRAY_TEXT)

    def toggle(_=None):
        body.visible = not body.visible
        arrow.icon = ft.Icons.KEYBOARD_ARROW_UP if body.visible else ft.Icons.KEYBOARD_ARROW_DOWN
        try:
            column.update()
        except (RuntimeError, AssertionError, AttributeError):
            pass  # fora da tela (testes)

    head = ft.Container(ft.Row([txt(title, 12.5, 'semibold', expand=True), arrow],
                               vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        on_click=toggle, ink=False, data=data or ('disclosure', title),
                        padding=ft.Padding(left=0, right=0, top=2, bottom=2))
    column = ft.Column([head, body], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    return column


def _metric(label, value):
    return ft.Column([txt(label, 10.5, 'regular', theme.GRAY_TEXT), num(value, 24)], spacing=0, expand=True,
                     tight=True)


def hero(receipt):
    """Resumo: posto, status, energia/total/tempo e data, número e selos."""
    station, times, point = receipt.get('station') or {}, receipt.get('times') or {}, receipt.get('point') or {}
    energy, charges, labels = receipt.get('energy') or {}, receipt.get('charges') or {}, receipt.get('labels') or {}
    place = area(station.get('address')) or ' · '.join(
        str(value) for value in (point.get('public_code'), point.get('connector_type')) if value)
    head = ft.Row([icon_tile(None, size=46),
                   ft.Column([txt(station.get('name') or 'Posto não identificado', 15, 'bold'),
                              *([txt(place, 10.5, 'regular', theme.GRAY_TEXT, max_lines=1,
                                     overflow=ft.TextOverflow.ELLIPSIS)] if place else [])],
                             spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                   status_chip(times.get('status_label') or times.get('status') or '—',
                               SESSION_TONES.get(times.get('status'), 'SLATE'))],
                  spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    minutes = _dec(times.get('duration_minutes'))
    metrics = ft.Row([_metric('Energia', kwh(_dec(energy.get('kwh')) or 0, 2)),
                      _metric('Total', _money(charges.get('total'))),
                      _metric('Tempo', duration(minutes) if minutes is not None else '—')],
                     spacing=10, vertical_alignment=ft.CrossAxisAlignment.START, data='detail-metrics')
    start = times.get('started_at') or times.get('created_at')
    period = f"{_day(start)} · {_hour(start)}" + (f"–{_hour(times['ended_at'])}" if times.get('ended_at') else '')
    when = [txt(period, 11.5, 'regular', expand=True)]
    if receipt.get('number'):
        when.append(txt(f"Nº {receipt['number']}", 11, 'semibold', theme.GRAY_TEXT))
    badges = []
    if labels.get('demo'):
        badges.append(badge('CONTA DEMO', bgcolor=BADGE_DEMO))
    if labels.get('simulated') or labels.get('measurement') == 'simulated':
        badges.append(badge('SIMULADO'))
    controls = [head, _divider(), metrics, ft.Row(when, vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    if badges:
        controls.append(ft.Row(badges, spacing=6, wrap=True))
    return card_box(ft.Column(controls, spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                    padding=ft.Padding(left=16, right=16, top=16, bottom=16), data='detail-hero')


def costs_section(price, charges, *, seller=False, paid=None):
    """Preço travado e valores. O motorista vê só o preço por kWh que pagou; o vendedor vê a composição
    (base, horário, demanda e cupom) e a explicação."""
    rows = []
    for line in price.get('lines') or []:
        key = line.get('key')
        if key == 'power_tier':
            continue  # aparece em "Sessão e bateria"
        if not seller and key != 'locked_price':
            continue  # base/horário/demanda são do vendedor; o cupom aparece como desconto abaixo
        if key == 'demand' and _dec(line.get('value')) in (None, Decimal(1)):
            continue
        rows.append(_row(line.get('label') or '—', _line_value(line), strong=key == 'locked_price',
                         caption=line.get('detail') if seller else None))
    moment = 'na reserva' if price.get('locked_by') == 'reservation' else 'no início da recarga'
    rows.append(_note(f"Travado às {_hour(price.get('locked_at'))} {moment}: mudanças depois disso não alteram "
                      'esta recarga.', icon=ft.Icons.LOCK_OUTLINE))
    rows.append(_divider())
    discount = _dec(charges.get('discount')) or Decimal(0)
    if discount:
        code = (price.get('coupon') or {}).get('code')
        rows.append(_row('Energia antes do cupom', _money(charges.get('energy_gross'))))
        rows.append(_row(f'Desconto do cupom {code}' if code else 'Desconto do cupom', '− ' + _money(discount)))
    rows.append(_row('Energia', _money(charges.get('energy_total'))))
    if charges.get('overstay') is not None:
        rows.append(_row('Permanência', _money(charges['overstay'])))
    rows.append(_row('Total', _money(charges.get('total')), strong=True))
    if charges.get('revenue_basis') == 'paid' and charges.get('paid_total') is not None:
        rows.append(_row('Valor pago (líquido)', _money(charges['paid_total']), strong=True,
                         caption='Capturado menos devolvido, confirmado pelo provedor'))
    if charges.get('status') == 'provisional':
        rows.append(_note('Valor provisório: a recarga ainda não terminou.', icon=ft.Icons.SCHEDULE,
                          color=theme.WARNING))
    note = charges.get('note')
    if note and not (seller and paid):
        rows.append(_note(note))
    if seller and price.get('explanation'):
        rows.append(disclosure('Como o preço foi calculado',
                               [txt('• ' + text, 11, 'regular', theme.GRAY_TEXT) for text in price['explanation']],
                               data='price-explanation'))
    return _section('Custos', rows, key='costs')


def _battery(energy, session, *, demo):
    start, end = _dec(energy.get('soc_start')), _dec(energy.get('soc_end'))
    if end is None and start is None:
        return []
    label = 'Bateria simulada' if demo else 'Bateria'
    value = f'{_pct(start)} → {_pct(end)}' if start is not None and end is not None else _pct(end if end is not None
                                                                                              else start)
    capacity = _dec((session or {}).get('battery_kwh'))
    rows = [_row(label, value, caption=f'Bateria do veículo {kwh(capacity, 0)}' if capacity else None)]
    level = end if end is not None else start
    rows.append(ft.ProgressBar(value=float(max(Decimal(0), min(Decimal(100), level))) / 100, color=theme.SUCCESS,
                               bgcolor=theme.SEGMENT_OFF, bar_height=6, border_radius=3))
    return rows


def _power(power):
    rows = []
    samples = power.get('samples') or []
    if samples:
        values = [_dec(point.get('kw')) or 0 for point in samples]
        step = max(1, len(samples) // 4)
        labels = [_hour(point.get('t')) if index % step == 0 or index == len(samples) - 1 else ''
                  for index, point in enumerate(samples)]
        rows.append(txt('Potência durante a recarga', 12, 'semibold'))
        rows.append(line_chart(values, labels, color=BLUE, fill=BLUE_FILL, plot_height=96, dots=()))
        rows.append(txt(f"Pico {_kw(power.get('peak_kw'))} · {power.get('sample_count') or len(samples)} leituras "
                        'do equipamento', 10.5, 'regular', theme.GRAY_TEXT))
    for change in power.get('changes') or []:
        applied = change.get('applied_kw') if change.get('status') == 'applied' else None
        value = _kw(applied or change.get('requested_kw') or change.get('applied_kw'))
        status = POWER_STATUS.get(change.get('status'), change.get('status') or '—')
        color = theme.SUCCESS if change.get('status') == 'applied' else (
            theme.ERROR if change.get('status') == 'failed' else theme.WARNING)
        detail = [txt(change.get('reason_label') or 'Ajuste de potência', 11.5, 'regular'),
                  txt(status, 10.5, 'regular', color)]
        if change.get('status') == 'failed' and change.get('failure_label'):
            detail.append(txt(change['failure_label'], 10.5, 'regular', theme.GRAY_TEXT))
        rows.append(ft.Row([txt(_hour(change.get('at')), 11.5, 'semibold', width=42),
                            ft.Column(detail, spacing=2, expand=True), txt(value, 12, 'bold')],
                           spacing=10, vertical_alignment=ft.CrossAxisAlignment.START, data='power-change'))
    return rows


def session_section(receipt, session=None, *, demo=False, seller=False):
    """Horários, término, bateria, velocidade/limites, origem da energia e potência."""
    times, energy = receipt.get('times') or {}, receipt.get('energy') or {}
    price, session = receipt.get('price') or {}, session or {}
    minutes = _dec(times.get('duration_minutes'))
    rows = [_row('Início', _stamp(times.get('started_at') or times.get('created_at'))),
            _row('Fim', _stamp(times.get('ended_at')) if times.get('ended_at') else '—'),
            _row('Duração', duration(minutes) if minutes is not None else '—')]
    if times.get('end_reason_label'):
        rows.append(_row('Término', times['end_reason_label']))
    rows.extend(_battery(energy, session, demo=demo))
    # Velocidade só quando registrada (sessão ou termos travados); recargas antigas não ganham "Máxima".
    tier = session.get('power_tier') or (price.get('power_tier') if price.get('recorded') else None)
    if tier in SPEEDS:
        rows.append(_row('Velocidade', SPEEDS[tier]))
    limits = []
    if session.get('max_duration_minutes') is not None:
        limits.append(f"{session['max_duration_minutes']} min")
    if session.get('max_cost') is not None:
        limits.append(f"até {_money(session['max_cost'])}")
    if limits:
        rows.append(_row('Limite escolhido', ' · '.join(limits)))
    if energy.get('power_limit_kw'):
        rows.append(_row('Limite de potência no início', _kw(energy['power_limit_kw'])))
    if energy.get('confirmed_by_device'):
        rows.append(_note(f"Energia confirmada pelo equipamento às {_hour(energy.get('confirmed_at'))}.",
                          icon=ft.Icons.VERIFIED_OUTLINED, color=theme.SUCCESS))
    elif not seller and energy.get('note'):
        rows.append(_note(energy['note'], icon=ft.Icons.SCHEDULE if energy.get('status') == 'pending'
                          else ft.Icons.INFO_OUTLINE, color=theme.WARNING))
    if energy.get('source_label'):
        rows.append(txt(energy['source_label'], 10.5, 'regular', theme.GRAY_TEXT))
    power = _power(receipt.get('power') or {})
    if power:
        rows.append(_divider())
        rows.extend(power)
    return _section('Sessão e bateria', rows, key='session')


def has_payment(payment):
    """Seção ``payment`` do recibo: ``status: available`` + fatos do pagamento (estado em ``payment_status``)."""
    return payment.get('status') not in ('not_applicable', 'unavailable', 'pending', None) or \
        payment.get('authorized_amount') is not None


def payment_state(payment):
    """Estado do pagamento: ``payment_status`` (a API grava ``status: available`` por cima do original)."""
    state = payment.get('payment_status')
    if state:
        return state
    state = payment.get('status')
    return state if state not in SECTION_STATES else None


def has_overstay(overstay):
    return overstay.get('status') not in ('not_applicable', 'unavailable', None) and any(
        overstay.get(key) is not None for key in ('amount', 'billable_minutes', 'grace_minutes', 'started_at'))


def _overstay_rows(overstay):
    rows = [_divider(), txt('Permanência após a recarga', 12, 'semibold')]
    phase = overstay.get('phase')
    if phase in OVERSTAY_PHASES:
        rows.append(_row('Situação', OVERSTAY_PHASES[phase]))
    if overstay.get('grace_minutes') is not None:
        rows.append(_row('Tolerância', f"{overstay['grace_minutes']} min"))
    if overstay.get('started_at'):
        rows.append(_row('Período', f"{_hour(overstay['started_at'])} – {_hour(overstay.get('ended_at'))}"))
    if overstay.get('billable_minutes') is not None:
        rows.append(_row('Minutos cobrados', f"{overstay['billable_minutes']} min"))
    if overstay.get('rate') is not None:
        rows.append(_row('Tarifa', price_text(overstay['rate']) + '/min'))
    if overstay.get('max_amount') is not None:
        rows.append(_row('Teto por recarga', _money(overstay['max_amount'])))
    if overstay.get('waived'):
        value = 'Dispensada'
    elif overstay.get('amount') is None and phase is not None:
        value = 'Sem taxa'  # sem termos aceitos antes do início: a API não cobra (``amount`` nulo)
    else:
        value = _money(overstay.get('amount'))
    rows.append(_row('Taxa de permanência', value, strong=True))
    if overstay.get('final') is False:
        rows.append(_note('Valor parcial: o carro ainda está conectado e a taxa pode subir até o teto.',
                          icon=ft.Icons.SCHEDULE, color=theme.WARNING))
    return rows


def payment_section(payment, overstay=None):
    """Pagamento do motorista (seção ``payment`` do recibo) e, se houve, a permanência."""
    payment, overstay = payment or {'status': 'not_applicable'}, overstay or {'status': 'not_applicable'}
    badges = []
    if not has_payment(payment):
        rows = [_note(payment.get('note') or 'Sem pagamento registrado: nenhum valor foi cobrado.')]
    else:
        environment = payment.get('environment')
        rows = []
        if payment.get('method'):
            rows.append(_row('Forma', PAYMENT_METHODS.get(payment['method'], payment['method'])))
        state = payment_state(payment)
        if state:
            rows.append(_row('Situação', PAYMENT_STATUS.get(state, state)))
        rows.append(_row('Autorizado', _money(payment.get('authorized_amount'))))
        if payment.get('charged_amount') is not None:
            rows.append(_row('Cobrado', _money(payment['charged_amount'])))
        if payment.get('captured_amount') is not None:
            rows.append(_row('Capturado', _money(payment['captured_amount'])))
        if payment.get('refunded_amount') is not None:
            rows.append(_row('Devolvido', _money(payment['refunded_amount']),
                             caption=REFUND_STATUS.get(payment.get('refund_status'))))
        elif payment.get('refund_status'):
            rows.append(_row('Devolução', REFUND_STATUS.get(payment['refund_status'], payment['refund_status'])))
        if payment.get('provider_fee') is not None:
            rows.append(_row('Tarifa do provedor', _money(payment['provider_fee'])))
        if payment.get('provider_reference'):
            rows.append(_row('Referência', str(payment['provider_reference']),
                             caption=payment.get('provider') and f"Provedor: {payment['provider']}"))
        if payment.get('confirmed_at'):
            rows.append(_row('Confirmado em', _stamp(payment['confirmed_at'])))
        rows.append(txt(PAYMENT_ENVIRONMENTS.get(environment, environment or 'Ambiente não informado'), 10.5,
                        'regular', theme.WARNING if environment in TEST_BADGES else theme.GRAY_TEXT))
        if environment in TEST_BADGES:
            badges.append(badge(TEST_BADGES[environment]))
    if has_overstay(overstay):
        rows.extend(_overstay_rows(overstay))
    return _section('Pagamento', rows, key='payment', badges=badges)


def seller_payment_section(session):
    """Pagamento visto pelo vendedor (``payment`` da listagem): origem, situação, acerto e permanência."""
    rows = []
    summary = owner_sessions.payment_summary(session.get('payment'))
    if summary:
        label, detail = summary
        rows.append(_row('Origem', owner_sessions.payment_source(session.get('payment'))))
        rows.append(_row('Situação', label, caption=detail))
    else:
        rows.append(_note('Sem pagamento registrado nesta recarga: valor estimado pela energia.'))
    overstay = owner_sessions.overstay_summary(session)
    if overstay:
        rows.append(_row('Permanência', overstay))
    return _section('Pagamento', rows, key='payment')


def station_section(app, receipt, session=None, *, link=True):
    station, point = receipt.get('station') or {}, receipt.get('point') or {}
    rows = [_row('Posto', station.get('name') or 'Posto não identificado')]
    if station.get('address'):
        rows.append(_row('Endereço', station['address']))
    if point.get('public_code'):
        rows.append(_row('Ponto', str(point['public_code'])))
    if point.get('connector_type'):
        rows.append(_row('Conector', str(point['connector_type'])))
    if point.get('power_kw'):
        rows.append(_row('Potência do carregador', _kw(point['power_kw'])))
    station_id = (session or {}).get('station_id')
    if link and station_id:
        rows.append(secondary_button('Ver estação', app.link('stations', station_id=station_id),
                                     icon=ft.Icons.EV_STATION_OUTLINED, height=42, size=13))
    return _section('Estação e carregador', rows, key='station')


def more_section(app, receipt, *, insight=False):
    """Linha do tempo, resumo inteligente e notas: recolhidos, abaixo de tudo."""
    controls = []
    timeline = receipt.get('timeline') or []
    if timeline:
        controls.append(disclosure('Linha do tempo', [
            ft.Row([txt(_hour(item.get('observed_at')), 11.5, 'semibold', width=42),
                    ft.Column([txt(item.get('label') or 'Evento', 11.5, 'regular'),
                               txt(item.get('source_label') or '', 10.5, 'regular', theme.GRAY_TEXT)],
                              spacing=2, expand=True)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.START) for item in timeline],
            data='timeline'))
    if insight:
        from ..ui.ai_features import session_insight_control
        controls.append(session_insight_control(app, receipt.get('session_id')))
    notes = (receipt.get('labels') or {}).get('notes') or []
    if notes:
        controls.append(ft.Column([txt(note, 10.5, 'regular', theme.GRAY_TEXT) for note in notes], spacing=4))
    if not controls:
        return None
    for index in range(len(controls) - 1, 0, -1):
        controls.insert(index, _divider())
    return _section('Mais detalhes', controls, key='more')


def export_control(app, receipt):
    """"Exportar recibo": PDF autenticado da API (na demo, gerado no aparelho) pela folha de compartilhamento."""
    async def export():
        try:
            data = await app.api.download(f"charging-sessions/{receipt['session_id']}/receipt.pdf")
            app.notice(await files.deliver(app, data, pdf_filename(receipt)))
        except ApiError as exc:
            app.notice(str(exc))
        except Exception:  # serviço de arquivos indisponível
            app.notice('Não foi possível abrir o PDF neste aparelho. Tente novamente.')

    button = primary_button(EXPORT_LABEL, app.action(export), icon=ft.Icons.IOS_SHARE)
    button.data = 'export-receipt'
    if not is_demo(app):
        return button
    return ft.Column([button, txt(EXPORT_DEMO_NOTE, 10.5, 'regular', theme.GRAY_TEXT,
                                  text_align=ft.TextAlign.CENTER)],
                     spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def detail_controls(app, receipt, session=None, *, seller=False):
    """Seções da tela na ordem (também usadas pelos testes)."""
    demo = is_demo(app)
    paid = bool((session or {}).get('payment'))
    controls = [hero(receipt),
                costs_section(receipt.get('price') or {}, receipt.get('charges') or {}, seller=seller, paid=paid),
                session_section(receipt, session, demo=demo, seller=seller)]
    if seller:
        controls.append(seller_payment_section(session or {}))
    else:
        controls.append(payment_section(receipt.get('payment'), receipt.get('overstay')))
    controls.append(station_section(app, receipt, session, link=not seller))
    if not seller:
        from ..ui.ai_features import ai_supported
        insight = ai_supported(app) and (receipt.get('times') or {}).get('status') in ('completed', 'interrupted')
        more = more_section(app, receipt, insight=insight)
        if more is not None:
            controls.append(more)
    return controls


# --------------------------------------------------------------------- telas

async def _optional_session(app, session_id):
    try:
        session = await app.api.request('GET', f'charging-sessions/{session_id}')
    except ApiError:
        return None
    return session if isinstance(session, dict) else None


def seller_receipt(session, *, demo=False):
    """Recibo montado no app a partir do item da listagem do vendedor (mesmo núcleo da API)."""
    receipt = core_receipt.build_receipt({
        'session': session,
        'station': {'name': session.get('station_name'), 'address': session.get('station_address')},
        'point': session.get('connector') or {},
        'demo': demo,
    })
    if demo:  # mesmo número legível do recibo demo do motorista (``demo_receipt.receipt``)
        receipt['number'] = 'DEMO' + str(session.get('id')).rsplit('-', 1)[-1].zfill(4)[-4:]
    return receipt


async def _seller_session(app, session_id, station_id):
    cached = (getattr(app, 'history_sessions', None) or {}).get(session_id)
    if isinstance(cached, dict) and cached.get('station_name') is not None and 'connector' in cached:
        return cached
    path = f'stations/{station_id}/charging-sessions' if station_id else 'operator/charging-sessions'
    try:
        listing = await app.api.request('GET', path, params={'limit': SELLER_PAGE, 'offset': 0})
    except ApiError:
        return None
    return next((item for item in (listing or {}).get('items') or [] if item.get('id') == session_id), None)


def _missing(back):
    return page(empty_state(ft.Icons.HISTORY, NOT_FOUND,
                            'Volte ao histórico e toque na recarga novamente.'),
                title=TITLE, on_back=back, title_size=22.6, gap=22)


async def build(app, session_id, *, manage=False, station_id=None, offset=0, **_):
    # "<" volta à mesma lista (o mesmo destino do voltar nativo em ``navigation.parent_route``).
    scope = {key: value for key, value in (('manage', True if manage else None), ('station_id', station_id),
                                           ('offset', offset or None)) if value}
    back = app.link('history', **scope)
    if manage or station_id:
        session = await _seller_session(app, session_id, station_id)
        if session is None:
            return _missing(back)
        receipt = seller_receipt(session, demo=is_demo(app))
        return page(*detail_controls(app, receipt, session, seller=True), ft.Container(height=8),
                    title=TITLE, on_back=back, title_size=22.6, gap=22)
    cached = (getattr(app, 'history_sessions', None) or {}).get(session_id)
    if isinstance(cached, dict):
        receipt, session = await app.api.request('GET', f'charging-sessions/{session_id}/receipt'), cached
    else:
        receipt, session = await asyncio.gather(app.api.request('GET', f'charging-sessions/{session_id}/receipt'),
                                                _optional_session(app, session_id))
    if session is not None and session.get('id') not in (None, session_id, receipt.get('session_id')):
        session = None
    return page(*detail_controls(app, receipt, session), ft.Container(height=8),
                title=TITLE, on_back=back, title_size=22.6, gap=22, footer=export_control(app, receipt))
