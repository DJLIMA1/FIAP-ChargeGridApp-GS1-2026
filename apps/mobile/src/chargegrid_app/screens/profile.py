import asyncio

import flet as ft

from ..api_client import ApiError
from ..services import driver as helpers
from ..services.driver_profile import save_vehicle
from ..ui import theme
from ..ui.components import button, card, field, title
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


async def build(app, mode=None):
    demo = getattr(app.api, 'is_demo', False)
    if mode == 'password':
        return password_form(app)
    # Conta e carro são independentes: buscados em paralelo.
    profile, driver = await asyncio.gather(app.api.request('GET','me'), driver_profile(app))
    app.profile = profile
    if mode == 'edit':
        return edit_form(app, profile, driver)

    email = (app.api.session.user or {}).get('email') or 'Não informado'
    account_label = 'Conta de demonstração' if demo else 'Conta de operador' if profile.get('account_type') == 'vendor' else 'Conta de motorista'

    def info(label, value):
        return ft.Column([
            ft.Text(label,size=13,color=theme.GRAY_TEXT),
            ft.Semantics(label=f"{label}: {value or 'Não informado'}",container=True,exclude_semantics=True,read_only=True,
                         content=ft.Text(value or 'Não informado',size=17,color=theme.TEXT_COLOR,selectable=True)),
        ],spacing=4)

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

    access = []
    if profile.get('operator_enabled') or profile.get('account_type') == 'vendor':
        vendor = getattr(app,'browsing_mode','consumer') == 'vendor'
        access = [card([
            ft.Text('Você está no modo operador' if vendor else 'Você está no modo motorista',size=14,color=theme.TEXT_COLOR),
            button('Usar como motorista' if vendor else 'Usar como operador',
                   app.action(lambda: app.switch_mode('consumer' if vendor else 'vendor')),secondary=True),
            ft.Text('A troca de modo mantém sua reserva ou recarga.',size=12,color=theme.GRAY_TEXT),
            ft.Text('Com a mesma conta, acompanhe receita, ocupação e alertas dos seus postos no painel web '
                    'do proprietário, com insights de IA.',size=12,color=theme.GRAY_TEXT),
        ])]

    settings = [
        ft.Switch(label='Tema escuro',value=theme.is_dark(),on_change=dark,data='preference'),
        button('Cupons para minhas recargas',app.link('coupons'),secondary=True),
    ]
    if not demo:
        settings.append(button('Alterar senha',app.link('profile',mode='password'),secondary=True))
    else:
        settings.append(ft.Text('Senha pública fixa: demo1234. Os dados simulados reiniciam ao sair.',size=12,color=theme.GRAY_TEXT))
    return ft.Column([
        title('Minha conta',account_label),
        ft.Container(ft.Column([
            info('Nome',profile.get('name')),info('E-mail',email),
            info('Telefone',profile.get('phone')),info('Carro elétrico',vehicle_text(profile,driver)),
        ],spacing=20),padding=ft.Padding(top=8,bottom=8)),
        button('Editar informações',app.link('profile',mode='edit'),secondary=True),
        *access,
        ft.ExpansionTile(title=ft.Text('Preferências e acesso',color=theme.TEXT_COLOR),
        expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,controls=settings,maintain_state=True),
        ft.Text('Sair reinicia os dados desta demonstração.' if demo else 'Sair não interrompe uma recarga em andamento.',size=12,color=theme.GRAY_TEXT),
    ],spacing=18,scroll=ft.ScrollMode.AUTO)


def edit_form(app, profile, driver=None):
    name, phone = field('Nome',profile.get('name') or ''),field('Telefone (opcional)',profile.get('phone') or '')
    for control, limit in ((name,100),(phone,30)):
        control.max_length = limit
        control.width = None
        control.counter = ''
    vehicle = saved_vehicle(driver)
    picker = VehiclePicker(vehicle, (driver or {}).get('presets'), allow_later=vehicle is None,
                           on_change=lambda _: app.page.update())
    async def save():
        if not name.value.strip():
            raise ApiError('Informe seu nome.')
        if len(name.value.strip()) > 100 or len(phone.value.strip()) > 30:
            raise ApiError('Confira o tamanho dos campos informados.')
        chosen = picker.read(strict=True)
        description = helpers.vehicle_name(chosen) if chosen else profile.get('vehicle_description')
        account = app.api.request('PATCH','me',{'name':name.value.strip(),'phone':phone.value.strip() or None,
                                                'vehicle_description':description or None})
        if chosen:
            # Mesmo carro do Modo motorista; as preferências do turno são mantidas.
            app.profile, _ = await asyncio.gather(account, save_vehicle(app.api, chosen, driver))
        else:
            app.profile = await account
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice('Perfil atualizado.')
        await app.go('profile')
    return ft.Column([
        title('Editar informações','Altere os campos e salve para atualizar sua conta.'),
        name,phone,
        card([ft.Text('Seu carro elétrico',size=14,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),
              ft.Text('Usado para estimar autonomia e planejar recargas no Modo motorista.',size=12,color=theme.GRAY_TEXT),
              picker.control],border=ft.Border.all(1,theme.LIGHT_GRAY)),
        button('Salvar informações',app.action(save)),
        button('Cancelar',app.link('profile'),secondary=True),
    ],spacing=16,scroll=ft.ScrollMode.AUTO)


def password_form(app):
    if getattr(app.api, 'is_demo', False):
        return ft.Column([title('Conta de demonstração','A senha pública desta conta é fixa; nenhuma credencial real é alterada.'),
                          button('Voltar à conta',app.link('profile'))],spacing=16)
    password = field('Nova senha', password=True)
    confirmation = field('Confirmar nova senha', password=True)
    for control in (password, confirmation):
        control.max_length = 128
        control.autocorrect = False
        control.enable_suggestions = False
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
    return ft.Column([
        title('Alterar senha', 'Você precisará entrar novamente após salvar.'),
        card(ft.Column([password, confirmation], spacing=16)),
        ft.Text('Você sairá deste app. Outros dispositivos pedirão login ao renovar o acesso; '
                'um acesso já emitido pode continuar válido até expirar. A recarga no equipamento não é interrompida.',
                size=13,color=theme.GRAY_TEXT),
        button('Salvar nova senha', submit),
        button('Cancelar', app.link('profile'), secondary=True),
    ], spacing=16, scroll=ft.ScrollMode.AUTO)
