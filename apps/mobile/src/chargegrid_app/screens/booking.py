"""Assistente de recarga do consumidor (rota ``booking``).

Dois fluxos, escolhidos na tela do posto (``kind``):
  * ``reserve`` (Reservar estação): 1 conector · 2 reserva (15 min + taxa) · 3 cobrança · 4 potência ·
    5 pagamento · 6 revisar · 7 aguardando pagamento (Stripe) · 8 reserva confirmada (o prazo de 15 min
    corre a partir da confirmação do posto; ao chegar, "Cheguei: informar código" inicia a recarga);
  * ``now`` (Carregar agora): 1 conector · 3 cobrança · 4 potência · 5 pagamento · 6 revisar · 7 aguardando
    pagamento (Stripe), e então o início no ponto com o código #F (sem etapa de reserva nem taxa).
Parâmetros de rota: ``step``, ``station_id``, ``connector_id`` e, para abrir uma etapa já preenchida
(captura/atalhos): ``kind`` (reserve|now), ``by`` (time|value|autonomy), ``amount``, ``power`` (max|reduced),
``pay`` (balance|stripe; ``pix``/``card`` antigos viram ``stripe``), ``slot``. O estado das escolhas fica
em ``app.booking`` (memória).

"Reservar" cria a reserva pela API (``POST reservations`` com chave de idempotência); "Agora" entrega
para o fluxo de início de recarga (``charging``), onde o código de presença #F continua obrigatório.

Pagamento: "Cartão ou Pix · Stripe (teste)" quando ``GET payments/config`` diz ``enabled`` — o app cria o
pagamento (``POST payments``, teto calculado pela API), abre a página hospedada da Stripe no navegador e
consulta o estado a cada 2 s; só com o pagamento confirmado pelo servidor segue (o ``payment_id`` vai no
início da recarga). Nenhum dado de cartão é lido, guardado ou enviado pelo app. "Saldo" (simulado,
``services.wallet``) fica na conta demo, ou como única opção quando a API não tem pagamento.

"Por autonomia": o motorista pede N km; a energia sai do carro do perfil (consumo) e é limitada ao espaço
livre da bateria (SoC escondido de ``services.vehicle_state``, nunca exibido aqui). Todo pagamento feito
aqui fica registrado em ``services.prepaid``: a sobra (ex.: bateria cheia) volta como crédito no saldo.
"""

import flet as ft
import flet.canvas as cv

from ..api_client import ApiError
from ..services import booking as rules
from ..services import payments, prepaid, vehicle_state, wallet
from ..ui import design, theme
from ..ui.point_summary import point_context

AMBER_BG = '#4E3F24'
AMBER = '#E8922B'
PAY_LABELS = {'balance': 'Saldo Disponível', 'stripe': payments.METHOD_LABEL}
PAY_ICONS = {'balance': ft.Icons.WALLET, 'stripe': ft.Icons.CREDIT_CARD}
STRIPE_SUBTITLE = 'Página segura da Stripe · ambiente de teste'
POLL_SECONDS = 2
LAST_STEP = 8


def _state(app, station_id, keep_done=False):
    state = getattr(app, 'booking', None)
    if not isinstance(state, dict) or state.get('station_id') != station_id or (state.get('done') and not keep_done):
        state = {'station_id': station_id, 'mode': 'reserve', 'by': 'time', 'power': 'max', 'pay': 'balance',
                 'minutes_text': '', 'value_text': '', 'km_text': '', 'car': None, 'group': None, 'connector_id': None, 'slot': None,
                 'key': None, 'result': None, 'done': False}
        app.booking = state
    return state


def _apply_presets(state, group_keys, presets):
    for name in ('kind', 'by', 'power', 'pay', 'slot'):
        if presets.get(name) is not None:
            value = str(presets[name])
            state['mode' if name == 'kind' else name] = None if value == 'none' else value
    if presets.get('amount') is not None:
        state[_amount_key(state['by'])] = str(presets['amount'])


def _amount_key(by):
    return {'value': 'value_text', 'autonomy': 'km_text'}.get(by, 'minutes_text')


KIND_LABELS = {'time': 'Por tempo', 'value': 'Por valor', 'autonomy': 'Por autonomia'}


