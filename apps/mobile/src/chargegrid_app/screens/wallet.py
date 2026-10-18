"""Meu saldo (consumidor): saldo, extrato e adicionar saldo (Pix / cartão) — tudo SIMULADO no aparelho.

Rota ``wallet``; params:
  (nada)               início do saldo
  page='statement'     extrato
  step=1 (page='add')  escolher o valor      -> step=2 método -> step=3 pagamento -> step=4 sucesso
  amount, method       valor (texto/número) e 'pix' | 'card' carregados entre as etapas
Nenhum dado de cartão é lido, enviado ou guardado; o Pix é um QR estático de demonstração.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..services import wallet
from ..ui import design, theme
from ..ui.components import money

PIX_CODE = '00020126580014br.gov.bcb.pix0136chargegrid-demo-simulado5204000053039865802BR5909ChargeGrid6009SAO PAULO6304ABCD'


def parse_amount(value):
    """'260', '260,5', 'R$ 1.260,00' -> Decimal; ``None`` se inválido ou <= 0."""
    text = re.sub(r'[^\d,.]', '', str(value or ''))
    if ',' in text:
        text = text.replace('.', '').replace(',', '.')
    elif text.count('.') > 1 or re.fullmatch(r'\d{1,3}\.\d{3}', text):
        text = text.replace('.', '')
    try:
        number = Decimal(text).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError):
        return None
    return number if number > 0 else None


def _date(value):
    try:
        return datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone().strftime('%d/%m/%Y')
    except ValueError:
        return ''


def balance_card(app):
    return ft.Container(
        ft.Column([ft.Text('SALDO DISPONÍVEL', size=11, color=theme.TEXT_COLOR, font_family=design.FONT,
                           style=ft.TextStyle(letter_spacing=1.4)),
                   design.money_text(wallet.balance(app), 28)], spacing=1),
        bgcolor=theme.CARD, border_radius=design.RADIUS_CARD, padding=ft.Padding(left=16, right=16, top=15, bottom=13),
        alignment=ft.Alignment(-1, 0), margin=ft.Margin(left=0, top=-8, right=0, bottom=0))


def leave_button(app):
    """Em Meu saldo "Sair" é voltar à Conta."""
    return design.primary_button('Sair', app.link('profile'), height=48, expand=False)


def _pix_tile(size=44):
    return design.icon_tile(ft.Icons.MONEY, size=size)


def _menu_row(title, subtitle, icon, on_click):
    """Linha sem cartão da referência (tile escuro 40, subtítulo 9,6 para caber em uma linha)."""
    return ft.Container(
        ft.Row([design.icon_tile(icon, size=40, dark=True, icon_size=22),
                ft.Column([design.txt(title, 13.5, 'bold'), design.txt(subtitle, 9.6, 'regular', theme.GRAY_TEXT)],
                          spacing=4, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                ft.Icon(ft.Icons.CHEVRON_RIGHT, size=22, color=theme.GRAY_TEXT)],
               spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(left=15, right=14, top=12, bottom=12), on_click=on_click, ink=True,
        border_radius=design.RADIUS_CARD)


def home(app):
    return design.page(
        balance_card(app),
        _menu_row('Extrato', 'Verificar transferências para seu Saldo ChargeGrid', ft.Icons.RECEIPT_LONG,
                 app.link('wallet', page='statement')),
        _menu_row('Adicionar ao Saldo', 'Fazer transferência para seu Saldo ChargeGrid', ft.Icons.WALLET,
                 app.link('wallet', page='add', step=1)),
        title='Meu saldo', title_size=15, on_back=app.back, footer=leave_button(app))


def statement(app):
    rows = []
    for item in wallet.transactions(app):
        sign = '-' if item['kind'] == 'debit' else ''
        rows.append(ft.Container(
            ft.Row([design.icon_tile(ft.Icons.MONEY, size=56),
                    ft.Column([design.txt(item['title'], 13.5, 'bold'),
                               design.txt(f'{sign}{money(item["amount"]).replace("R$ ", "R$")}', 10.5, 'regular',
                                          theme.GRAY_TEXT)], spacing=3, expand=True,
                              alignment=ft.MainAxisAlignment.CENTER),
                    design.txt(_date(item['created_at']), 12, 'regular', theme.GRAY_TEXT)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=theme.CARD, border_radius=design.RADIUS_CARD, padding=ft.Padding(left=13, right=16, top=15, bottom=15)))
    if not rows:
        rows.append(design.txt('Nenhuma transferência ainda.', 12, 'regular', theme.GRAY_TEXT))
    return design.page(
        balance_card(app), ft.Container(height=2), design.txt('Transferências', 15, 'bold'), *rows,
        title='Extrato', title_size=15, on_back=app.back, footer=leave_button(app))


def add_amount(app, amount=None):
    field = ft.TextField(
        value='' if amount in (None, '') else str(amount).replace('.', ','), hint_text='R$260,00',
        keyboard_type=ft.KeyboardType.NUMBER, filled=False, color='#1F1F1F', cursor_color='#1F1F1F',
        hint_style=ft.TextStyle(color='#999999', size=14.5, font_family=design.FONT),
        text_style=ft.TextStyle(size=14.5, font_family=design.FONT, color='#1F1F1F'),
        border=ft.NoInputBorder(), height=62,
        content_padding=ft.Padding(left=17, right=16, top=19, bottom=19))
    box = ft.Container(field, bgcolor='#FFFFFF', border_radius=design.RADIUS_BTN + 2, height=62,
                       clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    error = design.txt('', 11.5, 'regular', theme.RED, visible=False)

    async def proceed(event):
        value = parse_amount(field.value)
        if value is None:
            error.value, error.visible = 'Informe um valor maior que zero.', True
            error.update()
            return
        await app.go('wallet', page='add', step=2, amount=str(value))
    return design.page(
        balance_card(app), ft.Container(height=2), design.txt('Escolher o valor', 15, 'bold'), box, error,
        design.danger_button('Prosseguir para o pagamento', proceed, height=48),
        title='Adicionar ao Saldo', title_size=15, on_back=app.back, footer=leave_button(app))


def _wide(button, lower=12):
    """Botão de assistente: encosta ``lower`` pt mais perto da barra inferior que o padrão do ``page``."""
    return ft.Container(button, margin=ft.Margin(left=0, top=0, right=0, bottom=-lower))


def method(app, amount, selected='pix'):
    holder = {'value': selected}
    column = ft.Column(spacing=17)

    def render():
        column.controls = [
            _method_card('Pix', ft.Icons.MONEY, holder['value'] == 'pix', lambda e: choose('pix')),
            _method_card('Cartão de Crédito / Débito', ft.Icons.CREDIT_CARD, holder['value'] == 'card',
                         lambda e: choose('card'))]

    def choose(key):
        holder['value'] = key
        render()
        column.update()
    render()

    async def go_on(event):
        await app.go('wallet', page='add', step=3, amount=amount, method=holder['value'])
    return design.page(
        ft.Container(column, margin=ft.Margin(left=0, top=-3, right=0, bottom=0)), title='Método de Pagamento', title_size=17.5, on_back=app.back, gutter=5,
        footer=_wide(design.primary_button('Continuar', go_on, height=55, size=16, weight='bold')))


def _method_card(title, icon, selected, on_click):
    dot = ft.Container(
        None, width=14, height=14, border_radius=7, alignment=ft.Alignment(0, 0),
        bgcolor=theme.BTN_PRIMARY if selected else None,
        border=None if selected else ft.Border.all(2, theme.TEXT_COLOR))
    dot = ft.Container(dot, width=28, height=28, alignment=ft.Alignment(0, 0))
    return ft.Container(
        ft.Row([design.icon_tile(icon, size=44), design.txt(title, 13, 'bold', expand=True), dot],
               spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.CARD, border_radius=design.RADIUS_CARD, on_click=on_click, ink=False,
        padding=ft.Padding(left=10, right=18, top=11, bottom=11), height=65,
        border=ft.Border.all(1, theme.BTN_PRIMARY) if selected else None)


async def _confirm(app, amount):
    try:
        wallet.credit(app, amount, 'Pix Recebido')
    except ApiError as error:
        app.notice(str(error))
        return
    await app.go('wallet', page='add', step=4, amount=str(amount))


def pay_pix(app, amount):
    value = parse_amount(amount) or Decimal('0')

    async def copy(event):
        try:
            await ft.Clipboard().set(PIX_CODE)
            app.notice('Código Pix copiado.')
        except Exception:  # noqa: BLE001 — área de transferência indisponível no ambiente
            app.notice('Não foi possível copiar o código.')

    async def paid(event):
        await _confirm(app, value)
    qr = ft.Container(ft.Image(src=design.QR_SRC, width=286, height=286, fit=ft.BoxFit.COVER,
                               exclude_from_semantics=True),
                      width=260, height=263, bgcolor='#F7F7F7', border_radius=20, alignment=ft.Alignment(0, 0),
                      clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    return design.page(
        ft.Container(height=29),
        ft.Column([qr, ft.Column([design.txt(money(value), 28, 'bold', text_align=ft.TextAlign.CENTER),
                                  ft.Container(design.txt('Expira em 14:59', 12.5, 'bold', theme.GRAY_TEXT,
                                                          text_align=ft.TextAlign.CENTER),
                                               margin=ft.Margin(left=0, top=-5, right=0, bottom=0))], spacing=2,
                                 horizontal_alignment=ft.CrossAxisAlignment.CENTER)],
                  spacing=13, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        title='Efetuar Pagamento', title_size=17.5, on_back=app.back, gutter=6,
        footer=ft.Container(ft.Column([
            _secure_note(), _copy_button(copy),
            ft.Container(design.primary_button('Já paguei (Confirmar)', paid, height=55, size=16, weight='bold'),
                         margin=ft.Margin(left=0, top=2, right=0, bottom=0))], spacing=14,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH), margin=ft.Margin(left=0, top=0, right=0, bottom=28)))


def _copy_button(on_click):
    return ft.Container(
        ft.Row([ft.Icon(ft.Icons.CONTENT_COPY, size=16, color=theme.BTN_SECONDARY_FG),
                design.txt('Copiar código Pix', 13.5, 'semibold', theme.BTN_SECONDARY_FG)], spacing=8,
               alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.BTN_SECONDARY, border_radius=design.RADIUS_BTN, height=46, on_click=on_click, ink=True)


def _secure_note():
    return ft.Row([ft.Icon(ft.Icons.GPP_GOOD_OUTLINED, size=21, color=theme.SUCCESS),
                   design.txt('Pagamento seguro e criptografado', 12, 'regular', theme.GRAY_TEXT)],
                  spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _card_field(label, hint, *, password=False, keyboard=None):
    """Campo de demonstração (rótulo + caixa escura arredondada). Nada digitado é lido, enviado ou guardado."""
    field = ft.TextField(
        hint_text=hint, password=password, can_reveal_password=False, keyboard_type=keyboard, filled=False,
        color=theme.INPUT_TEXT, cursor_color=theme.INPUT_TEXT, border=ft.NoInputBorder(), height=45,
        hint_style=ft.TextStyle(color=theme.GRAY_TEXT, size=12.1, font_family=design.FONT),
        text_style=ft.TextStyle(size=12.1, font_family=design.FONT, color=theme.INPUT_TEXT),
        content_padding=ft.Padding(left=13, right=13, top=13, bottom=13))
    box = ft.Container(field, bgcolor=theme.INPUT_BG, border_radius=design.RADIUS_BTN + 2, height=45,
                       clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    return ft.Column([design.label(label), box], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def pay_card(app, amount):
    """Formulário de cartão apenas de demonstração: os campos nunca são lidos nem guardados."""
    value = parse_amount(amount) or Decimal('0')

    async def pay(event):
        await _confirm(app, value)
    number = _card_field('Número do cartão', '0000 0000 0000 0000', keyboard=ft.KeyboardType.NUMBER)
    name = _card_field('Nome impresso', 'Nome no cartão')
    expiry = _card_field('Validade', 'MM/AA')
    cvv = _card_field('CVV', '•••', password=True, keyboard=ft.KeyboardType.NUMBER)
    return design.page(
        ft.Container(height=0), number, name,
        ft.Row([ft.Column([expiry], expand=True), ft.Column([cvv], expand=True)], spacing=34),
        title='Efetuar Pagamento', title_size=17.5, on_back=app.back, gap=14, gutter=4,
        footer=[_secure_note(), _wide(design.primary_button('Efetuar Pagamento', pay, height=55, size=16, weight='bold'),
                                      8)])


def success(app):
    return design.page(
        ft.Container(height=117),
        design.txt('Valor adicionado ao Saldo!', 19, 'bold', text_align=ft.TextAlign.CENTER),
        ft.Container(height=66),
        ft.Row([ft.Container(ft.Icon(ft.Icons.CHECK_ROUNDED, size=130, color='#FFFFFF'), width=167, height=167,
                             border_radius=84, bgcolor='#3EBF80', alignment=ft.Alignment(0, 0))],
               alignment=ft.MainAxisAlignment.CENTER),
        ft.Container(height=72),
        ft.Column([design.secondary_button('Verificar Saldo', app.link('wallet'), height=46, size=13, weight='semibold'),
                   design.primary_button('Voltar ao início', app.link('home'), height=46, size=13, weight='semibold')],
                  spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        title=None, gap=0, gutter=6)


async def build(app, **params):
    page = params.get('page')
    try:
        step = int(params.get('step') or 0)
    except (TypeError, ValueError):
        step = 0
    amount = params.get('amount')
    if page == 'statement':
        return statement(app)
    if page == 'add' or step:
        if step == 2:
            return method(app, amount, params.get('method') or 'pix')
        if step == 3:
            return pay_card(app, amount) if params.get('method') == 'card' else pay_pix(app, amount)
        if step >= 4:
            return success(app)
        return add_amount(app, amount)
    return home(app)
