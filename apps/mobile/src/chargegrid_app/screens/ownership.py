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


CAMERA_HEIGHT = 470  # área da câmera no lugar do cartão (a tela rola em aparelhos baixos)
WEB_CAMERA = 'A câmera está disponível no APK Android. No navegador, cole o código privado do QR abaixo.'
NO_SCANNER = 'Leitor não instalado nesta versão. Cole o código privado ou instale o APK atualizado.'
CAMERA_FAILED = 'Não foi possível abrir a câmera. Confira a permissão nas configurações ou cole o código privado.'


def _set_primary(button, primary):
    """Alterna um ``cta`` entre principal (claro) e secundário sem recriá-lo."""
    button.bgcolor = theme.BTN_PRIMARY if primary else theme.BTN_SECONDARY
    button.content.color = theme.BTN_PRIMARY_FG if primary else theme.BTN_SECONDARY_FG


def _text_link(text, on_click):
    return ft.Container(design.txt(text, 12.5, 'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER),
                        on_click=on_click, ink=False, alignment=ft.Alignment(0, 0),
                        padding=ft.Padding(left=8, right=8, top=6, bottom=6))


async def build(app, station_id=None, show_real=False, scan=False, **_):
    """Vincular uma central pelo QR privado.

    Uma ação só: "Escanear QR Code". A câmera ocupa o lugar do cartão explicativo (com "Cancelar" e o
    ``<`` para fechá-la). Colar o código é o recurso quando não há câmera (navegador, versão sem leitor,
    permissão negada): o campo aparece pelo link discreto ou sozinho quando a câmera não abre. Ler o QR
    só preenche o código; o vínculo exige tocar em "Vincular ponto à minha conta". ``scan=True`` abre a
    câmera ao entrar (ou o campo de colar, se não houver câmera).
    """
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
    claimed = False
    demo_token = None
    credential_box.visible = False
    hint = design.txt('', 12, 'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER, visible=False)
    preview = ft.Container(height=CAMERA_HEIGHT, border_radius=20, bgcolor='#000000',
                           clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
    scanner = None

    def show_camera(open_):
        intro.visible = not open_
        actions.visible = not open_
        camera_view.visible = open_

    def stop_camera():
        nonlocal scanner
        if scanner is None:  # nada aberto (inclui o caminho de demonstração, sem câmera)
            return
        scanner.active = False
        preview.content = None
        scanner = None
        show_camera(False)

    def open_fallback(message=None):
        """Mostra o campo de colar o código e passa "Vincular" a ação principal."""
        credential_box.visible = True
        confirm_button.visible = True
        fallback_link.visible = False
        _set_primary(scan_button, False)
        if message:
            hint.value = message
            hint.color = theme.GRAY_TEXT
            hint.visible = True

    def start_camera():
        """Abre a câmera no lugar do conteúdo; sem câmera, abre o campo e devolve o motivo."""
        nonlocal scanner
        if getattr(app.page, 'web', False):
            open_fallback()
            return WEB_CAMERA
        try:
            from chargegrid_scanner import QRScanner
        except ImportError:
            open_fallback()
            return NO_SCANNER

        async def detected(event):
            if scanner is None:
                return
            stop_camera()
            open_fallback()
            try:
                credential.value = claim_token(event.data)
                hint.value = 'QR reconhecido. Toque em Vincular ponto à minha conta para concluir.'
                hint.color = theme.GREEN
                hint.visible = True
                scan_button.content.value = 'Escanear novamente'
            except ApiError as exc:
                app.notice(str(exc))
            app.page.update()

        async def failed(event):
            if scanner is None:
                return
            stop_camera()
            open_fallback()
            app.notice(CAMERA_FAILED)
            app.page.update()

        scanner = QRScanner(active=True, on_scan=detected, on_error=failed)
        preview.content = scanner
        show_camera(True)
        return None

    async def scan_action():
        message = start_camera()
        if message:
            raise ApiError(message)  # app.action mostra o aviso e redesenha (o campo já está visível)
        app.page.update()

    async def cancel_scan(event=None):
        stop_camera()
        app.page.update()

    async def title_back(event=None):
        # Com a câmera aberta, o "<" só fecha a câmera; senão volta como nas demais telas.
        if scanner is not None:
            await cancel_scan()
        elif getattr(app, 'back', None):
            await app.back(event)

    async def reveal_fallback(event=None):
        open_fallback()
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
        app.notice('Ponto vinculado ao posto. Agora confira o carregador e a tarifa.' if station_id else
                   'Ponto vinculado. Vamos configurar seu novo posto antes de publicá-lo.')
        await app.go('operator', station_id=result['station_id'], point_id=result['connector_id'],
                     onboarding=True, step=2 if station_id else 1,
                     **({'existing_station':True} if station_id else {}))

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
            setup_title(app, 'Vincular Central'),
            _intro_card(destination, [
                'Adicione uma central simulada a esta conta de demonstração.',
                'Depois informe nome, endereço e tarifa. ' + (
                    'O posto reúne os pontos no mesmo endereço. ' if station else
                    'Será um novo local simulado, publicado só quando você quiser. ') +
                'Esta central é inteiramente fictícia: nenhuma câmera, QR físico ou carregador real é necessário.']),
            cta('Adicionar central simulada', app.action(add_demo_equipment)),
            design.txt('O vínculo é criado apenas na demonstração. Você poderá editar, publicar e testar uma '
                       'recarga simulada.', 12, 'regular', theme.GRAY_TEXT, text_align=ft.TextAlign.CENTER),
            cta('Voltar', back, primary=False),
            gap=16)
    intro = _intro_card(destination, [
        'A central sem dono mostra um QR de vinculação.\nEscaneie-o para se tornar o proprietário.',
        'Depois informe nome, endereço e tarifa. O ponto só aparece aos motoristas quando você publicar.'])
    scan_button = cta('Escanear QR Code', app.action(scan_action))
    confirm_button = cta('Vincular ponto à minha conta', app.action(claim))
    confirm_button.visible = False
    fallback_link = _text_link('Não consegue escanear? Colar código do QR', reveal_fallback)
    actions = ft.Column([hint, credential_box, confirm_button, scan_button, fallback_link], spacing=16,
                        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    camera_view = ft.Column([
        preview,
        design.txt('Aponte a câmera para o QR exibido na tela da central.', 12.5, 'regular', theme.GRAY_TEXT,
                   text_align=ft.TextAlign.CENTER),
        cta('Cancelar', cancel_scan, primary=False)],
        spacing=16, visible=False, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    if scan:
        message = start_camera()
        if message:
            open_fallback(message)
    return design.page(
        setup_title(app, 'Vincular Central', on_back=title_back),
        intro, actions, camera_view,
        gap=16)
