"""Carteira e resgate do vendedor (simulado). Passos: 1 carteira, 2 modalidade, 3 confirmação, 4 resultado."""

import flet as ft

from ..services import payout as service
from ..ui import design, theme
from ..ui.components import money

TOP = 14
TITLE = 22.6
AMBER = '#F5B73A'
SUCCESS_DISC = '#143C29'
SUCCESS_CHECK = '#34C77B'


def _step(params):
    try:
        return max(1, min(4, int(params.get('step') or 1)))
    except (TypeError, ValueError):
        return 1


def _mode(params):
    return 'friday' if params.get('mode') == 'friday' else 'now'


async def _load_revenue(app):
    if service.is_demo(app):
        return
    try:
        summary, _ = await app.api.request('GET', 'operator/summary')
        if isinstance(summary, dict):
            service.set_revenue(app, summary.get('total_estimated_cost'))
    except Exception:  # sem rede: usa o último valor conhecido
        pass


def _balance_card(app):
    return design.card_box(ft.Column([
        design.txt('Saldo disponível para resgate', 11.5, 'regular', theme.GRAY_TEXT),
        ft.Container(design.txt(money(service.available(app)), 33, 'bold'), margin=ft.Margin(0, 8, 0, 0)),
    ], spacing=0), padding=ft.Padding(left=16, right=16, top=23, bottom=22), margin=ft.Margin(0, TOP, 0, 0))


