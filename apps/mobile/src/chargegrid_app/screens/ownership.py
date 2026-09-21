import flet as ft

from ..api_client import ApiError
from ..services.ownership import claim_token
from ..ui import theme
from ..ui.components import button, card, field, title


async def build(app, station_id=None):
    credential = field('Código privado do QR')
    credential.password = True
    credential.autocorrect = False
    credential.enable_suggestions = False
    credential.hint_text = 'Escaneie o QR ou cole o código privado'
    hint = ft.Text('O QR é privado e só pode vincular o ponto a um proprietário.',
                   size=13, color=theme.GRAY_TEXT)
    preview = ft.Container(visible=False)
    scanner = None
    claimed = False

    def stop_camera():
        nonlocal scanner
        if scanner is not None:
            scanner.active = False
        preview.content = None
        preview.visible = False
        scanner = None
        camera_button.visible = True
        cancel_camera.visible = False

    async def cancel_scan():
        stop_camera()
        app.page.update()

    async def scan():
        nonlocal scanner
        if getattr(app.page, 'web', False):
            raise ApiError('A câmera está disponível no APK Android. No navegador, cole o código privado do QR abaixo.')
        try:
            from chargegrid_scanner import QRScanner
        except ImportError as exc:
            raise ApiError('Leitor não instalado nesta versão. Cole o código privado ou instale o APK atualizado.') from exc

        async def detected(event):
            if scanner is None:
                return
            stop_camera()
            try:
                credential.value = claim_token(event.data)
                hint.value = 'QR reconhecido. Confirme abaixo para vincular o ponto à sua conta.'
                hint.color = theme.GREEN
            except ApiError as exc:
                app.notice(str(exc))
            app.page.update()

        async def failed(event):
            if scanner is None:
                return
            stop_camera()
            app.notice('Não foi possível abrir a câmera. Confira a permissão nas configurações ou cole o código privado.')
            app.page.update()

        scanner = QRScanner(active=True, on_scan=detected, on_error=failed)
        preview.content = scanner
        preview.height = 260
        preview.visible = True
        camera_button.visible = False
        cancel_camera.visible = True
        app.page.update()

    async def claim():
        nonlocal claimed
        if claimed:
            return
        token = claim_token(credential.value)
        stop_camera()
        body = {'token': token}
        if station_id:
            body['station_id'] = station_id
        result = await app.api.request('POST', 'ownership/claim', body)
        claimed = True
        credential.value = ''
        # The claim response confirms this permission; the destination reloads
        # /me. Do not strand a successful claim on a redundant network request.
        app.profile = {**app.profile, 'operator_enabled': True}
        if hasattr(app, 'mark_saved'):
            app.mark_saved()
        app.notice('Ponto vinculado. Vamos configurar sua estação antes de publicá-la.')
        await app.go('operator', station_id=result['station_id'], point_id=result['connector_id'],
                     onboarding=True, step=1)

    camera_button = button('Abrir câmera para ler o QR', app.action(scan))
    cancel_camera = button('Fechar câmera', app.action(cancel_scan), secondary=True)
    cancel_camera.visible = False
    return ft.Column([
        title('Vincular tela', 'Seu ponto, na sua conta'),
        card([
            ft.Icon(ft.Icons.QR_CODE_SCANNER, size=42, color=theme.RED),
            ft.Text('Aponte a câmera para o QR exibido no visor do ESP32.',
                    color=theme.TEXT_COLOR),
            hint,
        ]),
        camera_button, preview, cancel_camera, credential,
        button('Vincular ponto à minha conta', app.action(claim)),
        ft.Text('O QR aparece no visor somente enquanto o ponto não tem dono. '
                'Se a tela mostra “Disponível”, ela já está vinculada; abra Meus postos para editá-la. '
                'O código de recarga continua separado do QR de propriedade.',
                size=12, color=theme.GRAY_TEXT),
        button('Voltar', app.link('operator', **({'station_id': station_id} if station_id else {})), secondary=True),
    ], spacing=15, scroll=ft.ScrollMode.AUTO)
