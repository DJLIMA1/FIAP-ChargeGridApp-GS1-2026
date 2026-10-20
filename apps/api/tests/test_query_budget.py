"""Telas iniciais do app: o número de consultas SQL por pedido não cresce com postos/pontos (sem N+1)."""
import uuid

import pytest
from sqlalchemy import event
from test_http import clear_overrides, client_for

from app.models import Connector, Device, Station, now
from app.security import digest


def add_stations(db, owner, count, points=2):
    for index in range(count):
        station = Station(owner_id=owner, name=f'Posto {index}', address='Rua, 1, Bairro, São Paulo - SP',
                          latitude=0, longitude=0)
        db.add(station)
        db.flush()
        for number in range(points):
            point = Connector(station_id=station.id, public_code=f'Q{index}-{number}-{uuid.uuid4().hex[:4]}',
                              connector_type='Type 2', power_kw=22, price_per_kwh=2, max_duration_minutes=60)
            db.add(point)
            db.flush()
            db.add(Device(connector_id=point.id, key_hash=digest(point.public_code), last_seen=now(),
                          reconciled=True, physical_state='idle'))


def count_queries(engine, call):
    statements = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(engine, 'before_cursor_execute', record)
    try:
        response = call()
    finally:
        event.remove(engine, 'before_cursor_execute', record)
    assert response.status_code == 200, response.text
    return len(statements)


ROUTES = [
    ('a', '/v1/stations', {'limit': 20, 'offset': 0}),
    ('owner', '/v1/operator/stations', {'limit': 100, 'offset': 0}),
    ('a', '/v1/reservations/current', None),
    ('a', '/v1/charging-sessions/current', None),
    ('a', '/v1/me', None),
    ('a', '/v1/me/charging-sessions', {'limit': 20, 'offset': 0}),
    ('owner', '/v1/owner/overview', None),
]


@pytest.mark.parametrize('who,path,params', ROUTES)
def test_query_count_does_not_grow_with_stations(engine, factory, seed, who, path, params):
    client, _ = client_for(factory, seed[who])
    try:
        with factory.begin() as db:
            add_stations(db, seed['owner'], 1)
        few = count_queries(engine, lambda: client.get(path, params=params))
        with factory.begin() as db:
            add_stations(db, seed['owner'], 6, points=3)
        many = count_queries(engine, lambda: client.get(path, params=params))
    finally:
        clear_overrides()
    assert many == few, f'{path}: {few} consultas com 2 postos, {many} com 8'


def test_database_pool_is_opt_in(monkeypatch):
    """Padrão: NullPool (uma conexão por pedido). ``DB_POOL_SIZE`` liga um pool pequeno com pre-ping."""
    from sqlalchemy.pool import NullPool

    import app.database as database
    monkeypatch.delenv('DB_POOL_SIZE', raising=False)
    assert database.engine_options() == {'poolclass': NullPool}
    monkeypatch.setenv('DB_POOL_SIZE', '2')
    options = database.engine_options()
    assert options['pool_size'] == 2 and options['pool_pre_ping'] is True and options['pool_recycle'] <= 300
    monkeypatch.setenv('DB_POOL_SIZE', 'x')
    assert database.engine_options() == {'poolclass': NullPool}
