"""Exercita a API local real com os clientes do app/dashboard e compara contratos com o modo demo.

Uso (veja docs/revisao-integracao-2026-10.md):
  createdb chargegrid_live_check_test && (cd apps/api && MIGRATION_DATABASE_URL=... DATABASE_URL=... alembic upgrade head)
  <venv API>/python tools/live_contract_check/seed.py apps/api
  (cd apps/api && <venv API>/python ../../tools/live_contract_check/server.py "$PWD") &
  LIVE_TOKENS="$(<venv API>/python tools/live_contract_check/tokens.py)" \
    <venv app>/python tools/live_contract_check/exercise.py apps/mobile apps/dashboard
Sai com a lista de PROBLEMAS (campos divergentes entre API real e demo, vazamentos entre donos etc.).
"""
import asyncio
import csv
import io
import json
import os
import sys
import time

MOBILE, DASHBOARD = sys.argv[1], sys.argv[2]
sys.path[:0] = [os.path.join(MOBILE, 'src'), DASHBOARD]
os.environ['CHARGEGRID_ENABLE_DEMO'] = '1'
os.environ.pop('OPENROUTER_API_KEY', None)  # a demo local não chama o provedor neste roteiro

from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_dashboard.state import DashboardState

TOKENS = json.loads(os.environ['LIVE_TOKENS'])
BASE = f"http://127.0.0.1:{os.environ.get('CHARGEGRID_LIVE_PORT', '8631')}/v1"
PROBLEMS = []


def check(condition, message):
    if not condition:
        PROBLEMS.append(message)
        print('  !!', message)


def shape(value, depth=0):
    if isinstance(value, dict):
        return {key: shape(item, depth + 1) for key, item in value.items()} if depth < 4 else 'dict'
    if isinstance(value, list):
        return [shape(value[0], depth + 1)] if value else []
    return type(value).__name__


def compare(name, real, demo, path=''):
    """Chaves presentes na API real e ausentes na demo (ou vice-versa) quebram a mesma tela."""
    if isinstance(real, dict) and isinstance(demo, dict):
        for key in set(real) | set(demo):
            if key not in demo:
                check(False, f'{name}: campo {path}{key} só na API real')
            elif key not in real:
                check(False, f'{name}: campo {path}{key} só na demo')
            else:
                compare(name, real[key], demo[key], f'{path}{key}.')
    elif isinstance(real, list) and isinstance(demo, list) and real and demo:
        compare(name, real[0], demo[0], path + '[].')


def client_for(user):
    client = ApiClient(BASE)
    client.session.access_token, client.session.refresh_token = TOKENS[user], 'unused'
    client.session.expires_at = time.monotonic() + 3000
    return client


async def timed(label, coro):
    started = time.perf_counter()
    try:
        result = await coro
    except ApiError as exc:
        print(f'{label}: ApiError {exc.status} {exc.code} {exc}')
        raise
    print(f'{label}: {1000 * (time.perf_counter() - started):.0f} ms')
    return result


