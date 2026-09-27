from .screens import (
    auth,
    charging,
    chat,
    coupons,
    history,
    home,
    operator,
    profile,
    reservations,
    stations,
)

SCREENS = {module.__name__.split('.')[-1]: module.build for module in (auth,home,stations,reservations,charging,history,profile,operator,coupons,chat)}
TABS = [('home','Início'),('stations','Recarga'),('history','Histórico'),('chat','Chat'),('profile','Conta')]


def can_manage(profile):
    return bool(profile.get('operator_enabled') or profile.get('account_type') == 'vendor')


def tab_entries(mode):
    if mode == 'vendor':
        return [('operator', 'Postos', {}), ('history', 'Histórico', {'manage': True}),
                ('coupons', 'Cupons', {'manage': True}), ('chat', 'Chat', {}), ('profile', 'Conta', {})]
    return [(route, label, {}) for route, label in TABS]


def active_tab(route, data, mode):
    if route in ('stations', 'reservations', 'charging'):
        return 'stations' if mode != 'vendor' else None
    if route == 'profile' or (route == 'coupons' and not data.get('manage')):
        return 'profile'
    return route


def parent_route(route, data, mode='consumer'):
    """Logical parent for native Back, without replaying mutations or old forms."""
    if route == 'auth':
        return ('auth', {}) if data.get('mode', 'login') != 'login' else None
    if route == 'home':
        return None
    if route == 'operator':
        if data.get('onboarding'):
            step = int(data.get('step', 1))
            if step > 1:
                return 'operator', {**data, 'step': step - 1}
            return 'operator', {}
        if data.get('claim'):
            return 'operator', {'station_id': data['station_id']} if data.get('station_id') else {}
        if data.get('connector_id'):
            return 'operator', {'station_id': data.get('station_id')}
        return ('operator', {}) if data.get('station_id') else (None if mode == 'vendor' else ('profile', {}))
    if route == 'profile' and data.get('mode') in ('password', 'edit'):
        return 'profile', {}
    if route == 'coupons':
        if data.get('create') or data.get('coupon'):
            return 'coupons', {'manage': True}
        if data.get('station_id') and not data.get('manage'):
            return 'stations', {'station_id': data['station_id']}
        return ('operator', {}) if data.get('manage') else ('profile', {})
    if route == 'history' and data.get('station_id'):
        return 'operator', {'station_id': data['station_id']}
    if route == 'charging' and data.get('pending_start'):
        station_id = (data.get('point_context') or {}).get('station_id')
        return 'stations', {'station_id':station_id} if station_id else {}
    if route == 'charging' and not data.get('session_id') and int(data.get('step') or 1) > 1:
        return 'charging', {**data, 'step': int(data['step']) - 1}
    if route == 'charging' and data.get('reservation_id'):
        return 'reservations', {}
    if route == 'charging' and (data.get('point_context') or {}).get('station_id'):
        return 'stations', {'station_id': data['point_context']['station_id']}
    if route in ('charging', 'reservations') or (route == 'stations' and data.get('station_id')):
        return 'stations', {}
    return ('operator' if mode == 'vendor' else 'home'), {}


def editable_controls(control):
    """Traverse only visible form inputs, not live read-only telemetry."""
    import flet as ft
    if not getattr(control, 'visible', True):
        return
    if (isinstance(control, (ft.TextField, ft.Dropdown, ft.Switch)) and
            not control.disabled and not getattr(control, 'read_only', False) and control.data != 'preference'):
        yield control
    content = getattr(control, 'content', None)
    if content is not None and not isinstance(content, str):
        yield from editable_controls(content)
    for child in getattr(control, 'controls', []) or []:
        yield from editable_controls(child)


def form_route(route, data):
    return ((route == 'profile' and data.get('mode') in ('edit', 'password')) or
            (route == 'auth' and data.get('mode', 'login') != 'login') or
            (route == 'operator' and bool(data.get('station_id') or data.get('claim'))) or
            (route == 'coupons' and bool(data.get('create') or data.get('coupon'))))
