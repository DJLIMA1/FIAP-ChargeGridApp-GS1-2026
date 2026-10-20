"""Transporte fetch (Pyodide) e resolução da API no navegador, com o módulo pyodide simulado."""
import asyncio
import json
import sys
import types
import unittest
from unittest.mock import patch

import httpx

from chargegrid_app import config
from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.web_transport import PyodideFetchTransport


class FakeFetchResponse:
    def __init__(self, status=200, body=b'', headers=None, delay=0):
        self.status, self.body, self.headers, self.delay = status, body, headers or {}, delay

    async def bytes(self):
        if self.delay:
            await asyncio.sleep(self.delay)
        return self.body


class FakeFetch:
    def __init__(self, responder):
        self.responder, self.calls = responder, []

    async def __call__(self, url, **options):
        self.calls.append((url, options))
        result = self.responder(url, options)
        if isinstance(result, Exception):
            raise result
        return result


def json_response(payload, status=200, **headers):
    return FakeFetchResponse(status, json.dumps(payload).encode(), {'content-type': 'application/json', **headers})


def fake_pyodide(fetch):
    """Instala ``pyodide.http.pyfetch`` falso em ``sys.modules``."""
    pyodide = types.ModuleType('pyodide')
    http = types.ModuleType('pyodide.http')
    http.pyfetch = fetch
    pyodide.http = http
    return patch.dict(sys.modules, {'pyodide': pyodide, 'pyodide.http': http})


def fake_js(origin):
    js = types.ModuleType('js')
    js.location = types.SimpleNamespace(origin=origin)
    return patch.dict(sys.modules, {'js': js})


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_json_post_uses_fetch_without_forbidden_headers(self):
        fetch = FakeFetch(lambda url, options: json_response({'ok': True}, 201))
        async with httpx.AsyncClient(base_url='https://painel.example.test/v1/',
                                     transport=PyodideFetchTransport(fetch=fetch)) as client:
            response = await client.post('auth/login', json={'email': 'a@b.c'},
                                         headers={'Authorization': 'Bearer t', 'Idempotency-Key': 'k'})
        self.assertEqual((response.status_code, response.json()), (201, {'ok': True}))
        url, options = fetch.calls[0]
        self.assertEqual(url, 'https://painel.example.test/v1/auth/login')
        self.assertEqual(options['method'], 'POST')
        self.assertEqual(json.loads(options['body']), {'email': 'a@b.c'})
        self.assertEqual(options['redirect'], 'error')
        headers = {key.lower(): value for key, value in options['headers'].items()}
        self.assertEqual((headers['authorization'], headers['idempotency-key']), ('Bearer t', 'k'))
        self.assertEqual(headers['content-type'], 'application/json')
        for forbidden in ('host', 'content-length', 'accept-encoding', 'connection', 'user-agent'):
            self.assertNotIn(forbidden, headers)

    async def test_get_sends_no_body_and_query_is_kept(self):
        fetch = FakeFetch(lambda url, options: FakeFetchResponse(200, b'a;b\n1;2\n', {'content-type': 'text/csv'}))
        async with httpx.AsyncClient(base_url='https://x.test/v1/', transport=PyodideFetchTransport(fetch=fetch)) as client:
            response = await client.get('operator/exports/sessions', params={'format': 'csv', 'from': '2026-10-01'})
        self.assertEqual(response.content, b'a;b\n1;2\n')
        url, options = fetch.calls[0]
        self.assertNotIn('body', options)
        self.assertIn('format=csv', url)

    async def test_already_decoded_body_is_not_decompressed_again(self):
        fetch = FakeFetch(lambda url, options: json_response({'n': 1}, **{'content-encoding': 'gzip',
                                                                           'content-length': '999'}))
        async with httpx.AsyncClient(transport=PyodideFetchTransport(fetch=fetch)) as client:
            response = await client.get('https://x.test/v1/me')
        self.assertEqual(response.json(), {'n': 1})

    async def test_network_failure_becomes_connect_error(self):
        fetch = FakeFetch(lambda url, options: OSError('TypeError: Failed to fetch'))
        async with httpx.AsyncClient(transport=PyodideFetchTransport(fetch=fetch)) as client:
            with self.assertRaises(httpx.ConnectError):
                await client.get('https://x.test/v1/me')

    async def test_slow_server_becomes_timeout(self):
        fetch = FakeFetch(lambda url, options: FakeFetchResponse(200, b'{}', delay=1))
        async with httpx.AsyncClient(transport=PyodideFetchTransport(timeout=0.05, fetch=fetch),
                                     timeout=0.05) as client:
            with self.assertRaises(httpx.TimeoutException):
                await client.get('https://x.test/v1/me')

    async def test_uses_pyodide_pyfetch_by_default(self):
        fetch = FakeFetch(lambda url, options: json_response({'id': 'u'}))
        with fake_pyodide(fetch):
            async with httpx.AsyncClient(transport=PyodideFetchTransport()) as client:
                response = await client.get('https://x.test/v1/me')
        self.assertEqual(response.json(), {'id': 'u'})
        self.assertEqual(len(fetch.calls), 1)


class BrowserApiClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        config.set_build_options()
        self.addCleanup(config.set_build_options)

    async def test_api_client_in_browser_uses_fetch_and_same_origin(self):
        def responder(url, options):
            if url.endswith('/auth/login'):
                return json_response({'access_token': 'a', 'refresh_token': 'r', 'expires_in': 3600,
                                      'token_type': 'bearer', 'user': {'id': 'u'}})
            if '/operator/exports/' in url:
                return FakeFetchResponse(200, b'id;kwh\n1;2\n', {'content-type': 'text/csv'})
            return json_response({'error': {'code': 'not_found', 'message': 'Não encontrado'}}, 404)
        fetch = FakeFetch(responder)
        with fake_pyodide(fetch), fake_js('https://painel.example.test'), \
                patch.object(sys, 'platform', 'emscripten'), patch.dict('os.environ', {'CHARGEGRID_API_URL': ''}):
            client = ApiClient()
            try:
                await client.login('u@example.com', '12345678')
                content = await client.download('operator/exports/sessions', params={'format': 'csv'})
                with self.assertRaises(ApiError) as raised:
                    await client.request('GET', 'nada')
            finally:
                await client.close()
        self.assertEqual(content, b'id;kwh\n1;2\n')
        self.assertEqual(raised.exception.status, 404)
        self.assertTrue(all(url.startswith('https://painel.example.test/v1/') for url, _ in fetch.calls))

    async def test_desktop_client_keeps_default_transport(self):
        client = ApiClient('https://api.example.test/v1')
        try:
            self.assertNotIsInstance(client.http._transport, PyodideFetchTransport)
        finally:
            await client.close()


class BrowserConfigTests(unittest.TestCase):
    def setUp(self):
        config.set_build_options()
        self.addCleanup(config.set_build_options)

    def test_browser_api_url_is_same_origin(self):
        with fake_js('https://chargegrid-ffive.vercel.app'), patch.object(sys, 'platform', 'emscripten'):
            self.assertEqual(config.api_url(), 'https://chargegrid-ffive.vercel.app/v1')
            config.set_build_options(api_url='/api/v1')
            self.assertEqual(config.api_url(), 'https://chargegrid-ffive.vercel.app/api/v1')
            config.set_build_options(api_url='https://api.example.test/v1')
            self.assertEqual(config.api_url(), 'https://api.example.test/v1')

    def test_browser_rejects_insecure_origin_except_localhost(self):
        with patch.object(sys, 'platform', 'emscripten'):
            with fake_js('http://localhost:8650'):
                self.assertEqual(config.api_url(), 'http://localhost:8650/v1')
            with fake_js('http://painel.example.test'), self.assertRaises(ValueError):
                config.api_url()

    def test_browser_without_location_falls_back_to_placeholder(self):
        with patch.dict(sys.modules, {'js': None}), patch.object(sys, 'platform', 'emscripten'):
            self.assertEqual(config.browser_origin(), None)
            self.assertEqual(config.api_url(), 'https://chargegrid.example.com/v1')

    def test_build_options_enable_demo_only_when_explicit(self):
        with patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '0'}):
            self.assertFalse(config.demo_enabled())
            config.set_build_options(demo='true')  # só o booleano true libera
            self.assertFalse(config.demo_enabled())
            config.set_build_options(demo=True)
            self.assertTrue(config.demo_enabled())

    def test_load_build_options_from_packaged_json(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder, patch.dict('os.environ', {'CHARGEGRID_ENABLE_DEMO': '0'}):
            path = Path(folder) / 'dashboard_config.json'
            self.assertFalse(config.load_build_options(path))
            self.assertFalse(config.demo_enabled())
            path.write_text('[1, 2]')
            self.assertFalse(config.load_build_options(path))
            path.write_text('{"demo": true, "api_url": "/v1"}')
            self.assertTrue(config.load_build_options(path))
            self.assertTrue(config.demo_enabled())

    def test_relative_override_is_ignored_outside_browser(self):
        config.set_build_options(api_url='/v1')
        with patch.dict('os.environ', {'CHARGEGRID_API_URL': 'https://api.example.test/v1'}):
            self.assertEqual(config.api_url(), 'https://api.example.test/v1')
