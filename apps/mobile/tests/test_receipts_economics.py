"""Recibo explicável (motorista), resultado do período (vendedor), exportações e saldo = repasse."""

import json
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import flet as ft
import httpx

from chargegrid_app import demo_receipt_pdf
from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DEMO_PRESENCE_CODE, DemoApi
from chargegrid_app.screens import charge_detail, history, history_owner
from chargegrid_app.screens import payout as payout_screen
from chargegrid_app.services import files, payout
from chargegrid_app.ui.wording import FORBIDDEN
from chargegrid_core import analytics
from test_behavior import HandlerApp, descendants

SECTIONS = ('Custos', 'Sessão e bateria', 'Pagamento', 'Estação e carregador')


def texts(screen):
    return '\n'.join(str(c.value) for c in descendants(screen) if isinstance(c, ft.Text))


def tapper(screen, label):
    """Container clicável cujo texto é ``label`` (botões do design usam Row([Text]))."""
    for control in descendants(screen):
        if isinstance(control, ft.Container) and getattr(control, 'on_click', None):
            inner = [c for c in descendants(control.content) if isinstance(c, ft.Text)] if control.content else []
            if any(c.value == label for c in inner) and len(inner) <= 2:
                return control
    raise AssertionError(f'botão {label!r} não encontrado')


def real_receipt(**changes):
    """Recibo no formato da API (``chargegrid.receipt`` v1) com todas as seções preenchidas."""
    data = {
        'schema': 'chargegrid.receipt', 'schema_version': 1, 'final': True,
        'session_id': '1a2b3c4d-0000-0000-0000-000000000000', 'number': '1A2B3C4D',
        'labels': {'measurement': 'simulated', 'simulated': True, 'demo': False, 'payment_environment': 'sandbox',
                   'notes': ['SIMULADO: energia calculada pelo simulador do equipamento, não por medidor.',
                             'Documento sem valor fiscal.']},
        'station': {'name': 'Posto Central', 'address': 'Rua do Centro, 100, São Paulo - SP'},
        'point': {'public_code': 'CG-001', 'connector_type': 'CCS2', 'power_kw': '60.000'},
        'times': {'created_at': '2026-10-20T12:59:00+00:00', 'started_at': '2026-10-20T13:00:00+00:00',
                  'ended_at': '2026-10-20T13:40:00+00:00', 'duration_minutes': '40.0', 'status': 'completed',
                  'status_label': 'Recarga concluída', 'end_reason': 'battery_full',
                  'end_reason_label': 'Bateria cheia (100%)'},
        'price': {'status': 'available', 'recorded': True, 'locked_at': '2026-10-20T12:59:00+00:00',
                  'locked_by': 'reservation', 'price_per_kwh': '2.4570',
                  'lines': [
                      {'key': 'connector_base', 'label': 'Tarifa base do conector', 'value': '1.8900', 'unit': 'R$/kWh'},
                      {'key': 'schedule', 'label': 'Tarifa do horário 18:00–22:00', 'value': '1.8900', 'unit': 'R$/kWh'},
                      {'key': 'demand', 'label': 'Ajuste por demanda', 'value': '1.30', 'unit': '×',
                       'detail': 'Demanda alta · Ocupação: 3 de 4 pontos'},
                      {'key': 'locked_price', 'label': 'Preço travado', 'value': '2.4570', 'unit': 'R$/kWh'},
                      {'key': 'coupon', 'label': 'Cupom BEMVINDO', 'value': '10', 'unit': '%'}],
                  'explanation': ['Ajuste por demanda 1,3× (+R$ 0,57/kWh): Demanda alta.']},
        'energy': {'status': 'available', 'kwh': '12.500', 'source': 'simulated',
                   'source_label': 'Energia simulada pelo equipamento (não é medição de medidor)',
                   'confirmed_by_device': True, 'confirmed_at': '2026-10-20T13:40:05+00:00',
                   'soc_start': '20.0', 'soc_end': '100.0', 'power_limit_kw': '22.000',
                   'note': 'Energia confirmada pelo equipamento ao encerrar a recarga.'},
        'power': {'status': 'available', 'sample_count': 3, 'peak_kw': '22.00',
                  'samples': [{'t': '2026-10-20T13:00:00+00:00', 'kw': '11.00'},
                              {'t': '2026-10-20T13:20:00+00:00', 'kw': '22.00'},
                              {'t': '2026-10-20T13:40:00+00:00', 'kw': '11.00'}],
                  'changes': [{'at': '2026-10-20T13:25:00+00:00', 'requested_kw': '11.000', 'applied_kw': '11.000',
                               'status': 'applied', 'reason_code': 'store_load',
                               'reason_label': 'Redução de potência: carga da loja subiu'}]},
        'payment': {'status': 'settled', 'environment': 'sandbox', 'provider': 'stripe',
                    'provider_reference': 'pi_test_123', 'method': 'card', 'authorized_amount': '40.00',
                    'captured_amount': '27.64', 'refunded_amount': '0.00', 'net_amount': '27.64',
                    'provider_fee': '1.20', 'refund_status': 'released', 'confirmed_at': '2026-10-20T12:58:00+00:00'},
        'overstay': {'status': 'final', 'grace_minutes': 10, 'started_at': '2026-10-20T13:50:00+00:00',
                     'ended_at': '2026-10-20T14:00:00+00:00', 'billable_minutes': 10, 'rate': '0.50',
                     'amount': '5.00', 'waived': False},
        'charges': {'status': 'final', 'energy_gross': '30.71', 'discount': '3.07', 'energy_total': '27.64',
                    'overstay': '5.00', 'total': '32.64', 'revenue_basis': 'paid', 'paid_total': '27.64',
                    'note': None},
        'timeline': [{'kind': 'start_applied', 'label': 'Início confirmado pelo ponto',
                      'source_label': 'sincronização do ponto', 'observed_at': '2026-10-20T13:00:00+00:00'}],
    }
    data.update(changes)
    return data


