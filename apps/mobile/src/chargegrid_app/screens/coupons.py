"""Cupons (rota ``coupons``): gestão do vendedor (``manage``) e lista pública (sem ``manage``).

Gestão (visual do vendedor, ``ui/design.py`` + ``setup_ui``): resumo (ativos, expirados, inativos,
usos e desconto concedido aproximado), filtro Todos/Ativos/Expirados/Inativos (``status``), um cartão
por cupom com código, % OFF, status, validade, onde vale e o uso (``uses``/``last_used_at``/
``discount_total_approx`` do ``GET coupons?mine=true``), e as ações Editar e Desativar/Reativar.
Não há exclusão: desativar é ``PATCH active=false``. Reativar um cupom vencido abre a edição para
escolher nova validade (a API recusa sem ela).

Formulário: código e posto (só ao criar), descrição, desconto com atalhos 5/10/15/20 %, validade com
atalhos 7/30/90 dias (23:59, horário local) e Ativo (só ao editar). As regras e os corpos enviados
são os de antes: editar só a descrição não reenvia a validade; reativar exige validade futura.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import flet as ft

from ..api_client import ApiError
from ..ui import design, theme
from ..ui.components import date_time, money
from ..ui.states import empty_state
from .setup_ui import cta, setup_field
from .station_admin import heading

FILTERS = [('all', 'Todos'), ('active', 'Ativos'), ('expired', 'Expirados'), ('inactive', 'Inativos')]
DISCOUNT_PRESETS = (5, 10, 15, 20)
EXPIRY_PRESETS = (7, 30, 90)
EXPIRY_LABEL = 'Validade (dia/mês/ano hora:minuto)'
STATE_LABELS = {'active': 'Ativo', 'expired': 'Expirado', 'inactive': 'Inativo'}


async def owned_stations(app):
    stations = []
    while True:
        result = await app.api.request('GET','operator/stations',params={'limit':100,'offset':len(stations)})
        stations.extend(result['items'])
        if not result['items'] or len(stations) >= result['total']:
            return stations


def _expired(item):
    try:
        return datetime.fromisoformat(item['valid_until'].replace('Z','+00:00')) <= datetime.now(timezone.utc)
    except (KeyError, AttributeError, ValueError):
        return False


def state(item):
    """``active`` | ``expired`` | ``inactive`` (como o painel web: inativo prevalece sobre expirado)."""
    if not item.get('active', True):
        return 'inactive'
    return 'expired' if _expired(item) else 'active'


def _pill(key):
    color = {'active': theme.GREEN, 'expired': theme.WARNING, 'inactive': theme.SLATE}[key]
    return ft.Container(design.txt(STATE_LABELS[key], 10.5, 'bold', theme.on_color(color)),
                        bgcolor=color, border_radius=6, padding=ft.Padding(left=8, right=8, top=4, bottom=4))


def _decimal(value):
    try:
        return Decimal(str(value or 0))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def _int_or_none(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _day(value):
    text = date_time(value)
    return text.split(' ')[0] if text != '—' else text


def usage_line(item):
    """``N usos · último em dd/mm/aaaa`` (``None`` quando a API não informa o uso)."""
    if 'uses' not in item:
        return None
    uses = int(item.get('uses') or 0)
    if not uses:
        return 'Nenhum uso ainda'
    line = f"{uses} {'uso' if uses == 1 else 'usos'}"
    if item.get('last_used_at'):
        line += f" · último em {_day(item['last_used_at'])}"
    return line


def _granted_text(value):
    return f'Desconto concedido (aprox.): {money(value)}'


def _code_box(code, size=17):
    return ft.Container(design.txt(code, size, 'bold', selectable=True),
                        border=ft.Border.all(1, theme.GRAY_TEXT), border_radius=8,
                        padding=ft.Padding(left=10, right=10, top=4, bottom=4))


def _guard(app):
    return design.page(
        heading(app, 'Cupons', app.link('operator')),
        design.txt('Vincule sua primeira central para criar cupons.', 14, 'semibold'),
        design.txt('Depois de configurar seu posto, você poderá oferecer descontos para seus clientes.',
                   12, 'regular', theme.GRAY_TEXT),
        cta('Configurar meu primeiro ponto', app.link('operator'), weight='semibold'), gap=16)


async def build(app, manage=False, coupon=None, create=False, station_id=None, offset=0, status='all'):
    if (manage or create or coupon) and not app.profile.get('operator_enabled'):
        return _guard(app)
    if create or coupon:
        return form(app,coupon,await owned_stations(app))
    params = {'limit':50,'offset':offset}
    if manage:
        params['mine'] = 'true'
    if station_id:
        params['station_id'] = station_id
    result = await app.api.request('GET','coupons',params=params)
    station_names = {}
    if manage:
        station_names = {station['id']: station['name'] for station in await owned_stations(app)}
    else:
        async def station_name(identifier):
            try:
                station = await app.api.request('GET',f'stations/{identifier}')
                return identifier, station['name']
            except ApiError as exc:
                if exc.status != 404:
                    raise
                return identifier, 'Posto indisponível'
        identifiers = {item['station_id'] for item in result['items'] if item.get('station_id')}
        station_names = dict(await asyncio.gather(*(station_name(identifier) for identifier in identifiers)))
    destination = {'manage':manage}
    if station_id:
        destination['station_id'] = station_id
    if manage:
        controls = _manage_list(app, result['items'], station_names, destination, status, offset)
    else:
        controls = _public_list(result['items'], station_names)
    total = result.get('total',len(result['items']))
    if offset + len(result['items']) < total and result['items']:
        controls.append(cta('Mais cupons',app.link('coupons',offset=offset+50,**destination),primary=False))
    if offset:
        controls.append(cta('Cupons anteriores',app.link('coupons',offset=max(0,offset-50),**destination),
                            primary=False))
    back = app.link('operator') if manage else app.link('profile')
    return design.page(heading(app, 'Cupons', back), *controls, gap=16)


def _scope(item, station_names):
    if not item.get('station_id'):
        return 'Todos os postos deste operador'
    return station_names.get(item['station_id'], 'Posto indisponível')


def _summary(items):
    counts = {key: sum(1 for item in items if state(item) == key) for key in STATE_LABELS}
    cells = [(counts['active'], 'Ativos'), (counts['expired'], 'Expirados'), (counts['inactive'], 'Inativos')]
    usage = any('uses' in item for item in items)
    if usage:
        cells.append((sum(int(item.get('uses') or 0) for item in items), 'Usos'))
    lines = [ft.Row([ft.Column([design.num(value, 26), design.txt(label, 10.5, 'regular', theme.GRAY_TEXT)],
                               spacing=0, expand=True) for value, label in cells], spacing=8)]
    granted = sum((_decimal(item.get('discount_total_approx')) for item in items), Decimal(0))
    if usage and granted > 0:
        lines.append(design.txt(_granted_text(granted), 11.5, 'semibold'))
    return design.card_box(ft.Column(lines, spacing=10), padding=16, data='coupon-summary')


def _manage_card(app, item, station_names, destination):
    key = state(item)
    expired = _expired(item)
    details = [
        ft.Row([_code_box(item['code']), _pill(key)], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
        design.num(f"{item['discount_percent']}% OFF", 24, theme.ACCENT),
    ]
    if item.get('description'):
        details.append(design.txt(item['description'], 12.5, 'regular'))
    details.append(design.txt('Válido em: ' + _scope(item, station_names), 11, 'regular', theme.GRAY_TEXT))
    details.append(design.txt(f"{'Expirou em' if expired else 'Válido até'} {date_time(item['valid_until'])}",
                              11, 'regular', theme.WARNING if key == 'expired' else theme.GRAY_TEXT))
    usage = usage_line(item)
    if usage:
        details.append(ft.Row([ft.Icon(ft.Icons.CONFIRMATION_NUMBER_OUTLINED, size=15, color=theme.GRAY_TEXT),
                               design.txt(usage, 11, 'semibold', expand=True)],
                              spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER, data='coupon-usage'))
        granted = _decimal(item.get('discount_total_approx'))
        if granted > 0:
            details.append(design.txt(_granted_text(granted), 11, 'regular', theme.GRAY_TEXT))

    async def toggle():
        if not item.get('active', True) and expired:
            # A API exige nova validade para reativar: abre a edição já explicando o motivo.
            if hasattr(app, 'notice'):
                app.notice('Cupom vencido: escolha uma nova validade e marque Ativo para reativar.')
            await app.go('coupons', manage=True, coupon=item)
            return
        await app.api.request('PATCH', f"coupons/{item['id']}", {'active': not item.get('active', True)})
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        await app.go('coupons', **destination)

    def small(text, on_click):
        return ft.Container(cta(text, on_click, primary=False, height=40, size=13, weight='semibold'), expand=True)
    details.append(ft.Row([small('Editar', app.link('coupons', manage=True, coupon=item)),
                           small('Desativar' if item.get('active', True) else 'Reativar', app.action(toggle))],
                          spacing=10))
    return design.card_box(ft.Column(details, spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
                           padding=16, data=f"coupon:{item['id']}")


def _manage_list(app, items, station_names, destination, status, offset):
    status = status if status in dict(FILTERS) else 'all'
    controls = [design.txt('Desconto sobre a energia da recarga, aplicado no início.', 11.5, 'regular',
                           theme.GRAY_TEXT)]
    if items:
        controls.append(_summary(items))
    controls.append(cta('Criar cupom', app.link('coupons', manage=True, create=True), weight='semibold'))
    if not items:
        controls.append(empty_state(ft.Icons.LOCAL_OFFER_OUTLINED, 'Nenhum cupom criado',
                                    'Crie um código de desconto para atrair motoristas aos seus pontos.'))
        return controls

    async def choose(key):
        extra = {'offset': offset} if offset else {}
        if key != 'all':
            extra['status'] = key
        await app.go('coupons', **destination, **extra)
    controls.append(design.segmented(FILTERS, status, choose))
    shown = [item for item in items if status == 'all' or state(item) == status]
    controls += [_manage_card(app, item, station_names, destination) for item in shown]
    if not shown:
        controls.append(design.txt(f'Nenhum cupom {dict(FILTERS)[status].lower()} nesta página.', 12, 'regular',
                                   theme.GRAY_TEXT))
    return controls


def _public_list(items, station_names):
    controls = [design.txt('Digite o código ao preparar a recarga. O desconto vale sobre a energia.', 11.5,
                           'regular', theme.GRAY_TEXT)]
    for item in items:
        details = [ft.Row([_code_box(item['code'], 18),
                           design.num(f"{item['discount_percent']}% OFF", 22, theme.ACCENT)],
                          alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                          vertical_alignment=ft.CrossAxisAlignment.CENTER)]
        if item.get('description'):
            details.append(design.txt(item['description'], 12.5, 'regular'))
        details += [design.txt(f"Válido até {date_time(item['valid_until'])}", 11, 'regular', theme.GRAY_TEXT),
                    design.txt('Válido em: ' + _scope(item, station_names), 11, 'regular', theme.GRAY_TEXT)]
        controls.append(design.card_box(ft.Column(details, spacing=8), padding=16))
    if not items:
        controls.append(empty_state(ft.Icons.LOCAL_OFFER_OUTLINED, 'Nenhum cupom disponível agora',
                                    'Quando um posto oferecer desconto, o código aparece aqui para usar no início da recarga.'))
    return controls


def _chip_row(values, current, label, on_pick):
    """Atalhos (5 %, 30 dias...): o escolhido fica branco; ``on_pick(valor)`` preenche o campo.

    ``linha.data(valor)`` repinta a seleção (ex.: o desconto digitado bate com um atalho)."""
    holder = ft.Row(spacing=8)

    def paint(selected):
        def pick(value):
            async def handler(event=None):
                paint(value)
                await on_pick(value)
            return handler
        # Lado a lado, dividindo a largura (o chip sozinho ocuparia a linha inteira).
        holder.controls = [ft.Container(design.chip_option(label(value), selected=value == selected,
                                                           on_click=pick(value)), expand=True)
                           for value in values]
    paint(current)
    holder.data = paint
    return holder


def form(app,coupon=None,stations=None):
    item = coupon or {}
    stations = stations or []
    code_box = setup_field('Código', item.get('code',''), 'Ex.: VERAO15')
    description_box = setup_field('Descrição', item.get('description',''), 'Ex.: 10% na primeira recarga')
    discount_box = setup_field('Desconto %', str(item.get('discount_percent','10')), keyboard=ft.KeyboardType.NUMBER)
    code, description, discount = code_box.controls[1], description_box.controls[1], discount_box.controls[1]
    initial_expiry = datetime.fromisoformat(item['valid_until'].replace('Z','+00:00')).astimezone() if item.get('valid_until') else datetime.now().astimezone()+timedelta(days=30)
    station = ft.Dropdown(value=item.get('station_id') or '__all__',
                          options=[ft.DropdownOption(key='__all__',text='Todos os meus postos')]+[ft.DropdownOption(key=entry['id'],text=entry['name']) for entry in stations],
                          color=theme.TEXT_COLOR,bgcolor=theme.INPUT_BG,filled=True,fill_color=theme.INPUT_BG,
                          border_radius=design.RADIUS_CARD,border_color='#00000000',text_size=13,expand=True)
    expiry_box = setup_field(EXPIRY_LABEL, initial_expiry.strftime('%d/%m/%Y %H:%M'), 'dd/mm/aaaa hh:mm')
    expiry = expiry_box.controls[1]
    original_expiry_text = expiry.value
    active = ft.Switch(value=item.get('active',True),visible=bool(coupon),active_color=theme.GREEN)
    preview = design.txt('', 13, 'semibold', data='coupon-preview')

    def paint_preview():
        typed = item.get('code','') if coupon else (code.value or '').strip().upper()
        preview.value = f"{typed or 'CÓDIGO'} · {(discount.value or '0').strip()}% OFF"

    async def pick_discount(value):
        discount.value = str(value)
        paint_preview()
        app.page.update()

    async def pick_days(days):
        target = (datetime.now().astimezone() + timedelta(days=days)).replace(hour=23, minute=59, second=0,
                                                                             microsecond=0)
        expiry.value = target.strftime('%d/%m/%Y %H:%M')
        app.page.update()

    discount_chips = _chip_row(DISCOUNT_PRESETS, _int_or_none(discount.value), lambda value: f'{value}%', pick_discount)
    expiry_chips = _chip_row(EXPIRY_PRESETS, None, lambda value: f'{value} dias', pick_days)

    def changed(event=None):
        paint_preview()
        discount_chips.data(_int_or_none(discount.value))
        app.page.update()
    code.on_change = discount.on_change = changed
    paint_preview()

    async def save():
        try:
            percent = int(discount.value.strip())
        except ValueError as exc:
            raise ApiError('Informe um desconto inteiro de 0 a 100%.') from exc
        if not 0 <= percent <= 100:
            raise ApiError('Informe um desconto inteiro de 0 a 100%.')
        try:
            valid_until = datetime.strptime(expiry.value.strip(),'%d/%m/%Y %H:%M').astimezone()
        except ValueError as exc:
            raise ApiError('Use dia/mês/ano hora:minuto na validade, por exemplo 30/12/2026 18:00.') from exc
        expiry_changed = expiry.value.strip() != original_expiry_text
        reactivating = bool(coupon and active.value and not item.get('active',True))
        # Preserve the original timestamp when only editing text or disabling.
        # Formatting it to minutes must not silently change seconds or timezone.
        if coupon and not expiry_changed:
            valid_until = initial_expiry
        if (not coupon or expiry_changed or reactivating) and valid_until <= datetime.now().astimezone():
            raise ApiError('Escolha uma validade futura para o cupom.')
        if not coupon and not code.value.strip():
            raise ApiError('Informe o código do cupom.')
        if len(description.value.strip()) > 200 or (not coupon and len(code.value.strip()) > 50):
            raise ApiError('Use até 50 caracteres no código e 200 na descrição.')
        body = {'description':description.value.strip(),'discount_percent':percent}
        if not coupon or expiry_changed:
            body['valid_until'] = valid_until.astimezone(timezone.utc).isoformat()
        if coupon:
            if active.value != item.get('active',True):
                body['active'] = active.value
        else:
            # Codes are matched case-insensitively and stored in upper case.
            body['code'] = code.value.strip().upper()
            if station.value and station.value != '__all__':
                body['station_id'] = station.value
        await app.api.request('PATCH' if coupon else 'POST',f"coupons/{item['id']}" if coupon else 'coupons',body)
        if hasattr(app,'mark_saved'):
            app.mark_saved()
        await app.go('coupons',manage=True)

    scope = next((entry['name'] for entry in stations if entry['id'] == item.get('station_id')), 'Posto indisponível') if item.get('station_id') else 'Todos os meus postos'
    if coupon:
        identity = [design.label('Código'),
                    ft.Row([_code_box(item['code'], 18), _pill(state(item))],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    design.txt('Válido em: '+scope, 11.5, 'regular', theme.GRAY_TEXT),
                    design.txt('O código e o posto não mudam depois de criados.', 10.5, 'regular', theme.GRAY_TEXT)]
        if usage_line(item):
            identity.append(design.txt(usage_line(item), 11, 'semibold'))
        head = [ft.Column(identity, spacing=8)]
    else:
        head = [code_box, design.labeled('Válido em', ft.Row([station]), gap=6)]
    active_row = ft.Row([ft.Column([design.txt('Cupom ativo', 13, 'semibold'),
                                    design.txt('Desativado, o código deixa de valer na hora.', 10.5, 'regular',
                                               theme.GRAY_TEXT)], spacing=2, expand=True), active],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER, visible=bool(coupon))
    preview_card = design.card_box(ft.Row([
        design.icon_tile(ft.Icons.CONFIRMATION_NUMBER_OUTLINED, size=38, dark=True),
        ft.Column([design.txt('O motorista digita', 10.5, 'regular', theme.GRAY_TEXT), preview], spacing=2,
                  expand=True)], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER), padding=14)
    back = app.link('coupons',manage=True)
    return design.page(
        heading(app, 'Editar cupom' if coupon else 'Novo cupom', back),
        *head,
        description_box,
        ft.Column([discount_box, discount_chips], spacing=10),
        ft.Column([expiry_box, expiry_chips,
                   design.txt('Horário local do seu dispositivo.', 10.5, 'regular', theme.GRAY_TEXT)], spacing=10),
        active_row,
        preview_card,
        cta('Salvar cupom', app.action(save), weight='semibold'),
        cta('Voltar', back, primary=False),
        gap=18)
