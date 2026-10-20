"""Operação do posto pelo vendedor: Ao vivo, Energia do estabelecimento e Pagamentos (teste).

Páginas de ``station_admin`` (``page`` = 'live' | 'energy' | 'payments'), com os mesmos dados do painel web:

* **Ao vivo** (``GET /owner/live?station_id``, a cada 3 s): status de cada ponto, energia, potência agora e
  a APLICADA pelo equipamento com o motivo (rebalanceamento) e quem ocupa a vaga depois da recarga
  (fase, tolerância restante e taxa acumulada; ``occupancy``), mais os alertas operacionais do posto
  (``GET /owner/alerts``: offline, falha, sem dispositivo, comandos falhos, ponto parado).
* **Energia do estabelecimento** (``GET /stations/{id}/power``, a cada 1,5 s com a página aberta): limite
  contratado (``PUT power-site``), rebalanceamento ao vivo liga/desliga, consumo da loja SIMULADO
  (``PUT building-load``, com debounce), soma dos pontos contra o disponível, alvo/aplicada/estado/motivo
  por ponto e as últimas decisões. API sem a rota (404): a página avisa e o menu do posto não a mostra.
* **Pagamentos (Stripe · teste)**: ``prepay_required`` e ``kiosk_payments`` (``PATCH stations``); o interruptor
  só muda com a resposta do servidor. Sem os campos no posto, a entrada some do menu.

Conta demo: ``demo_site`` responde as mesmas rotas; "Simular carros no posto (demo)" coloca motoristas
fictícios carregando e na vaga.
"""

import flet as ft

from chargegrid_core.formatting import kwh

from ..api_client import ApiError
from ..services import owner_sessions
from ..services import site_power as sp
from ..ui import design, theme
from ..ui.availability import point_status
from ..ui.components import date_time, money
from ..ui.states import status_chip

LIVE_POLL_SECONDS = 3
BAR_BLUE = '#6B9DFF'
PAYMENT_FLAGS = (
    ('prepay_required', 'Exigir pagamento antecipado (Stripe · teste)',
     'O motorista paga um teto antes da recarga começar; no fim, cobra-se só a energia confirmada e o resto '
     'é liberado ou devolvido.', 'Pagamento antecipado exigido', 'Pagamento antecipado desligado'),
    ('kiosk_payments', 'Pagamento pelo QR do painel',
     'O painel físico mostra um QR para pagar sem o app (R$ 10, 20 ou 40) e a recarga começa após a '
     'confirmação.', 'QR de pagamento ligado', 'QR de pagamento desligado'),
)


def _heading(app, text, sid):
    from .station_admin import heading
    return heading(app, text, app.link('station_admin', station_id=sid))


def _hhmm(value):
    stamp = date_time(value)
    return stamp.split(' ')[-1] if ' ' in stamp else '—'


def _demo(app):
    return getattr(app.api, 'is_demo', False) is True


def _pill(text, tone):
    return status_chip(text, tone)


# ---------------------------------------------------------------- menu do posto
def has_energy(station):
    """A API manda as colunas do rebalanceamento no posto (``rebalance_enabled``)."""
    return isinstance((station or {}).get('rebalance_enabled'), bool)


def has_payments(station):
    return any(isinstance((station or {}).get(flag), bool) for flag, *_ in PAYMENT_FLAGS)


def energy_subtitle(station):
    limit = sp.number(station.get('site_limit_kw'))
    head = f"Limite contratado {sp.kw(limit)}" if limit is not None else 'Sem limite contratado'
    return f"{head} · rebalanceamento {'ligado' if station.get('rebalance_enabled') else 'desligado'}"


def payments_subtitle(station):
    parts = []
    if isinstance(station.get('prepay_required'), bool):
        parts.append(f"Antecipado {'exigido' if station['prepay_required'] else 'desligado'}")
    if isinstance(station.get('kiosk_payments'), bool):
        parts.append(f"QR do painel {'ligado' if station['kiosk_payments'] else 'desligado'}")
    return ' · '.join(parts)


