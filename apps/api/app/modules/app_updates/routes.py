"""Atualização do app Android pelo nosso servidor (sem depender do GitHub).

``tools/release_apk.py`` envia o APK e ``app/latest.json`` ao Vercel Blob (público). ``GET
/v1/app/latest`` (sem login: o aviso aparece antes de entrar) devolve esse manifesto validado,
com cache curto em memória. O app compara ``version`` com a versão empacotada e oferece ``url``.
"""
import re
import threading
import time

import httpx
from fastapi import APIRouter

from ...config import settings
from ...errors import fail

router = APIRouter()
TTL_SECONDS = 60
TIMEOUT_SECONDS = 4
_cache: dict[str, tuple[float, dict | None]] = {}
_lock = threading.Lock()


def _valid(data) -> dict | None:
    if not isinstance(data, dict):
        return None
    version, url = str(data.get("version") or ""), str(data.get("url") or "")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not url.startswith("https://") or not url.endswith(".apk"):
        return None
    return {
        "version": version,
        "build": int(data["build"]) if str(data.get("build", "")).isdigit() else None,
        "url": url,
        "size_bytes": int(data["size_bytes"]) if str(data.get("size_bytes", "")).isdigit() else None,
        "sha256": data.get("sha256") if re.fullmatch(r"[0-9a-f]{64}", str(data.get("sha256") or "")) else None,
        "notes": str(data.get("notes") or "")[:1000],
        "published_at": data.get("published_at"),
    }


def _manifest() -> dict | None:
    now = time.monotonic()
    with _lock:
        hit = _cache.get("latest")
        if hit and now - hit[0] < TTL_SECONDS:
            return hit[1]
    try:
        response = httpx.get(settings().app_manifest_url, timeout=TIMEOUT_SECONDS,
                             headers={"Cache-Control": "no-cache"})
        response.raise_for_status()
        manifest = _valid(response.json())
    except (httpx.HTTPError, ValueError):
        manifest = None
    with _lock:
        _cache["latest"] = (now, manifest)
    return manifest


def clear_cache():
    with _lock:
        _cache.clear()


@router.get("/app/latest")
def latest():
    manifest = _manifest()
    if manifest is None:
        fail("updates_unavailable", "Nenhuma versão publicada agora", 404)
    return manifest
