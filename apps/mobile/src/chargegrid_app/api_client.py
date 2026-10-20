import asyncio
import json
from copy import deepcopy
from uuid import uuid4

import httpx

from . import api_cache
from .config import api_url, running_in_browser, validate_api_url
from .owner_api import OwnerApiMixin
from .session import Session
from .web_transport import PyodideFetchTransport

TIMEOUT = httpx.Timeout(12, connect=6)
LIMITS = httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30)
# Falhas de conexão (conexão parada que o servidor já fechou, rede trocando de antena): um GET é
# repetido uma vez na hora. Escritas e prazos esgotados nunca são repetidos aqui.
RETRYABLE = (httpx.ConnectError, httpx.RemoteProtocolError, httpx.ReadError, httpx.WriteError)


class ApiError(Exception):
    def __init__(self, message, status=0, code="network_error"):
        super().__init__(message)
        self.status, self.code = status, code


class ApiClient(OwnerApiMixin):
    # The backend exposes /v1/ai/* (chat, NL search, insights); the key never reaches the app.
    ai_enabled = True

    def __init__(self, base_url=None, transport=None):
        self.session = Session()
        if transport is None and running_in_browser():
            # Pyodide (flet build web) não abre sockets: usa o fetch do navegador.
            transport = PyodideFetchTransport()
        # Conexões reaproveitadas por 30 s (o padrão do httpx fecha após 5 s parado e cada toque
        # seguinte pagava um novo aperto de mão TLS); conectar tem prazo menor que responder.
        self.http = httpx.AsyncClient(base_url=validate_api_url(base_url or api_url()) + '/', timeout=TIMEOUT,
                                      limits=LIMITS, transport=transport, follow_redirects=False)
        self.cache = api_cache.ResponseCache()
        self.refresh_lock = asyncio.Lock()
        self.operation_keys = {}
        self.charging_operation_sessions = {}
        self.last_session_id = None
        self.last_reservation_id = None

    def clear_operation(self, path):
        self.operation_keys = {signature: key for signature,key in self.operation_keys.items() if signature[1] != path}
        if path == 'charging-sessions':
            self.last_session_id = None
            self.charging_operation_sessions.clear()
        elif path == 'reservations':
            self.last_reservation_id = None

    def _record_result(self, method, path, result, body=None):
        if method == 'POST' and path == 'reservations':
            self.last_reservation_id = result['id']
        elif method == 'GET' and path == 'reservations/current':
            if result and not self.last_reservation_id:
                for request_method, request_path, request_body in self.operation_keys:
                    if request_method != 'POST' or request_path != 'reservations':
                        continue
                    pending = json.loads(request_body)
                    if pending.get('connector_id') == result.get('connector_id'):
                        self.last_reservation_id = result['id']
                        break
            terminal = result is None or result.get('status') in {'cancelled', 'expired', 'consumed'}
            if self.last_reservation_id and terminal:
                self.clear_operation('reservations')
        elif method == 'POST' and path == 'charging-sessions':
            self.last_session_id = result['id']
            signature = (method,path,json.dumps(body,sort_keys=True,separators=(',',':')))
            if signature in self.operation_keys:
                self.charging_operation_sessions[signature] = result['id']
            # A criação da sessão comprova que a reserva associada foi consumida.
            self.clear_operation('reservations')
        elif method == 'GET' and path.startswith('charging-sessions/') and isinstance(result, dict) and result:
            # Só objetos de sessão; ``charging-sessions/{id}/events`` devolve uma lista.
            if path == 'charging-sessions/current' and self.last_session_id != result['id']:
                # Recover the identity after an ambiguous POST timeout. A null
                # current result alone must never retire a possibly in-flight key.
                self.last_session_id = result['id']
                for signature in self.operation_keys:
                    if signature[:2] == ('POST', 'charging-sessions'):
                        self.charging_operation_sessions.setdefault(signature, result['id'])
            if result.get('status') in {'completed', 'failed', 'interrupted'}:
                for signature, session_id in tuple(self.charging_operation_sessions.items()):
                    if session_id == result['id']:
                        self.operation_keys.pop(signature, None)
                        self.charging_operation_sessions.pop(signature, None)
        return result

    @staticmethod
    def new_key():
        return str(uuid4())

    async def _send(self, method, path, body=None, headers=None, params=None):
        try:
            try:
                response = await self.http.request(method, path.lstrip('/'), json=body, headers=headers, params=params)
            except RETRYABLE:
                if method != 'GET':
                    raise
                response = await self.http.request(method, path.lstrip('/'), json=body, headers=headers, params=params)
        except httpx.TimeoutException as exc:
            raise ApiError("O servidor demorou a responder. Confira o estado antes de repetir.") from exc
        except httpx.RequestError as exc:
            raise ApiError("Não foi possível conectar com segurança. Verifique a rede, a URL e os certificados.") from exc
        if response.is_error or response.is_redirect:
            try:
                error = response.json().get('error', {})
                message = error.get('message') or 'Confira os dados informados.'
                code = error.get('code', 'invalid_request')
            except (ValueError, AttributeError):
                message, code = 'O servidor não pôde concluir o pedido.', 'server_error'
            if response.status_code == 429:
                message = 'Muitas tentativas. Aguarde antes de tentar novamente.'
            raise ApiError(message, response.status_code, code)
        try:
            return response.json() if response.content else None
        except ValueError as exc:
            raise ApiError('Resposta inválida do servidor.', response.status_code) from exc

    async def refresh(self, old_token=None):
        async with self.refresh_lock:
            if old_token is not None and self.session.access_token != old_token:
                return
            if not self.session.refresh_token:
                self.session.clear()
                raise ApiError('Entre novamente para continuar.', 401)
            try:
                result = await self._send('POST', 'auth/refresh', {'refresh_token': self.session.refresh_token})
                self.session.update(result)
            except ApiError as exc:
                if exc.status in (400, 401, 403):
                    self.session.clear()
                raise

    async def request(self, method, path, body=None, *, key=None, params=None, auth=True):
        path = path.lstrip('/')
        if method == 'GET' and auth and body is None and key is None:
            rule = api_cache.policy(path)
            if rule is not None:
                return await self._cached_get(path, params, rule)
        elif method != 'GET':
            pattern = api_cache.invalidation(path)
            self.cache.invalidate(pattern)
            try:
                return await self._request(method, path, body, key=key, params=params, auth=auth)
            finally:
                self.cache.invalidate(pattern)
        return await self._request(method, path, body, key=key, params=params, auth=auth)

    # ------------------------------------------------------------------ cache das respostas GET
    async def _cached_get(self, path, params, rule):
        cache_key = api_cache.key(path, params)
        mode = api_cache.current_mode()
        if mode is not None and self.session.access_token:
            mode.seen.add(cache_key)
            hit = self.cache.read(cache_key, rule, mode.stale_ok)
            if hit is not None:
                value, stale = hit
                if stale:
                    mode.served.append(api_cache.StaleRead(cache_key, path, dict(params or {}), deepcopy(value)))
                return deepcopy(value)
        return deepcopy(await asyncio.shield(self._shared_fetch(cache_key, path, params)))

    def _shared_fetch(self, cache_key, path, params):
        """Uma consulta por chave: quem pede o mesmo GET enquanto ele está em andamento espera a mesma.

        A consulta roda numa tarefa própria: sair da tela não a cancela e a resposta fica no cache."""
        task = self.cache.inflight.get(cache_key)
        if task is not None:
            return task
        epoch = self.cache.epoch

        async def fetch():
            result = await self._request('GET', path, params=params)
            self.cache.store(cache_key, deepcopy(result), epoch)
            return result

        task = asyncio.ensure_future(fetch())
        self.cache.inflight[cache_key] = task

        def finished(done):
            if self.cache.inflight.get(cache_key) is done:
                del self.cache.inflight[cache_key]
            if not done.cancelled():
                done.exception()  # erro já entregue a quem esperava; evita aviso de exceção não lida
        task.add_done_callback(finished)
        return task

    def prefetch(self, path, params=None):
        """Busca em segundo plano uma tela provável (só rotas guardadas; erros são ignorados)."""
        path = path.lstrip('/')
        rule = api_cache.policy(path)
        if rule is None or not self.session.access_token:
            return None
        cache_key = api_cache.key(path, params)
        if self.cache.fresh(cache_key, rule):
            return None
        return self._shared_fetch(cache_key, path, params)

    def seed(self, path, value, params=None, at=None):
        """Guarda uma resposta já conhecida (ex.: o posto da lista = ``GET stations/{id}``)."""
        path = path.lstrip('/')
        if api_cache.policy(path) is None or value is None:
            return False
        return self.cache.store(api_cache.key(path, params), deepcopy(value), self.cache.epoch, at)

    def cached_at(self, path, params=None):
        entry = self.cache.entries.get(api_cache.key(path.lstrip('/'), params))
        return entry[0] if entry else None

    async def revalidate(self, reads):
        """Consulta de novo (rede) o que foi mostrado velho; devolve as chaves cuja resposta mudou."""
        unique = {read.key: read for read in reads}

        async def check(read):
            try:
                with api_cache.network_only():
                    fresh = await asyncio.shield(self._shared_fetch(read.key, read.path, read.params))
            except ApiError:
                return None
            return read.key if fresh != read.value else None
        results = await asyncio.gather(*(check(read) for read in unique.values()))
        return [item for item in results if item is not None]

    async def warm_up(self):
        """Abre a conexão TLS e acorda a função do servidor enquanto a pessoa ainda está na tela de login."""
        try:
            await self.http.get(self.http.base_url.join('/health'), timeout=8)
        except (httpx.HTTPError, ValueError, RuntimeError):
            pass

    async def _request(self, method, path, body=None, *, key=None, params=None, auth=True):
        token = self.session.access_token
        if auth and self.session.needs_refresh:
            await self.refresh(token)
        if auth and not self.session.access_token:
            raise ApiError('Entre novamente para continuar.', 401)
        if key:
            signature = (method,path,json.dumps(body,sort_keys=True,separators=(',',':')))
            key = self.operation_keys.setdefault(signature,key)
        headers = {'Idempotency-Key': key} if key else {}
        if auth:
            headers['Authorization'] = 'Bearer ' + self.session.access_token
        try:
            result = await self._send(method, path, body, headers, params)
            return self._record_result(method, path, result, body)
        except ApiError as exc:
            if auth and exc.status == 401:
                rejected_token = headers['Authorization'].removeprefix('Bearer ')
                await self.refresh(rejected_token)
                headers['Authorization'] = 'Bearer ' + self.session.access_token
                try:
                    result = await self._send(method, path, body, headers, params)
                except ApiError as replay_error:
                    if replay_error.status == 401:
                        self.session.clear()
                    raise
                return self._record_result(method, path, result, body)
            raise

    async def login(self, email, password):
        self.session.update(await self.request('POST', 'auth/login', {'email': email, 'password': password}, auth=False))

    async def close(self):
        for task in self.cache.clear():
            task.cancel()
        self.session.clear()
        self.operation_keys.clear()
        self.charging_operation_sessions.clear()
        self.last_session_id = None
        self.last_reservation_id = None
        await self.http.aclose()

    async def download(self, path, params=None):
        """GET autenticado que devolve o corpo bruto (exportações CSV/JSON)."""
        if self.session.needs_refresh:
            await self.refresh(self.session.access_token)
        if not self.session.access_token:
            raise ApiError('Entre novamente para continuar.', 401)
        for attempt in range(2):
            token = self.session.access_token
            try:
                response = await self.http.get(path.lstrip('/'), params=params,
                                               headers={'Authorization': 'Bearer ' + token})
            except httpx.TimeoutException as exc:
                raise ApiError('O servidor demorou a gerar o arquivo. Tente um período menor.') from exc
            except httpx.RequestError as exc:
                raise ApiError('Não foi possível conectar com segurança. Verifique a rede.') from exc
            if response.status_code == 401 and attempt == 0:
                await self.refresh(token)
                continue
            if response.is_error or response.is_redirect:
                try:
                    error = response.json().get('error', {})
                    message, code = error.get('message') or 'Não foi possível exportar.', error.get('code', 'invalid_request')
                except (ValueError, AttributeError):
                    message, code = 'O servidor não pôde gerar o arquivo.', 'server_error'
                if response.status_code == 401:
                    self.session.clear()
                raise ApiError(message, response.status_code, code)
            return response.content
        raise ApiError('Entre novamente para continuar.', 401)