def margin_report(owner_net='75.00'):
    return {'totals': {'revenue_total': '100.00', 'platform_fee': '25.00', 'provider_fee': None,
                       'owner_net': owner_net, 'energy_cost': '20.00', 'margin': '55.00', 'sessions': 4,
                       'coverage': {'sessions': 4, 'with_energy_cost': 4, 'missing_energy_cost': 0}},
            'stations': [{'station_id': 'st-1', 'station_name': 'Posto Central', 'energy_cost_per_kwh': '0.8500',
                          'platform_fee_percent': '25.00', 'fee_editable': False}],
            'warnings': [], 'methodology': ['Receita bruta não é lucro.'], 'coupons': {}, 'dynamic_pricing': {},
            'items': []}


class DemoReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.clock = [0.0]
        self.app = HandlerApp()
        self.app.api = DemoApi(clock=lambda: self.clock[0], start_at=datetime(2026, 10, 20, 15, tzinfo=timezone.utc))
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')

    async def charge_with_coupon(self):
        api = self.app.api
        station = (await api.request('GET', 'operator/stations'))['items'][0]
        point = next(p for p in station['connectors'] if p['connector_type'] == 'Tipo 2')
        session = await api.request('POST', 'charging-sessions', {
            'public_code': point['public_code'], 'presence_code': DEMO_PRESENCE_CODE, 'coupon_code': 'bemvindo10',
            'max_duration_minutes': 5}, key='receipt-test')
        api.chargegrid_prepaid = [{'id': 'abcdef1234', 'amount': '20.00', 'energy_amount': '18.00', 'method': 'pix',
                                   'session_id': session['id'], 'status': 'settled', 'credited': '15.00',
                                   'created_at': '2026-10-20T14:59:00+00:00'}]
        self.clock[0] = 400
        done = await api.request('GET', f"charging-sessions/{session['id']}")
        self.assertEqual(done['status'], 'completed')
        return done

    async def test_demo_receipt_has_every_section_with_the_same_core(self):
        session = await self.charge_with_coupon()
        data = await self.app.api.request('GET', f"charging-sessions/{session['id']}/receipt")
        self.assertEqual((data['schema'], data['schema_version']), ('chargegrid.receipt', 1))
        self.assertTrue(data['labels']['demo'] and data['labels']['simulated'])
        self.assertEqual(data['price']['locked_by'], 'start')
        self.assertTrue(data['price']['recorded'])
        self.assertIn('Cupom BEMVINDO10', [line['label'] for line in data['price']['lines']])
        self.assertTrue(data['energy']['confirmed_by_device'])
        self.assertGreater(len(data['power']['samples']), 3)
        self.assertEqual(data['power']['peak_kw'], '22.00')
        self.assertEqual(data['power']['changes'][0]['status'], 'applied')
        self.assertEqual((data['payment']['environment'], data['payment']['refunded_amount']), ('mock', '15.00'))
        self.assertEqual(data['overstay'], {'status': 'not_applicable'})
        self.assertEqual(data['charges']['revenue_basis'], 'paid')
        # A tela: detalhes da recarga (subpágina do histórico) com todas as seções e o PDF exportável na demo.
        screen = await history.build(self.app, session=session['id'])
        text = texts(screen)
        for section in SECTIONS:
            self.assertIn(section, text)
        for expected in (charge_detail.TITLE, 'Desconto do cupom BEMVINDO10', 'Travado às',
                         'Energia confirmada pelo equipamento às', 'Pico 22,0 kW', 'Energia calculada pelo equipamento',
                         'Bateria', charge_detail.EXPORT_LABEL, charge_detail.EXPORT_DEMO_NOTE):
            self.assertIn(expected, text)
        self.assertNotRegex(text, FORBIDDEN)  # sem selos "CONTA DEMO"/"SIMULADO" nem "pagamento simulado"
        self.assertIsNotNone(tapper(screen, charge_detail.EXPORT_LABEL).on_click)

    async def test_seeded_session_receipt_is_honest_without_payment_or_reason(self):
        items = (await self.app.api.request('GET', 'me/charging-sessions'))['items']
        data = await self.app.api.request('GET', f"charging-sessions/{items[0]['id']}/receipt")
        self.assertEqual(data['payment']['status'], 'not_applicable')
        self.assertFalse(data['price']['recorded'])
        self.assertEqual(data['charges']['total'], '4.54')
        self.assertIn('Sem pagamento registrado: nenhum valor foi cobrado.', data['labels']['notes'])
        text = texts(await history.build(self.app, session=items[0]['id']))
        self.assertIn('Sem pagamento registrado', text)
        self.assertNotIn('Velocidade', text)  # não registrada nesta recarga antiga: não vira "Máxima"

    async def test_demo_receipt_pdf_is_local_and_history_pdf_is_refused(self):
        items = (await self.app.api.request('GET', 'me/charging-sessions'))['items']
        pdf = await self.app.api.download(f"charging-sessions/{items[0]['id']}/receipt.pdf")
        self.assertTrue(pdf.startswith(b'%PDF'))
        receipt = await self.app.api.request('GET', f"charging-sessions/{items[0]['id']}/receipt")
        labels = [label for _, rows in demo_receipt_pdf.rows(receipt) for label, _ in rows]
        self.assertIn('Preço travado', labels)
        self.assertFalse(any('demanda' in label.lower() or 'tarifa base' in label.lower() for label in labels))
        with self.assertRaises(ApiError) as caught:
            await self.app.api.download('me/charging-sessions/export.pdf')
        self.assertEqual(caught.exception.code, 'demo_pdf_unavailable')
        content = (await self.app.api.download('me/charging-sessions/export.csv')).decode('utf-8')
        self.assertTrue(content.startswith('ID da sessão,Posto,Ponto'))
        self.assertEqual(content.count('\r\n'), 3)  # cabeçalho + duas recargas de exemplo

    async def test_demo_export_shares_the_local_pdf(self):
        items = (await self.app.api.request('GET', 'me/charging-sessions'))['items']
        screen = await history.build(self.app, session=items[0]['id'])
        with patch.object(files, 'deliver', AsyncMock(return_value='ok')) as deliver:
            await tapper(screen, charge_detail.EXPORT_LABEL).on_click(None)
        data, filename = deliver.await_args.args[1:]
        self.assertTrue(data.startswith(b'%PDF'))
        self.assertRegex(filename, r'^chargegrid-recibo-cg\d{4}\.pdf$')
        self.assertEqual(self.app.notices, ['ok'])

    def test_demo_pdf_is_marked_and_never_shows_demand(self):
        data = real_receipt()
        data['labels'] = {**data['labels'], 'demo': True}
        sections = dict(demo_receipt_pdf.rows(data))
        flat = ' '.join(f'{label} {value}' for rows in sections.values() for label, value in rows)
        self.assertIn('R$ 2,4570/kWh', flat)
        self.assertIn('Desconto do cupom', flat)
        for hidden in ('demanda', 'Tarifa do horário', 'Tarifa base', '1,3×'):
            self.assertNotIn(hidden, flat)
        self.assertTrue(demo_receipt_pdf.receipt_pdf(data).startswith(b'%PDF'))
        self.assertEqual(demo_receipt_pdf.MARK, 'Documento sem valor fiscal')
        self.assertNotRegex(flat, FORBIDDEN)