# ---------------------------------------------------------------- Ao vivo
ORDER = ('charging', 'occupied', 'reserved', 'fault', 'offline', 'reconciling', 'available', 'disabled')


def _occupancy_box(occupancy):
    label, tone = owner_sessions.occupancy_label(occupancy)
    head = [_pill(label, tone)]
    if occupancy.get('driver_label'):
        head.append(design.txt(occupancy['driver_label'], 11.5, 'regular', theme.GRAY_TEXT, expand=True))
    lines = [ft.Row(head, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
             design.txt(owner_sessions.occupancy_text(occupancy), 13.5, 'bold')]
    if occupancy.get('started_at'):
        lines.append(design.txt(f"Recarga terminou às {_hhmm(occupancy['started_at'])}", 11, 'regular',
                                theme.GRAY_TEXT))
    return ft.Container(ft.Column(lines, spacing=6), bgcolor=theme.TILE, border_radius=12, data='occupancy',
                        padding=ft.Padding(left=12, right=12, top=10, bottom=10))


def live_card(item):
    """Cartão de um ponto no Ao vivo (mesmas informações do painel web)."""
    label, color = point_status(item)
    from .operator import _status_pill
    rows = [ft.Row([ft.Column([design.txt(item.get('public_code') or 'Ponto', 14.5, 'bold'),
                               design.txt(f"{item.get('connector_type') or 'Conector'} · {sp.kw(item.get('power_kw'))}",
                                          11, 'regular', theme.GRAY_TEXT)], spacing=3, expand=True),
                    _status_pill(label, color)], vertical_alignment=ft.CrossAxisAlignment.CENTER)]
    session = item.get('session')
    if session:
        energy = sp.number(session.get('energy_wh')) or 0
        parts = [f'{kwh(energy / 1000, 2)} entregues']
        power_w = sp.number(session.get('power_w'))
        if power_w is not None:
            parts.append(f'{sp.kw(power_w / 1000)} agora')
        parts.append(money(session.get('cost_estimate')))
        rows.append(design.txt(' · '.join(parts), 12, 'regular'))
        if session.get('applied_power_kw') is not None:
            rows.append(design.txt(f"Potência aplicada: {sp.kw(session['applied_power_kw'])}", 12.5, 'semibold'))
        soc = sp.number(session.get('soc_percent'))
        if soc is not None:
            rows.append(ft.ProgressBar(value=float(max(0, min(100, soc))) / 100, color=BAR_BLUE,
                                       bgcolor=theme.SEGMENT_OFF, bar_height=6, border_radius=3))
        if session.get('power_reason'):
            rows.append(design.txt(session['power_reason'], 11, 'regular', theme.GRAY_TEXT))
        rows.append(design.txt(f"Iniciada às {_hhmm(session.get('started_at'))}", 11, 'regular', theme.GRAY_TEXT))
    else:
        rows.append(design.txt(f"{money(item.get('price_per_kwh'))}/kWh", 12, 'regular', theme.GRAY_TEXT))
    if isinstance(item.get('occupancy'), dict):
        rows.append(_occupancy_box(item['occupancy']))
    foot = ['Online' if item.get('online') else
            ('Sem dispositivo' if item.get('has_device') is False else 'Equipamento sem comunicação')]
    if item.get('reserved_until'):
        foot.append(f"Reservado até {_hhmm(item['reserved_until'])}")
    rows.append(design.txt(' · '.join(foot), 10.5, 'regular', theme.GRAY_TEXT))
    return design.card_box(ft.Column(rows, spacing=8), padding=ft.Padding(left=16, right=16, top=14, bottom=14),
                           data=f"live:{item.get('connector_id')}")


def _live_items(data):
    items = [item for item in (data or {}).get('items') or [] if not item.get('retired')]
    return sorted(items, key=lambda item: ORDER.index(item.get('availability_status'))
                  if item.get('availability_status') in ORDER else len(ORDER))


def live_summary(items):
    counts = {}
    for item in items:
        counts[item.get('availability_status')] = counts.get(item.get('availability_status'), 0) + 1
    problems = counts.get('offline', 0) + counts.get('fault', 0)
    parked = sum(1 for item in items if isinstance(item.get('occupancy'), dict))
    text = (f"{counts.get('charging', 0)} carregando · {counts.get('available', 0)} disponíveis · "
            f"{problems} com problema")
    return text + (f' · {parked} na vaga após a recarga' if parked else '')


SEVERITY = {'critical': ('Crítico', 'RED'), 'warning': ('Atenção', 'AMBER'), 'info': ('Informativo', 'SLATE')}


def alert_rows(payload):
    """Alertas do posto (``/owner/alerts``), críticos primeiro; lista vazia sem alertas ou sem a rota."""
    order = list(SEVERITY)
    items = sorted((payload or {}).get('items') or [],
                   key=lambda item: order.index(item.get('severity')) if item.get('severity') in order else 9)
    rows = []
    for item in items:
        label, tone = SEVERITY.get(item.get('severity'), ('Alerta', 'SLATE'))
        title = ' · '.join(str(part) for part in (item.get('public_code'), item.get('title')) if part)
        rows.append(ft.Column([ft.Row([_pill(label, tone), design.txt(title, 12.5, 'semibold', expand=True)],
                                      spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                               design.txt(item.get('detail') or '', 11, 'regular', theme.GRAY_TEXT)], spacing=4))
    return rows


async def _alerts(app, sid):
    try:
        return await app.api.request('GET', 'owner/alerts', params={'station_id': sid})
    except ApiError:
        return None  # alertas são complemento: sem a rota ou com falha, a página continua


async def live_page(app, station):
    sid = station['id']
    data = await app.api.request('GET', 'owner/live', params={'station_id': sid})
    summary = design.txt('', 11.5, 'regular', theme.GRAY_TEXT)
    cards = ft.Column(spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    alerts = ft.Column(spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    alerts_box = ft.Column([design.txt('Alertas', 14.6, 'bold'),
                            design.card_box(alerts, padding=ft.Padding(left=16, right=16, top=14, bottom=14))],
                           spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH, data='alerts')

    def draw_alerts(payload):
        alerts.controls = alert_rows(payload)
        alerts_box.visible = bool(alerts.controls)

    draw_alerts(await _alerts(app, sid))

    def draw(payload):
        items = _live_items(payload)
        summary.value = (live_summary(items) + f' · atualiza a cada {LIVE_POLL_SECONDS} s'
                         + (f" ({_hhmm(payload.get('generated_at'))})" if payload.get('generated_at') else ''))
        cards.controls = [live_card(item) for item in items] or [
            design.txt('Nenhum ponto cadastrado neste posto.', 12.5, 'regular', theme.GRAY_TEXT)]

    draw(data)

    ticks = {'count': 0}

    async def update():
        draw(await app.api.request('GET', 'owner/live', params={'station_id': sid}))
        ticks['count'] += 1
        if ticks['count'] % 10 == 0:  # alertas mudam devagar: a cada ~30 s
            draw_alerts(await _alerts(app, sid))
        app.page.update()

    app.set_poll(update, LIVE_POLL_SECONDS)
    extra = [_demo_traffic_button(app, sid, 'live')] if _demo(app) else []
    return design.page(_heading(app, 'Ao vivo', sid), summary, cards, alerts_box, *extra, gap=14, gutter=3)


# ---------------------------------------------------------------- Energia do estabelecimento
def _demo_traffic_button(app, sid, page):
    async def simulate():
        await app.api.request('POST', f'stations/{sid}/demo-traffic', {})
        app.notice('Movimento simulado no posto: carros fictícios carregando e na vaga.')
        await app.go('station_admin', station_id=sid, page=page)
    return ft.Column([
        design.secondary_button('Simular carros no posto (demo)', app.action(simulate), height=46),
        design.txt('Só na demonstração: um carro carregando, um que terminou e continua na vaga e uma recarga paga '
                   'no histórico. Sem limite contratado, usa 30 kW com a loja em 12 kW e liga o rebalanceamento.',
                   10.5, 'regular', theme.GRAY_TEXT)], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def _point_row(point):
    session = point.get('session')
    label, tone = sp.state_label(session)
    head = ft.Row([ft.Column([design.txt(point.get('public_code') or 'Ponto', 13.5, 'bold'),
                              design.txt(sp.point_detail(point), 10.5, 'regular', theme.GRAY_TEXT)],
                             spacing=2, expand=True),
                   _pill(label, tone)], vertical_alignment=ft.CrossAxisAlignment.CENTER)
    lines = [head]
    if session:
        lines.append(design.txt(f"Alvo {sp.kw(session.get('target_kw'))} · Aplicada {sp.kw(session.get('applied_kw'))}",
                                12.5, 'semibold'))
        reason = session.get('reason') or session.get('reason_short')
        if reason:
            lines.append(design.txt(reason, 11, 'regular', theme.GRAY_TEXT))
    return ft.Container(ft.Column(lines, spacing=5), data=f"power:{point.get('connector_id')}")


def _decision_row(decision):
    return ft.Row([design.txt(_hhmm(decision.get('created_at')), 11, 'regular', theme.GRAY_TEXT, width=40),
                   ft.Column([design.txt(decision.get('summary') or '', 11.5, 'regular'),
                              design.txt(sp.decision_detail(decision), 10.5, 'regular', theme.GRAY_TEXT)],
                             spacing=2, expand=True)], vertical_alignment=ft.CrossAxisAlignment.START, spacing=8)


def _section(title, *controls, padding=16):
    return ft.Column([design.txt(title, 14.6, 'bold'),
                      design.card_box(ft.Column(list(controls), spacing=10,
                                                horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                                      padding=ft.Padding(left=padding, right=padding, top=15, bottom=15))],
                     spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)


def _unsupported(app, sid):
    return design.page(_heading(app, 'Energia do estabelecimento', sid), design.txt(
        'Este servidor ainda não tem o rebalanceamento ao vivo. Os limites de potência continuam em '
        'Potência por conector.', 12.5, 'regular', theme.GRAY_TEXT), gap=14, gutter=3)


async def energy_page(app, station):
    sid = station['id']
    try:
        view = await app.api.request('GET', f'stations/{sid}/power')
    except ApiError as exc:
        if exc.status == 404:
            return _unsupported(app, sid)
        raise
    state = {'view': view, 'touched': False}

    # Limite contratado e rebalanceamento.
    limit = design.number_field(sp.limit_input(view.get('site_limit_kw')), suffix='kW', hint='sem limite')
    limit.data = 'site_limit'

    def limit_changed(event=None):
        state['touched'] = True
        limit.error_text = None
    limit.on_change = limit_changed
    rebalance = ft.Switch(value=bool(view.get('rebalance_enabled')), active_color=theme.RED, data='rebalance')
    rebalance_caption = design.txt('', 11, 'regular', theme.GRAY_TEXT)

    # Consumo da loja (SIMULADO).
    load_value = design.txt('', 22, 'bold')
    sending = design.txt('', 10.5, 'regular', theme.GRAY_TEXT)
    load = ft.Slider(value=0, min=0, max=10, divisions=20, active_color=theme.BTN_PRIMARY,
                     inactive_color=theme.SEGMENT_OFF, thumb_color=theme.BTN_PRIMARY, data='building_load', padding=0)
    load_max = design.txt('', 10.5, 'regular', theme.GRAY_TEXT)

    # Soma, pontos e decisões (redesenhados a cada atualização).
    used = design.txt('', 13, 'semibold')
    cars = design.txt('', 11, 'regular', theme.GRAY_TEXT)
    bar = ft.ProgressBar(value=0, color=BAR_BLUE, bgcolor=theme.SEGMENT_OFF, bar_height=10, border_radius=5)
    available = design.txt('', 11, 'regular', theme.GRAY_TEXT)
    over = design.txt('', 11.5, 'semibold', theme.ERROR, visible=False)
    points = ft.Column(spacing=14, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    decisions = ft.Column(spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    failure = design.txt('', 11, 'regular', theme.ERROR, visible=False)

    async def send_load(value):
        sending.value = 'enviando…'
        app.page.update()
        try:
            fresh = await app.api.request('PUT', f'stations/{sid}/building-load', {'building_load_kw': f'{value:.1f}'})
        except ApiError as exc:
            failure.value, failure.visible = f'Consumo da loja não salvo: {exc}', True
        else:
            failure.visible = False
            apply(fresh, keep_load=debounce.pending)
        finally:
            sending.value = ''
            app.page.update()

    debounce = sp.Debouncer(send_load)

    def apply(fresh, keep_load=False):
        state['view'] = fresh
        if not state['touched']:
            limit.value = sp.limit_input(fresh.get('site_limit_kw'))
        rebalance.value = bool(fresh.get('rebalance_enabled'))
        rebalance_caption.value = ('Ligado: ajusta os pontos a cada sincronização' if rebalance.value
                                   else 'Desligado: vale a potência do início de cada recarga')
        top = sp.load_max(fresh)
        load.max, load.divisions = float(top), top * 2
        load_max.value = f'0 kW – {top} kW · sem medidor: valor simulado para a demonstração'
        if not keep_load and not debounce.pending:
            load.value = float(min(top, sp.number(fresh.get('building_load_kw')) or 0))
            load_value.value = sp.kw(load.value)
        info = sp.usage(fresh)
        used.value = f"Em uso {sp.kw(info['used'])} de {sp.kw(info['available'], 'sem limite')} disponíveis"
        count = int(fresh.get('cars') or 0)
        cars.value = f"{count} carro{'s' if count != 1 else ''} carregando"
        bar.value = info['fraction']
        bar.color = theme.RED if info['over'] else BAR_BLUE
        available.value = sp.availability_text(fresh)
        warning = sp.over_text(fresh, info)
        over.value, over.visible = warning or '', bool(warning)
        points.controls = [_point_row(point) for point in fresh.get('points') or []] or [
            design.txt('Nenhum ponto neste posto.', 12, 'regular', theme.GRAY_TEXT)]
        decisions.controls = [_decision_row(item) for item in (fresh.get('decisions') or [])[:5]] or [
            design.txt('Nenhuma decisão registrada ainda.', 11.5, 'regular', theme.GRAY_TEXT)]

    async def save_site(**body):
        try:
            fresh = await app.api.request('PUT', f'stations/{sid}/power-site', body)
        except ApiError as exc:
            apply(state['view'])  # o interruptor volta ao estado do servidor
            app.page.update()
            app.notice(f'Alteração de energia não salva: {exc}')
            return None
        state['touched'] = False
        apply(fresh)
        app.page.update()
        return fresh

    async def save_limit():
        value, error = sp.parse_site_limit(limit.value)
        if error:
            limit.error_text = error
            app.page.update()
            return
        current = sp.number(state['view'].get('site_limit_kw'))
        if (value is None and current is None) or (value is not None and current == sp.number(value)):
            state['touched'] = False
            app.notice('Nenhuma alteração para salvar.')
            return
        if await save_site(site_limit_kw=value):
            app.notice('Limite contratado salvo' if value is not None else 'Limite contratado removido')

    async def toggle(event):
        enabled = bool(event.control.value)
        fresh = await save_site(rebalance_enabled=enabled)
        if fresh:
            app.notice('Rebalanceamento ligado' if fresh.get('rebalance_enabled') else 'Rebalanceamento desligado')
    rebalance.on_change = toggle

    async def slide(event):
        value = round(float(event.control.value) * 2) / 2
        load_value.value = sp.kw(value)
        debounce(value)
        app.page.update()

    async def released(event=None):
        await debounce.flush()
    load.on_change = slide
    load.on_change_end = released

    apply(view)

    async def update():
        fresh = await app.api.request('GET', f'stations/{sid}/power')
        apply(fresh, keep_load=debounce.pending)
        app.page.update()

    app.set_poll(update, sp.POLL_SECONDS)
    limit_row = ft.Row([ft.Container(limit, expand=True, border_radius=14, bgcolor=theme.INPUT_BG,
                                     clip_behavior=ft.ClipBehavior.ANTI_ALIAS),
                        design.primary_button('Salvar', app.action(save_limit), height=45)],
                       spacing=10, vertical_alignment=ft.CrossAxisAlignment.START)
    controls = [
        design.txt('Divide a potência entre os carros sem passar do limite contratado da instalação. '
                   f"Atualiza a cada {str(sp.POLL_SECONDS).replace('.', ',')} s.", 11.5, 'regular', theme.GRAY_TEXT),
        _section('Limite contratado',
                 design.txt('Instalação inteira, loja incluída. Vazio remove o limite.', 11, 'regular',
                            theme.GRAY_TEXT),
                 limit_row,
                 ft.Row([ft.Column([design.txt('Rebalanceamento ao vivo', 12.5, 'semibold'), rebalance_caption],
                                   spacing=2, expand=True), rebalance],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER)),
        _section('Consumo da loja',
                 ft.Row([_pill('SIMULADO', 'AMBER'), ft.Container(expand=True), sending, load_value],
                        spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                 load, load_max),
        _section('Potência dos carregadores', ft.Row([used], wrap=True), cars, bar, available, over),
        _section('Por ponto', points),
        _section('Últimas decisões', decisions),
        failure,
    ]
    if _demo(app):
        controls.append(_demo_traffic_button(app, sid, 'energy'))
    return design.page(_heading(app, 'Energia do estabelecimento', sid), *controls, gap=16, gutter=3)


# ---------------------------------------------------------------- Pagamentos (teste)
def payments_page(app, station):
    sid = station['id']
    flags = [entry for entry in PAYMENT_FLAGS if isinstance(station.get(entry[0]), bool)]
    current = {flag: bool(station.get(flag)) for flag, *_ in flags}
    busy = {'flag': None}
    rows = []

    def make(flag, title, detail, on_text, off_text):
        switch = ft.Switch(value=current[flag], active_color=theme.RED, data=flag)
        note = design.txt(detail, 11, 'regular', theme.GRAY_TEXT)

        async def changed(event):
            value = bool(event.control.value)
            if busy['flag']:
                switch.value = current[flag]
                app.page.update()
                return
            busy['flag'] = flag
            note.value = 'Salvando…'
            app.page.update()
            try:
                saved = await app.api.request('PATCH', f'stations/{sid}', {flag: value})
            except ApiError as exc:
                switch.value = current[flag]  # sem atualização otimista: volta ao valor do servidor
                app.notice(f'Configuração de pagamento não salva: {exc}')
            else:
                current[flag] = bool(saved.get(flag, value))
                switch.value = current[flag]
                app.notice(on_text if current[flag] else off_text)
            finally:
                busy['flag'] = None
                note.value = detail
                app.page.update()
        switch.on_change = changed
        return ft.Column([ft.Row([design.txt(title, 13, 'semibold', expand=True), switch],
                                 vertical_alignment=ft.CrossAxisAlignment.CENTER), note], spacing=4)

    for entry in flags:
        rows.append(make(*entry))
    body = rows or [design.txt('Este servidor ainda não tem pagamentos por posto.', 12, 'regular', theme.GRAY_TEXT)]
    return design.page(
        _heading(app, 'Pagamentos', sid),
        ft.Row([_pill('TESTE', 'AMBER'),
                design.txt('Stripe em modo teste: nenhum valor real é cobrado.', 11.5, 'regular', theme.GRAY_TEXT,
                           expand=True)], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        design.card_box(ft.Column(body, spacing=18), padding=ft.Padding(left=16, right=16, top=16, bottom=16)),
        gap=16, gutter=3)
