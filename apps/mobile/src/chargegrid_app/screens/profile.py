import flet as ft

from ..api_client import ApiError
from ..ui import theme
from ..ui.components import button, card, field, title


async def build(app):
    profile = await app.api.request('GET','me')
    app.profile = profile
    name, phone, vehicle = field('Nome',profile.get('name') or ''),field('Telefone (opcional)',profile.get('phone') or ''),field('Veículo (opcional)',profile.get('vehicle_description') or '')
    async def save():
        if not name.value.strip():
            raise ApiError('Informe seu nome.')
        app.profile = await app.api.request('PATCH','me',{'name':name.value.strip(),'phone':phone.value.strip() or None,'vehicle_description':vehicle.value.strip() or None})
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice('Perfil atualizado.')
    async def dark(e):
        if hasattr(app, 'prepare_navigation') and not await app.prepare_navigation():
            e.control.value = app.dark_mode
            app.page.update()
            return
        theme.set_dark(e.control.value)
        app.dark_mode = theme.is_dark()
        saved = app.preferences.save(theme.is_dark())
        await app.go('profile')
        if not saved:
            app.notice('Tema aplicado nesta sessão. Não foi possível salvar a preferência no dispositivo.')
    operator_access = [button('Meus equipamentos e postos',app.link('operator'),secondary=True)] if profile.get('operator_enabled') or profile.get('account_type') == 'vendor' else []
    account_label = 'Conta de vendedor' if profile.get('account_type') == 'vendor' else 'Conta de consumidor'
    status = 'Gerencie seus postos e vincule novos equipamentos pelo QR.' if profile.get('operator_enabled') else ('Escaneie o QR do equipamento para vincular seu primeiro ponto. Você também pode usar as recargas.' if profile.get('account_type') == 'vendor' else 'Encontre um posto e acompanhe suas recargas pelo aplicativo.')
    settings = card(ft.Column([
        ft.Text('Configurações do aplicativo', size=18, weight=ft.FontWeight.BOLD, color=theme.TEXT_COLOR),
        ft.Switch(label='Tema escuro', value=theme.is_dark(), on_change=dark, data='preference'),
    ], spacing=12))
    return ft.Column([title('Minha conta',app.api.session.user.get('email','') if app.api.session.user else ''),ft.Text(account_label,color=theme.GRAY_TEXT),card(ft.Column([name,phone,vehicle],spacing=12)),button('Salvar informações',app.action(save)),ft.Text(status,color=theme.GRAY_TEXT),*operator_access,settings,button('Meus cupons',app.link('coupons'),secondary=True),button('Sair da conta',app.action(app.logout),secondary=True),ft.Text('Sair não interrompe uma recarga em andamento.',size=12,color=theme.GRAY_TEXT)],scroll=ft.ScrollMode.AUTO,spacing=15)