class ChargeDetailScreenTests(unittest.IsolatedAsyncioTestCase):
    SESSION = {'id': '1a2b3c4d-0000-0000-0000-000000000000', 'station_id': 'st-1', 'battery_kwh': '60.00',
               'power_tier': 'reduced', 'max_duration_minutes': 60, 'max_cost': '40.0000', 'status': 'completed'}

    def real_app(self, *, web=False, session=None):
        app = HandlerApp()
        row = self.SESSION if session is None else session

        async def request(method, path, **kwargs):
            if path.endswith('/receipt'):
                return real_receipt()
            if row is False:
                raise ApiError('Sessão não encontrada', 404, 'not_found')
            return row
        app.api.request = AsyncMock(side_effect=request)
        app.api.download = AsyncMock(return_value=b'%PDF-1.4 recibo')
        app.page = SimpleNamespace(update=lambda: None, web=web, platform=ft.PagePlatform.ANDROID)
        return app

    async def test_real_detail_shows_every_fact_once_without_demand_for_the_driver(self):
        app = self.real_app()
        screen = await history.build(app, session='1a2b3c4d-0000-0000-0000-000000000000')
        paths = sorted(call.args[1] for call in app.api.request.await_args_list)
        self.assertEqual(paths, ['charging-sessions/1a2b3c4d-0000-0000-0000-000000000000',
                                 'charging-sessions/1a2b3c4d-0000-0000-0000-000000000000/receipt'])
        text = texts(screen)
        for section in SECTIONS:
            self.assertIn(section, text)
        hero = next(c for c in descendants(screen) if getattr(c, 'data', None) == 'detail-hero')
        for expected in ('Posto Central', 'Recarga concluída', '12,50 kWh', 'R$ 32,64', '40 min', 'Nº 1A2B3C4D'):
            self.assertIn(expected, texts(hero))
        for expected in ('R$ 2,4570/kWh', 'na reserva', 'Desconto do cupom', 'R$ 3,07',
                         'Valor pago (líquido)', 'Energia calculada pelo equipamento', 'Pico 22,0 kW', 'Redução de potência: carga da loja subiu',
                         'Aplicada', '20% → 100%', 'Bateria do veículo 60 kWh', 'Reduzida · mais econômica',
                         '60 min · até R$ 40,00', 'Limite de potência no início',
                         'pi_test_123', 'R$ 40,00', 'R$ 27,64', 'Sobra da pré-autorização liberada',
                         'Tolerância', 'R$ 5,00', 'CG-001', 'CCS2', '60,0 kW', 'Ver estação', 'Linha do tempo',
                         'Início confirmado pelo ponto', 'Documento sem valor fiscal.', charge_detail.EXPORT_LABEL):
            self.assertIn(expected, text)
        # Demanda e a composição do preço são do vendedor: o motorista vê só o preço travado.
        for hidden in ('Ajuste por demanda', '1,3×', 'Demanda alta', 'Tarifa do horário', 'Tarifa base',
                       'Como o preço foi calculado', 'Ver recibo', 'Ver eventos da sessão', 'Custo estimado:'):
            self.assertNotIn(hidden, text)
        self.assertNotIn(charge_detail.EXPORT_DEMO_NOTE, text)
        # O recibo do fixture ainda traz "SIMULADO"/"(sandbox)" (API antiga): a tela não mostra nada disso.
        self.assertNotRegex(text, FORBIDDEN)
        await tapper(screen, 'Ver estação').on_click(None)
        app.go.assert_awaited_with('stations', station_id='st-1')

    async def test_optional_sections_may_be_empty_and_session_is_optional(self):
        app = self.real_app(session=False)
        app.api.request = AsyncMock(side_effect=[real_receipt(
            power={'status': 'unavailable', 'samples': [], 'changes': [],
                   'note': 'Amostras de potência indisponíveis (não enviadas pelo equipamento ou já expiradas).'},
            payment={'status': 'not_applicable', 'note': 'Sem pagamento registrado: valor estimado, sem cobrança real.'},
            overstay={'status': 'not_applicable'}, timeline=[]), ApiError('x', 404, 'not_found')])
        text = texts(await charge_detail.build(app, 'x'))
        self.assertIn('Sem pagamento registrado', text)
        for hidden in ('Pico', 'Mudanças de potência', 'Permanência após a recarga', 'Linha do tempo', 'Ver estação'):
            self.assertNotIn(hidden, text)

    async def test_back_returns_to_the_same_list(self):
        app = self.real_app()
        screen = await history.build(app, session='1a2b3c4d-0000-0000-0000-000000000000', offset=20)
        back = next(c for c in descendants(screen) if isinstance(c, ft.Container) and c.tooltip == 'Voltar')
        await back.on_click(None)
        app.go.assert_awaited_with('history', offset=20)

    async def test_legacy_receipt_route_opens_the_same_screen(self):
        app = self.real_app()
        text = texts(await history.build(app, receipt='1a2b3c4d-0000-0000-0000-000000000000'))
        self.assertIn(charge_detail.TITLE, text)
        self.assertIn(charge_detail.EXPORT_LABEL, text)

    async def test_export_downloads_with_auth_and_opens_the_share_sheet(self):
        app = self.real_app()
        screen = await charge_detail.build(app, '1a2b3c4d-0000-0000-0000-000000000000')
        share = Mock()
        share.return_value.share_files = AsyncMock()
        with patch.object(files.ft, 'Share', share):
            await tapper(screen, charge_detail.EXPORT_LABEL).on_click(None)
        app.api.download.assert_awaited_once_with('charging-sessions/1a2b3c4d-0000-0000-0000-000000000000/receipt.pdf')
        shared = share.return_value.share_files.await_args.args[0][0]
        self.assertEqual((shared.data, shared.name, shared.mime_type),
                         (b'%PDF-1.4 recibo', 'chargegrid-recibo-1a2b3c4d.pdf', 'application/pdf'))
        self.assertIn('compartilhar', app.notices[-1])

    async def test_export_on_web_uses_save_dialog_and_falls_back(self):
        app = self.real_app(web=True)
        screen = await charge_detail.build(app, 'x')
        picker = Mock()
        picker.return_value.save_file = AsyncMock(return_value=None)
        with patch.object(files.ft, 'FilePicker', picker):
            await tapper(screen, charge_detail.EXPORT_LABEL).on_click(None)
        kwargs = picker.return_value.save_file.await_args.kwargs
        self.assertEqual((kwargs['src_bytes'], kwargs['file_name']), (b'%PDF-1.4 recibo', 'chargegrid-recibo-1a2b3c4d.pdf'))
        # Share falha no celular -> "Salvar como".
        app = self.real_app()
        broken = Mock()
        broken.return_value.share_files = AsyncMock(side_effect=RuntimeError('sem plugin'))
        with patch.object(files.ft, 'Share', broken), patch.object(files.ft, 'FilePicker', picker):
            message = await files.deliver(app, b'abc', 'a.csv')
        self.assertIn('a.csv', message)
        self.assertEqual(picker.return_value.save_file.await_args.kwargs['allowed_extensions'], ['csv'])

    async def test_export_error_is_reported(self):
        app = self.real_app()
        app.api.download.side_effect = ApiError('Sessão não encontrada', 404, 'not_found')
        screen = await charge_detail.build(app, 'x')
        await tapper(screen, charge_detail.EXPORT_LABEL).on_click(None)
        self.assertEqual(app.notices, ['Sessão não encontrada'])


class SellerChargeDetailTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = HandlerApp()
        self.app.api = DemoApi()
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')

    async def test_seller_card_opens_the_same_detail_without_export(self):
        listing = await history.build(self.app, manage=True)
        card = next(c for c in descendants(listing) if getattr(c, 'data', None) == 'session-card')
        items = (await self.app.api.request('GET', 'operator/charging-sessions'))['items']
        await card.on_click(None)
        self.app.go.assert_awaited_with('history', session=items[0]['id'], manage=True)
        receipt_calls = []
        original = self.app.api.request

        async def spy(method, path, *args, **kwargs):
            receipt_calls.append(path)
            return await original(method, path, *args, **kwargs)
        self.app.api.request = spy
        screen = await history.build(self.app, manage=True, session=items[0]['id'])
        text = texts(screen)
        self.assertFalse(any(path.endswith('/receipt') for path in receipt_calls))
        for expected in (charge_detail.TITLE, items[0]['station_name'], 'Custos', 'Sessão e bateria', 'Pagamento',
                         'Estação e carregador', 'Tarifa base', 'Como o preço foi calculado', '2,40 kWh'):
            self.assertIn(expected, text)
        for hidden in (charge_detail.EXPORT_LABEL, 'Ver estação', 'Resumo inteligente da recarga'):
            self.assertNotIn(hidden, text)

    async def test_seller_detail_shows_demand_and_payment_from_the_listing(self):
        session = {'id': 'own-1', 'status': 'completed', 'created_at': '2026-10-20T12:59:00+00:00',
                   'started_at': '2026-10-20T13:00:00+00:00', 'ended_at': '2026-10-20T13:30:00+00:00',
                   'price_per_kwh': '2.4570', 'base_price_per_kwh': '1.8900', 'demand_multiplier': '1.30',
                   'discount_percent': 0, 'energy_wh': '10000', 'cost_estimate': '24.57', 'source': 'simulated',
                   'station_name': 'Posto Central', 'station_address': 'Rua A, 1, Centro, São Paulo - SP',
                   'connector': {'public_code': 'CG-1', 'connector_type': 'CCS2', 'power_kw': '60.000'},
                   'payment': {'status': 'completed', 'status_label': 'Concluído', 'channel': 'kiosk_totem',
                               'provider': 'simulated', 'settlement': {'status': 'done', 'captured': '24.57'}},
                   'overstay': {'status': 'closed', 'billable_seconds': 600, 'fee_due': '4.00', 'fee_applies': True}}
        app = HandlerApp()
        app.history_sessions = {'own-1': session}
        text = texts(await history.build(app, manage=True, session='own-1'))
        app.api.request.assert_not_awaited()
        for expected in ('Ajuste por demanda', '1,3×', 'R$ 2,4570/kWh', 'Totem · Sem cobrança', 'Capturado R$ 24,57',
                         '10 min na vaga · taxa R$ 4,00', '10,00 kWh'):
            self.assertIn(expected, text)
        self.assertNotIn(charge_detail.EXPORT_LABEL, text)

    async def test_seller_detail_without_cache_searches_the_listing_or_says_not_found(self):
        app = HandlerApp()
        app.api.request.return_value = {'items': [], 'total': 0}
        text = texts(await history.build(app, station_id='st-9', session='gone'))
        app.api.request.assert_awaited_once_with('GET', 'stations/st-9/charging-sessions',
                                                 params={'limit': charge_detail.SELLER_PAGE, 'offset': 0})
        self.assertIn(charge_detail.NOT_FOUND, text)


