import asyncio
import inspect
import json
import os
from pathlib import Path

import flet as ft

from ..api_client import ApiError
from ..config import packaged_version
from ..services import driver as helpers
from ..services import vehicle_state
from ..services.driver_profile import save_vehicle
from ..ui import design, theme
from ..ui.components import button, money
from ..ui.vehicle import VehiclePicker


async def driver_profile(app):
    """Perfil do motorista (carro); a conta continua acessível se ele não carregar."""
    try:
        data = await app.api.request('GET', 'driver/profile')
    except ApiError:
        return None
    return data if isinstance(data, dict) and isinstance(data.get('vehicle'), dict) else None


def saved_vehicle(driver):
    return driver['vehicle'] if driver and driver.get('saved') else None


def vehicle_text(profile, driver):
    vehicle = saved_vehicle(driver)
    return helpers.vehicle_headline(vehicle) if vehicle else profile.get('vehicle_description')


DEMO_PIX_KEY = '000.000.000-00'
MAX_PIX_LENGTH = 77


class PixKeyStore:
    """Chave Pix de repasse, guardada só neste aparelho (a API não tem o campo).

    Demonstração: fica em memória (``app``); conta real: JSON em ``FLET_APP_STORAGE_DATA``.
    """

    def __init__(self, path=None):
        storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
        self.path = Path(path or storage / 'pix_key.json')

    def load(self, account_id):
        try:
            data = json.loads(self.path.read_text())
            value = data.get(str(account_id)) if isinstance(data, dict) else None
            return value if isinstance(value, str) else ''
        except (OSError, ValueError, TypeError):
            return ''

    def save(self, account_id, value):
        try:
            try:
                data = json.loads(self.path.read_text())
            except (OSError, ValueError):
                data = {}
            data = data if isinstance(data, dict) else {}
            data[str(account_id)] = value
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(data))
            return True
        except OSError:
            return False


def load_pix_key(app, profile):
    if getattr(app.api, 'is_demo', False):
        return getattr(app, 'demo_pix_key', DEMO_PIX_KEY)
    return PixKeyStore().load(profile.get('id') or '')


def save_pix_key(app, profile, value):
    if getattr(app.api, 'is_demo', False):
        app.demo_pix_key = value
        return True
    return PixKeyStore().save(profile.get('id') or '', value)


async def balance_text(app, vendor):
    """"R$ 214,80 disponíveis" vindo da carteira simulada (G4/G11); texto neutro se ainda não existir."""
    try:
        if vendor:
            from ..services import payout
            try:
                await payout.load_owner_net(app)  # saldo = repasse (após a comissão), não a receita bruta
            except Exception:  # sem rede: usa o último valor conhecido
                pass
            value = payout.available(app)
        else:
            from ..services import wallet
            value = wallet.balance(app)
        if inspect.isawaitable(value):
            value = await value
        return f'{money(value)} disponíveis'
    except Exception:  # serviço ainda ausente ou saldo indisponível: a tela Conta não pode quebrar
        return 'Consultar saldo e extrato'


def _row(title_text, subtitle, icon, on_click, trailing=None, chevron=True):
    return ft.Container(design.list_row(title_text, subtitle, on_click=on_click, icon=icon, tile=34, dark_tile=True,
                                        plain=True, trailing=trailing, chevron=chevron),
                        padding=ft.Padding(left=5, right=5, top=7.5, bottom=7.5))


