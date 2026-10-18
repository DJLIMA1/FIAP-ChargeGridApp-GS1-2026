from .screens import (
    auth,
    booking,
    charging,
    chat,
    coupons,
    design_gallery,
    driver,
    history,
    home,
    notifications,
    operator,
    payout,
    profile,
    reservations,
    station_admin,
    stations,
    tariffs,
    wallet,
)


async def home_entry(app, **data):
    """``home`` serves both modes: vendors get ``home.build_vendor`` when it exists."""
    if getattr(app, 'browsing_mode', 'consumer') == 'vendor':
        vendor = getattr(home, 'build_vendor', None)
        return await (vendor or operator.build)(app, **data)
    return await home.build(app, **data)


SCREENS = {module.__name__.split('.')[-1]: module.build for module in (
    auth, home, stations, reservations, charging, history, profile, operator, coupons, chat, driver,
    notifications, wallet, payout, booking, tariffs, station_admin, design_gallery)}
SCREENS['home'] = home_entry
TABS = [('home','Início'),('reservations','Recarga'),('history','Histórico'),('chat','Chat'),('profile','Conta')]
# Routes that follow the wizard/back contract documented in ui/design.py.
FLOW_ROUTES = ('booking', 'wallet', 'payout', 'tariffs', 'station_admin', 'notifications')


def nav_visible(route, data):
    """Bottom tab bar visibility: ``nav=False`` in the route params hides it (the reference hides it in
    the vendor station/point registration wizard, i.e. ``operator`` with ``onboarding``/``claim``)."""
    if 'nav' in data:
        return bool(data['nav'])
    return not (route == 'operator' and (data.get('onboarding') or data.get('claim')))


def screen_params(data):
    """Route params minus shell-only keys (``nav``) before calling ``build``."""
    return {key: value for key, value in data.items() if key != 'nav'}


def can_manage(profile):
    return bool(profile.get('operator_enabled') or profile.get('account_type') == 'vendor')


def tab_entries(mode):
    if mode == 'vendor':
        return [('home', 'Início', {}), ('operator', 'Estações', {}), ('history', 'Histórico', {'manage': True}),
                ('chat', 'Chat', {}), ('profile', 'Conta', {})]
    return [(route, label, {}) for route, label in TABS]


def active_tab(route, data, mode):
    if route == 'driver':
        return 'home'
    if route in ('stations', 'reservations', 'charging', 'booking'):
        return 'reservations' if mode != 'vendor' else None
    if route == 'wallet':
        return 'profile'
    if route in ('payout', 'tariffs', 'station_admin'):
        return 'operator'
    if route == 'notifications':
        return None
    if route == 'profile' or (route == 'coupons' and not data.get('manage')):
        return 'profile'
    return route


def parent_route(route, data, mode='consumer'):
    """Logical parent for native Back, without replaying mutations or old forms."""
    if route == 'auth':
        return ('auth', {}) if data.get('mode', 'login') != 'login' else None
    if route == 'home':
        return None
    if route in FLOW_ROUTES:
        return _flow_parent(route, data, mode)
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
        return 'stations', {**(data.get('station_search') or {}),'station_id':station_id} if station_id else {}
    if route == 'charging' and not data.get('session_id') and int(data.get('step') or 1) > 1:
        return 'charging', {**data, 'step': int(data['step']) - 1}
    if route == 'charging' and data.get('reservation_id'):
        return 'reservations', {}
    if route == 'charging' and (data.get('point_context') or {}).get('station_id'):
        return 'stations', {**(data.get('station_search') or {}),'station_id': data['point_context']['station_id']}
    if route == 'stations' and data.get('station_id'):
        return 'stations', {key:value for key,value in data.items() if key != 'station_id'}
    if route in ('charging', 'reservations'):
        return 'stations', {}
    return 'home', {}


def _flow_parent(route, data, mode):
    """Back contract of the redesigned routes (see ui/design.py)."""
    try:
        step = int(data.get('step') or 1)
    except (TypeError, ValueError):
        step = 1
    if step > 1 and route in ('booking', 'wallet', 'payout', 'tariffs'):
        return route, {**data, 'step': step - 1}
    origin = data.get('origin')
    if origin and origin in SCREENS and origin != route:
        return origin, {}
    if route == 'notifications':
        return 'home', {}
    if route == 'booking':
        sid = data.get('station_id')
        return 'stations', {'station_id': sid} if sid else {}
    if route == 'wallet':
        return 'profile', {}
    if route == 'payout':
        return 'home', {}
    if route == 'tariffs':
        sid = data.get('station_id')
        return ('station_admin', {'station_id': sid}) if sid else ('home', {})
    # station_admin
    sid = data.get('station_id')
    if data.get('page') and sid:
        return 'station_admin', {'station_id': sid}
    return 'operator', {}


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
