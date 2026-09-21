import re

import flet as ft

from ..api_client import ApiError
from ..ui import motion, theme
from ..ui.components import flat_button, labeled_field, text_link, title


def auth_button(text, action, *, secondary=False):
    return flat_button(
        text,
        theme.WHITE if secondary else theme.RED,
        theme.TEXT_COLOR if secondary else '#FFFFFF',
        on_click=action,
        height=48,
        border=ft.Border.all(1, theme.LIGHT_GRAY) if secondary else None,
    )


def back_link(app):
    return ft.Container(
        ft.Row(
            [
                ft.Icon(ft.Icons.CHEVRON_LEFT, size=22, color=theme.TEXT_COLOR),
                ft.Text(
                    'Voltar',
                    size=16,
                    color=theme.TEXT_COLOR,
                    style=ft.TextStyle(decoration=ft.TextDecoration.UNDERLINE),
                ),
            ],
            spacing=2,
            tight=True,
        ),
        on_click=app.link('auth'),
        ink=True,
        alignment=ft.Alignment(-1, 0),
    )


def brand():
    return ft.Row(
        [
            ft.Container(
                ft.Icon(ft.Icons.EV_STATION, size=28, color='#FFFFFF'),
                width=44,
                height=44,
                bgcolor=theme.RED,
                border_radius=10,
                alignment=ft.Alignment(0, 0),
            ),
            ft.Text(
                'ChargeGrid',
                size=32,
                weight=ft.FontWeight.BOLD,
                color=theme.TEXT_COLOR,
                font_family='BarlowSemiBold',
            ),
        ],
        spacing=8,
        tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def account_selector(app, selection):
    options = []
    semantics = []
    indicator = ft.Container(
        bgcolor=theme.RED, height=44, expand=True, border_radius=7,
        offset=ft.Offset(1 if selection['value'] == 'vendor' else 0, 0),
        animate_offset=motion.animation(280), data='account-indicator',
    )

    def choose(value):
        async def changed(event):
            if getattr(app, 'active_actions', None) or selection['value'] == value:
                return
            theme.set_dark(getattr(app, 'dark_mode', theme.is_dark()))
            selection['value'] = value
            indicator.offset = ft.Offset(1 if value == 'vendor' else 0, 0)
            for option, accessible in zip(options, semantics):
                active = option.data == value
                option.content.color = '#FFFFFF' if active else theme.TEXT_COLOR
                option.content.weight = ft.FontWeight.BOLD if active else ft.FontWeight.NORMAL
                accessible.selected = active
            app.page.update()
        return changed

    def option(label, value):
        active = selection['value'] == value
        control = ft.Container(
            ft.Text(
                label,
                size=14,
                color='#FFFFFF' if active else theme.TEXT_COLOR,
                weight=ft.FontWeight.BOLD if active else ft.FontWeight.NORMAL,
                text_align=ft.TextAlign.CENTER,
            ),
            height=44,
            expand=True,
            alignment=ft.Alignment(0, 0),
            on_click=choose(value),
            data=value,
            ink=False,
        )
        options.append(control)
        accessible = ft.Semantics(content=control, selected=active, expand=True)
        semantics.append(accessible)
        return accessible

    return ft.Container(
        ft.Stack([
            ft.Container(ft.Row([indicator, ft.Container(expand=True)], spacing=0),
                         left=0, right=0, top=0, bottom=0),
            ft.Container(ft.Row([option('Sou consumidor', 'consumer'), option('Sou vendedor', 'vendor')], spacing=0),
                         left=0, right=0, top=0, bottom=0),
        ]),
        height=46,
        bgcolor=theme.WHITE,
        border=ft.Border.all(1, theme.LIGHT_GRAY),
        border_radius=8,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
    )


async def build(app, mode='login', email_value='', account_type='consumer'):
    selection = {'value': account_type if account_type in ('consumer', 'vendor') else 'consumer'}
    email_field = labeled_field('E-mail', email_value, 'voce@email.com')
    password_field = labeled_field('Senha', hint='••••••••', password=True)
    name_field = labeled_field('Nome completo', hint='Seu nome')
    code_field = labeled_field('Código recebido por e-mail', hint='Código')
    email = email_field.controls[1]
    password = password_field.controls[1]
    name = name_field.controls[1]
    code = code_field.controls[1]
    email.keyboard_type = ft.KeyboardType.EMAIL
    email.autocorrect = False
    password.autocorrect = False
    feedback = ft.Text('', size=13, color=theme.RED, visible=False)
    submit_button = None
    submitting = False
    errors = {}
    for group in (name_field, email_field, password_field, code_field):
        control = group.controls[1]
        error = ft.Semantics(content=ft.Text('', size=12, color=theme.ERROR), live_region=True, visible=False)
        group.controls.append(error)
        control.offset = ft.Offset(0, 0)
        control.animate_offset = ft.Animation(motion.duration(60), ft.AnimationCurve.EASE_IN_OUT)
        errors[id(control)] = error

        def clear_error(field, message):
            async def changed(event):
                theme.set_dark(getattr(app, 'dark_mode', theme.is_dark()))
                if message.visible:
                    message.visible = False
                    field.border_color = theme.LIGHT_GRAY
                    field.focused_border_color = None
                    app.page.update()
            return changed

        control.on_change = clear_error(control, error)

    async def show_invalid(control, message):
        error = errors[id(control)]
        error.content.value = message
        error.visible = True
        control.border_color = theme.ERROR
        control.focused_border_color = theme.ERROR
        feedback.visible = False
        app.page.update()
        if isinstance(app.page, ft.Page):
            await control.focus()
        generation = getattr(app, 'generation', 0)
        await motion.shake(control, app.page.update, reduced=getattr(app, 'reduced_motion', False),
                           is_current=lambda: not getattr(app, 'closed', False) and generation == getattr(app, 'generation', 0))

    def show_feedback(message, color=theme.RED):
        feedback.value = message
        feedback.color = color
        feedback.visible = True
        app.page.update()

    async def submit():
        nonlocal submitting
        if submitting:
            return
        address = email.value.strip()
        full_name = name.value.strip()
        password_value = password.value or ''
        validation_message = None
        invalid_field = email
        if mode == 'register' and not full_name:
            invalid_field = name
            validation_message = 'Informe seu nome completo.'
        elif mode == 'register' and len(full_name) > 100:
            invalid_field = name
            validation_message = 'Use até 100 caracteres no nome.'
        elif len(address) > 254:
            validation_message = 'O e-mail informado é muito longo.'
        elif not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', address):
            validation_message = 'Informe um e-mail válido.'
        elif mode == 'login' and not password_value:
            invalid_field = password
            validation_message = 'Informe sua senha.'
        elif mode in ('register', 'reset') and len(password_value) < 8:
            invalid_field = password
            validation_message = 'A senha precisa ter pelo menos 8 caracteres.'
        elif len(password_value) > 128:
            invalid_field = password
            validation_message = 'Use até 128 caracteres na senha.'
        elif mode == 'reset' and len(code.value.strip()) < 6:
            invalid_field = code
            validation_message = 'Informe o código recebido por e-mail.'

        if validation_message:
            await show_invalid(invalid_field, validation_message)
            return

        submitting = True
        show_feedback(
            'Criando sua conta…' if mode == 'register' else 'Aguarde…',
            theme.GRAY_TEXT,
        )
        submit_button.disabled = True
        submit_button.opacity = 0.65
        app.page.update()
        try:
            if mode == 'login':
                try:
                    await app.api.login(address, password_value)
                except ApiError as exc:
                    if exc.code != 'email_not_confirmed':
                        raise
                    await app.go('auth', mode='verify', email_value=address)
                    app.notice(str(exc))
                    return
                await app.signed_in()
            elif mode == 'register':
                result = await app.api.request(
                    'POST',
                    'auth/register',
                    {'email': address, 'password': password_value, 'name': full_name,
                     'account_type': selection['value']},
                    auth=False,
                )
                if result.get('access_token') and result.get('refresh_token'):
                    app.api.session.update(result)
                    await app.signed_in()
                elif result.get('requires_email_confirmation'):
                    await app.go('auth', mode='verify', email_value=address)
                else:
                    await app.go('auth', email_value=address)
                    app.notice('Confira seu e-mail. Se já tem uma conta, entre com sua senha.')
            elif mode == 'forgot':
                result = await app.api.request(
                    'POST', 'auth/password/forgot', {'email': address}, auth=False
                )
                show_feedback(result['message'], theme.GREEN)
            else:
                await app.api.request(
                    'POST',
                    'auth/password/reset',
                    {'email': address, 'code': code.value, 'password': password_value},
                    auth=False,
                )
                await app.go('auth', email_value=address)
                app.notice('Senha atualizada. Entre com sua nova senha.')
        except ApiError as exc:
            message = str(exc)
            if exc.code == 'weak_password':
                await show_invalid(password, message)
            else:
                show_feedback(message)
        finally:
            submitting = False
            submit_button.disabled = False
            submit_button.opacity = 1
            app.page.update()

    async def resend():
        address = email.value.strip()
        if '@' not in address or '.' not in address.rpartition('@')[2]:
            show_feedback('Informe um e-mail válido.')
            return
        await app.api.request('POST', 'auth/resend-signup', {'email': address}, auth=False)
        show_feedback(
            'Se a conta ainda precisar de confirmação, uma nova mensagem será enviada.',
            theme.GREEN,
        )

    async def return_to_login():
        await app.link('auth', email_value=email.value.strip())(None)

    if mode == 'login':
        submit_button = auth_button('Entrar', app.action(submit))
        password.on_submit = app.action(submit)
        controls = [
            brand(),
            email_field,
            password_field,
            text_link('Esqueci minha senha', app.link('auth', mode='forgot', email_value=email_value)),
            submit_button,
            feedback,
            auth_button('Criar conta', app.link('auth', mode='register'), secondary=True),
        ]
        spacing = 20
    elif mode == 'register':
        submit_button = auth_button('Criar conta', app.action(submit))
        password.on_submit = app.action(submit)
        controls = [
            back_link(app),
            title('Criar conta', 'Escolha como você vai usar o ChargeGrid.'),
            account_selector(app, selection),
            ft.Text('Vendedores vinculam seus equipamentos pelo QR fornecido com o ponto.', size=12, color=theme.GRAY_TEXT),
            name_field,
            email_field,
            password_field,
            submit_button,
            feedback,
        ]
        spacing = 16
    elif mode == 'forgot':
        submit_button = auth_button('Enviar link', app.action(submit))
        email.on_submit = app.action(submit)
        controls = [
            back_link(app),
            title('Recuperar senha', 'Enviaremos um link de redefinição para seu e-mail.'),
            email_field,
            submit_button,
            feedback,
        ]
        spacing = 22
    elif mode == 'verify':
        controls = [
            back_link(app),
            title(
                'Verifique seu e-mail',
                'Abra o link de confirmação. Se já confirmou, volte para entrar.',
            ),
            email_field,
            auth_button('Voltar para entrar', app.action(return_to_login)),
            auth_button('Reenviar confirmação', app.action(resend), secondary=True),
            feedback,
        ]
        spacing = 22
    else:
        submit_button = auth_button('Alterar senha', app.action(submit))
        password.on_submit = app.action(submit)
        controls = [
            back_link(app),
            title('Nova senha'),
            email_field,
            code_field,
            password_field,
            submit_button,
            feedback,
        ]
        spacing = 22

    return ft.Column(
        controls,
        spacing=spacing,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        alignment=ft.MainAxisAlignment.CENTER,
        scroll=ft.ScrollMode.AUTO,
    )
