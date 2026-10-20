"""Entrega de arquivos gerados pela API (recibo em PDF, exportações CSV/PDF) ao usuário.

No celular abre a folha de compartilhamento do sistema (``ft.Share``: salvar em Arquivos, enviar por
WhatsApp/e-mail...). No navegador e no desktop abre o "Salvar como" (``ft.FilePicker.save_file`` com os
bytes, que no navegador vira um download). Se o primeiro caminho falhar, tenta o outro.
"""

import logging

import flet as ft

log = logging.getLogger(__name__)

MIME = {'pdf': 'application/pdf', 'csv': 'text/csv'}


def _platform(app):
    page = getattr(app, 'page', None)
    web = bool(getattr(page, 'web', False))
    platform = getattr(page, 'platform', None)
    try:
        mobile = bool(platform is not None and platform.is_mobile())
    except (AttributeError, TypeError):
        mobile = False
    return web, mobile


async def _share(data, filename, mime):
    await ft.Share().share_files([ft.ShareFile.from_bytes(data, mime_type=mime, name=filename)],
                                 title=filename, subject=filename)
    return 'Arquivo pronto: escolha onde salvar ou com quem compartilhar.'


async def _save(data, filename, extension):
    path = await ft.FilePicker().save_file(dialog_title='Salvar arquivo', file_name=filename,
                                           file_type=ft.FilePickerFileType.CUSTOM,
                                           allowed_extensions=[extension], src_bytes=data)
    # Desktop devolve o caminho escolhido; no navegador o arquivo vai para os downloads.
    return f'Arquivo salvo em {path}.' if path else f'{filename} enviado para os seus downloads.'


async def deliver(app, data, filename):
    """Compartilha/salva ``data`` (bytes) como ``filename``; devolve a mensagem para o aviso."""
    if not data:
        raise ValueError('O servidor devolveu um arquivo vazio.')
    extension = filename.rsplit('.', 1)[-1].lower()
    mime = MIME.get(extension, 'application/octet-stream')
    web, mobile = _platform(app)
    first, second = ((lambda: _share(data, filename, mime)), (lambda: _save(data, filename, extension)))
    if web or not mobile:
        first, second = second, first
    try:
        return await first()
    except Exception:  # serviço indisponível nesta plataforma: tenta o outro caminho
        log.warning('file delivery fallback for %s', filename, exc_info=True)
        return await second()
