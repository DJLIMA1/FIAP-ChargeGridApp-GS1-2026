"""Medição de velocidade das telas: o app real contra a API de demonstração com latência simulada.

Cada pedido HTTP do ``ApiClient`` (o cliente de produção, com cache e tudo) passa por um
``httpx.MockTransport`` que espera ``LATENCY`` segundos e responde com a ``DemoApi``. Para cada
abertura de tela, o harness conta os pedidos feitos até o conteúdo aparecer (``app.go`` terminar),
a maior cadeia de pedidos em série (um só começa depois que o anterior termina) e o tempo até o
conteúdo. A composição do mapa (tiles + Pillow) é simulada com ``MAP_COMPOSE`` segundos numa thread.

Uso (tabela antes→depois)::

    cd apps/mobile && PYTHONPATH=src:packages:tests python tests/speed_harness.py
"""
import asyncio
import json
import os
import time
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import httpx

from chargegrid_app import app as app_module
from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi

LATENCY = 0.15
MAP_COMPOSE = 0.30
BASE_URL = 'https://api.speed.test/v1'


def _typed(value):
    if value in ('true', 'false'):
        return value == 'true'
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value


class LatencyBackend:
    """Transporte HTTP falso: DemoApi atrás de uma latência fixa, com registro de cada pedido."""

    def __init__(self, demo, latency=LATENCY):
        self.demo, self.latency = demo, latency
        self.calls = []

    def reset(self):
        self.calls = []

    async def handle(self, request):
        loop = asyncio.get_running_loop()
        record = {'method': request.method, 'path': request.url.path.removeprefix('/v1/'),
                  'start': loop.time(), 'end': None}
        self.calls.append(record)
        await asyncio.sleep(self.latency)
        params = {key: _typed(value) for key, value in request.url.params.items()}
        body = json.loads(request.content) if request.content else None
        try:
            if record['path'] == 'driver/profile' and request.method == 'GET':
                # A demonstração não tem esta rota; a API real responde o carro do perfil.
                result = {'vehicle': {'model': 'BYD Dolphin'}, 'saved': False, 'preferences': {}}
                response = httpx.Response(200, json=result)
                record['end'] = loop.time()
                return response
            result = await self.demo.request(request.method, record['path'], body, params=params,
                                             key=request.headers.get('Idempotency-Key'))
            response = httpx.Response(200, content=json.dumps(result, default=str).encode(),
                                      headers={'content-type': 'application/json'})
        except ApiError as exc:
            record['status'] = exc.status
            response = httpx.Response(exc.status or 400, json={'error': {'message': str(exc), 'code': exc.code}})
        record['end'] = loop.time()
        return response


def serial_depth(calls):
    """Maior cadeia de pedidos em que cada um só começa depois do fim do anterior."""
    done = sorted((c for c in calls if c['end'] is not None), key=lambda c: c['start'])
    depth = {}
    for index, call in enumerate(done):
        before = [depth[j] for j in range(index) if done[j]['end'] <= call['start'] + 1e-6]
        depth[index] = 1 + max(before, default=0)
    return max(depth.values(), default=0)


def fake_page():
    return SimpleNamespace(width=390, window=SimpleNamespace(), views=[SimpleNamespace()], add=Mock(),
                           update=Mock(), show_dialog=Mock(), pop_dialog=Mock(), platform=None)


def _compose(*args, **kwargs):
    time.sleep(MAP_COMPOSE)
    return b'\xff\xd8\xff' + b'0' * 64


class Harness:
    def __init__(self, latency=LATENCY):
        self.latency = latency
        self.stack = ExitStack()
        self.offset = 0.0

    async def start(self, mode='consumer'):
        os.environ.setdefault('FLET_APP_STORAGE_DATA', '/tmp/chargegrid-speed')
        self.stack.enter_context(patch('chargegrid_app.services.maps._compose_map', side_effect=_compose))
        from chargegrid_app.services import maps
        maps._map_cache.clear()
        self.demo = DemoApi()
        await self.demo.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.backend = LatencyBackend(self.demo, self.latency)
        client = ApiClient(BASE_URL, httpx.MockTransport(self.backend.handle))
        client.session.update(self.demo._tokens())
        self.clock_patch()
        with patch('chargegrid_app.app.ApiClient', return_value=client), \
                patch('chargegrid_app.app.Preferences') as preferences:
            preferences.return_value.load.return_value = True
            self.app = app_module.ChargeGridApp(fake_page())
        self.app.profile = await self.demo.request('GET', 'me')
        self.app.browsing_mode = mode
        return self

    def clock_patch(self):
        """Relógio do cache (se existir) com deslocamento controlado: simula o tempo passado numa aba."""
        try:
            from chargegrid_app import api_cache
        except ImportError:
            return
        real = time.monotonic
        self.stack.enter_context(patch.object(api_cache, 'clock', lambda: real() + self.offset))

    def advance(self, seconds):
        self.offset += seconds

    async def settle(self, seconds=0.6):
        """Deixa terminar prefetch e revalidação em segundo plano; depois para os polls da tela."""
        await asyncio.sleep(seconds)
        self.app.cancel_screen()
        await asyncio.sleep(0)

    async def open(self, label, route, **params):
        self.backend.reset()
        loop = asyncio.get_running_loop()
        started = loop.time()
        await self.app.go(route, **params)
        elapsed = loop.time() - started
        during = [c for c in self.backend.calls if c['start'] <= started + elapsed]
        row = {'label': label, 'calls': len(during), 'serial': serial_depth(during), 'ms': round(elapsed * 1000)}
        await self.settle()
        row['background'] = len(self.backend.calls) - len(during)
        return row

    async def close(self):
        self.app.cancel_screen()
        await self.app.api.close()
        self.stack.close()


