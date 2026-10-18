"""Assistente de recarga do consumidor (rota ``booking``).

Etapas (``step``; voltar = etapa anterior, contrato de ``navigation.parent_route``):
  1 conector · 2 Reservar/Agora · 3 por tempo/valor · 4 potência · 5 pagamento · 6 revisar
  7 Pix/cartão (simulado) · 8 reserva confirmada
Parâmetros de rota: ``step``, ``station_id``, ``connector_id`` e, para abrir uma etapa já preenchida
(captura/atalhos): ``kind`` (reserve|now), ``by`` (time|value), ``amount``, ``power`` (max|reduced),
``pay`` (balance|pix|card), ``slot``. O estado das escolhas fica em ``app.booking`` (memória).

"Reservar" cria a reserva pela API (``POST reservations`` com chave de idempotência); "Agora" entrega
para o fluxo de início de recarga (``charging``), onde o código de presença #F continua obrigatório.
O pagamento é simulado: Saldo debita ``services.wallet``; Pix/cartão apenas confirmam. Nenhum dado de
cartão é lido, guardado ou enviado.
"""

import flet as ft

from ..api_client import ApiError
from ..services import booking as rules
from ..services import wallet
from ..ui import design, theme
from ..ui.point_summary import point_context

PIX_CODE = '00020126580014br.gov.bcb.pix0136chargegrid-demo-simulado5204000053039865802BR5909ChargeGrid6009SAO PAULO6304ABCD'
AMBER_BG = '#4E3F24'
AMBER = '#E8922B'
WARNING_TEXT = 'A potência real pode variar conforme o veículo e o nível da bateria.'
PAY_LABELS = {'balance': 'Saldo Disponível', 'pix': 'Pix', 'card': 'Cartão de Crédito / Débito'}
PAY_ICONS = {'balance': ft.Icons.WALLET, 'pix': ft.Icons.MONEY, 'card': ft.Icons.CREDIT_CARD}
LAST_STEP = 8


def _state(app, station_id, keep_done=False):
    state = getattr(app, 'booking', None)
    if not isinstance(state, dict) or state.get('station_id') != station_id or (state.get('done') and not keep_done):
        state = {'station_id': station_id, 'mode': 'reserve', 'by': 'time', 'power': 'max', 'pay': 'balance',
                 'minutes_text': '', 'value_text': '', 'group': None, 'connector_id': None, 'slot': None,
                 'key': None, 'result': None, 'done': False}
        app.booking = state
    return state


def _apply_presets(state, group_keys, presets):
    for name in ('kind', 'by', 'power', 'pay', 'slot'):
        if presets.get(name) is not None:
            state['mode' if name == 'kind' else name] = str(presets[name])
    if presets.get('amount') is not None:
        state['value_text' if state['by'] == 'value' else 'minutes_text'] = str(presets['amount'])


