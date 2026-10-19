"""Notifications screen: cards grouped by day, built from account data."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import flet as ft

from chargegrid_app.screens import notifications


def descendants(control):
    yield control
    content = getattr(control, 'content', None)
    if content is not None and not isinstance(content, str):
        yield from descendants(content)
    for child in getattr(control, 'controls', []) or []:
        yield from descendants(child)


def texts(control):
    found = []

    def visit(item):
        if isinstance(item, ft.Text):
            found.append(item.value)
        content = getattr(item, 'content', None)
        if content is not None and not isinstance(content, str):
            visit(content)
        for child in getattr(item, 'controls', []) or []:
            visit(child)
    visit(control)
    return found


class NotificationsScreenTests(unittest.IsolatedAsyncioTestCase):
    def app(self, *, demo, session=None):
        async def request(method, path, **kwargs):
            return session
        return SimpleNamespace(api=SimpleNamespace(is_demo=demo, request=AsyncMock(side_effect=request)),
                               browsing_mode='consumer', back=AsyncMock())

    async def test_demo_shows_reference_cards_under_today(self):
        screen = await notifications.build(self.app(demo=True))
        visible = texts(screen)
        self.assertEqual(visible[:3], ['Notificações', 'Marcar todas como lidas', 'Hoje'])
        for expected in ('Meta de bateria atingida', 'Estação Marginal Pinheiros', 'Bateria atingiu 80% - 12:42',
                         'Estação sem comunicação', 'Verifique o status do dispositivo.'):
            self.assertIn(expected, visible)

    async def test_real_account_without_events_shows_empty_message(self):
        visible = texts(await notifications.build(self.app(demo=False)))
        self.assertIn('Nenhuma notificação por enquanto.', visible)
        self.assertNotIn('Meta de bateria atingida', visible)

    async def test_real_battery_notification_from_current_session(self):
        session = {'id': 's1', 'soc_percent': 82, 'station_name': 'Posto Real',
                   'last_measurement_at': '2026-10-18T15:42:00+00:00'}
        visible = texts(await notifications.build(self.app(demo=False, session=session)))
        self.assertIn('Estação Posto Real', visible)
        self.assertIn('Meta de bateria atingida', visible)

    async def test_vendor_power_limit_in_use_when_notify_is_on(self):
        point = {'id': 'p1', 'connector_type': 'CCS2', 'power_kw': '60.000', 'effective_power_kw': '40.000',
                 'power_limited': True, 'availability_status': 'charging', 'online': True}
        idle = {**point, 'id': 'p2', 'availability_status': 'available'}
        listing = {'items': [{'id': 's', 'name': 'Marginal Pinheiros', 'power_limit_notify': True,
                              'connectors': [point, idle]},
                             {'id': 'quiet', 'name': 'Sem aviso', 'power_limit_notify': False,
                              'connectors': [{**point, 'id': 'p3'}]}]}
        app = self.app(demo=False, session=listing)
        app.browsing_mode = 'vendor'
        visible = texts(await notifications.build(app))
        self.assertIn('Limite de potência em uso', visible)
        self.assertIn('CCS2 a 40 kW de 60 kW', visible)
        self.assertEqual(visible.count('Limite de potência em uso'), 1)
        items = notifications.service.power_items(listing['items'])
        self.assertRegex(items[0]['id'], r'^power-p1-\d{8}$')  # one item per point per day


if __name__ == '__main__':
    unittest.main()


class NotificationReadTests(unittest.IsolatedAsyncioTestCase):
    async def test_marking_all_read_clears_unread_and_badge(self):
        app = SimpleNamespace(api=SimpleNamespace(is_demo=True, request=AsyncMock(return_value=None)),
                              browsing_mode='consumer', back=AsyncMock(), go=AsyncMock())
        screen = await notifications.build(app)
        self.assertIn('Marcar como lida', texts(screen))
        button = next(item for item in descendants(screen) if getattr(item, 'on_click', None)
                      and 'Marcar todas como lidas' in texts(item))
        await button.on_click(None)
        self.assertFalse(app.has_unread_notifications)
        app.go.assert_awaited_with('notifications')
        again = await notifications.build(app)
        self.assertNotIn('Marcar como lida', texts(again))
        self.assertNotIn('Marcar todas como lidas', texts(again))