class HistoryReceiptLinkTests(unittest.IsolatedAsyncioTestCase):
    async def test_each_consumer_card_opens_its_detail_and_offers_export(self):
        app = HandlerApp()
        app.api = DemoApi()
        await app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        app.profile = await app.api.request('GET', 'me')
        screen = await history.build(app)
        cards = [c for c in descendants(screen) if getattr(c, 'data', None) == 'session-card']
        items = (await app.api.request('GET', 'me/charging-sessions'))['items']
        self.assertEqual(len(cards), len(items))
        await cards[0].on_click(None)
        app.go.assert_awaited_with('history', session=items[0]['id'])
        for hidden in ('Ver recibo', 'Ver eventos da sessão', 'Resumo inteligente da recarga', 'Custo estimado:'):
            self.assertNotIn(hidden, texts(screen))
        self.assertIn('Exportar (PDF/CSV)', texts(screen))
        self.assertIn('PDF indisponível nesta conta', texts(screen))
        # CSV na demo: gerado localmente e entregue ao usuário.
        with patch.object(files, 'deliver', AsyncMock(return_value='ok')) as deliver:
            await tapper(screen, 'CSV').on_click(None)
        content, filename = deliver.await_args.args[1:]
        self.assertTrue(content.startswith('ID da sessão'.encode()))
        self.assertRegex(filename, r'^chargegrid-historico-\d{8}-\d{4}\.csv$')

    async def test_real_export_downloads_pdf_for_the_chosen_period(self):
        app = HandlerApp()
        app.api.request.return_value = {'items': [{'id': 's1', 'status': 'completed', 'station_name': 'Posto',
                                                   'started_at': '2026-10-20T13:00:00+00:00',
                                                   'max_duration_minutes': 30}], 'total': 1}
        app.api.download = AsyncMock(return_value=b'%PDF')
        screen = await history.build(app)
        menu = next(c for c in descendants(screen) if isinstance(c, ft.PopupMenuButton) and c.data == 'export-period')
        menu.items[1].on_click(None)  # Últimos 90 dias
        with patch.object(files, 'deliver', AsyncMock(return_value='ok')):
            await tapper(screen, 'PDF').on_click(None)
        path = app.api.download.await_args.args[0]
        params = app.api.download.await_args.kwargs['params']
        self.assertEqual(path, 'me/charging-sessions/export.pdf')
        span = datetime.fromisoformat(params['to']) - datetime.fromisoformat(params['from'])
        self.assertEqual(span.days, 90)


class OwnerResultTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = HandlerApp()
        self.app.api = DemoApi()
        await self.app.api.login(DEMO_EMAIL, DEMO_PASSWORD)
        self.app.profile = await self.app.api.request('GET', 'me')

    async def test_dashboard_shows_period_result_with_the_core_cascade(self):
        screen = await history.build(self.app, manage=True)
        card = next(c for c in descendants(screen) if getattr(c, 'data', None) == 'owner-result')
        text = texts(card)
        for expected in ('Resultado do período', 'Receita cobrada', 'Comissão da plataforma (25%)', 'Repasse ao dono',
                         'Aluguel das centrais (', 'Repasse líquido', 'Custo da energia', 'Resultado estimado',
                         'Margem de contribuição antes do aluguel', 'Receita bruta não é lucro.'):
            self.assertIn(expected, text)
        report = await self.app.api.owner_margin({**history_owner._window(7), 'limit': 1})
        totals = report['totals']
        self.assertEqual(Decimal(totals['revenue_total']) - Decimal(totals['platform_fee']), Decimal(totals['owner_net']))
        self.assertEqual(Decimal(totals['owner_net']) - Decimal(totals['energy_cost']), Decimal(totals['margin']))
        # Aluguel R$ 99,00/mês por central, 7 dias: descontado do repasse e do resultado.
        self.assertGreater(Decimal(totals['central_rent']), 0)
        self.assertEqual(Decimal(totals['owner_net']) - Decimal(totals['central_rent']),
                         Decimal(totals['owner_net_after_rent']))
        self.assertEqual(Decimal(totals['margin']) - Decimal(totals['central_rent']), Decimal(totals['result']))
        self.assertIn(history_owner._brl(totals['owner_net']), text)
        self.assertIn(history_owner._brl(totals['owner_net_after_rent']), text)
        self.assertNotIn('demo', text.lower())
        self.assertNotIn('simulad', text.lower())
        await card.on_click(None)
        self.app.go.assert_awaited_with('history', manage=True, page='economics')

    async def test_dashboard_without_margin_endpoint_keeps_working(self):
        self.app.api.owner_margin = AsyncMock(side_effect=ApiError('Not found', 404, 'not_found'))
        screen = await history.build(self.app, manage=True)
        self.assertFalse(any(getattr(c, 'data', None) == 'owner-result' for c in descendants(screen)))
        self.assertIn('Receita total', texts(screen))

    async def test_economics_page_edits_cost_keeps_fee_read_only_and_exports(self):
        screen = await history.build(self.app, manage=True, page='economics', days=14)
        text = texts(screen)
        for expected in ('Resultado do período', 'Últimos 14 dias', 'Custo da energia', 'Marginal Pinheiros',
                         'Custo do kWh pago à distribuidora', 'Comissão da plataforma: 25% · definida em contrato (só leitura).',
                         'Exportar resultado (PDF/CSV)', 'PDF indisponível nesta conta'):
            self.assertIn(expected, text)
        field = next(c for c in descendants(screen) if isinstance(c, ft.TextField)
                     and str(c.data or '').startswith('energy-cost-'))
        self.assertEqual(field.value, '0,85')
        station_id = field.data.removeprefix('energy-cost-')
        field.value = '200'
        await tapper(screen, 'Salvar custo').on_click(None)
        self.assertEqual(self.app.notices[-1], 'O custo do kWh vai de R$ 0,00 a R$ 100,00.')
        field.value = '0,92'
        await tapper(screen, 'Salvar custo').on_click(None)
        self.assertEqual((await self.app.api.station_economics(station_id))['energy_cost_per_kwh'], '0.9200')
        self.app.go.assert_awaited_with('history', manage=True, page='economics', days=14)
        with self.assertRaises(ApiError) as caught:
            await self.app.api.request('PUT', f'stations/{station_id}/economics', {'platform_fee_percent': 10})
        self.assertEqual(caught.exception.code, 'fee_read_only')
        exporter = next(c for c in descendants(screen) if getattr(c, 'data', None) == 'margin-export')
        with patch.object(files, 'deliver', AsyncMock(return_value='ok')) as deliver:
            await tapper(exporter, 'CSV').on_click(None)
        content, filename = deliver.await_args.args[1:]
        self.assertTrue(content.decode('utf-8').startswith('ID da sessão,Fim,Posto'))
        self.assertRegex(filename, r'^chargegrid-resultado-\d{8}-\d{4}\.csv$')

    async def test_real_economics_page_uses_the_api_contract(self):
        app = HandlerApp()
        app.profile = {'operator_enabled': True}
        app.api.owner_margin = AsyncMock(return_value=margin_report())
        app.api.update_station_economics = AsyncMock(return_value={})
        app.api.owner_export = AsyncMock(return_value=b'%PDF')
        screen = await history.build(app, manage=True, page='economics')
        params = app.api.owner_margin.await_args.args[0]
        self.assertEqual(set(params), {'from', 'to', 'limit'})
        field = next(c for c in descendants(screen) if isinstance(c, ft.TextField))
        field.value = ''
        await tapper(screen, 'Salvar custo').on_click(None)
        app.api.update_station_economics.assert_awaited_once_with('st-1', None)
        with patch.object(files, 'deliver', AsyncMock(return_value='ok')):
            await tapper(screen, 'PDF').on_click(None)
        self.assertEqual(app.api.owner_export.await_args.args[:2], ('margin', 'pdf'))
        self.assertEqual(set(app.api.owner_export.await_args.args[2]), {'from', 'to'})

    async def test_economics_page_offers_month_statements_with_rent_lines(self):
        screen = await history.build(self.app, manage=True, page='economics', days=history_owner.MONTH_PREVIOUS)
        text = texts(screen)
        for expected in ('Mês anterior', 'Aluguel das centrais', 'Repasse líquido', 'Aluguel por central: R$ 99,00/mês'):
            self.assertIn(expected, text)
        card = next(c for c in descendants(screen) if getattr(c, 'data', None) == 'central-rent')
        self.assertRegex(texts(card), r'\d{2}/\d{4} · (28|29|30|31)/(28|29|30|31) dias')
        self.assertIn('R$ 99,00', texts(card))  # mês anterior inteiro = o valor mensal
        window = history_owner._window(history_owner.MONTH_CURRENT)
        start = datetime.fromisoformat(window['from']).astimezone(analytics.REPORT_TZ)
        self.assertEqual((start.day, start.hour), (1, 0))
        self.assertIn('Mês atual', texts(await history.build(self.app, manage=True, page='economics',
                                                             days=history_owner.MONTH_CURRENT)))

    async def test_detailed_cascade_closes_from_gross_to_charged(self):
        report = margin_report()
        report['totals'].update(gross='112.00', discount='10.00', overstay_revenue=None, payment_adjustment='-2.00')
        report['coupons'] = {'sessions': 2, 'discount': '10.00'}
        text = texts(ft.Column(history_owner.cascade(report, detailed=True)))
        for expected in ('Receita bruta', 'R$ 112,00', 'Cupons (2 recargas)', 'Ajuste do pagamento', '− R$ 2,00',
                         'Receita cobrada', 'R$ 100,00', 'Margem estimada'):
            self.assertIn(expected, text)
        self.assertNotIn('Aluguel', text)

    async def test_missing_cost_is_never_zero(self):
        report = margin_report()
        report['totals'].update(energy_cost=None, margin=None,
                                coverage={'sessions': 4, 'with_energy_cost': 0, 'missing_energy_cost': 4})
        text = texts(history_owner.result_card(self.app, report))
        self.assertIn('não informado', text)
        self.assertIn('4 de 4 recargas sem custo do kWh', text)
        self.assertNotIn('R$ 0,00', text)


class OwnerApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_margin_and_economics_routes(self):
        calls = []

        def handler(request):
            calls.append((request.method, request.url.path, dict(request.url.params),
                          request.content.decode() or None))
            if request.url.path.endswith('.pdf'):
                return httpx.Response(200, content=b'%PDF')
            return httpx.Response(200, json={'ok': True})

        client = ApiClient('https://api.example.test/v1', httpx.MockTransport(handler))
        client.session.update({'access_token': 'a', 'refresh_token': 'r', 'expires_in': 3600})
        await client.owner_margin({'from': 'a', 'station_id': None})
        self.assertEqual(await client.owner_export('margin', 'pdf', {'to': 'b'}), b'%PDF')
        await client.station_economics('st')
        await client.update_station_economics('st', '0.85')
        self.assertEqual(calls[0][:3], ('GET', '/v1/owner/margin', {'from': 'a'}))
        self.assertEqual(calls[1][:3], ('GET', '/v1/owner/export/margin.pdf', {'to': 'b'}))
        self.assertEqual(calls[2][:2], ('GET', '/v1/stations/st/economics'))
        self.assertEqual((calls[3][:2], json.loads(calls[3][3])),
                         (('PUT', '/v1/stations/st/economics'), {'energy_cost_per_kwh': '0.85'}))
        with self.assertRaises(ValueError):
            await client.owner_export('margin', 'json')
        with self.assertRaises(ValueError):
            await client.owner_export('sessions', 'pdf')
        await client.close()


class PayoutUsesOwnerNetTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_balance_is_the_owner_net_not_gross_revenue(self):
        app = SimpleNamespace(api=SimpleNamespace(is_demo=False, owner_margin=AsyncMock(return_value=margin_report())),
                              link=lambda *a, **k: None, back=None)
        self.assertEqual(await payout.load_owner_net(app), Decimal('75.00'))
        params = app.api.owner_margin.await_args.args[0]
        span = datetime.fromisoformat(params['to']) - datetime.fromisoformat(params['from'])
        self.assertEqual((span.days, params['limit']), (payout.NET_DAYS, 1))
        self.assertEqual(payout.available(app), Decimal('75.00'))  # receita bruta 100, comissão 25
        self.assertEqual(payout.movements(app)[-1]['title'], 'Repasse das recargas')
        app.api.owner_margin.return_value = margin_report(owner_net='60.00')
        screen = await payout_screen.build(app)
        self.assertIn('R$ 60,00', texts(screen))
        app.api.owner_margin.side_effect = ApiError('offline')
        await payout_screen.build(app)  # sem rede: mantém o último valor
        self.assertEqual(payout.available(app), Decimal('60.00'))

    async def test_demo_payout_never_calls_the_api(self):
        app = SimpleNamespace(api=SimpleNamespace(is_demo=True, owner_margin=AsyncMock()))
        self.assertIsNone(await payout.load_owner_net(app))
        app.api.owner_margin.assert_not_called()


if __name__ == '__main__':
    unittest.main()
