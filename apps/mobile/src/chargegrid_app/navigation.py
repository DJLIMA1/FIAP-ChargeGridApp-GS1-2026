from .screens import (
    auth,
    charging,
    coupons,
    help,
    history,
    home,
    operator,
    profile,
    reservations,
    stations,
)

SCREENS = {module.__name__.split('.')[-1]: module.build for module in (auth,home,stations,reservations,charging,history,profile,operator,coupons,help)}
TABS = [('home','Início'),('stations','Recarga'),('history','Histórico'),('help','Ajuda'),('profile','Conta')]


def parent_route(route, data):
    """Logical parent for native Back, without replaying mutations or old forms."""
    if route == 'auth':
        return ('auth', {}) if data.get('mode', 'login') != 'login' else None
    if route == 'home':
        return None
    if route == 'operator':
        if data.get('connector_id'):
            return 'operator', {'station_id': data.get('station_id')}
        return ('operator', {}) if data.get('station_id') else ('profile', {})
    if route == 'coupons':
        if data.get('create') or data.get('coupon'):
            return 'coupons', {'manage': True}
        if data.get('station_id') and not data.get('manage'):
            return 'stations', {'station_id': data['station_id']}
        return ('operator', {}) if data.get('manage') else ('profile', {})
    if route == 'history' and data.get('station_id'):
        return 'operator', {'station_id': data['station_id']}
    if route == 'charging' and data.get('reservation_id'):
        return 'reservations', {}
    if route in ('charging', 'reservations') or (route == 'stations' and data.get('station_id')):
        return 'stations', {}
    return 'home', {}


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
    return (route == 'profile' or
            (route == 'auth' and data.get('mode', 'login') != 'login') or
            (route == 'operator' and bool(data.get('station_id'))) or
            (route == 'coupons' and bool(data.get('create') or data.get('coupon'))) or
            route == 'charging')
