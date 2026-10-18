import flet as ft

from ..api_client import ApiError
from ..services.ownership import claim_token
from ..ui import design, theme
from .setup_ui import cta, setup_field, setup_title, status_card


def _intro_card(destination, paragraphs):
    """Cartão escuro: [destino] + ícone de QR + parágrafo em negrito + parágrafo regular (228 pt na referência)."""
    leading = ft.TextStyle(height=1.8)
    return ft.Container(status_card(
        *destination,
        ft.Container(ft.Icon(ft.Icons.QR_CODE_SCANNER, size=64, color=theme.TEXT_COLOR),
                     alignment=ft.Alignment(0, 0), height=64),
        ft.Container(height=13.5),
        design.txt(paragraphs[0], 11.5, 'bold', style=leading),
        ft.Container(height=21.5),
        design.txt(paragraphs[1], 11.5, 'regular', style=leading),
        padding=14, spacing=0, top=22, height=None if destination else 228),
        margin=ft.Margin(left=0, top=-7, right=0, bottom=0))


async def build(app, station_id=None, show_real=False, **_):
    is_demo = bool(getattr(app.api,'is_demo',False)) and not show_real
    station = await app.api.request('GET',f'stations/{station_id}') if station_id else None
    credential_box = setup_field('Código privado do QR', hint='Código privado do QR', rest_bg='#313131',
                                 text_size=13.6)
    credential = credential_box.controls[1]
    credential_box.controls[0].visible = False
    credential.password = True
    credential.autocorrect = False
    credential.enable_suggestions = False
    credential.hint_text = 'Código privado do QR'
    credential.can_reveal_password = False
    credential.height = 49
    hint = design.txt('', 12, 'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER, visible=False)
    preview = ft.Container(visible=False)
    scanner = None
    claimed = False
    demo_token = None

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
                hint.visible = True
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
        app.notice('Ponto vinculado ao posto. Agora confira o conector e a tarifa.' if station_id else
                   'Ponto vinculado. Vamos configurar seu novo posto antes de publicá-lo.')
        await app.go('operator', station_id=result['station_id'], point_id=result['connector_id'],
                     onboarding=True, step=2 if station_id else 1,
                     **({'existing_station':True} if station_id else {}))

    camera_button = cta('Escanear QR Code', app.action(scan))
    cancel_camera = cta('Fechar câmera', app.action(cancel_scan), primary=False)
    cancel_camera.visible = False
    back = app.link('operator', **({'station_id': station_id} if station_id else {}))
    destination = ([design.txt('ADICIONAR PONTO AO POSTO', 11, 'bold', theme.ACCENT),
                    design.txt(station.get('name', 'Posto selecionado'), 16, 'bold'),
                    design.txt(station.get('address', ''), 12, 'regular', theme.GRAY_TEXT)] if station else [])
    if is_demo:
        from ..demo import DEMO_CLAIM_TOKEN

        async def add_demo_equipment():
            nonlocal demo_token
            if demo_token is None:
                demo_token = app.api.new_claim_token() if hasattr(app.api, 'new_claim_token') else DEMO_CLAIM_TOKEN
            credential.value = demo_token
            await claim()

        return design.page(
            setup_title(app, 'Vincular Tela'),
            _intro_card(destination, [
                'Adicione um equipamento simulado a esta conta de demonstração.',
                'Depois informe nome, endereço e tarifa. ' + (
                    'O posto reúne os pontos no mesmo endereço. ' if station else
                    'Será um novo local simulado, publicado só quando você quiser. ') +
                'Este equipamento é inteiramente fictício: nenhuma câmera, QR físico ou carregador real é necessário.']),
            cta('Adicionar equipamento simulado', app.action(add_demo_equipment)),
            design.txt('O vínculo é criado apenas na demonstração. Você poderá editar, publicar e testar uma '
                       'recarga simulada.', 12, 'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER),
            cta('Voltar', back, primary=False),
            gap=16)
    return design.page(
        setup_title(app, 'Vincular Tela'),
        _intro_card(destination, [
            'A tela sem dono mostra um QR de vinculação.\nEscaneie-o para se tornar o proprietário.',
            'Depois informe nome, endereço e tarifa. O ponto só aparece aos motoristas quando você publicar.']),
        camera_button, preview, cancel_camera, hint,
        ft.Container(height=25),
        design.txt('Inserir o Código Privado do QR', 14.2, 'regular', text_align=ft.TextAlign.CENTER),
        credential_box,
        cta('Vincular ponto à minha conta', app.action(claim)),
        gap=16)
