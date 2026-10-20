"""Atualização do APK pelo nosso servidor.

``tools/release_apk.py`` envia o APK e o manifesto ``app/latest.json`` ao Vercel Blob; a API
devolve o manifesto em ``GET /v1/app/latest`` (sem login). Ao abrir (e ao voltar ao app), o app
Android compara ``version`` com a versão empacotada e, se houver uma maior, oferece o download.
O Android baixa o APK e o usuário instala por cima (mesma assinatura: dados mantidos).
Qualquer falha (sem rede, sem versão publicada) é silenciosa.
"""
import re

import httpx

from ..config import api_url

TIMEOUT_SECONDS = 6


def latest_url():
    return api_url() + '/app/latest'


def parse_version(text):
    """``'0.6.10'`` (ou ``'app-v0.6.10'``) -> ``(0, 6, 10)``; ``None`` se não for uma versão."""
    match = re.fullmatch(r'(?:app-)?v?(\d+)\.(\d+)\.(\d+)', str(text or '').strip())
    return tuple(int(part) for part in match.groups()) if match else None


def release_info(data):
    """Versão, link do APK, tamanho e notas do manifesto da API (ou ``None`` se inválido)."""
    if not isinstance(data, dict):
        return None
    version, url = parse_version(data.get('version')), str(data.get('url') or '')
    if not version or not url.startswith('https://') or not url.endswith('.apk'):
        return None
    size = data.get('size_bytes')
    return {'version': '.'.join(map(str, version)), 'url': url,
            'size_mb': round(size / 1_048_576) if isinstance(size, int) and size > 0 else None,
            'notes': str(data.get('notes') or '').strip()}


def is_newer(latest, current):
    latest, current = parse_version(latest), parse_version(current)
    return bool(latest and current and latest > current)


async def available_update(current_version, client=None):
    """Versão publicada mais nova que ``current_version``; ``None`` se não houver ou se a consulta falhar."""
    if not parse_version(current_version):
        return None
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as own:
                response = await own.get(latest_url())
        else:
            response = await client.get(latest_url())
        response.raise_for_status()
        info = release_info(response.json())
    except (httpx.HTTPError, ValueError):
        return None
    return info if info and is_newer(info['version'], current_version) else None