async def main():
    driver, owner, rival = client_for('driver'), client_for('owner'), client_for('rival')
    demo = DemoApi()
    await demo.login(DEMO_EMAIL, DEMO_PASSWORD)

    print('== Modo Motorista')
    profile = await timed('GET driver/profile', driver.request('GET', 'driver/profile'))
    saved = await timed('PUT driver/profile', driver.request('PUT', 'driver/profile', {
        'vehicle': {'preset': 'byd_dolphin'}, 'preferences': {'shift_start': '08:00', 'shift_end': '20:00'}}))
    check(saved['saved'] is True, 'perfil não salvo')
    body = {'soc_percent': 35, 'lat': -23.5614, 'lng': -46.6559, 'live_signals': True}
    plan = await timed('POST driver/plan', driver.request('POST', 'driver/plan', {**body, 'mode': 'full_shift'}))
    demo_plan = await demo.request('POST', 'driver/plan', {**body, 'mode': 'full_shift'})
    compare('driver/plan', plan, demo_plan)
    compare('driver/profile', profile, await demo.request('GET', 'driver/profile'))
    check(plan['stations_considered'] >= 3, f"postos considerados: {plan['stations_considered']}")
    print('   sinais:', plan['demand']['signals'], '| paradas:', [s['station_name'] for s in plan['stops']])
    for soc in (16, 0):
        stop = await timed(f'POST driver/next-stop soc={soc}', driver.request('POST', 'driver/next-stop', {**body, 'soc_percent': soc}))
        print('   ', stop['recommendation']['action'], '-', stop['recommendation']['headline'])
        check(stop['recommendation']['action'] != 'keep_driving', f'next-stop soc={soc} manda seguir rodando')
    compare('driver/next-stop', stop, await demo.request('POST', 'driver/next-stop', {**body, 'soc_percent': 0}))

    print('== Dashboard do proprietário')
    state = DashboardState(period='30d')
    params = state.params()
    demo_params = DashboardState(period='30d').params(demo._now())
    for resource in ('overview', 'timeseries', 'heatmap', 'alerts', 'live'):
        extra = {'granularity': state.granularity()} if resource == 'timeseries' else {}
        real = await timed(f'GET owner/{resource}', owner.owner_get(resource, {**params, **extra}))
        fake = await demo.owner_get(resource, {**demo_params, **extra})
        compare(f'owner/{resource}', real, fake)
    overview = await owner.owner_overview(params)
    kpis = overview['kpis']
    print('   KPIs:', {k: kpis[k] for k in ('revenue', 'energy_kwh', 'sessions', 'occupancy_percent', 'uptime_percent', 'no_show_percent')})
    check(all('Rival' not in item['station_name'] for item in overview['ranking']), 'ranking vazou posto rival')
    hours = await owner.owner_timeseries({**DashboardState(period='today').params(), 'granularity': 'hour'})
    check(len(hours['buckets']) == len(hours['series']['revenue']), 'série horária inconsistente')
    for table in ('sessions', 'reservations'):
        page = await timed(f'GET owner/{table}', owner.owner_get(table, {**params, 'limit': 10, 'offset': 0}))
        compare(f'owner/{table}', page, await demo.owner_get(table, {**demo_params, 'limit': 10, 'offset': 0}))
        last = await owner.owner_get(table, {**params, 'limit': 10, 'offset': max(0, page['total'] - 3)})
        check(len(last['items']) == min(3, page['total']), f'paginação {table}')
        wild = await owner.owner_get(table, {**params, 'q': '%'})
        check(wild['total'] == 0, f'busca com % retornou {wild["total"]} em {table}')
    csv_bytes = await timed('GET owner/export/sessions.csv', owner.owner_export('sessions', 'csv', params))
    rows = list(csv.reader(io.StringIO(csv_bytes.decode('utf-8'))))
    dangerous = [cell for row in rows[1:] for cell in row if cell[:1] in ('=', '+', '@')]
    check(not dangerous, f'CSV com fórmula: {dangerous[:2]}')
    check(any(cell.startswith("'=") for row in rows[1:] for cell in row), 'CSV não neutralizou fórmula de teste')
    envelope = json.loads(await owner.owner_export('reservations', 'json', params))
    check(envelope['total'] == len(envelope['items']), 'envelope JSON inconsistente')
    rival_station = (await rival.request('GET', 'operator/stations', params={'limit': 10}))['items'][0]['id']
    for resource in ('overview', 'sessions', 'live'):
        try:
            await owner.owner_get(resource, {'station_id': rival_station})
            check(False, f'owner/{resource} aceitou posto alheio')
        except ApiError as exc:
            check(exc.status in (403, 404), f'owner/{resource} posto alheio -> {exc.status}')
    try:
        await driver.owner_overview({})
        check(False, 'motorista acessou owner/overview')
    except ApiError as exc:
        check(exc.status == 403, f'motorista owner/overview -> {exc.status}')

    print('== IA (sem chave: regras)')
    search = await timed('POST ai/search', driver.request('POST', 'ai/search', {'query': 'carga rápida perto da Paulista até R$ 2,50/kWh'}))
    compare('ai/search', search, await demo.request('POST', 'ai/search', {'query': 'carga rápida perto da Paulista até R$ 2,50/kWh'}))
    print('   ', search['explanation'], search['params'])
    stations = await driver.request('GET', 'stations', params=search['params'])
    print('    postos com os parâmetros da busca:', stations['total'])
    insights = await timed('POST ai/owner-insights', owner.owner_insights({'from': params['from'], 'to': params['to']}))
    compare('ai/owner-insights', insights, await demo.owner_insights({}))
    check(all(item['kind'] in ('pricing', 'operations', 'marketing') for item in insights['recommendations']), 'kind fora do contrato')
    history = await driver.request('GET', 'me/charging-sessions', params={'limit': 5})
    session_id = next(item['id'] for item in history['items'] if item['status'] == 'completed')
    insight = await timed('POST ai/session-insight', driver.request('POST', 'ai/session-insight', {'session_id': session_id}))
    print('   ', insight['summary'][:100])
    try:
        await rival.request('POST', 'ai/session-insight', {'session_id': session_id})
        check(False, 'session-insight de outro usuário')
    except ApiError as exc:
        check(exc.status == 404, f'session-insight alheio -> {exc.status}')
    try:
        await driver.request('POST', 'ai/chat', {'messages': [{'role': 'user', 'content': 'oi'}]})
        print('    chat respondeu (IA ligada)')
    except ApiError as exc:
        print('    chat sem IA:', exc.status, exc.code)
    for client in (driver, owner, rival, demo):
        await client.close()
    print('PROBLEMAS:', len(PROBLEMS))
    for item in PROBLEMS:
        print(' -', item)
    return len(PROBLEMS)


sys.exit(1 if asyncio.run(main()) else 0)
