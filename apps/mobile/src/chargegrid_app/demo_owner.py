"""Dados do dashboard do proprietário na conta demo (somente memória, sem rede).

Gera um histórico fictício e determinístico de 30 dias para os pontos da conta
demo e responde às mesmas rotas ``owner/*`` da API, usando os cálculos de
``chargegrid_core.analytics``. Sessões criadas durante a demonstração entram
nos indicadores junto com o histórico simulado.
"""

import json
import random
from datetime import timedelta
from decimal import Decimal

from chargegrid_core import analytics, economics
from chargegrid_core.formatting import brl

from .api_client import ApiError

SEED = 20261013
HISTORY_DAYS = 30
HOUR_WEIGHTS = (1, 1, 1, 1, 1, 2, 4, 9, 10, 6, 4, 5, 8, 7, 4, 4, 5, 9, 11, 10, 7, 4, 2, 1)
END_REASONS = ('duration_limit', 'requested', 'requested', 'cost_limit', 'local_stop')
SAMPLE_INSIGHT_MODEL = 'demo-local'
# Custo do kWh dos postos da conta demo (valor de exemplo; o dono pode trocar na tela de resultado).
DEMO_ENERGY_COST = Decimal('0.8500')


def _fail(message, code='validation_error', status=422):
    raise ApiError(message, status, code)


