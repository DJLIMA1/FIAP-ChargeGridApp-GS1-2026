"""Atualização do APK sem servidor próprio: cada versão é uma release pública no GitHub.

``tools/release_apk.py`` publica a release ``app-v<versão>`` com ``chargegrid-<versão>.apk``. Ao abrir,
o app Android consulta ``releases/latest``; se houver versão maior que a empacotada, oferece o
download. O Android baixa o arquivo e o usuário instala por cima (mesma assinatura: dados mantidos).
Qualquer falha (sem rede, limite da API do GitHub, release sem APK) é silenciosa.
"""
import re

import httpx

REPOSITORY = 'DJLIMA1/FIAP-ChargeGridApp-GS1-2026'
LATEST_URL = f'https://api.github.com/repos/{REPOSITORY}/releases/latest'
TAG_PREFIX = 'app-v'
TIMEOUT_SECONDS = 6


def parse_version(text):
    """``'app-v0.6.10'`` / ``'0.6.10'`` -> ``(0, 6, 10)``; ``None`` se não for uma versão."""
    match = re.fullmatch(r'(?:app-)?v?(\d+)\.(\d+)\.(\d+)', str(text or '').strip())
    return tuple(int(part) for part in match.groups()) if match else None


def release_info(data):
    """Versão, link do APK e notas de uma resposta de ``releases/latest`` (ou ``None``)."""
    if not isinstance(data, dict) or data.get('draft') or data.get('prerelease'):
        return None
    tag = str(data.get('tag_name') or '')
    version = parse_version(tag) if tag.startswith(TAG_PREFIX) else None
    apk = next((asset for asset in data.get('assets') or []
                if str(asset.get('name', '')).endswith('.apk') and asset.get('browser_download_url')), None)
    if not version or not apk:
        return None
    return {'version': '.'.join(map(str, version)), 'url': apk['browser_download_url'],
            'size_mb': round((apk.get('size') or 0) / 1_048_576), 'notes': str(data.get('body') or '').strip()}


def is_newer(latest, current):
    latest, current = parse_version(latest), parse_version(current)
    return bool(latest and current and latest > current)


async def available_update(current_version, client=None):
    """Release mais nova que ``current_version``; ``None`` se não houver ou se a consulta falhar."""
    if not parse_version(current_version):
        return None
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as own:
                response = await own.get(LATEST_URL, headers={'Accept': 'application/vnd.github+json'})
        else:
            response = await client.get(LATEST_URL, headers={'Accept': 'application/vnd.github+json'})
        response.raise_for_status()
        info = release_info(response.json())
    except (httpx.HTTPError, ValueError):
        return None
    return info if info and is_newer(info['version'], current_version) else None