def _movement_row(item):
    amount = item['amount']
    sign = '+' if amount >= 0 else '–'
    tile = ft.Container(ft.Icon(ft.Icons.TRENDING_UP if amount >= 0 else ft.Icons.NORTH_EAST, size=18,
                                color=theme.TILE_FG), width=34, height=34, bgcolor=theme.TILE, border_radius=8,
                        alignment=ft.Alignment(0, 0))
    row = ft.Row([
        tile,
        ft.Column([design.txt(item['title'], 13, 'semibold'),
                   design.txt(item['subtitle'], 10, 'regular', theme.GRAY_TEXT)],
                  spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER),
        design.txt(f'{sign} {money(abs(amount))}', 12, 'bold',
                   theme.SUCCESS if amount >= 0 and not theme.is_dark() else None),
    ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return design.card_box(row, padding=ft.Padding(left=15, right=16, top=17, bottom=17))


def _row(title, subtitle, icon, on_click=None, trailing=None):
    tile = ft.Container(ft.Icon(icon, size=18, color=theme.TILE_FG), width=34, height=34, bgcolor=theme.TILE,
                        border_radius=8, alignment=ft.Alignment(0, 0))
    right = trailing if trailing is not None else ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22, color=theme.GRAY_TEXT)
    row = ft.Row([tile, ft.Column([design.txt(title, 13, 'semibold'), design.txt(subtitle, 10, 'regular', theme.GRAY_TEXT)],
                                  spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER), right],
                 spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return design.card_box(row, padding=ft.Padding(left=15, right=16, top=17, bottom=17), on_click=on_click)


async def _wallet(app):
    await _load_revenue(app)
    items = service.movements(app)
    rows = [_movement_row(item) for item in items] or [
        design.txt('Nenhuma movimentação ainda.', 12, 'regular', theme.GRAY_TEXT)]
    can_redeem = service.available(app) > 0
    return design.page(
        _balance_card(app),
        ft.Container(design.section_label('Movimentações'), margin=ft.Margin(0, 21, 0, -2)),
        *rows,
        title='Minha Carteira', on_back=app.back, gap=16, title_size=TITLE,
        footer=design.primary_button('Resgatar saldo', app.link('payout', step=2), height=46, expand=True, size=13, weight='bold',
                                     disabled=not can_redeem))


async def _choose(app):
    await _load_revenue(app)
    return design.page(
        _balance_card(app),
        ft.Container(design.section_label('Escolha a modalidade'), margin=ft.Margin(0, 21, 0, -2)),
        _row('Receber agora', 'Antecipação com taxa de 2%', ft.Icons.BOLT_OUTLINED,
             app.link('payout', step=3, mode='now')),
        _row('Receber na sexta-feira', 'Sem taxa de antecipação', ft.Icons.CALENDAR_TODAY_OUTLINED,
             app.link('payout', step=3, mode='friday')),
        _before_confirm(),
        title='Resgatar Saldo', on_back=app.back, gap=16, title_size=TITLE)


def _before_confirm():
    return ft.Container(
        ft.Column([
            ft.Icon(ft.Icons.INFO_OUTLINE, size=20, color=theme.RED),
            design.txt('Antes de confirmar', 12.5, 'semibold', text_align=ft.TextAlign.CENTER),
            ft.Container(design.txt('Confira o valor líquido, os dados bancários e o prazo de cada modalidade.',
                                    11, 'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER),
                         margin=ft.Margin(0, 6, 0, 0)),
        ], spacing=2, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.WARN_BG, border_radius=design.RADIUS_CARD, padding=ft.Padding(left=60, right=60, top=18, bottom=20),
        margin=ft.Margin(0, 3, 0, 0))


def _line(left, right):
    return ft.Row([design.txt(left, 11.5, 'regular', theme.GRAY_TEXT), design.txt(right, 12, 'bold')],
                  alignment=ft.MainAxisAlignment.SPACE_BETWEEN)


async def _confirm(app, mode):
    await _load_revenue(app)
    values = service.quote(app, mode)
    now = mode == 'now'
    demo = service.is_demo(app)
    card = design.card_box(ft.Column([
        _line('Valor bruto' if now else 'Saldo para resgate', money(values['gross'])),
        ft.Container(height=3),
        _line('Taxa de antecipação • 2%' if now else 'Taxa de antecipação',
              f"– {money(values['fee'])}" if now else money(values['fee'])),
        ft.Container(height=12),
        ft.Divider(height=1, thickness=1, color=theme.BORDER_SOFT),
        ft.Container(height=10),
        design.txt('Você recebe', 12.5, 'regular', theme.GRAY_TEXT),
        design.txt(money(values['net']), 30, 'bold'),
    ], spacing=7), padding=ft.Padding(left=15, right=15, top=21, bottom=19))
    name = ft.Row([design.txt('Banco Inter - final 0378' if demo else 'Conta cadastrada', 13.5, 'semibold'),
                   *([ft.Icon(ft.Icons.CHECK, size=20, color=SUCCESS_CHECK)] if demo else [])], spacing=6)
    dest = design.card_box(ft.Row([
        ft.Column([name, design.txt('Conta cadastrada' if demo else 'Dados bancários do seu cadastro', 10.5, 'regular',
                                    theme.GRAY_TEXT)], spacing=12, expand=True),
        ft.Icon(ft.Icons.CHEVRON_RIGHT, size=26, color=theme.GRAY_TEXT)], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(left=15, right=14, top=22, bottom=22))
    disabled = values['gross'] <= 0

    async def confirm(event):
        try:
            result = service.request(app, mode)
        except ValueError:
            return
        app._payout_last = result
        await app.go('payout', step=4, mode=mode)

    return design.page(
        ft.Container(card, margin=ft.Margin(0, TOP, 0, 0)),
        ft.Container(design.section_label('Conta de destino'), margin=ft.Margin(0, 24, 0, -4)),
        dest,
        ft.Container(design.primary_button('Confirmar resgate (com taxa)' if now else 'Confirmar resgate (sem taxa)',
                                           confirm, height=46, expand=True, disabled=disabled, size=13, weight='bold'),
                     margin=ft.Margin(0, -4 if now else 12, 0, 0)),
        title='Resgate agora' if now else 'Receber na sexta-feira', on_back=app.back, gap=16, title_size=TITLE)


def _detail_row(left, value, color=None):
    return ft.Row([design.txt(left, 11.5, 'regular', theme.GRAY_TEXT), design.txt(value, 12, 'bold', color)],
                  alignment=ft.MainAxisAlignment.SPACE_BETWEEN)


async def _result(app, params):
    done = params.get('status') in ('done', 'concluido')
    last = getattr(app, '_payout_last', None)
    if done or not last:
        info = {'destination': service.destination(app), 'status': 'Concluído' if done else 'Em processamento',
                'protocol': 'CG-RS-1021' if done else 'CG-RS-1026'}
    else:
        info = last
    finished = info['status'] == 'Concluído'
    color = SUCCESS_CHECK if finished else AMBER
    disc = ft.Container(ft.Icon(ft.Icons.CHECK, size=64, color=SUCCESS_CHECK), width=124, height=124, border_radius=62,
                        bgcolor=SUCCESS_DISC, alignment=ft.Alignment(0, 0))
    details = design.card_box(ft.Column([
        _detail_row('Destino', info['destination']),
        _detail_row('Status', info['status'], color),
        _detail_row('Protocolo', info['protocol']),
    ], spacing=21), padding=ft.Padding(left=10, right=10, top=23, bottom=29))
    heading = design.txt('Resgate concluído' if finished else 'Solicitação registrada', TITLE, 'bold',
                         text_align=ft.TextAlign.CENTER)
    return design.page(
        ft.Container(heading, margin=ft.Margin(0, 0, 0, 7)),
        ft.Column([disc, ft.Column([
            design.txt('Resgate Concluído' if finished else 'Solicitação recebida', 19, 'bold',
                       text_align=ft.TextAlign.CENTER),
            design.txt('Acompanhe o status no seu banco.' if finished else 'Acompanhe o status na sua carteira.',
                       11.5, 'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER)], spacing=15,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER)],
            spacing=17, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Container(details, margin=ft.Margin(3, 15, 3, 0)),
        gap=24,
        footer=ft.Container(design.primary_button('Voltar à carteira', app.link('payout'), height=46, expand=True,
                                                  size=13, weight='bold'), margin=ft.Margin(3, 0, 3, 0)))


async def build(app, **params):
    step = _step(params)
    if step == 2:
        return await _choose(app)
    if step == 3:
        return await _confirm(app, _mode(params))
    if step == 4:
        return await _result(app, params)
    return await _wallet(app)
