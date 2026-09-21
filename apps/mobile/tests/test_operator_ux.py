import unittest
from unittest.mock import patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.screens import coupons, operator
from test_behavior import HandlerApp, click, descendants


class OperatorUxTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_coupon_uses_station_names_and_posts_selected_id(self):
        app = HandlerApp()
        app.profile = {'operator_enabled':True}
        app.api.request.return_value = {'items':[{'id':'station-id','name':'Posto Central'}],'total':1}
        screen = await coupons.build(app,manage=True,create=True)
        dropdown = next(item for item in descendants(screen) if isinstance(item,ft.Dropdown))
        self.assertTrue(dropdown.expand)
        self.assertTrue(any(isinstance(item,ft.Row) and dropdown in item.controls for item in descendants(screen)))
        self.assertEqual([(item.key,item.text) for item in dropdown.options],[('__all__','Todos os meus postos'),('station-id','Posto Central')])
        self.assertFalse(next(item for item in descendants(screen) if isinstance(item,ft.Switch)).visible)
        fields = {item.label:item for item in descendants(screen) if isinstance(item,ft.TextField)}
        self.assertNotIn('ID do posto (opcional)',fields)
        fields['Código'].value = 'WELCOME'
        dropdown.value = 'station-id'
        await click(screen,'Salvar cupom')(None)
        self.assertEqual(app.api.request.call_args.args[:2],('POST','coupons'))
        self.assertEqual(app.api.request.call_args.args[2]['station_id'],'station-id')
        self.assertNotIn('active',app.api.request.call_args.args[2])

    async def test_all_station_coupon_does_not_send_fake_identifier(self):
        app = HandlerApp()
        screen = coupons.form(app,stations=[{'id':'s','name':'Posto'}])
        code = next(item for item in descendants(screen) if isinstance(item,ft.TextField) and item.label == 'Código')
        code.value = 'ALL'
        await click(screen,'Salvar cupom')(None)
        self.assertNotIn('station_id',app.api.request.call_args.args[2])

    async def test_owned_station_options_include_later_pages(self):
        app = HandlerApp()
        app.api.request.side_effect = [{'items':[{'id':'first','name':'A'}],'total':2},{'items':[{'id':'second','name':'B'}],'total':2}]
        result = await coupons.owned_stations(app)
        self.assertEqual([item['id'] for item in result],['first','second'])
        self.assertEqual(app.api.request.call_args.kwargs['params']['offset'],1)

    async def test_manage_coupon_list_shows_names_and_active_state(self):
        app = HandlerApp()
        app.profile = {'operator_enabled':True}
        app.api.request.side_effect = [
            {'items':[{'id':'coupon','code':'OFF','description':'Desconto','discount_percent':10,'valid_until':'2030-01-01T00:00:00Z','station_id':'hidden-uuid','active':False}]},
            {'items':[{'id':'hidden-uuid','name':'Posto Central'}],'total':1},
        ]
        screen = await coupons.build(app,manage=True)
        texts = ' '.join(str(item.value) for item in descendants(screen) if isinstance(item,ft.Text))
        self.assertIn('Válido em: Posto Central',texts)
        self.assertIn('Inativo',texts)
        self.assertNotIn('hidden-uuid',texts)

    async def test_consumer_coupon_resolves_public_station_name(self):
        app = HandlerApp()
        app.api.request.side_effect = [
            {'items':[{'id':'coupon','code':'OFF','description':'Desconto','discount_percent':10,'valid_until':'2030-01-01T00:00:00Z','station_id':'hidden-uuid'}]},
            {'id':'hidden-uuid','name':'Posto Central'},
        ]
        screen = await coupons.build(app)
        texts = ' '.join(str(item.value) for item in descendants(screen) if isinstance(item,ft.Text))
        self.assertIn('Válido em: Posto Central',texts)
        self.assertNotIn('hidden-uuid',texts)
        app.api.request.assert_awaited_with('GET','stations/hidden-uuid')

    async def test_connector_edit_rediscovers_readonly_device_without_secret(self):
        app = HandlerApp()
        app.api.request.return_value = {'device_id':'known-device','online':True,'last_seen':None}
        screen = await operator.connector_form(app,'station',{'id':'connector'},device_id='stale-navigation-id')
        device = next(item for item in descendants(screen) if isinstance(item,ft.TextField) and item.label == 'Dispositivo vinculado')
        self.assertTrue(device.read_only)
        self.assertTrue(device.visible)
        self.assertEqual(device.value,'known-device')
        app.api.request.assert_awaited_once_with('GET','connectors/connector/device')
        provision = next(item for item in descendants(screen) if isinstance(getattr(item,'content',None),ft.Text) and item.content.value == 'Provisionar dispositivo')
        self.assertFalse(provision.visible)
        await click(screen,'Revogar dispositivo')(None)
        self.assertFalse(device.visible)
        self.assertTrue(provision.visible)

    async def test_missing_device_can_be_provisioned_and_keeps_returned_id(self):
        app = HandlerApp()
        app.api.request.side_effect = [ApiError('Ausente',404),{'device_id':'new-device','device_key':'test-only-secret'}]
        screen = await operator.connector_form(app,'station',{'id':'connector'})
        with patch('chargegrid_app.screens.operator.show_key') as show_key:
            await click(screen,'Provisionar dispositivo')(None)
            show_key.assert_called_once()
        device = next(item for item in descendants(screen) if isinstance(item,ft.TextField) and item.label == 'Dispositivo vinculado')
        self.assertEqual(device.value,'new-device')
        self.assertTrue(device.visible)
        texts = ' '.join(str(item.value) for item in descendants(screen) if isinstance(item,ft.Text))
        self.assertNotIn('test-only-secret',texts)

    async def test_device_lookup_network_failure_is_not_mistaken_for_unprovisioned(self):
        app = HandlerApp()
        app.api.request.side_effect = ApiError('Rede indisponível',503)
        with self.assertRaises(ApiError):
            await operator.connector_form(app,'station',{'id':'connector'})
