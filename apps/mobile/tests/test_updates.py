"""Atualização do APK via GitHub Releases (sem servidor próprio)."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import flet as ft
import httpx

from chargegrid_app.app import ChargeGridApp
from chargegrid_app.services import updates

RELEASE = {'version': '0.6.10', 'build': 38, 'size_bytes': 172486490, 'notes': 'Autocomplete de endereço.',
           'url': 'https://9x2lhsbjqbuqehzd.public.blob.vercel-storage.com/app/chargegrid-0.6.10.apk'}


def client_for(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class UpdateServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_versions_compare_numerically(self):
        self.assertEqual(updates.parse_version('0.6.10'), (0, 6, 10))
        self.assertTrue(updates.is_newer('0.6.10', '0.6.9'))
        self.assertFalse(updates.is_newer('0.6.3', '0.6.3'))
        self.assertFalse(updates.is_newer('lixo', '0.6.3'))

    async def test_newer_release_returns_apk_link_and_notes(self):
        seen = []

        def handler(request):
            seen.append(str(request.url))
            return httpx.Response(200, json=RELEASE)
        async with client_for(handler) as client:
            info = await updates.available_update('0.6.9', client)
        self.assertEqual(info['version'], '0.6.10')
        self.assertTrue(info['url'].endswith('chargegrid-0.6.10.apk'))
        self.assertEqual((info['size_mb'], info['notes']), (164, 'Autocomplete de endereço.'))
        self.assertTrue(seen[0].endswith('/v1/app/latest'))  # nosso servidor, não o GitHub

    async def test_same_version_other_tags_failures_are_silent(self):
        cases = [httpx.Response(200, json=RELEASE), httpx.Response(200, json={**RELEASE, 'version': 'latest'}),
                 httpx.Response(200, json={**RELEASE, 'url': 'https://x/arquivo.zip'}),
                 httpx.Response(404, json={'error': {'code': 'updates_unavailable'}}),
                 httpx.Response(200, text='não é json')]
        for response in cases:
            async with client_for(lambda request, r=response: r) as client:
                self.assertIsNone(await updates.available_update('0.6.10', client))
        self.assertIsNone(await updates.available_update(None))  # app sem versão empacotada: nem consulta


def shell():
    app = SimpleNamespace(closed=False, prompting=False, page=MagicMock(), notices=[])
    app.notice = app.notices.append
    return app


class OfferUpdateTests(unittest.IsolatedAsyncioTestCase):
    async def test_dialog_offers_download_and_opens_the_apk_link(self):
        app = shell()
        info = {'version': '0.6.10', 'url': 'https://example.test/c.apk', 'size_mb': 164, 'notes': 'Novidades.'}
        with patch.object(updates, 'available_update', AsyncMock(return_value=info)):
            self.assertTrue(await ChargeGridApp.offer_update(app, '0.6.3', delay=0))
        dialog = app.page.show_dialog.call_args.args[0]
        self.assertIsInstance(dialog, ft.AlertDialog)
        self.assertIn('0.6.10', dialog.content.controls[0].value)
        launcher = AsyncMock()
        with patch.object(ft, 'UrlLauncher', return_value=launcher):
            await dialog.actions[1].on_click(None)
        launcher.launch_url.assert_awaited_with('https://example.test/c.apk')
        self.assertIn('instale por cima', app.notices[0])

    async def test_no_update_shows_nothing(self):
        app = shell()
        with patch.object(updates, 'available_update', AsyncMock(return_value=None)):
            self.assertFalse(await ChargeGridApp.offer_update(app, '0.6.3', delay=0))
        app.page.show_dialog.assert_not_called()


class UpdateTriggerTests(unittest.IsolatedAsyncioTestCase):
    async def test_manual_check_reports_when_already_up_to_date(self):
        app = shell()
        with patch.object(updates, 'available_update', AsyncMock(return_value=None)):
            self.assertFalse(await ChargeGridApp.offer_update(app, '0.6.5', delay=0, manual=True))
        self.assertIn('versão mais recente (0.6.5)', app.notices[0])

    async def test_returning_from_background_rechecks_on_android(self):
        import asyncio
        import time

        from chargegrid_app import app as app_module
        app = SimpleNamespace(backgrounded=True, closed=False, poll_callback=None, building_generation=None,
                              page=SimpleNamespace(platform=ft.PagePlatform.ANDROID), offer_update=AsyncMock(),
                              update_checked_at=time.monotonic() - app_module.UPDATE_RECHECK_SECONDS - 1)
        await ChargeGridApp.lifecycle(app, SimpleNamespace(state=ft.AppLifecycleState.RESUME))
        await asyncio.sleep(0)
        app.offer_update.assert_awaited_once()
        # Checado há pouco: voltar ao app não consulta de novo.
        app.backgrounded, app.update_checked_at = True, time.monotonic()
        app.offer_update.reset_mock()
        await ChargeGridApp.lifecycle(app, SimpleNamespace(state=ft.AppLifecycleState.RESUME))
        await asyncio.sleep(0)
        app.offer_update.assert_not_awaited()