def _info_box(text, icon=ft.Icons.INFO_OUTLINE, width=None):
    return ft.Container(
        ft.Row([ft.Icon(icon, size=20, color=theme.TEXT_COLOR), design.txt(text, 12.2, 'regular')], spacing=8,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.CARD, border_radius=design.RADIUS_BTN + 2, height=42, width=width,
        padding=ft.Padding(left=13, right=13, top=0, bottom=0), alignment=ft.Alignment(-1, 0))


def _fee_box(free=False):
    """Taxa de reserva (simulada). ``free``: só há pagamento Stripe (teste), que cobra apenas a energia."""
    return ft.Container(
        ft.Row([ft.Icon(ft.Icons.INFO_OUTLINE, size=20, color=AMBER),
                ft.Text(spans=[ft.TextSpan('Taxa de reserva: ', ft.TextStyle(font_family=design.FONT, size=11.6)),
                               ft.TextSpan('sem cobrança no pagamento de teste' if free else
                                           rules.money(rules.RESERVATION_FEE),
                                           ft.TextStyle(font_family=design.FONT_BOLD, size=11.6))],
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
    field.hint_style = ft.TextStyle(color='#000000', size=13, font_family=design.FONT)
    field.text_style = ft.TextStyle(size=13, font_family=design.FONT, color='#000000')
    return field


def _option(title, subtitle, *, selected, on_click, icon=None, chevron=False):
    """Cartão de opção com seletor circular (conector, potência, pagamento) ou seta (revisão)."""
    if chevron:
        trailing = ft.Container(ft.Icon(ft.Icons.ARROW_FORWARD_IOS, size=12, color=theme.TEXT_COLOR), width=22,
                                alignment=ft.Alignment(0, 0))
        selected = True
    else:
        trailing = ft.Container(width=14, height=14, border_radius=7, bgcolor=theme.BTN_PRIMARY if selected else None,
                                border=None if selected else ft.Border.all(1.5, theme.TEXT_COLOR))
    texts = [design.txt(title, 12.6, 'bold')]
    if subtitle:
        texts.append(design.txt(subtitle, 9.6, 'regular', theme.GRAY_TEXT))
    return ft.Container(
        ft.Row([design.icon_tile(icon, size=42), ft.Column(texts, spacing=4, expand=True,
                                                          alignment=ft.MainAxisAlignment.CENTER), trailing],
               spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        padding=ft.Padding(left=9.8, right=14 if chevron else 17.8, top=10.3, bottom=10.3),
        border_radius=design.RADIUS_CARD, bgcolor=theme.CARD,
        border=ft.Border.all(1.2, '#FFFFFF' if selected else theme.CARD), on_click=on_click, ink=bool(on_click))


def _chip(text, selected, on_click):
    return ft.Container(
        design.txt(text, 10.6, 'bold' if selected else 'medium', theme.BTN_PRIMARY_FG if selected else '#6F6F6F',
                   text_align=ft.TextAlign.CENTER),
        height=51, alignment=ft.Alignment(0, 0), expand=True, border_radius=design.RADIUS_BTN,
        bgcolor=theme.BTN_PRIMARY if selected else '#262626', on_click=on_click, ink=bool(on_click))


def _footer(button):
    """Só o botão; o aviso de potência variável foi retirado do fluxo de reserva/recarga."""
    return [button]


def _bar(total, current, inset=0):
    """Barra de etapas da referência: só o segmento da etapa atual fica aceso."""
    return ft.Container(
        ft.Row([ft.Container(height=3, expand=True, border_radius=2,
                             bgcolor=theme.BTN_PRIMARY if index + 1 == current else theme.SEGMENT_OFF)
                for index in range(total)], spacing=6),
        padding=ft.Padding(left=0, right=inset, top=0, bottom=0))


def _replace_bar(control, total, current, inset=0):
    content = getattr(control, 'content', None)
    if isinstance(control, ft.Container) and isinstance(content, ft.Row) and content.controls and all(
            getattr(item, 'height', None) == 3 for item in content.controls):
        control.content = _bar(total, current, inset).content
        control.padding = _bar(total, current, inset).padding
        return True
    if content is not None and not isinstance(content, str) and _replace_bar(content, total, current, inset):
        return True
    return any(_replace_bar(child, total, current, inset) for child in getattr(control, 'controls', None) or [])


# A referência desloca levemente as margens laterais de uma etapa para outra; reproduzimos por etapa.
# (esquerda_px, direita_px_dos_cartões, recuo_da_barra_pt, recuo_do_rodapé_pt, x_do_título_px, base_do_botão_px)
# em 804 px de largura (1503 = posição padrão do botão principal, 9 pt acima do rodapé do kit).
EDGES = {
    'c1': (46, 754, 4, 4, 90, 1503), 'c2r': (46, 764, 9, 9, 96, 1489), 'c2n': (55, 755, 0, 0, 105, 1493),
    'c3t': (46, 764, 9, 9, 96, 1505), 'c3v': (54, 754, 0, 0, 104, 1505), 'c4': (51, 759, 4, 4, 107, 1509),
    'c5': (51, 759, 4, 4, 106, 1507), 'c6': (50, 758, 0, 4, 104, 1509), 'c7p': (52, 752, 0, 0, 102, 1505),
    'c7c': (48, 756, 0, 4, 98, 1500),
}


def _title(text, on_back, left, title_x):
    """Linha de título da referência: «<» fino a 13 px da margem e o texto a ``title_x`` px (varia por etapa)."""
    chevron = ft.Container(ft.Icon(ft.Icons.ARROW_BACK_IOS_NEW, size=11, color=theme.TEXT_COLOR),
                           width=(title_x - left) / 2, height=34, alignment=ft.Alignment(-1, 0),
                           padding=ft.Padding(left=5.5, right=0, top=0, bottom=0), on_click=on_back, ink=False)
    return ft.Row([chevron, design.txt(text, 17.6, 'bold', expand=True)], spacing=0,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER)


def _toggle(options, value, on_change):
    """Alternância Por tempo/Por valor da referência: borda #414141, selecionado branco, fundo da página."""
    def make(option):
        key, text = option
        active = key == value

        async def click(event, key=key):
            result = on_change(key)
            if hasattr(result, '__await__'):
                await result
        return ft.Container(design.txt(text, 12, 'bold' if active else 'regular',
                                       theme.BTN_PRIMARY_FG if active else theme.TEXT_COLOR,
                                       text_align=ft.TextAlign.CENTER),
                            expand=True, alignment=ft.Alignment(0, 0), on_click=click,
                            bgcolor=theme.BTN_PRIMARY if active else None)
    return ft.Container(ft.Row([make(option) for option in options], spacing=0), height=37.5, border_radius=4,
                        border=ft.Border.all(1, '#414141'), clip_behavior=ft.ClipBehavior.ANTI_ALIAS)


def _page(*controls, steps=None, step=None, edge=None, **kwargs):
    title = None
    if edge:
        left, right, bar_inset, foot_inset, title_x, btn_bottom = EDGES[edge]
        kwargs['gutter'] = 1
        title = kwargs.pop('title', None)
        on_back = kwargs.pop('on_back', None)
        foot = kwargs.get('footer')
        if foot:
            foot = list(foot) if isinstance(foot, (list, tuple)) else [foot]
            lift = 9 + (1503 - btn_bottom) / 2
            kwargs['footer'] = [ft.Container(item, margin=ft.Margin(left=0, top=0, right=foot_inset,
                                                                    bottom=lift if last else 0))
                                for last, item in ((index == len(foot) - 1, item) for index, item in enumerate(foot))]
    column = design.page(*controls, steps=steps, step=step, **kwargs)
    if edge:
        column.controls[0].padding = ft.Padding(left=left / 2 - 20, right=(804 - right) / 2 - 20, top=0, bottom=0)
    if steps:
        _replace_bar(column, steps, step, bar_inset if edge else 0)
        inner = column.controls[0].content if edge else column
        inner.controls[0].margin = ft.Margin(left=0, top=4.5, right=0, bottom=0)  # barra 1 pt mais baixa (referência)
        if edge and title:
            inner.controls.insert(1, _title(title, on_back, left, title_x))
    return column


def _section(text):
    return design.txt(text, 13, 'bold')


def _secure_note(text='Pagamento seguro e criptografado'):
    return ft.Row([ft.Icon(ft.Icons.VERIFIED_USER_OUTLINED, size=15, color=theme.SUCCESS),
                   design.txt(text, 11.5, 'regular', theme.GRAY_TEXT, expand=True)], spacing=14)


def pay_options(demo, stripe_enabled):
    """Formas de pagamento da etapa 5: Saldo (simulado) só na demo ou sem Stripe na API."""
    if demo:
        return ['balance', 'stripe'] if stripe_enabled else ['balance']
    return ['stripe'] if stripe_enabled else ['balance']


def overstay_terms(station):
    """Termos da taxa de permanência do posto (``station.overstay``) ou ``None`` (desligada/API antiga)."""
    terms = (station or {}).get('overstay')
    if isinstance(terms, dict) and terms.get('enabled') and terms.get('summary'):
        return terms
    return None


def overstay_box(terms):
    """Aviso da revisão: o texto pronto da API (ex.: "Após a recarga: 10 min de tolerância, ...")."""
    return ft.Container(
        ft.Row([ft.Icon(ft.Icons.TIMER_OUTLINED, size=20, color=AMBER),
                ft.Column([design.txt('Taxa de permanência', 12.4, 'bold'),
                           design.txt(str(terms['summary']), 11.6, 'regular', theme.GRAY_TEXT)],
                          spacing=2, expand=True)],
               spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.CARD, border_radius=design.RADIUS_BTN + 2, data='overstay-terms',
        padding=ft.Padding(left=13, right=13, top=10, bottom=10))


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
        if presets.get('pick'):  # captura: já abre com o primeiro grupo de conectores marcado
            state['group'] = groups[0]['key']
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
    if presets.get('kind') in ('reserve', 'now'):
        state['mode'] = presets['kind']  # o botão da tela do posto define o fluxo
    reserving = state['mode'] != 'now'
    if step == 2 and not reserving:
        step = 1  # "Carregar agora" não tem etapa de reserva (voltar da cobrança leva ao conector)
    # Limite geral do motorista: potência máxima do carro do perfil (DC/AC) ∩ efetivo do conector.
    car_power = vehicle_state.car_specs(await vehicle_state.vehicle(app)) if step >= 3 and group else None
    if state['by'] == 'autonomy' and step >= 3:
        # Carro + SoC escondido (no modo apresentação, a bateria do celular) para converter km em energia.
        state['car'] = await vehicle_state.snapshot(app)

    def nav(target):
        async def handler(event=None):
            await app.go('booking', step=target, station_id=station_id)
        return handler

    def autonomy():
        car = state['car'] or {'consumption': 14.0, 'usable_kwh': 44.9, 'soc': vehicle_state.SOC_MIN}
        return rules.autonomy_energy(rules.parse_km(state['km_text'] or '0'), car['consumption'], car['soc'],
                                     car['usable_kwh'])

    def quote():
        power = rules.power_options(group, car_power)[state['power'] or 'max'][0]
        if state['by'] == 'autonomy':
            result = autonomy()
            if result['energy_kwh'] <= 0:
                raise ValueError(rules.autonomy_note(result))
            return {**rules.estimate(power, group['price'], energy=result['energy_kwh']), 'autonomy': result}
        if state['by'] == 'value':
            return rules.estimate(power, group['price'], value=rules.parse_value(state['value_text'] or '0'))
        return rules.estimate(power, group['price'], minutes=rules.parse_minutes(state['minutes_text'] or '0'))

    def safe_quote():
        try:
            return quote()
        except (ValueError, ArithmeticError):
            return None

    if step > 3 and safe_quote() is None:
        state['minutes_text'] = state['minutes_text'] or '30'
        if state['by'] == 'value' and not state['value_text']:
            state['value_text'] = '50,00'
        if state['by'] == 'autonomy' and not state['km_text']:
            state['km_text'] = '100'
        if safe_quote() is None:  # ex.: bateria já cheia no modo autonomia
            state['by'] = 'time'

    demo = getattr(app.api, 'is_demo', False) is True
    stripe_config = await payments.config(app) if step >= 2 else {}
    options = pay_options(demo, stripe_config.get('enabled') is True)
    if state['pay'] in ('pix', 'card'):  # atalhos antigos: o formulário falso de cartão/Pix saiu
        state['pay'] = 'stripe'
    if state['pay'] is not None and state['pay'] not in options:
        state['pay'] = options[0]
    if step > 5 and not state['pay']:
        state['pay'] = options[0]
    stripe_only = options == ['stripe']

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
            await app.go('booking', step=2 if reserving else 3, station_id=station_id)
        button = (design.primary_button('Continuar', app.action(go_on), height=55, size=16, weight='bold')
                  if ready else ft.Container(design.txt('Continuar', 16, 'bold', '#6C6C6C', text_align=ft.TextAlign.CENTER), height=55,
                                        bgcolor='#1C1C1C', border_radius=design.RADIUS_BTN,
                                        alignment=ft.Alignment(0, 0)))
        demand = station.get('demand') or {}
        if str(demand.get('multiplier') or '1.00') != '1.00':
            # Tarifa dinâmica (calculada pela API): o motorista vê antes de escolher, como num app de corrida.
            label = str(demand['multiplier']).rstrip('0').rstrip('.').replace('.', ',')
            cards.insert(0, ft.Container(
                ft.Row([ft.Icon(ft.Icons.TRENDING_UP, size=20, color=theme.TEXT_COLOR),
                        design.txt(f"Demanda {demand.get('level_label', 'alta').lower()} agora: tarifa {label}× a base. "
                                   'O preço fica travado ao reservar ou iniciar.', 12, 'regular', expand=True)],
                       spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                bgcolor=theme.CARD, border_radius=design.RADIUS_BTN + 2, data='demand-note',
                padding=ft.Padding(left=13, right=13, top=10, bottom=10)))
        return _page(*cards, title='Qual conector deseja reservar?' if reserving else 'Qual conector deseja usar?',
                     on_back=app.back, steps=4, step=1, edge='c1',
                           footer=_footer(button), **wizard)

    if step == 2:
        # Só "Reservar estação": o ponto fica guardado por 15 min a partir da confirmação do posto.
        hold = design.card_box(ft.Column([
            ft.Row([ft.Icon(ft.Icons.TIMER_OUTLINED, size=22, color=theme.TEXT_COLOR),
                    design.txt(f'Ponto reservado por {rules.TOLERANCE_MINUTES} minutos', 15, 'bold', expand=True)],
                   spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            design.txt('O prazo começa quando o posto confirma a reserva. Chegando, toque em "Cheguei" e informe o '
                       'código #F da tela do equipamento. Se não chegar a tempo, a reserva expira.', 12, 'regular',
                       theme.GRAY_TEXT)], spacing=10), padding=ft.Padding(left=15, right=15, top=15, bottom=16))
        body = [ft.Container(height=4), hold, ft.Container(height=6), _fee_box(free=stripe_only)]
        return _page(*body, title='Reservar estação', on_back=app.back, steps=4, step=2, edge='c2r',
                     footer=_footer(design.primary_button('Continuar', nav(3), height=55, size=16, weight='bold')),
                     **wizard)

    if step == 3:
        by_value = state['by'] == 'value'
        by_km = state['by'] == 'autonomy'

        def set_by(key):
            state['by'] = key
            return app.go('booking', step=3, station_id=station_id)
        toggle = _toggle(list(KIND_LABELS.items()), state['by'], set_by)
        key = _amount_key(state['by'])
        note = design.txt('', 11, 'regular', theme.GRAY_TEXT, visible=False)

        def refresh_note():
            try:
                text = rules.autonomy_note(autonomy()) if by_km else None
            except (ValueError, ArithmeticError):
                text = None
            note.value, note.visible = text or '', bool(text)

        def changed(event):
            state[key] = event.control.value or ''
            if by_km:
                refresh_note()
                app.page.update()
        hint = 'Exemplo: 249,90' if by_value else 'Exemplo: 120' if by_km else 'Exemplo: 30'
        field = _white_field(hint, state[key], changed)
        refresh_note()
        label = ('Valor da recarga (R$)' if by_value else 'Autonomia desejada (km)' if by_km
                 else 'Tempo de recarga (minutos)')

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
            ft.Container(height=4), ft.Container(toggle, margin=ft.Margin(left=0, top=0, right=0 if by_value else 9,
                                                                           bottom=0)),
            ft.Column([design.txt(label, 10.4), field, *([note] if by_km else [])], spacing=15,
                      horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            title='Defina como será sua recarga', on_back=app.back, steps=4, step=2,
            edge='c3v' if by_value else 'c3t', footer=_footer(design.primary_button('Próximo Passo', app.action(next_step), height=55, size=16,
                                                weight='bold')), **wizard)

    if step == 4:
        options = rules.power_options(group, car_power)

        def choose_power(key):
            async def handler(event=None):
                state['power'] = key
                await app.go('booking', step=4, station_id=station_id)
            return handler
        cards = [_option(rules.power_title(group, key, car_power), options[key][1],
                                     selected=state['power'] == key, on_click=choose_power(key),
                                     icon=ft.Icons.OFFLINE_BOLT_OUTLINED) for key in ('max', 'reduced')]
        return _page(*cards, title='Potência e Velocidade', on_back=app.back, steps=4, step=3, edge='c4',
                           footer=_footer(design.primary_button('Continuar', nav(5), height=55, size=16,
                                                                weight='bold')), **wizard)

    balance = wallet.balance(app)
    if step == 5:
        def choose_pay(key):
            async def handler(event=None):
                state['pay'] = key
                await app.go('booking', step=5, station_id=station_id)
            return handler
        cards = [_option(PAY_LABELS[key], rules.money(balance) if key == 'balance' else STRIPE_SUBTITLE,
                                     selected=state['pay'] == key, on_click=choose_pay(key), icon=PAY_ICONS[key])
                 for key in options]

        async def pay_next():
            if not state['pay']:
                raise failing('Escolha uma forma de pagamento para continuar.')
            if state['pay'] == 'balance' and balance < rules.total(quote()['cost'], reserving):
                raise failing('Saldo insuficiente para esta recarga. Escolha Pix ou cartão.')
            await app.go('booking', step=6, station_id=station_id)
        return _page(*cards, title='Método de Pagamento', on_back=app.back, steps=4, step=4, edge='c5',
                           footer=_footer(design.primary_button('Continuar', app.action(pay_next), height=55, size=16,
                                                                weight='bold')), **wizard)

    estimate = quote()
    stripe = state['pay'] == 'stripe'
    # Stripe (teste): a taxa de reserva simulada não é cobrada; o valor final é o teto calculado pela API.
    amount = estimate['cost'] if stripe else rules.total(estimate['cost'], reserving)
    connector = next((p for p in group['connectors'] if p.get('id') == state['connector_id']),
                     (group['free'] or group['connectors'])[0])
    overstay = overstay_terms(station)

    def charging_intent():
        if state['by'] == 'autonomy':
            intent = {'mode': 'autonomy', 'km': rules.parse_km(state['km_text'])}
        elif state['by'] == 'value':
            intent = {'mode': 'value', 'max_cost': str(estimate['cost'])}
        else:
            intent = {'mode': 'time', 'minutes': max(1, estimate['minutes'] or 30)}
        # Potência escolhida (conector efetivo ∩ carro ∩ opção): a API aplica no início da recarga.
        intent['max_power_kw'] = str(rules.power_options(group, car_power)[state['power'] or 'max'][0])
        return intent

    async def finish(payment=None):
        """Confirma a recarga: reserva pela API (Reservar) ou entrega ao fluxo de início (Agora).

        ``payment``: pagamento Stripe (teste) já confirmado pelo servidor; o ``payment_id`` segue no início.
        """
        if not payment and state['pay'] == 'balance' and wallet.balance(app) < amount:
            raise failing('Saldo insuficiente para esta recarga.')
        description = f"Recarga {station.get('name', '')}".strip()
        intent = charging_intent()
        if payment:
            intent.update(payment_id=payment['id'], payment_amount=str(payment.get('amount') or ''))
        if overstay and overstay.get('version'):
            # Termos mostrados na revisão: a API recusa (409) se o dono mudou a taxa depois.
            intent['overstay_terms_version'] = overstay['version']
        paid_amount = payment.get('amount') if payment else amount
        paid = dict(amount=amount, energy_amount=estimate['cost'], method=state['pay'], station_id=station_id,
                    station_name=station.get('name', ''), connector_id=connector['id'])
        if reserving:
            state['key'] = state['key'] or app.api.new_key()
            reservation = await app.api.request('POST', 'reservations', {'connector_id': connector['id']},
                                                key=state['key'])
            state['key'] = None
            if not payment:
                if state['pay'] == 'balance':
                    wallet.debit(app, amount, description)
                prepaid.record(app, **paid, reservation_id=reservation['id'])
            # Ao chegar e iniciar com esta reserva, o assistente #F já abre com os mesmos limites.
            app.planning_intent = {'connector_id': connector['id'], 'intent': intent}
            state['result'] = {'id': reservation['id'], 'arrival': f'Em até {rules.TOLERANCE_MINUTES} min',
                               'code': rules.reservation_code(reservation['id']), 'paid': str(paid_amount),
                               'pay': state['pay'], 'station': station.get('name', ''),
                               'payment_id': payment['id'] if payment else None}
            state['payment'] = None
            state['done'] = True
            await app.go('booking', step=8, station_id=station_id)
            return
        if not payment:
            if state['pay'] == 'balance':
                wallet.debit(app, amount, description)
            prepaid.record(app, **paid)
        state['payment'] = None
        state['done'] = True
        limit = int(connector.get('max_duration_minutes') or 1440)
        await app.go('charging', public_code=connector.get('public_code') or '',
                     point_context=point_context(station, connector),
                     max_duration=max(1, min(estimate['minutes'] or 30, limit)), planning_intent=intent)

    async def open_payment(fresh=False):
        """Cria o pagamento na API (teto calculado lá) e abre a etapa 7.

        O mesmo pedido repete a mesma ``Idempotency-Key`` (uma resposta perdida não cria dois pagamentos);
        ``fresh`` (tentar de novo depois de expirar/cancelar) usa uma chave nova.
        """
        body = payments.request_body(connector['id'], charging_intent(), estimate['energy_kwh'])
        if fresh or state.get('pay_body') != body or not state.get('pay_key'):
            app.api.clear_operation('payments')  # o cliente reaproveita a chave do mesmo corpo
            state['pay_key'], state['pay_body'] = app.api.new_key(), body
        payment = await payments.create(app, body, state['pay_key'])
        if payment.get('status') in payments.CLOSED and not fresh:
            await open_payment(fresh=True)  # a chave antiga devolveu um pagamento já encerrado
            return
        state['payment'] = payment
        await app.go('booking', step=7, station_id=station_id)

    if step == 6:
        def row(title, subtitle, icon, target):
            return _option(title, subtitle, selected=True, on_click=nav(target), icon=icon, chevron=True)

        def block(heading, card, gap, top):
            return ft.Container(ft.Column([_section(heading), card], spacing=gap),
                                margin=ft.Margin(left=0, top=top, right=0, bottom=0))
        if state['by'] == 'value':
            detail = f"{rules.money(estimate['cost'])} | {estimate['minutes']} minutos"
        elif state['by'] == 'autonomy':
            detail = f"{estimate['autonomy']['km']} km | {estimate['minutes']} minutos"
        else:
            detail = f"{estimate['minutes']} minutos"
        when = (f'Reservado por {rules.TOLERANCE_MINUTES} min' if reserving else 'Início no ponto com o código #F')
        kind = KIND_LABELS.get(state['by'], 'Por tempo')
        power_note = rules.power_options(group, car_power)[state['power'] or 'max'][1]
        pay_sub = rules.money(balance) if state['pay'] == 'balance' else STRIPE_SUBTITLE
        first = block('Recarga', row(f"{kind} | {'Reservar estação' if reserving else 'Carregar agora'}", f'{detail} | {when}',
                                     ft.Icons.ACCESS_TIME, 3), 11, 18.5)
        second = block('Método de Pagamento', row(PAY_LABELS[state['pay']], pay_sub, PAY_ICONS[state['pay']], 5),
                       14, 36)
        third = block('Potência e Velocidade', row(rules.power_title(group, state['power'] or 'max', car_power), power_note,
                                                   ft.Icons.OFFLINE_BOLT_OUTLINED, 4), 14, 36)
        place = ft.Container(ft.Column([design.txt(f"Estação: {station.get('name', '')}", 13.4, 'bold'),
                                        design.txt(', '.join(str(station.get('address') or '').split(', ')[:2]), 12.4, 'regular',
                                                  theme.GRAY_TEXT, max_lines=1,
                                                  overflow=ft.TextOverflow.ELLIPSIS)],
                                       spacing=1), margin=ft.Margin(left=0, top=31.5, right=0, bottom=0))
        # Sem linha extra de taxa na tela (a taxa de reserva já foi mostrada na etapa 2 e entra no total).
        total_lines = [ft.Container(design.txt('Total estimado' if stripe else 'Total', 17, 'bold'), height=18,
                                    alignment=ft.Alignment(-1, -1)),
                       design.txt(rules.money(amount), 32.5, 'bold')]
        if stripe:
            note = 'Pré-autorização na Stripe (teste): cobramos só a energia confirmada pelo equipamento.'
            if reserving:
                note += ' Sem taxa de reserva no pagamento de teste.'
            total_lines.append(design.txt(note, 11, 'regular', theme.GRAY_TEXT))
        total_block = ft.Container(ft.Column(total_lines, spacing=0),
                                   margin=ft.Margin(left=0, top=25, right=0, bottom=0))
        extra = [ft.Container(overstay_box(overstay), margin=ft.Margin(left=0, top=18, right=0, bottom=0))] \
            if overstay else []

        async def confirm():
            if stripe:
                await open_payment()
            else:
                await finish()
        return _page(first, second, third, place, total_block, *extra, title='Revisar Dados', on_back=app.back,
                     steps=1, step=1, gap=0, edge='c6',
                     footer=[design.primary_button('Confirmar reserva' if reserving else 'Confirmar e iniciar no ponto',
                                                   app.action(confirm), height=55, size=16, weight='bold')])

    if step == 7:
        return _awaiting_payment(app, state, station_id, finish, open_payment, stripe_config, nav)

    # ------------------------------------------------------------------ 8: confirmada
    result = state.get('result') or {'id': 'demo', 'arrival': f'Em até {rules.TOLERANCE_MINUTES} min',
                                     'code': rules.reservation_code(connector['id']),
                                     'station': station.get('name', ''), 'pay': state['pay'], 'paid': str(amount)}

    async def cancel():
        if result['id'] != 'demo':
            await app.api.request('POST', f"reservations/{result['id']}/cancel")
            if result.get('payment_id'):
                # Libera a pré-autorização (cartão) ou devolve o Pix: nada é cobrado (teste).
                try:
                    await payments.cancel(app, result['payment_id'])
                except ApiError:
                    app.notice('Reserva cancelada. O pagamento de teste é liberado no fim do prazo de início.')
            if result['pay'] == 'balance':
                wallet.credit(app, result['paid'], f"Estorno de reserva {result['station']}".strip())
            prepaid.cancel_reservation(app, result['id'])
        app.planning_intent = None
        state['result'] = None
        await app.go('stations')

    def info(name, value):
        return ft.Row([design.txt(name, 11.5, 'regular', theme.GRAY_TEXT, expand=True),
                       design.txt(value, 11.5, 'bold')])
    check = ft.Container(
        ft.Stack([cv.Canvas([
            cv.Line(-41 + 83.5, -1 + 83.5, -9.5 + 83.5, 29 + 83.5, ft.Paint(
                color='#FFFFFF', stroke_width=11, stroke_cap=ft.StrokeCap.ROUND, style=ft.PaintingStyle.STROKE)),
            cv.Line(-9.5 + 83.5, 29 + 83.5, 41 + 83.5, -32 + 83.5, ft.Paint(
                color='#FFFFFF', stroke_width=11, stroke_cap=ft.StrokeCap.ROUND, style=ft.PaintingStyle.STROKE))],
            width=167, height=167)], width=167, height=167),
        width=167, height=167, border_radius=84, bgcolor='#3EBF80', alignment=ft.Alignment(0, 0))
    inset = ft.Margin(left=6, top=0, right=6, bottom=0)

    def action_button(text, on_click, light):
        return ft.Container(design.txt(text, 12.8, 'bold', theme.BTN_PRIMARY_FG if light else theme.TEXT_COLOR,
                                       text_align=ft.TextAlign.CENTER), height=46, alignment=ft.Alignment(0, 0),
                            bgcolor=theme.BTN_PRIMARY if light else '#252525', border_radius=design.RADIUS_BTN,
                            on_click=on_click, ink=True)
    column = _page(
        ft.Container(check, alignment=ft.Alignment(0, 0), margin=ft.Margin(left=0, top=52, right=0, bottom=0)),
        ft.Container(ft.Column([info('Estação', result['station']), info('Chegada', result['arrival']),
                                info('Código', result['code'])], spacing=22),
                     padding=ft.Padding(left=16, right=16.5, top=82.5, bottom=0)),
        title='Reserva confirmada', steps=None,
        footer=[ft.Container(action_button('Ver reserva e prazo', app.link('reservations', detail=True), False),
                             margin=inset),
                ft.Container(action_button('Cancelar Recarga', app.action(cancel), True),
                             margin=ft.Margin(left=6, top=4, right=6, bottom=52))],
        gutter=0, gap=16, title_size=18.5)
    column.controls[0] = ft.Container(column.controls[0], margin=ft.Margin(left=0, top=2.5, right=0, bottom=0))
    return column


# ---------------------------------------------------------------------- 7: aguardando pagamento
AWAIT_TEXTS = {
    'awaiting_payment': 'Aguardando a confirmação da Stripe (teste)…',
    'declined': 'Pagamento recusado. Tente de novo com outro cartão de teste na mesma página.',
    'expired': 'O prazo do pagamento acabou. Nada foi cobrado.',
    'canceled': 'Pagamento cancelado. Nada foi cobrado.',
    'funded': 'Pagamento confirmado (teste). Continuando…',
}


def _awaiting_payment(app, state, station_id, finish, open_payment, config, nav):
    """Etapa 7 com a Stripe: valor, "Abrir pagamento seguro", consulta a cada 2 s e o prazo.

    O app não coleta dados de cartão: o motorista paga na página da Stripe e o servidor confirma.
    Recusado: abre a mesma página de novo. Expirado/cancelado: "Tentar de novo" cria outro pagamento.
    """
    payment = state.get('payment')
    if state.get('pay') != 'stripe' or not payment:
        return _page(design.txt('Revise os dados da recarga para abrir o pagamento.', 13, 'regular', theme.GRAY_TEXT),
                     title='Aguardando pagamento', on_back=app.back,
                     footer=[design.primary_button('Revisar dados', nav(6), height=55, size=16, weight='bold')])
    amount = design.txt(payments.money(payment.get('amount')), 32.5, 'bold', text_align=ft.TextAlign.CENTER)
    status = design.txt('', 12.4, 'semibold', text_align=ft.TextAlign.CENTER)
    countdown = design.txt('', 11.6, 'bold', '#ABABAB', text_align=ft.TextAlign.CENTER)
    test_card = config.get('test_card') or payments.TEST_CARD
    hint = ft.Container(
        ft.Row([ft.Icon(ft.Icons.CREDIT_CARD, size=20, color=theme.TEXT_COLOR),
                ft.Column([design.txt(f'Cartão de teste: {test_card}', 12.2, 'bold'),
                           design.txt('Use qualquer validade futura e qualquer CVC. Ambiente de teste: nenhum valor '
                                      'real é cobrado.', 11, 'regular', theme.GRAY_TEXT)], spacing=2, expand=True)],
               spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.CARD, border_radius=design.RADIUS_BTN + 2, data='test-card-hint',
        padding=ft.Padding(left=13, right=13, top=10, bottom=10))
    explain = design.txt('Pré-autorização do teto. No fim, cobramos só a energia confirmada pelo equipamento e o '
                         'restante é liberado ou devolvido.', 11.4, 'regular', theme.GRAY_TEXT,
                         text_align=ft.TextAlign.CENTER)

    async def open_checkout():
        current = state.get('payment') or {}
        if not await payments.open_checkout(app, current):
            raise ApiError('A página de pagamento não está disponível. Toque em "Tentar de novo".', 409,
                           'checkout_unavailable')

    async def retry():
        await open_payment(fresh=True)

    async def cancel():
        current = state.get('payment') or {}
        if current.get('status') in payments.AWAITING + payments.DECLINED + payments.FUNDED:
            state['payment'] = await payments.cancel(app, current['id'])
        state['payment'] = None
        await app.go('booking', step=6, station_id=station_id)

    open_button = design.primary_button('Abrir pagamento seguro', app.action(open_checkout), height=55, size=16,
                                        weight='bold')
    retry_button = design.primary_button('Tentar de novo', app.action(retry), height=55, size=16, weight='bold')
    cancel_button = design.secondary_button('Cancelar pagamento', app.action(cancel), height=45)

    def render(current):
        code = current.get('status')
        key = 'funded' if code in payments.FUNDED else code
        status.value = AWAIT_TEXTS.get(key, str(current.get('status_label') or ''))
        status.color = theme.ERROR if code in payments.DECLINED + payments.CLOSED else theme.TEXT_COLOR
        left = payments.seconds_left(current) if code in payments.AWAITING + payments.DECLINED else None
        countdown.value = f'Expira em {payments.clock(left)}' if left is not None else ''
        countdown.visible = left is not None
        closed = code in payments.CLOSED
        open_button.visible = not closed and code not in payments.FUNDED
        if code in payments.DECLINED:
            open_button.content.controls[0].value = 'Tentar de novo'
        retry_button.visible = closed
        cancel_button.visible = not closed and code not in payments.FUNDED
    render(payment)

    async def update():
        current = state.get('payment')
        if not current:
            return
        current = await payments.fetch(app, current['id'])
        state['payment'] = current
        if current.get('status') in payments.FUNDED:
            render(current)
            app.page.update()
            try:
                await finish(current)
            except ApiError as exc:
                # Ex.: o ponto ficou indisponível ao reservar. O pagamento segue confirmado (e é liberado no
                # prazo de início); o motorista pode cancelar agora. A próxima consulta tenta de novo.
                status.value, status.color = f'Pagamento confirmado (teste), mas: {exc}', theme.ERROR
                cancel_button.visible = True
                app.page.update()
            return
        render(current)
        app.page.update()
    app.set_poll(update, POLL_SECONDS)
    body = [ft.Container(height=36),
            ft.Container(design.icon_tile(ft.Icons.LOCK_OUTLINE, size=64, icon_size=30), alignment=ft.Alignment(0, 0)),
            ft.Column([amount, status, countdown], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            explain, hint]
    footer = [ft.Container(_secure_note('Pagamento na página segura da Stripe: o app não recebe dados do cartão'),
                           margin=ft.Margin(left=0, top=0, right=0, bottom=3.5)),
              open_button, retry_button, cancel_button]
    return _page(*body, title='Aguardando pagamento', on_back=app.back, steps=1, step=1, footer=footer,
                 edge='c7p', gap=13.5)
