"""Regra de limite de bateria por estação — SIMULADA, 100% no aparelho (a API não tem esse recurso).

* Conta demo: em memória.
* Conta real: arquivo JSON em ``FLET_APP_STORAGE_DATA`` (como ``preferences.py``), por usuário e estação.

Interface: ``battery_rule(app, station_id)`` e ``save_battery_rule(app, station_id, limit, active)``.
A regra apenas define a meta usada nos alertas; nenhum comando é enviado ao equipamento.
"""

import json
import os
from pathlib import Path

from ..api_client import ApiError

DEFAULT_RULE = {'limit': 80, 'active': True, 'action': 'notify'}
_demo_state = {}


def _is_demo(app):
    return bool(getattr(getattr(app, 'api', None), 'is_demo', False))


def _path():
    storage = Path(os.environ.get('FLET_APP_STORAGE_DATA') or Path.home() / '.chargegrid')
    return storage / 'station_settings.json'


def _key(app, station_id):
    return f"{(getattr(app, 'profile', None) or {}).get('id') or 'anonymous'}:{station_id}"


def reset_demo():
    """Reinicia as regras demo (testes)."""
    _demo_state.clear()


def _read_all():
    try:
        data = json.loads(_path().read_text())
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _clean(entry):
    rule = dict(DEFAULT_RULE)
    if isinstance(entry, dict):
        try:
            rule['limit'] = max(0, min(100, int(entry.get('limit', rule['limit']))))
        except (TypeError, ValueError):
            pass
        if isinstance(entry.get('active'), bool):
            rule['active'] = entry['active']
    return rule


def battery_rule(app, station_id):
    source = _demo_state if _is_demo(app) else _read_all()
    return _clean(source.get(_key(app, station_id)))


def save_battery_rule(app, station_id, limit, active=True):
    try:
        limit = int(round(float(limit)))
    except (TypeError, ValueError) as exc:
        raise ApiError('Informe um limite entre 0% e 100%.') from exc
    if not 0 <= limit <= 100:
        raise ApiError('Informe um limite entre 0% e 100%.')
    rule = {'limit': limit, 'active': bool(active), 'action': 'notify'}
    if _is_demo(app):
        _demo_state[_key(app, station_id)] = rule
        return rule
    data = _read_all()
    data[_key(app, station_id)] = rule
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data))
    except OSError as exc:
        raise ApiError('Não foi possível salvar a regra neste aparelho.') from exc
    return rule