def _info_box(text, icon=ft.Icons.INFO_OUTLINE):
    return ft.Container(
        ft.Row([ft.Icon(icon, size=20, color=theme.TEXT_COLOR), design.txt(text, 13, 'regular')], spacing=10,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.CARD, border_radius=design.RADIUS_BTN + 2, height=42,
        padding=ft.Padding(left=13, right=13, top=0, bottom=0), alignment=ft.Alignment(-1, 0))


def _fee_box():
    return ft.Container(
        ft.Row([ft.Icon(ft.Icons.INFO_OUTLINE, size=20, color=AMBER),
                ft.Text(spans=[ft.TextSpan('Taxa de reserva: ', ft.TextStyle(font_family=design.FONT, size=12.5)),
                               ft.TextSpan(rules.money(rules.RESERVATION_FEE),
                                           ft.TextStyle(font_family=design.FONT_BOLD, size=12.5))],
                        color=theme.TEXT_COLOR)],
               spacing=10, alignment=ft.MainAxisAlignment.CENTER, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=AMBER_BG, border_radius=design.RADIUS_CARD, height=65, alignment=ft.Alignment(0, 0))


def _white_field(hint, value, on_change):
    field = design.input_field(value, hint, keyboard=ft.KeyboardType.NUMBER, on_change=on_change, height=43)
    field.border = ft.InputBorder.OUTLINE
    field.border_color = '#FFFFFF'
    field.border_radius = 14
    field.fill_color = '#FFFFFF'
    field.color = '#000000'
    field.cursor_color = '#000000'
    field.hint_style = ft.TextStyle(color='#6B6B6B', size=13, font_family=design.FONT)
    field.text_style = ft.TextStyle(size=13, font_family=design.FONT, color='#000000')
    return field


def _option(title, subtitle, *, selected, on_click, icon=None):
    """Cartão de opção com seletor circular (conector, potência, pagamento)."""
    dot = ft.Container(
        ft.Container(width=12, height=12, border_radius=6, bgcolor=theme.BTN_PRIMARY) if selected else None,
        width=20, height=20, border_radius=10, alignment=ft.Alignment(0, 0),
        border=None if selected else ft.Border.all(1.6, theme.TEXT_COLOR))
    texts = [design.txt(title, 13, 'bold')]
    if subtitle:
        texts.append(design.txt(subtitle, 10, 'regular', theme.GRAY_TEXT))
    return ft.Container(
        ft.Row([design.icon_tile(icon, size=42), ft.Column(texts, spacing=3, expand=True,
                                                          alignment=ft.MainAxisAlignment.CENTER), dot],
               spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(left=11, right=16, top=11, bottom=11), border_radius=design.RADIUS_CARD,
        bgcolor=theme.CARD, border=ft.Border.all(1.2, '#FFFFFF') if selected else None, on_click=on_click,
        ink=bool(on_click))


def _chip(text, selected, on_click):
    return ft.Container(
        design.txt(text, 12, 'bold' if selected else 'medium', theme.BTN_PRIMARY_FG if selected else '#6F6F6F',
                   text_align=ft.TextAlign.CENTER),
        height=51, alignment=ft.Alignment(0, 0), expand=True, border_radius=design.RADIUS_BTN,
        bgcolor=theme.BTN_PRIMARY if selected else '#262626', on_click=on_click, ink=bool(on_click))


def _footer(button, warning=True):
    """Aviso + botão como na referência (16 pt entre eles, botão 41 pt acima da barra)."""
    items = [ft.Container(design.warning_box(WARNING_TEXT), margin=ft.Margin(left=0, top=0, right=0, bottom=4))] \
        if warning else []
    return [*items, ft.Container(button, margin=ft.Margin(left=0, top=0, right=0, bottom=9))]


def _bar(total, current):
    """Barra de etapas da referência: só o segmento da etapa atual fica aceso."""
    return ft.Container(
        ft.Row([ft.Container(height=3, expand=True, border_radius=2,
                             bgcolor=theme.BTN_PRIMARY if index + 1 == current else theme.SEGMENT_OFF)
                for index in range(total)], spacing=6),
        padding=ft.Padding(left=3, right=3, top=0, bottom=0))


def _replace_bar(control, total, current):
    content = getattr(control, 'content', None)
    if isinstance(control, ft.Container) and isinstance(content, ft.Row) and content.controls and all(
            getattr(item, 'height', None) == 3 for item in content.controls):
        control.content = _bar(total, current).content
        return True
    if content is not None and not isinstance(content, str) and _replace_bar(content, total, current):
        return True
    return any(_replace_bar(child, total, current) for child in getattr(control, 'controls', None) or [])


def _page(*controls, steps=None, step=None, **kwargs):
    column = design.page(*controls, steps=steps, step=step, **kwargs)
    if steps:
        _replace_bar(column, steps, step)
    return column


def _section(text):
    return design.txt(text, 13, 'bold')


def _secure_note():
    return ft.Row([ft.Icon(ft.Icons.VERIFIED_USER_OUTLINED, size=14, color=theme.SUCCESS),
                   design.txt('Pagamento seguro e criptografado', 11, 'regular', theme.GRAY_TEXT)], spacing=8)


async def build(app, step=1, station_id=None, connector_id=None, **presets):
    step = max(1, min(LAST_STEP, int(step or 1)))
    if not station_id:
        return _page(
            design.txt('Escolha uma estação para iniciar sua recarga.', 13, 'regular', theme.GRAY_TEXT),
            design.primary_button('Buscar estação', app.link('stations'), height=55, size=16, weight='bold'),
            title='Reservar estação', on_back=app.back)
    try:
        station = await app.api.request('GET', f'stations/{station_id}') or {}
    except ApiError as exc:
        return design.page(design.txt(str(exc), 13, 'regular', theme.GRAY_TEXT), title='Reservar estação',
                           on_back=app.back)
    groups = rules.group_connectors(station)
    state = _state(app, station_id, keep_done=step == LAST_STEP)
    fresh = state['group'] is None
    if not groups:
        return _page(
            design.txt('Esta estação não tem conectores disponíveis para recarga.', 13, 'regular', theme.GRAY_TEXT),
            title='Reservar estação', on_back=app.back)
    if fresh:
        _apply_presets(state, [g['key'] for g in groups], presets)
    by_key = {group['key']: group for group in groups}
    if connector_id and state['group'] is None:
        for group in groups:
            if any(point.get('id') == connector_id for point in group['connectors']):
                state['group'], state['connector_id'] = group['key'], connector_id
    if state['group'] not in by_key:
        state['group'] = None
        state['connector_id'] = None
    if state['group'] is None and step > 1:
        # Abertura direta em etapa posterior: escolhe o primeiro grupo com conector livre.
        first = next((g for g in groups if g['free']), groups[0])
        state['group'] = first['key']
    group = by_key.get(state['group'])
    slots = rules.time_slots()
    if state['slot'] not in slots:
        state['slot'] = slots[0]
    reserving = state['mode'] == 'reserve'

    def nav(target):
        async def handler(event=None):
            await app.go('booking', step=target, station_id=station_id)
        return handler

    def quote():
        power = rules.power_options(group)[state['power']][0]
        if state['by'] == 'value':
            return rules.estimate(power, group['price'], value=rules.parse_value(state['value_text'] or '0'))
        return rules.estimate(power, group['price'], minutes=rules.parse_minutes(state['minutes_text'] or '0'))

    def safe_quote():
        try:
            return quote()
        except (ValueError, ArithmeticError):
            return None

    if step > 3 and safe_quote() is None:
        state['by'], state['minutes_text'] = state['by'], state['minutes_text'] or '30'
        if state['by'] == 'value' and not state['value_text']:
            state['value_text'] = '50,00'

    def failing(message):
        return ApiError(message, 422, 'booking_invalid')

    # ------------------------------------------------------------------ etapas
    wizard = dict(gutter=3, gap=16)

    if step == 1:
        def choose(key):
            async def handler(event=None):
                state['group'] = key
                state['connector_id'] = None
                await app.go('booking', step=1, station_id=station_id)
            return handler

        cards = [_option(group_title, subtitle, selected=state['group'] == item['key'],
                         on_click=choose(item['key']))
                 for item in groups
                 for group_title, subtitle in [(rules.group_title(item), rules.group_subtitle(item))]]
        chosen = state['group'] and by_key[state['group']]
        ready = bool(chosen and chosen['free'])

        async def go_on():
            if not ready:
                raise failing('Escolha um conector livre para continuar.')
            if not state['connector_id'] or state['connector_id'] not in [p['id'] for p in chosen['free']]:
                state['connector_id'] = chosen['free'][0]['id']
            await app.go('booking', step=2, station_id=station_id)
        button = (design.primary_button('Continuar', app.action(go_on), height=55, size=16, weight='bold')
                  if ready else design.secondary_button('Continuar', None, height=55, size=16, weight='bold',
                                                        disabled=True))
        return _page(*cards, title='Qual conector deseja usar?', on_back=app.back, steps=4, step=1,
                           footer=_footer(button), **wizard)

    if step == 2:
        def set_mode(value):
            async def handler(key):
                state['mode'] = key
                await app.go('booking', step=2, station_id=station_id)
            return handler
        toggle = design.segmented([('reserve', 'Reservar'), ('now', 'Agora')], state['mode'], set_mode(None), height=38)

        def pick_slot(value):
            async def handler(event=None):
                state['slot'] = value
                await app.go('booking', step=2, station_id=station_id)
            return handler
        if reserving:
            chips = ft.Container(
                ft.Row([_chip(text, text == state['slot'], pick_slot(text)) for text in slots], spacing=14),
                bgcolor=theme.CARD, border_radius=design.RADIUS_CARD, padding=13.5)
            body = [ft.Container(height=4), toggle,
                    ft.Container(ft.Column([design.label('Horários disponíveis', strong=False), chips], spacing=10),
                                 margin=ft.Margin(left=0, top=24, right=0, bottom=0)),
                    ft.Container(design.labeled('Tempo de tolerância', _info_box(f'{rules.TOLERANCE_MINUTES} minutos'),
                                                10, strong=False), margin=ft.Margin(left=0, top=4, right=0, bottom=0)),
                    ft.Container(height=14), _fee_box()]
        else:
            body = [ft.Container(height=4), toggle, ft.Container(height=6), design.txt('Tempo de tolerância', 18, 'bold'),
                    _info_box(f'{rules.TOLERANCE_MINUTES} minutos')]
        return _page(*body, title='Defina como será sua recarga', on_back=app.back, steps=4, step=2,
                           footer=_footer(design.primary_button('Continuar', nav(3), height=55, size=16,
                                                                weight='bold')), **wizard)

    if step == 3:
        by_value = state['by'] == 'value'

        def set_by(key):
            state['by'] = key
            return app.go('booking', step=3, station_id=station_id)
        toggle = design.segmented([('time', 'Por tempo'), ('value', 'Por valor')], state['by'], set_by, height=38)
        key = 'value_text' if by_value else 'minutes_text'

        def changed(event):
            state[key] = event.control.value or ''
        field = _white_field('Exemplo: 249,90' if by_value else 'Exemplo: 30', state[key], changed)

        async def next_step():
            try:
                result = quote()
            except (ValueError, ArithmeticError) as exc:
                raise failing(str(exc) or 'Confira o valor informado.') from None
            limit = int(group['connectors'][0].get('max_duration_minutes') or 0)
            if limit and result['minutes'] > limit:
                raise failing(f'Este conector permite recargas de até {limit} minutos.')
            await app.go('booking', step=4, station_id=station_id)
        return _page(
            ft.Container(height=4), toggle,
            design.labeled('Valor da recarga (R$)' if by_value else 'Tempo de recarga (minutos)', field, 10,
                           strong=False),
            title='Defina como será sua recarga', on_back=app.back, steps=4, step=2,
            footer=_footer(design.primary_button('Próximo Passo', app.action(next_step), height=55, size=16,
                                                weight='bold')), **wizard)

    if step == 4:
        options = rules.power_options(group)

        def choose_power(key):
            async def handler(event=None):
                state['power'] = key
                await app.go('booking', step=4, station_id=station_id)
            return handler
        cards = [_option(f'Até {rules.fmt_number(options[key][0])} kW', options[key][1],
                                     selected=state['power'] == key, on_click=choose_power(key),
                                     icon=ft.Icons.OFFLINE_BOLT_OUTLINED) for key in ('max', 'reduced')]
        return _page(*cards, title='Potência e Velocidade', on_back=app.back, steps=4, step=3,
                           footer=_footer(design.primary_button('Continuar', nav(5), height=55, size=16,
                                                                weight='bold')), **wizard)

    balance = wallet.balance(app)
    if step == 5:
        def choose_pay(key):
            async def handler(event=None):
                state['pay'] = key
                await app.go('booking', step=5, station_id=station_id)
            return handler
        cards = [_option(PAY_LABELS[key], rules.money(balance) if key == 'balance' else None,
                                     selected=state['pay'] == key, on_click=choose_pay(key), icon=PAY_ICONS[key])
                 for key in ('balance', 'pix', 'card')]

        async def pay_next():
            if state['pay'] == 'balance' and balance < rules.total(quote()['cost'], reserving):
                raise failing('Saldo insuficiente para esta recarga. Escolha Pix ou cartão.')
            await app.go('booking', step=6, station_id=station_id)
        return _page(*cards, title='Método de Pagamento', on_back=app.back, steps=4, step=4,
                           footer=_footer(design.primary_button('Continuar', app.action(pay_next), height=55, size=16,
                                                                weight='bold')), **wizard)

    estimate = quote()
    amount = rules.total(estimate['cost'], reserving)
    connector = next((p for p in group['connectors'] if p.get('id') == state['connector_id']),
                     (group['free'] or group['connectors'])[0])

    async def finish():
        """Confirma a recarga: reserva pela API (Reservar) ou entrega ao fluxo de início (Agora)."""
        if state['pay'] == 'balance' and wallet.balance(app) < amount:
            raise failing('Saldo insuficiente para esta recarga.')
        description = f"Recarga {station.get('name', '')}".strip()
        if reserving:
            state['key'] = state['key'] or app.api.new_key()
            reservation = await app.api.request('POST', 'reservations', {'connector_id': connector['id']},
                                                key=state['key'])
            state['key'] = None
            if state['pay'] == 'balance':
                wallet.debit(app, amount, description)
            state['result'] = {'id': reservation['id'], 'arrival': f"Hoje - {state['slot']}",
                               'code': rules.reservation_code(reservation['id']), 'paid': str(amount),
                               'pay': state['pay'], 'station': station.get('name', '')}
            state['done'] = True
            await app.go('booking', step=8, station_id=station_id)
            return
        if state['pay'] == 'balance':
            wallet.debit(app, amount, description)
        state['done'] = True
        limit = int(connector.get('max_duration_minutes') or 1440)
        await app.go('charging', public_code=connector.get('public_code') or '',
                     point_context=point_context(station, connector),
                     max_duration=max(1, min(estimate['minutes'] or 30, limit)))

    if step == 6:
        def row(title, subtitle, icon, target):
            return design.list_row(title, subtitle, on_click=nav(target), icon=icon, tile=42, selected=True)
        if state['by'] == 'value':
            detail = f"{rules.money(estimate['cost'])} | {estimate['minutes']} minutos"
        else:
            detail = f"{estimate['minutes']} minutos"
        when = f"Horário: {state['slot']}" if reserving else f'Tolerância: {rules.TOLERANCE_MINUTES} min'
        kind = 'Por valor' if state['by'] == 'value' else 'Por tempo'
        power_value, power_note = rules.power_options(group)[state['power']]
        pay_sub = rules.money(balance) if state['pay'] == 'balance' else None
        first = ft.Container(ft.Column([_section('Recarga'),
                                        row(f"{kind} | {'Reservar' if reserving else 'Agora'}", f'{detail} | {when}',
                                            ft.Icons.ACCESS_TIME, 2)], spacing=12),
                             margin=ft.Margin(left=0, top=15, right=0, bottom=0))
        second = ft.Column([_section('Método de Pagamento'),
                            row(PAY_LABELS[state['pay']], pay_sub, PAY_ICONS[state['pay']], 5)], spacing=12)
        third = ft.Column([_section('Potência e Velocidade'),
                           row(f'Até {rules.fmt_number(power_value)} kW', power_note, ft.Icons.OFFLINE_BOLT_OUTLINED,
                               4)], spacing=12)
        place = ft.Column([design.txt(f"Estação: {station.get('name', '')}", 13, 'bold'),
                           design.txt(station.get('address') or '', 11, 'regular', theme.GRAY_TEXT)], spacing=4)
        heading = [design.txt('Total', 15, 'bold')]
        if reserving:
            heading += [ft.Container(expand=True),
                        design.txt(f'Inclui taxa de reserva de {rules.money(rules.RESERVATION_FEE)}', 10, 'regular',
                                   theme.GRAY_TEXT)]
        total_block = ft.Column([ft.Row(heading, vertical_alignment=ft.CrossAxisAlignment.END),
                                 design.txt(rules.money(amount), 27, 'bold')], spacing=2)

        async def confirm():
            if state['pay'] == 'balance':
                await finish()
            else:
                await app.go('booking', step=7, station_id=station_id)
        return _page(first, second, third, place, total_block, title='Revisar Dados', on_back=app.back,
                           steps=1, step=1, gap=29,
                           footer=[ft.Container(design.primary_button('Confirmar Recarga', app.action(confirm), height=55,
                                                                   size=16, weight='bold'),
                                              margin=ft.Margin(left=0, top=0, right=0, bottom=4))], gutter=3)

    if step == 7:
        async def copy_code():
            await ft.Clipboard().set(PIX_CODE)
            app.notice('Código Pix copiado (demonstração).')
        if state['pay'] == 'card':
            fields = {name: design.labeled_input(label, '', hint, keyboard=ft.KeyboardType.NUMBER
                                                 if name in ('number', 'valid', 'cvv') else None,
                                                 password=name == 'cvv')
                      for name, label, hint in (('number', 'Número do cartão', '0000 0000 0000 0000'),
                                                ('name', 'Nome impresso', 'Nome no cartão'),
                                                ('valid', 'Validade', 'MM/AA'), ('cvv', 'CVV', '•••'))}

            async def pay_card():
                # Os campos são apenas ilustrativos: valores nunca são guardados nem enviados.
                if not all((item.controls[1].value or '').strip() for item in fields.values()):
                    raise failing('Preencha os dados do cartão (demonstração: nada é enviado ou guardado).')
                for item in fields.values():
                    item.controls[1].value = ''
                await finish()
            for item in fields.values():
                item.controls[1].can_reveal_password = False
            body = [ft.Container(height=15), fields['number'], fields['name'], ft.Row([ft.Container(fields['valid'], expand=True),
                                                              ft.Container(fields['cvv'], expand=True)], spacing=16)]
            footer = [_secure_note(), design.primary_button('Efetuar Pagamento', app.action(pay_card), height=55,
                                                            size=16, weight='bold')]
        else:
            plate = ft.Container(
                ft.Image(src=design.QR_SRC, width=238, height=238, fit=ft.BoxFit.CONTAIN,
                         exclude_from_semantics=True),
                width=262, height=262, bgcolor='#FFFFFF', border_radius=18, alignment=ft.Alignment(0, 0))
            body = [ft.Container(plate, alignment=ft.Alignment(0, 0), margin=ft.Margin(left=0, top=49, right=0,
                                                                                         bottom=0)),
                ft.Column([design.txt(rules.money(amount).replace('R$', 'R$ '), 26, 'bold'),
                           design.txt('Expira em 14:59', 11, 'bold')], spacing=2,
                          horizontal_alignment=ft.CrossAxisAlignment.CENTER)]
            footer = [_secure_note(), ft.Container(
                          ft.Row([ft.Icon(ft.Icons.CONTENT_COPY, size=13, color=theme.BTN_SECONDARY_FG),
                                  design.txt('Copiar código Pix', 12.5, 'bold', theme.BTN_SECONDARY_FG)], spacing=8,
                                 alignment=ft.MainAxisAlignment.CENTER),
                          height=45, bgcolor=theme.BTN_SECONDARY, border_radius=design.RADIUS_BTN,
                          on_click=app.action(copy_code), ink=True),
                      design.primary_button('Já paguei (Confirmar)', app.action(finish), height=55, size=16,
                                            weight='bold')]
        footer[-1] = ft.Container(footer[-1], margin=ft.Margin(left=0, top=0, right=0, bottom=8))
        return _page(*body, title='Efetuar Pagamento', on_back=app.back, steps=1, step=1, footer=footer,
                           gutter=3, gap=14 if state['pay'] == 'card' else 20)

    # ------------------------------------------------------------------ 8: confirmada
    result = state.get('result') or {'id': 'demo', 'arrival': f"Hoje - {state['slot']}",
                                     'code': rules.reservation_code(connector['id']),
                                     'station': station.get('name', ''), 'pay': state['pay'], 'paid': str(amount)}

    async def cancel():
        if result['id'] != 'demo':
            await app.api.request('POST', f"reservations/{result['id']}/cancel")
            if result['pay'] == 'balance':
                wallet.credit(app, result['paid'], f"Estorno de reserva {result['station']}".strip())
        app.planning_intent = None
        state['result'] = None
        await app.go('stations')

    def info(name, value):
        return ft.Row([design.txt(name, 13.5, 'regular', theme.GRAY_TEXT, expand=True),
                       design.txt(value, 13.5, 'bold')])
    check = ft.Container(ft.Icon(ft.Icons.CHECK, size=96, color='#FFFFFF'), width=167, height=167, border_radius=84,
                         bgcolor='#3EBF80', alignment=ft.Alignment(0, 0))
    inset = ft.Margin(left=6, top=0, right=6, bottom=0)
    return _page(
        ft.Container(check, alignment=ft.Alignment(0, 0), margin=ft.Margin(left=0, top=52, right=0, bottom=0)),
        ft.Container(ft.Column([info('Estação', result['station']), info('Chegada', result['arrival']),
                                info('Código', result['code'])], spacing=22),
                     padding=ft.Padding(left=16, right=0, top=82, bottom=0)),
        title='Reserva confirmada', steps=None,
        footer=[ft.Container(design.secondary_button('Ver Minhas Recargas', app.link('reservations'), height=46,
                                                       size=14.5), margin=inset),
                ft.Container(design.primary_button('Cancelar Recarga', app.action(cancel), height=46, size=14.5),
                             margin=ft.Margin(left=6, top=4, right=6, bottom=50))],
        gutter=0, gap=16)