class DemoOwner:
    def __init__(self, api):
        self.api = api
        self._cache_key = None
        self._history = ([], [], {})

    # ------------------------------------------------------------ histórico
    def _history_points(self):
        points = [p for p in self.api._points.values()
                  if self.api._stations[p['station_id']]['owner_id'] == self.api._profile.get('id')
                  and p['active'] and self.api._stations[p['station_id']]['active']]
        return sorted(points, key=lambda p: p['id'])[:4]

    def history(self):
        points = self._history_points()
        key = (self.api._wall, tuple(p['id'] for p in points))
        if key == self._cache_key:
            return self._history
        rng = random.Random(SEED)
        wall = self.api._wall
        sessions, reservations, failures = [], [], {}
        for index, point in enumerate(points):
            offline = not self._online(point)
            # Pontos offline pararam de receber recargas dois dias antes da demonstração.
            last_day = HISTORY_DAYS - (2 if offline else 0)
            daily = (4, 9) if index == 0 else (2, 6)
            power = float(point['power_kw'])
            price = Decimal(point['price_per_kwh'])
            for day in range(HISTORY_DAYS, HISTORY_DAYS - last_day, -1):
                midnight = (wall - timedelta(days=day)).astimezone(analytics.REPORT_TZ).replace(
                    hour=0, minute=0, second=0, microsecond=0)
                weekend = midnight.weekday() >= 5
                for _ in range(rng.randint(*daily) + (1 if weekend else 0)):
                    hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
                    began = midnight + timedelta(hours=hour, minutes=rng.randint(0, 59))
                    minutes = rng.randint(18, 95)
                    roll = rng.random()
                    status = 'failed' if roll < 0.04 else 'interrupted' if roll < 0.1 else 'completed'
                    if status == 'interrupted':
                        minutes = rng.randint(5, 30)
                    ended = began + timedelta(minutes=1 if status == 'failed' else minutes)
                    if ended >= wall:
                        continue
                    discount = 10 if rng.random() < 0.15 else 0
                    energy = (Decimal(str(power * rng.uniform(0.78, 0.98))) * minutes * 1000 / 60
                              if status != 'failed' else Decimal(0)).quantize(Decimal('0.001'))
                    cost = (energy / 1000 * price * (100 - discount) / 100).quantize(Decimal('0.0001'))
                    sid = f'demo-hist-session-{len(sessions) + 1}'
                    sessions.append({
                        'id': sid, 'user_id': f'demo-driver-{rng.randint(1, 40)}', 'connector_id': point['id'],
                        'reservation_id': None, 'status': status,
                        'created_at': (began - timedelta(minutes=1)).isoformat(),
                        'started_at': None if status == 'failed' else began.isoformat(),
                        'ended_at': ended.isoformat(), 'max_duration_minutes': 120, 'max_cost': None,
                        'price_per_kwh': str(price), 'discount_percent': discount,
                        'energy_wh': str(energy), 'soc_percent': None, 'source': 'simulated',
                        'last_measurement_at': ended.isoformat(), 'cost_estimate': str(cost),
                        'end_reason': ('device_fault' if status == 'failed' else 'communication_lost'
                                       if status == 'interrupted' else rng.choice(END_REASONS)),
                    })
                    if rng.random() < 0.3:
                        reservations.append(self._reservation(point, began - timedelta(minutes=rng.randint(5, 12)),
                                                              'consumed', len(reservations)))
                for _ in range(rng.choice((0, 0, 0, 1, 1, 2))):
                    created = midnight + timedelta(hours=rng.choice((8, 12, 18, 19)), minutes=rng.randint(0, 59))
                    if created < wall:
                        status = 'expired' if rng.random() < 0.6 else 'cancelled'
                        reservations.append(self._reservation(point, created, status, len(reservations)))
            if offline:
                failures[point['id']] = 2
        self._cache_key, self._history = key, (sessions, reservations, failures)
        return self._history

    @staticmethod
    def _reservation(point, created, status, index):
        return {'id': f'demo-hist-reservation-{index + 1}', 'user_id': 'demo-driver', 'connector_id': point['id'],
                'status': status, 'created_at': created.isoformat(),
                'confirmation_deadline': (created + timedelta(seconds=30)).isoformat(),
                'expires_at': (created + timedelta(minutes=10)).isoformat()}

    def _online(self, point):
        device = self.api._device_for(point['id'])
        return bool(device and device['online'])

    # --------------------------------------------------------------- escopo
    def _owned_points(self, station_id=None):
        owner = self.api._profile.get('id')
        return [p for p in self.api._points.values()
                if self.api._stations[p['station_id']]['owner_id'] == owner
                and (station_id is None or p['station_id'] == station_id)]

    def _context(self, record):
        point = self.api._points[record['connector_id']]
        station = self.api._stations[point['station_id']]
        return {**record, 'station_id': station['id'], 'station_name': station['name'],
                'public_code': point['public_code']}

    def records(self, station_id=None):
        allowed = {p['id'] for p in self._owned_points(station_id)}
        sessions, reservations, _ = self.history()
        live_sessions = list(self.api._sessions.values())
        live_reservations = list(self.api._reservations.values())
        pick = [self._context(s) for s in sessions + live_sessions if s['connector_id'] in allowed]
        booked = [self._context(r) for r in reservations + live_reservations if r['connector_id'] in allowed]
        return pick, booked

    def _station(self, params):
        station_id = params.get('station_id') or None
        if station_id:
            self.api._owned(station_id)
        return station_id

    def _window(self, params, granularity=None):
        end = analytics.parse_time(params.get('to')) or self.api._now()
        start = analytics.parse_time(params.get('from')) or end - timedelta(days=7)
        for name in ('from', 'to'):
            if params.get(name) and analytics.parse_time(params[name]) is None:
                _fail('Informe datas válidas no período.', 'invalid_period')
        try:
            analytics.validate_window(start, end, granularity)
        except ValueError as exc:
            _fail(str(exc), 'invalid_period')
        return start, end

    # --------------------------------------------------------------- rotas
    def route(self, method, path, params, body):
        if not self.api._profile.get('operator_enabled'):
            _fail('Operador não habilitado.', 'forbidden', 403)
        if (method, path) == ('POST', 'ai/owner-insights'):
            return self.insights({**(params or {}), **(body or {})})
        if path.startswith('stations/') and path.endswith('/economics'):
            return self.economics(method, path.split('/')[1], body)
        if method != 'GET':
            _fail('Operação não disponível na demonstração.', 'demo_route_not_supported', 404)
        resource = path.split('/', 1)[1]
        handler = {'overview': self.overview, 'timeseries': self.timeseries, 'heatmap': self.heatmap,
                   'sessions': self.sessions, 'reservations': self.reservations, 'alerts': self.alerts,
                   'live': self.live, 'margin': self.margin}.get(resource)
        if handler is None:
            _fail('Esta operação não está disponível na demonstração.', 'demo_route_not_supported', 404)
        return handler(params)

    def overview(self, params):
        station_id = self._station(params)
        start, end = self._window(params)
        now = self.api._now()
        sessions, reservations = self.records(station_id)
        points = self._owned_points(station_id)
        published = [p for p in points if p['active'] and self.api._stations[p['station_id']]['active']
                     and not p['retired']]
        online = sum(self._online(p) for p in published)
        totals = analytics.summarize_sessions(sessions, start, end, now)
        totals.update(analytics.summarize_reservations(reservations, start, end))
        stations = {p['station_id'] for p in points} if station_id else {
            s['id'] for s in self.api._stations.values() if s['owner_id'] == self.api._profile.get('id')}
        ranking_points = [{'connector_id': p['id'], 'station_id': p['station_id'],
                           'station_name': self.api._stations[p['station_id']]['name'],
                           'public_code': p['public_code']} for p in points]
        return {
            'period': {'from': start.isoformat(), 'to': end.isoformat(), 'timezone': analytics.REPORT_TZ_NAME},
            'station_id': station_id,
            'kpis': analytics.build_kpis(totals, points=len(published), points_online=online, start=start, end=end),
            'stations': {'total': len(stations),
                         'active': sum(self.api._stations[s]['active'] for s in stations),
                         'points': len(points), 'points_published': len(published), 'points_online': online},
            'ranking': analytics.ranking_payload(
                analytics.ranking_rows(sessions, ranking_points, start, end, now), start, end, 10),
            'generated_at': now.isoformat(),
        }

    def timeseries(self, params):
        granularity = params.get('granularity', 'day')
        if granularity not in analytics.GRANULARITIES:
            _fail('Granularidade deve ser hour ou day.')
        station_id = self._station(params)
        start, end = self._window(params, granularity)
        sessions, _ = self.records(station_id)
        payload = analytics.series_payload(analytics.series_rows(sessions, start, end, granularity),
                                           start, end, granularity)
        metric = params.get('metric', 'all')
        if metric != 'all':
            if metric not in analytics.METRICS:
                _fail('Métrica inválida.')
            payload['series'] = {metric: payload['series'][metric]}
        return payload

    def heatmap(self, params):
        station_id = self._station(params)
        start, end = self._window(params)
        sessions, _ = self.records(station_id)
        payload = analytics.heatmap_payload(analytics.heatmap_cells(sessions, start, end))
        payload['peak_hours'] = analytics.peak_hours(payload)
        return payload

    def _statuses(self, params, allowed):
        raw = params.get('status')
        if not raw:
            return None
        items = [item.strip() for item in str(raw).split(',') if item.strip()]
        if any(item not in allowed for item in items):
            _fail('Status inválido.', 'invalid_status')
        return set(items)

    def _filtered(self, records, params, allowed):
        start, end = self._window(params)
        statuses = self._statuses(params, allowed)
        query = str(params.get('q') or '').strip().casefold()
        result = []
        for record in records:
            created = analytics.parse_time(record.get('created_at'))
            if created is None or not start <= created < end:
                continue
            if statuses and record['status'] not in statuses:
                continue
            if query and query not in record['station_name'].casefold() and \
                    query not in record['public_code'].casefold() and not record['id'].casefold().startswith(query):
                continue
            result.append(record)
        result.sort(key=lambda r: (r['created_at'], r['id']), reverse=True)
        return result

    def session_rows(self, params):
        sessions, _ = self.records(self._station(params))
        now = self.api._now()
        return [analytics.session_export_row(s, now)
                for s in self._filtered(sessions, params, analytics.SESSION_STATUSES)]

    def reservation_rows(self, params):
        _, reservations = self.records(self._station(params))
        return [analytics.reservation_export_row(r)
                for r in self._filtered(reservations, params, analytics.RESERVATION_STATUSES)]

    def sessions(self, params):
        return self.api._page(self.session_rows(params), {'limit': params.get('limit', 25),
                                                          'offset': params.get('offset', 0)})

    def reservations(self, params):
        return self.api._page(self.reservation_rows(params), {'limit': params.get('limit', 25),
                                                              'offset': params.get('offset', 0)})

    def alerts(self, params):
        station_id = self._station(params)
        sessions, _ = self.records(station_id)
        _, _, failures = self.history()
        now = self.api._now()
        last = {}
        for session in sessions:
            last[session['connector_id']] = max(last.get(session['connector_id'], ''), session['created_at'])
        points = []
        for point in self._owned_points(station_id):
            row = self.api._point_row(point)
            station = self.api._stations[point['station_id']]
            online = row['online']
            points.append({
                'connector_id': point['id'], 'station_id': station['id'], 'station_name': station['name'],
                'public_code': point['public_code'], 'published': point['active'] and station['active'],
                'has_device': self.api._device_for(point['id']) is not None, 'online': online,
                'last_seen': now.isoformat() if online else (self.api._wall - timedelta(days=2)).isoformat(),
                'physical_state': row['physical_state'], 'failed_commands': failures.get(point['id'], 0),
                'last_session_at': last.get(point['id']), 'retired': point['retired'],
                'created_reference': self.api._wall.isoformat(),
            })
        return {'items': analytics.build_alerts(points, now), 'generated_at': now.isoformat()}

    def live(self, params):
        station_id = self._station(params)
        now = self.api._now()
        items = []
        for point in sorted(self._owned_points(station_id),
                            key=lambda p: (self.api._stations[p['station_id']]['name'], p['public_code'])):
            row = self.api._point_row(point)
            station = self.api._stations[point['station_id']]
            device = self.api._device_for(point['id'])
            session = self.api._current('session', point['id'])
            items.append({
                **{key: row[key] for key in ('public_code', 'connector_type', 'power_kw', 'price_per_kwh',
                                             'max_duration_minutes', 'active', 'retired', 'online',
                                             'physical_state', 'available', 'availability_status',
                                             'reserved_until')},
                'connector_id': point['id'], 'station_id': station['id'], 'station_name': station['name'],
                'station_active': station['active'], 'has_device': device is not None,
                'device_id': device['id'] if device else None,
                'last_seen': now.isoformat() if row['online'] else None, 'firmware_version': 'demo-0.3.6',
                'session': {
                    'id': session['id'], 'status': session['status'], 'started_at': session['started_at'],
                    'energy_wh': session['energy_wh'], 'cost_estimate': session['cost_estimate'],
                    'soc_percent': session['soc_percent'],
                    'power_w': str(int(Decimal(point['power_kw']) * 1000)) if session['status'] == 'charging' else None,
                    'source': session['source'], 'last_measurement_at': session['last_measurement_at'],
                } if session else None,
            })
        return {'items': items, 'generated_at': now.isoformat()}

    # ---------------------------------------------------- resultado do dono
    def _economics_config(self):
        """Custo do kWh por posto (some a cada login, como o resto da demonstração)."""
        state = getattr(self, '_economics_state', None)
        if state is None or state[0] != self.api._wall:
            state = self._economics_state = (self.api._wall, {})
        return state[1]

    def _station_economics(self, station, notes=True):
        config = self._economics_config()
        cost = config.get(station['id'], DEMO_ENERGY_COST)
        result = {'station_id': station['id'],
                  'energy_cost_per_kwh': analytics.decimal_text(cost, '0.0001') if cost is not None else None,
                  'platform_fee_percent': analytics.decimal_text(economics.DEFAULT_PLATFORM_FEE_PERCENT, '0.01'),
                  'fee_editable': False, 'currency': 'BRL'}
        if notes:
            result['notes'] = ['Custo do kWh: informe o valor médio pago à distribuidora (R$/kWh). Vale para as '
                               'próximas recargas; as anteriores mantêm o custo travado no início.',
                               'A comissão da plataforma é definida em contrato e não pode ser alterada no painel.']
        return result

    def economics(self, method, station_id, body):
        station = self.api._owned(station_id)
        if method == 'PUT':
            if not isinstance(body, dict):
                _fail('Envie um objeto com energy_cost_per_kwh.', 'invalid_economics')
            if 'platform_fee_percent' in body:
                _fail('A comissão da plataforma é definida em contrato e não pode ser alterada no painel.',
                      'fee_read_only')
            unknown = sorted(set(body) - {'energy_cost_per_kwh'})
            if unknown:
                _fail('Campo não permitido: ' + ', '.join(unknown), 'invalid_economics')
            if 'energy_cost_per_kwh' in body:
                try:
                    self._economics_config()[station['id']] = economics.clean_energy_cost(body['energy_cost_per_kwh'])
                except ValueError as error:
                    _fail(str(error), 'invalid_economics')
        elif method != 'GET':
            _fail('Operação não disponível na demonstração.', 'demo_route_not_supported', 404)
        return self._station_economics(station)

    def margin_report(self, params):
        """Mesmo relatório de ``GET /owner/margin`` (``Decimal``), com o núcleo ``economics``."""
        station_id = self._station(params)
        start, end = self._window(params)
        sessions, _ = self.records(station_id)
        config = self._economics_config()
        eligible = sorted((s for s in sessions if analytics.is_eligible(s, start, end)),
                          key=lambda s: (s['ended_at'], s['id']), reverse=True)
        rows = [economics.session_economics(s, station_energy_cost=config.get(s['station_id'], DEMO_ENERGY_COST))
                for s in eligible]
        owner = self.api._profile.get('id')
        stations = sorted((s for s in self.api._stations.values() if s['owner_id'] == owner
                           and (station_id is None or s['id'] == station_id)), key=lambda s: (s['name'], s['id']))
        report = economics.aggregate(rows)
        report.update(
            schema_version=economics.SCHEMA_VERSION,
            period={'from': start.isoformat(), 'to': end.isoformat(), 'timezone': analytics.REPORT_TZ_NAME},
            basis='ended_at', currency='BRL', station_id=station_id,
            stations=[{**self._station_economics(s, notes=False), 'station_name': s['name']} for s in stations],
            methodology=list(economics.METHODOLOGY), generated_at=self.api._now().isoformat(), items=rows,
            total=len(rows))
        return report

    def margin(self, params):
        report = self.margin_report(params)
        limit = int(params.get('limit') or 50)
        offset = int(params.get('offset') or 0)
        report.update(items=report['items'][offset:offset + limit], limit=limit, offset=offset)
        return economics.serialize(report)

    # ------------------------------------------------------------ exportação
    def download(self, path, params):
        name = path.strip('/').removeprefix('v1/').removeprefix('owner/export/')
        dataset, _, fmt = name.partition('.')
        if dataset == 'margin':
            if not self.api.session.access_token:
                _fail('Entre na conta de demonstração para continuar.', 'unauthorized', 401)
            if fmt != 'csv':
                _fail('O PDF só é gerado na conta real. Na demo, exporte o CSV.', 'demo_pdf_unavailable', 404)
            self.api._advance()
            return economics.margin_csv(self.margin_report(dict(params or {}))['items']).encode('utf-8')
        if dataset not in ('sessions', 'reservations') or fmt not in ('csv', 'json'):
            _fail('Exportação não disponível na demonstração.', 'demo_route_not_supported', 404)
        if not self.api.session.access_token:
            _fail('Entre na conta de demonstração para continuar.', 'unauthorized', 401)
        self.api._advance()
        params = dict(params or {})
        rows = self.session_rows(params) if dataset == 'sessions' else self.reservation_rows(params)
        if fmt == 'csv':
            columns = (analytics.SESSION_EXPORT_COLUMNS if dataset == 'sessions'
                       else analytics.RESERVATION_EXPORT_COLUMNS)
            return analytics.to_csv(rows, columns).encode('utf-8')
        start, end = self._window(params)
        envelope = analytics.export_envelope(rows, dataset=dataset, generated_at=self.api._now(), filters={
            'from': start.isoformat(), 'to': end.isoformat(), 'station_id': params.get('station_id'),
            'status': params.get('status'), 'q': params.get('q')})
        envelope['notes'] = 'Conta demonstração: dados fictícios e simulados. ' + envelope['notes']
        return json.dumps(envelope, ensure_ascii=False).encode('utf-8')

    # ------------------------------------------------------------- insights
    def insights(self, params):
        """Resultado de exemplo no mesmo contrato de ``POST /v1/ai/owner-insights``."""
        end = self.api._now()
        query = {'from': params.get('from') or (end - timedelta(days=30)).isoformat(),
                 'to': params.get('to') or end.isoformat(), 'station_id': params.get('station_id')}
        overview = self.overview(query)
        heat = self.heatmap(query)
        alerts = self.alerts({'station_id': params.get('station_id')})['items']
        kpis = overview['kpis']
        peaks = ', '.join(f"{item['hour']:02d}h" for item in heat['peak_hours']) or 'sem pico definido'
        recommendations = [{
            'title': 'Tarifa diferenciada nos horários de pico',
            'detail': f'A maior procura ocorre por volta de {peaks}. Teste um acréscimo leve nesses horários '
                      'e um cupom fora do pico para distribuir a demanda.',
            'impact': 'high', 'kind': 'pricing',
        }]
        if any(alert['kind'] == 'device_offline' for alert in alerts):
            recommendations.append({
                'title': 'Recupere o ponto offline',
                'detail': 'Há equipamento sem comunicação: cada dia parado reduz a disponibilidade e a receita. '
                          'Verifique energia e Wi-Fi do painel.',
                'impact': 'high', 'kind': 'operations',
            })
        if kpis.get('no_show_percent') and Decimal(kpis['no_show_percent']) >= 10:
            recommendations.append({
                'title': 'Reduza reservas não utilizadas',
                'detail': f"{kpis['no_show_percent'].replace('.', ',')}% das reservas expiraram sem recarga. "
                          'Considere lembretes ou um prazo de tolerância menor.',
                'impact': 'medium', 'kind': 'operations',
            })
        recommendations.append({
            'title': 'Cupom para horários ociosos',
            'detail': 'A ocupação fica baixa de madrugada e no meio da tarde. Um cupom de 10% nesses períodos '
                      'pode atrair motoristas sem afetar o pico.',
            'impact': 'medium', 'kind': 'marketing',
        })
        occupancy = (kpis['occupancy_percent'] or '0').replace('.', ',')
        summary = (f"No período analisado foram {kpis['sessions']} recargas concluídas, "
                   f"{brl(Decimal(kpis['revenue'] or 0))} estimados e ocupação de {occupancy}%. "
                   'Exemplo gerado localmente na conta demo, sem chamar um modelo de IA.')
        return {'summary': summary, 'recommendations': recommendations, 'generated_at': end.isoformat(),
                'model': SAMPLE_INSIGHT_MODEL}


def owner_for(api):
    """Instância por cliente demo (cache do histórico invalida a cada login)."""
    owner = getattr(api, '_owner_demo', None)
    if owner is None:
        owner = api._owner_demo = DemoOwner(api)
    return owner