async def driver_rows(latency=LATENCY):
    h = await Harness(latency).start('consumer')
    rows = []
    try:
        history = await h.demo.request('GET', 'me/charging-sessions', params={'limit': 1, 'offset': 0})
        receipt_id = (history.get('items') or [{}])[0].get('id')
        station = (await h.demo.request('GET', 'stations', params={'limit': 1, 'offset': 0}))['items'][0]
        rows.append(await h.open('Início (1ª abertura)', 'home'))
        rows.append(await h.open('Recarga / estações', 'stations'))
        rows.append(await h.open('Detalhe do posto', 'stations', station_id=station['id']))
        rows.append(await h.open('Booking passo 1', 'booking', station_id=station['id'], step=1, kind='reserve'))
        rows.append(await h.open('Booking passo 2', 'booking', station_id=station['id'], step=2, kind='reserve'))
        rows.append(await h.open('Histórico', 'history'))
        if receipt_id:
            rows.append(await h.open('Recibo', 'history', receipt=receipt_id))
        rows.append(await h.open('Chat', 'chat'))
        rows.append(await h.open('Conta', 'profile'))
        h.advance(30)
        rows.append(await h.open('Início (volta, 30 s depois)', 'home'))
        rows.append(await h.open('Recarga (volta)', 'stations'))
        rows.append(await h.open('Histórico (volta)', 'history'))
        rows.append(await h.open('Conta (volta)', 'profile'))
        # Recarga em andamento: reserva + início direto na demo (sem latência), depois a tela.
        point = next(p for p in station['connectors'] if p.get('available'))
        await h.demo.request('POST', 'charging-sessions', {
            'presence_code': '#F12345', 'public_code': point['public_code'], 'max_duration_minutes': 30},
            key='speed-session')
        rows.append(await h.open('Recarga em andamento', 'charging'))
    finally:
        await h.close()
    return rows


async def vendor_rows(latency=LATENCY):
    h = await Harness(latency).start('vendor')
    rows = []
    try:
        owned = (await h.demo.request('GET', 'operator/stations', params={'limit': 100, 'offset': 0}))['items']
        sid = owned[0]['id']
        rows.append(await h.open('Vendedor: Início', 'home'))
        rows.append(await h.open('Vendedor: Estações', 'operator'))
        rows.append(await h.open('Vendedor: Posto', 'station_admin', station_id=sid))
        rows.append(await h.open('Vendedor: Energia', 'station_admin', station_id=sid, page='energy'))
        rows.append(await h.open('Vendedor: Ao vivo', 'station_admin', station_id=sid, page='live'))
        rows.append(await h.open('Vendedor: Histórico', 'history', manage=True))
        rows.append(await h.open('Vendedor: Resultado', 'history', manage=True, page='economics'))
        rows.append(await h.open('Vendedor: Consumo', 'history', manage=True, page='energy'))
        rows.append(await h.open('Vendedor: Previsão', 'history', manage=True, page='forecast'))
        rows.append(await h.open('Vendedor: Conta', 'profile'))
        h.advance(30)
        rows.append(await h.open('Vendedor: Início (volta)', 'home'))
        rows.append(await h.open('Vendedor: Estações (volta)', 'operator'))
        rows.append(await h.open('Vendedor: Histórico (volta)', 'history', manage=True))
    finally:
        await h.close()
    return rows


async def all_rows(latency=LATENCY):
    return await driver_rows(latency) + await vendor_rows(latency)


def table(rows):
    lines = ['| Tela | Chamadas até o conteúdo | Em série | Tempo até conteúdo | Em 2º plano |',
             '|---|---:|---:|---:|---:|']
    for row in rows:
        lines.append(f"| {row['label']} | {row['calls']} | {row['serial']} | {row['ms']} ms | {row['background']} |")
    return '\n'.join(lines)


if __name__ == '__main__':
    os.environ.setdefault('FLET_APP_STORAGE_DATA', '/tmp/chargegrid-speed')
    print(table(asyncio.run(all_rows())))
