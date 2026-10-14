"""Transporte ``httpx`` para o navegador (Pyodide / ``flet build web``).

No Pyodide não há sockets: o transporte padrão do ``httpx`` falha ao conectar.
Este transporte converte cada pedido em ``fetch`` do navegador via
``pyodide.http.pyfetch``. Só é usado quando ``sys.platform == 'emscripten'``;
app desktop e APK continuam com o transporte padrão.
"""

import asyncio

import httpx

# Cabeçalhos controlados pelo navegador (proibidos no fetch) ou que mudariam a
# requisição (User-Agent customizado). O navegador define os valores corretos.
_SKIPPED_REQUEST_HEADERS = {'host', 'connection', 'content-length', 'accept-encoding', 'user-agent'}
# O fetch já entrega o corpo descompactado; repassar estes cabeçalhos faria o
# httpx tentar descompactar de novo.
_SKIPPED_RESPONSE_HEADERS = {'content-encoding', 'content-length', 'transfer-encoding'}


def _pyfetch():
    from pyodide.http import pyfetch  # disponível apenas no Pyodide
    return pyfetch


class PyodideFetchTransport(httpx.AsyncBaseTransport):
    """Envia pedidos com ``fetch`` (mesma origem; redirecionamentos viram erro).

    ``redirect='error'`` mantém a política do ``ApiClient`` (``follow_redirects=False``):
    um redirecionamento nunca leva o token para outro endereço.
    """

    def __init__(self, timeout=12, fetch=None):
        self.timeout = timeout
        self._fetch = fetch

    async def handle_async_request(self, request):
        fetch = self._fetch or _pyfetch()
        headers = {key: value for key, value in request.headers.items()
                   if key.lower() not in _SKIPPED_REQUEST_HEADERS}
        options = {'method': request.method, 'headers': headers, 'redirect': 'error',
                   'credentials': 'same-origin', 'cache': 'no-store'}
        body = await request.aread()
        if body:
            try:
                options['body'] = body.decode('utf-8')
            except UnicodeDecodeError:
                options['body'] = body
        timeout = self._timeout_for(request)
        try:
            response = await asyncio.wait_for(fetch(str(request.url), **options), timeout)
            content = await asyncio.wait_for(response.bytes(), timeout)
        except asyncio.TimeoutError as exc:
            raise httpx.ReadTimeout('Tempo esgotado aguardando o servidor.', request=request) from exc
        except httpx.HTTPError:
            raise
        except Exception as exc:  # JsException/OSError: rede, CORS, redirecionamento bloqueado
            raise httpx.ConnectError(str(exc) or 'Falha de rede no navegador.', request=request) from exc
        response_headers = [(key, value) for key, value in dict(response.headers).items()
                            if key.lower() not in _SKIPPED_RESPONSE_HEADERS]
        return httpx.Response(response.status, headers=response_headers, content=content, request=request)

    def _timeout_for(self, request):
        configured = request.extensions.get('timeout') or {}
        values = [value for value in configured.values() if value]
        return max(values) if values else self.timeout