async def build(app, mode=None, **_):
    demo = getattr(app.api, 'is_demo', False)
    if mode == 'password':
        return password_form(app)
    if getattr(app, 'browsing_mode', 'consumer') == 'vendor' and mode != 'edit':
        from ..services import prefetch
        prefetch.fetch(app, prefetch.owner_net())  # saldo da carteira junto com a conta, não depois
    # Conta e carro são independentes: buscados em paralelo.
    profile, driver = await asyncio.gather(app.api.request('GET','me'), driver_profile(app))
    app.profile = profile
    if mode == 'edit':
        return edit_form(app, profile, driver)

    email = (app.api.session.user or {}).get('email') or 'Não informado'
    vendor_account = profile.get('operator_enabled') or profile.get('account_type') == 'vendor'
    vendor = getattr(app,'browsing_mode','consumer') == 'vendor'

    async def dark(e):
        if hasattr(app, 'prepare_navigation') and not await app.prepare_navigation():
            e.control.value = app.dark_mode
            app.page.update()
            return
        app.dark_mode = bool(e.control.value)
        theme.set_dark(app.dark_mode)
        saved = True if demo else app.preferences.save(app.dark_mode)
        await app.go('profile')
        if not saved:
            app.notice('Tema aplicado nesta sessão. Não foi possível salvar a preferência no dispositivo.')

    def labeled_text(label, value, size, weight, color):
        return ft.Semantics(label=f"{label}: {value or 'Não informado'}", container=True, exclude_semantics=True,
                            read_only=True, content=design.txt(value or 'Não informado', size, weight, color))

    identity = ft.Container(ft.Row([
        design.avatar(app, 54),
        ft.Column([labeled_text('Nome', profile.get('name'), 16, 'bold', theme.TEXT_COLOR),
                   labeled_text('E-mail', email, 11, 'regular', theme.GRAY_TEXT)],
                  spacing=7, expand=True, alignment=ft.MainAxisAlignment.CENTER),
    ], spacing=17, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=theme.INPUT_BG, border_radius=design.RADIUS_CARD, padding=ft.Padding(left=12, right=12, top=16, bottom=16))

    money_row = _row('Minha Carteira' if vendor else 'Meu saldo', await balance_text(app, vendor),
                     ft.Icons.CREDIT_CARD, app.link('payout' if vendor else 'wallet'))
    # Ordem pedida: Perfil, saldo/carteira, Alterar senha, troca de modo (quando houver), Tema escuro.
    rows = [_row('Perfil', 'Editar informações do usuário', ft.Icons.EDIT, app.link('profile', mode='edit')),
            money_row]
    if not demo:
        rows.append(_row('Alterar senha', 'Você precisará entrar novamente', ft.Icons.LOCK_OUTLINE,
                         app.link('profile', mode='password')))
    if vendor_account:
        rows.append(_row('Usar como motorista' if vendor else 'Usar como operador',
                         'A troca de modo mantém sua reserva ou recarga.', ft.Icons.SWAP_HORIZ,
                         app.action(lambda: app.switch_mode('consumer' if vendor else 'vendor'))))
    rows.append(_row('Tema escuro', 'Aparência do aplicativo', ft.Icons.DARK_MODE_OUTLINED, None, chevron=False,
                     trailing=ft.Switch(value=theme.is_dark(), on_change=dark, data='preference',
                                        active_color=theme.RED)))
    if vehicle_state.presentation_available(app):
        # Pitch: o celular carregado pelo ChargeGrid Mini faz o papel do carro (preferência do aparelho).
        async def presentation(e):
            if not vehicle_state.set_presentation_mode(app, bool(e.control.value)):
                app.notice('Modo apresentação aplicado nesta sessão. Não foi possível salvar no dispositivo.')
            app.page.update()
        rows.append(_row('Modo apresentação', 'Usa a bateria do celular como bateria do carro',
                         ft.Icons.BATTERY_CHARGING_FULL, None, chevron=False,
                         trailing=ft.Switch(value=vehicle_state.presentation_mode(app), on_change=presentation,
                                            data='presentation', active_color=theme.RED)))
    version = packaged_version()
    if version and hasattr(app, 'offer_update'):
        # Versão instalada + checagem na hora (o aviso automático roda ao abrir e ao voltar ao app).
        rows.append(_row(f'Versão {version}', 'Verificar atualização', ft.Icons.SYSTEM_UPDATE_OUTLINED,
                         app.action(lambda: app.offer_update(version, delay=0, manual=True))))
    notes = [design.demo_note(app)]
    if demo:
        notes.append(design.txt('Senha pública: demo1234 · os dados simulados reiniciam ao sair', 10,
                                'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER))
    else:
        notes.append(design.txt('Sair não interrompe uma recarga em andamento.', 11, 'regular', theme.GRAY_TEXT,
                                text_align=ft.TextAlign.CENTER))
    sair = design.primary_button('Sair', app.action(app.logout), height=48, size=15)
    # Na referência o botão do operador fica 10 pt mais baixo que o do motorista.
    footer = [ft.Container(sair, margin=ft.Margin(left=0, top=0, right=0, bottom=-10 if vendor else 0))]
    heading = ft.Container(design.page_title('Conta', size=15), margin=ft.Margin(left=0, top=3.5, right=0, bottom=1.5))
    return design.page(heading, identity, *rows, *notes, gap=14, footer=footer)


def edit_form(app, profile, driver=None):
    email = (app.api.session.user or {}).get('email') or ''
    name = design.input_field(profile.get('name') or '', max_length=100)
    mail = design.input_field(email, read_only=True)
    phone = design.input_field(profile.get('phone') or '', max_length=30, keyboard=ft.KeyboardType.PHONE)
    pix = design.input_field(load_pix_key(app, profile), DEMO_PIX_KEY, max_length=MAX_PIX_LENGTH)
    for control in (name, mail, phone, pix):
        control.counter = ''
        control.border = ft.OutlineInputBorder(border_radius=design.RADIUS_BTN + 2,
                                               side=ft.BorderSide(0, ft.Colors.TRANSPARENT))
        control.content_padding = ft.Padding(left=9, right=9, top=13, bottom=13)
    vehicle = saved_vehicle(driver)
    picker = VehiclePicker(vehicle, (driver or {}).get('presets'), allow_later=vehicle is None,
                           on_change=lambda _: app.page.update(), label='Meu carro', outer_labels=True)
    for control in (picker.model, picker.name, picker.battery, picker.consumption):
        # Mesmo campo de Nome/Telefone: escuro, arredondado e com o mesmo recuo interno.
        control.content_padding = ft.Padding(left=9, right=9, top=13, bottom=13)
    async def save():
        if not name.value.strip():
            raise ApiError('Informe seu nome.')
        if len(name.value.strip()) > 100 or len(phone.value.strip()) > 30:
            raise ApiError('Confira o tamanho dos campos informados.')
        if len((pix.value or '').strip()) > MAX_PIX_LENGTH:
            raise ApiError('Confira o tamanho da chave Pix.')
        chosen = picker.read(strict=True)
        description = helpers.vehicle_name(chosen) if chosen else profile.get('vehicle_description')
        account = app.api.request('PATCH','me',{'name':name.value.strip(),'phone':phone.value.strip() or None,
                                                'vehicle_description':description or None})
        if chosen:
            vehicle_state.remember_vehicle(app, chosen)
            # Mesmo carro do Modo motorista; as preferências do turno são mantidas.
            app.profile, _ = await asyncio.gather(account, save_vehicle(app.api, chosen, driver))
        else:
            app.profile = await account
        pix_saved = save_pix_key(app, profile, (pix.value or '').strip())
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice('Perfil atualizado.' if pix_saved else
                   'Perfil atualizado. Não foi possível guardar a chave Pix neste aparelho.')
        await app.go('profile')
    return design.page(
        *[ft.Container(design.labeled(text, control, 14), padding=ft.Padding(left=0, right=8, top=0, bottom=0),
                       margin=ft.Margin(left=0, top=13 if text == 'Nome' else 0, right=0, bottom=0))
          for text, control in (('Nome', name), ('E-mail', mail), ('Telefone', phone), ('Chave Pix', pix))],
        ft.Container(picker.control, padding=ft.Padding(left=0, right=8, top=0, bottom=0)),
        design.primary_button('Salvar informações', app.action(save), height=48, size=16),
        ft.Container(height=8),
        title='Perfil', on_back=getattr(app, 'back', None) or app.link('profile'), gap=16, title_size=22)


def password_form(app):
    back = getattr(app, 'back', None) or app.link('profile')
    if getattr(app.api, 'is_demo', False):
        return design.page(
            design.txt('A senha pública desta conta é fixa; nenhuma credencial real é alterada.', 12, 'regular',
                       theme.GRAY_TEXT),
            title='Alterar senha', on_back=back, gap=16, title_size=22,
            footer=[button('Voltar à conta', app.link('profile'))])
    password = design.input_field(password=True, max_length=128)
    confirmation = design.input_field(password=True, max_length=128)
    for control in (password, confirmation):
        control.autocorrect = False
        control.enable_suggestions = False
        control.counter = ''
        control.height = None
        control.error_max_lines = 3
        control.border = ft.OutlineInputBorder(border_radius=design.RADIUS_BTN + 2,
                                               side=ft.BorderSide(0, ft.Colors.TRANSPARENT))
        control.content_padding = ft.Padding(left=9, right=9, top=13, bottom=13)
    async def save():
        value = password.value or ''
        if not 8 <= len(value) <= 128:
            raise ApiError('Use uma senha com 8 a 128 caracteres.')
        if value != confirmation.value:
            raise ApiError('As senhas não coincidem. Confira a confirmação.')
        await app.api.request('POST', 'auth/password/update', {'password': value})
        password.value = confirmation.value = ''
        # The provider revokes refresh tokens; discard this client's access too.
        app.api.session.clear()
        app.api.clear_operation('charging-sessions')
        app.api.clear_operation('reservations')
        app.profile = {}
        if hasattr(app,'reset_account_ui'):
            app.reset_account_ui()
        await app.go('auth')
        app.notice('Senha alterada. Entre novamente. Outros dispositivos pedirão login ao renovar o acesso.')
    submit = app.action(save)
    confirmation.on_submit = submit
    # Mesmo padrão de Perfil: título com "<", rótulos acima dos campos escuros e botão branco.
    return design.page(
        *[ft.Container(design.labeled(text, control, 14), padding=ft.Padding(left=0, right=8, top=0, bottom=0),
                       margin=ft.Margin(left=0, top=13 if text == 'Nova senha' else 0, right=0, bottom=0))
          for text, control in (('Nova senha', password), ('Confirmar nova senha', confirmation))],
        design.txt('Você precisará entrar novamente. Outros dispositivos pedirão login ao renovar o acesso; '
                   'a recarga no equipamento não é interrompida.', 11, 'regular', theme.GRAY_TEXT),
        button('Salvar nova senha', submit),
        title='Alterar senha', on_back=back, gap=16, title_size=22)
