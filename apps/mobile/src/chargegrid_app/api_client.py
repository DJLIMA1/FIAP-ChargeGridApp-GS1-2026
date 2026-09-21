import asyncio
import json
from uuid import uuid4

import httpx

from .config import api_url, validate_api_url
from .session import Session


class ApiError(Exception):
    def __init__(self, message, status=0, code="network_error"):
        super().__init__(message)
        self.status, self.code = status, code


class ApiClient:
    def __init__(self, base_url=None, transport=None):
        self.session = Session()
        self.http = httpx.AsyncClient(base_url=validate_api_url(base_url or api_url()) + '/', timeout=12, transport=transport, follow_redirects=False)
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
        elif method == 'GET' and path.startswith('charging-sessions/') and result:
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
        self.session.clear()
        self.operation_keys.clear()
        self.charging_operation_sessions.clear()
        self.last_session_id = None
        self.last_reservation_id = None
        await self.http.aclose()
