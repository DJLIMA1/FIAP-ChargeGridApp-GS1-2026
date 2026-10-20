"""Recibo explicável da recarga: subpágina do histórico (``history?receipt=<id>``).

Lê o contrato ``chargegrid.receipt`` (``GET /v1/charging-sessions/{id}/receipt``; na conta demo o
mesmo núcleo ``chargegrid_core.receipt`` roda localmente) e mostra: preço com os motivos (base,
horário, demanda, cupom, travado às HH:MM), energia confirmada pelo equipamento com o selo SIMULADO,
curva de potência e mudanças com motivo, pagamento, permanência e totais. Seções desconhecidas são
ignoradas; seções ``not_applicable``/``unavailable`` aparecem com a explicação.

O PDF (``/receipt.pdf``) é baixado com autenticação e entregue pela folha de compartilhamento
(celular) ou pelo "Salvar como" (navegador/desktop). Na conta demo o botão fica desabilitado.
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

import flet as ft

from chargegrid_core.formatting import brl, duration, kwh
from chargegrid_core.pricing import multiplier_label

from ..api_client import ApiError
from ..services import files
from ..ui import theme
from ..ui.design import card_box, page, page_title, primary_button, section_label, txt
from ..ui.states import SESSION_TONES, status_chip
from .history_owner import BLUE, BLUE_FILL, line_chart

PDF_LABEL = 'Baixar/compartilhar PDF'
PDF_DEMO_NOTE = 'PDF disponível só na conta real. Na conta demo o recibo usa dados simulados.'
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
POWER_STATUS = {'applied': 'Aplicada (confirmada pelo equipamento)', 'requested': 'Pedida, sem confirmação',
                'failed': 'Não aplicada'}
TEST_BADGES = {'mock': 'SIMULADO', 'sandbox': 'TESTE'}


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


def _line_value(line):
    unit = line.get('unit')
    if unit == 'R$/kWh':
        return price_text(line.get('value')) + '/kWh'
    if unit == '×':
        return multiplier_label(line.get('value') or 1)
    if unit == '%':
        return f"−{line.get('value')}%"
    return str(line.get('value') or '—')


# ------------------------------------------------------------------- blocos

BADGE_AMBER = '#F5B73A'  # selo fixo (preto sobre âmbar é legível nos temas claro e escuro)
BADGE_DEMO = '#FF858A'


def badge(text, *, bgcolor=None, color='#000000'):
    return ft.Container(txt(text, 9.5, 'bold', color), bgcolor=bgcolor or BADGE_AMBER, border_radius=6,
                        padding=ft.Padding(left=7, right=7, top=3, bottom=3), tooltip=None)


def _row(label, value, *, strong=False, color=None, caption=None):
    left = [txt(label, 12, 'semibold' if strong else 'regular', None if strong else theme.GRAY_TEXT)]
    if caption:
        left.append(txt(caption, 10.5, 'regular', theme.GRAY_TEXT))
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


def _section(title, controls, *, badges=()):
    head = ft.Row([section_label(title, expand=True), *badges], spacing=8,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Column([head, card_box(ft.Column(list(controls), spacing=11,
                                               horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                                     padding=ft.Padding(left=16, right=16, top=16, bottom=16))],
                     spacing=12, data=f'receipt-{title}')


def _header(receipt):
    times, station, point = receipt.get('times') or {}, receipt.get('station') or {}, receipt.get('point') or {}
    labels = receipt.get('labels') or {}
    identity = ' · '.join(part for part in (
        point.get('public_code') and f"Ponto {point['public_code']}", point.get('connector_type'),
        point.get('power_kw') and _kw(point['power_kw'])) if part)
    minutes = _dec(times.get('duration_minutes'))
    period = [f"Início {_stamp(times.get('started_at') or times.get('created_at'))}"]
    if times.get('ended_at'):
        period.append(f"Fim {_hour(times['ended_at'])}")
    if minutes is not None:
        period.append(duration(minutes))
    badges = []
    if labels.get('demo'):
        badges.append(badge('CONTA DEMO', bgcolor=BADGE_DEMO))
    if labels.get('measurement') == 'simulated' or (labels.get('simulated') and not labels.get('demo')):
        badges.append(badge('SIMULADO'))
    controls = [
        ft.Row([txt(f"Nº {receipt.get('number') or '—'}", 11.5, 'semibold', theme.GRAY_TEXT, expand=True),
                status_chip(times.get('status_label') or times.get('status') or '—',
                            SESSION_TONES.get(times.get('status'), 'SLATE'))],
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        txt(station.get('name') or 'Posto não identificado', 16, 'bold'),
    ]
    if station.get('address'):
        controls.append(txt(station['address'], 11, 'regular', theme.GRAY_TEXT))
    if identity:
        controls.append(txt(identity, 11.5, 'regular'))
    controls.append(txt(' · '.join(period), 11.5, 'regular'))
    if times.get('end_reason_label'):
        controls.append(txt(f"Término: {times['end_reason_label']}", 11.5, 'regular', theme.GRAY_TEXT))
    if badges:
        controls.append(ft.Row(badges, spacing=6, wrap=True))
    return card_box(ft.Column(controls, spacing=6), padding=ft.Padding(left=16, right=16, top=16, bottom=16))


def price_block(price):
    rows = []
    for line in price.get('lines') or []:
        rows.append(_row(line.get('label') or '—', _line_value(line), strong=line.get('key') == 'locked_price',
                         caption=line.get('detail')))
    moment = 'na reserva' if price.get('locked_by') == 'reservation' else 'no início da recarga'
    rows.append(_note(f"Preço travado às {_hour(price.get('locked_at'))} {moment}: mudanças depois disso não "
                      'alteram esta recarga.', icon=ft.Icons.LOCK_OUTLINE))
    explanation = price.get('explanation') or []
    if explanation:
        rows.append(_divider())
        rows.extend(txt('• ' + text, 11, 'regular', theme.GRAY_TEXT) for text in explanation)
    return _section('Preço', rows)


def energy_block(energy):
    simulated = energy.get('source') == 'simulated'
    rows = [txt(kwh(_dec(energy.get('kwh')) or 0, 2), 26, 'bold'),
            txt(energy.get('source_label') or 'Origem da medição não informada', 11, 'regular', theme.GRAY_TEXT)]
    if energy.get('confirmed_by_device'):
        rows.append(_note(f"Confirmada pelo equipamento às {_hour(energy.get('confirmed_at'))}.",
                          icon=ft.Icons.VERIFIED_OUTLINED, color=theme.SUCCESS))
        if energy.get('note') and 'simulado' in energy['note']:
            rows.append(txt(energy['note'], 11, 'regular', theme.GRAY_TEXT))
    elif energy.get('note'):
        rows.append(_note(energy['note'], icon=ft.Icons.SCHEDULE if energy.get('status') == 'pending'
                          else ft.Icons.INFO_OUTLINE, color=theme.WARNING))
    if energy.get('soc_start') or energy.get('soc_end'):
        start = energy.get('soc_start')
        end = energy.get('soc_end')
        rows.append(_row('Bateria', f"{_pct(start)} → {_pct(end)}" if start else _pct(end)))
    if energy.get('power_limit_kw'):
        rows.append(_row('Limite de potência no início', _kw(energy['power_limit_kw'])))
    return _section('Energia', rows, badges=[badge('SIMULADO')] if simulated else [])


def _pct(value):
    number = _dec(value)
    return '—' if number is None else f'{number.quantize(Decimal("1"))}%'


def power_block(power):
    rows = []
    samples = power.get('samples') or []
    if samples:
        values = [_dec(point.get('kw')) or 0 for point in samples]
        step = max(1, len(samples) // 4)
        labels = [_hour(point.get('t')) if index % step == 0 or index == len(samples) - 1 else ''
                  for index, point in enumerate(samples)]
        rows.append(line_chart(values, labels, color=BLUE, fill=BLUE_FILL, plot_height=110, dots=()))
        rows.append(txt(f"Pico {_kw(power.get('peak_kw'))} · {power.get('sample_count') or len(samples)} leituras "
                        'do equipamento', 11, 'regular', theme.GRAY_TEXT))
    else:
        rows.append(_note(power.get('note') or 'Amostras de potência indisponíveis.'))
    rows.append(_divider())
    rows.append(txt('Mudanças de potência', 12.5, 'semibold'))
    changes = power.get('changes') or []
    if not changes:
        rows.append(txt('Nenhuma mudança de potência registrada nesta recarga.', 11, 'regular', theme.GRAY_TEXT))
    for change in changes:
        applied = change.get('applied_kw') if change.get('status') == 'applied' else None
        value = _kw(applied or change.get('requested_kw') or change.get('applied_kw'))
        status = POWER_STATUS.get(change.get('status'), change.get('status') or '—')
        color = theme.SUCCESS if change.get('status') == 'applied' else (
            theme.ERROR if change.get('status') == 'failed' else theme.WARNING)
        rows.append(ft.Row([
            txt(_hour(change.get('at')), 11.5, 'semibold', width=42),
            ft.Column([txt(change.get('reason_label') or 'Ajuste de potência', 11.5, 'regular'),
                       txt(status, 10.5, 'regular', color),
                       *([txt(change['failure_label'], 10.5, 'regular', theme.GRAY_TEXT)]
                         if change.get('status') == 'failed' and change.get('failure_label') else [])],
                      spacing=2, expand=True),
            txt(value, 12, 'bold'),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.START))
    return _section('Potência', rows)


SECTION_STATES = ('available', 'pending', 'not_applicable', 'unavailable')


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


def payment_block(payment):
    if not has_payment(payment):
        return _section('Pagamento', [_note(payment.get('note') or 'Sem pagamento registrado: nenhum valor foi '
                                            'cobrado.')])
    environment = payment.get('environment')
    labels = {'mock': 'Pagamento simulado (nenhum dinheiro real)', 'sandbox': 'Pagamento de teste (sandbox)',
              'production': 'Pagamento real'}
    rows = [_row('Ambiente', labels.get(environment, environment or '—'))]
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
    if environment in TEST_BADGES:
        rows.append(_note('Ambiente de teste: nenhum dinheiro real foi movimentado.', color=theme.WARNING))
    badges = [badge(TEST_BADGES[environment])] if environment in TEST_BADGES else []
    return _section('Pagamento', rows, badges=badges)


def overstay_block(overstay):
    if not has_overstay(overstay):
        return _section('Permanência', [txt('Sem taxa de permanência nesta recarga.', 11.5, 'regular',
                                            theme.GRAY_TEXT)])
    rows = []
    phase = overstay.get('phase')
    if phase in OVERSTAY_PHASES:
        rows.append(_row('Situação', OVERSTAY_PHASES[phase]))
    if overstay.get('grace_minutes') is not None:
        rows.append(_row('Tolerância após a recarga', f"{overstay['grace_minutes']} min"))
    if overstay.get('started_at'):
        rows.append(_row('Período', f"{_hour(overstay['started_at'])} – {_hour(overstay.get('ended_at'))}"))
    if overstay.get('billable_minutes') is not None:
        rows.append(_row('Minutos cobrados', f"{overstay['billable_minutes']} min"))
    if overstay.get('rate') is not None:
        rows.append(_row('Tarifa', price_text(overstay['rate']) + '/min'))
    if overstay.get('max_amount') is not None:
        rows.append(_row('Teto por recarga', _money(overstay['max_amount'])))
    waived = bool(overstay.get('waived'))
    if waived:
        value = 'Dispensada'
    elif overstay.get('amount') is None and phase is not None:
        value = 'Sem taxa'  # sem termos aceitos antes do início: a API não cobra (``amount`` nulo)
    else:
        value = _money(overstay.get('amount'))
    rows.append(_row('Taxa de permanência', value, strong=True))
    if overstay.get('final') is False:
        rows.append(_note('Valor parcial: o carro ainda está conectado e a taxa pode subir até o teto.',
                          icon=ft.Icons.SCHEDULE, color=theme.WARNING))
    return _section('Permanência', rows)


def totals_block(charges):
    rows = []
    discount = _dec(charges.get('discount')) or Decimal(0)
    if discount:
        rows.append(_row('Energia antes do cupom', _money(charges.get('energy_gross'))))
        rows.append(_row('Desconto do cupom', '− ' + _money(discount)))
    rows.append(_row('Energia', _money(charges.get('energy_total'))))
    if charges.get('overstay') is not None:
        rows.append(_row('Permanência', _money(charges['overstay'])))
    rows.append(_divider())
    rows.append(_row('Total', _money(charges.get('total')), strong=True))
    if charges.get('revenue_basis') == 'paid' and charges.get('paid_total') is not None:
        rows.append(_row('Valor pago (líquido)', _money(charges['paid_total']), strong=True,
                         caption='Capturado menos devolvido, confirmado pelo provedor'))
    if charges.get('status') == 'provisional':
        rows.append(_note('Valor provisório: a recarga ainda não terminou.', icon=ft.Icons.SCHEDULE,
                          color=theme.WARNING))
    if charges.get('note'):
        rows.append(_note(charges['note']))
    return _section('Totais', rows)


def timeline_block(timeline):
    rows = [ft.Row([txt(_hour(item.get('observed_at')), 11.5, 'semibold', width=42),
                    ft.Column([txt(item.get('label') or 'Evento', 11.5, 'regular'),
                               txt(item.get('source_label') or '', 10.5, 'regular', theme.GRAY_TEXT)],
                              spacing=2, expand=True)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.START) for item in timeline]
    return _section('Linha do tempo', rows)


def receipt_controls(receipt):
    """Blocos do recibo na ordem da tela (também usados pelos testes)."""
    controls = [_header(receipt), price_block(receipt.get('price') or {}),
                energy_block(receipt.get('energy') or {}), power_block(receipt.get('power') or {}),
                payment_block(receipt.get('payment') or {'status': 'not_applicable'}),
                overstay_block(receipt.get('overstay') or {'status': 'not_applicable'}),
                totals_block(receipt.get('charges') or {})]
    if receipt.get('timeline'):
        controls.append(timeline_block(receipt['timeline']))
    notes = (receipt.get('labels') or {}).get('notes') or []
    if notes:
        controls.append(ft.Column([txt(note, 10.5, 'regular', theme.GRAY_TEXT) for note in notes], spacing=4))
    return controls


def pdf_filename(receipt):
    return f"chargegrid-recibo-{str(receipt.get('number') or receipt.get('session_id') or 'sessao').lower()}.pdf"


def pdf_control(app, receipt):
    demo = getattr(app.api, 'is_demo', False) is True
    if demo:
        return ft.Column([primary_button(PDF_LABEL, icon=ft.Icons.PICTURE_AS_PDF_OUTLINED, disabled=True),
                          txt(PDF_DEMO_NOTE, 10.5, 'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER)],
                         spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    async def download():
        try:
            data = await app.api.download(f"charging-sessions/{receipt['session_id']}/receipt.pdf")
            app.notice(await files.deliver(app, data, pdf_filename(receipt)))
        except ApiError as exc:
            app.notice(str(exc))
        except Exception:  # serviço de arquivos indisponível
            app.notice('Não foi possível abrir o PDF neste aparelho. Tente novamente.')

    return primary_button(PDF_LABEL, app.action(download), icon=ft.Icons.PICTURE_AS_PDF_OUTLINED)


async def build(app, session_id, **_):
    receipt = await app.api.request('GET', f'charging-sessions/{session_id}/receipt')
    head = page_title('Recibo', app.link('history'), size=22.6)
    return page(head, *receipt_controls(receipt), pdf_control(app, receipt), ft.Container(height=8), gap=22)
