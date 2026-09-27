"""Regressions for seller setup, device maintenance and coupon management."""
import unittest
from unittest.mock import Mock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.screens import coupons, onboarding, operator, ownership
from test_behavior import HandlerApp, click, descendants


def texts(screen):
    return ' '.join(str(control.value) for control in descendants(screen) if isinstance(control,ft.Text))


def fields(screen):
    return {control.label:control for control in descendants(screen) if isinstance(control,ft.TextField)}


def station_fixture(active=True):
    return {
        'id':'station','name':'Posto Central','address':'Rua do Centro, 100, São Paulo',
        'latitude':-23.55,'longitude':-46.63,'active':active,
        'connectors':[{
            'id':'point','public_code':'CG-POINT','connector_type':'Tipo 2','power_kw':'7.4',
            'price_per_kwh':'1.5','max_duration_minutes':60,'active':False,'online':True,
        }],
    }


def coupon_fixture(**changes):
    return {
        'id':'coupon','code':'OLD','description':'Desconto','discount_percent':10,
        'valid_until':'2020-01-01T12:30:47Z','active':True,'station_id':None,**changes,
    }


class SellerFlowFixesTests(unittest.IsolatedAsyncioTestCase):
    async def test_reset_after_provision_uses_new_device_and_polls_it(self):
        app = HandlerApp()
        app.page.show_dialog = Mock()
        app.page.pop_dialog = Mock()
        app.api.request.side_effect = [
            ApiError('Ausente',404),{'device_id':'new-device','device_key':'test-only'},
            {'status':'pending'},{'status':'applied'},
        ]
        screen = await operator.connector_form(app,'station',{'id':'point'})
        with patch('chargegrid_app.screens.operator.show_key'):
            await click(screen,'Provisionar dispositivo')(None)
        await click(screen,'Restaurar ESP32 de fábrica')(None)
        dialog = app.page.show_dialog.call_args.args[0]
        self.assertIn('Wi-Fi será preservado',dialog.content.value)
        await dialog.actions[1].on_click(None)
        self.assertEqual(app.api.request.await_args.args,('POST','devices/new-device/factory-reset'))
        await app.poll()
        self.assertEqual(app.api.request.await_args.args,('GET','devices/new-device/factory-reset'))
        self.assertIn('Restauração confirmada',texts(screen))
        active = next(control for control in descendants(screen) if isinstance(control,ft.Switch))
        self.assertFalse(active.value)
        self.assertTrue(active.disabled)

    async def test_reset_after_reprovision_never_targets_revoked_device(self):
        app = HandlerApp()
        app.page.show_dialog = Mock()
        app.page.pop_dialog = Mock()
        app.api.request.side_effect = [
            {'device_id':'old-device','online':True}, {'status':'not_requested'},
            {'revoked':True}, {'device_id':'replacement','device_key':'test-only'}, {'status':'pending'},
        ]
        screen = await operator.connector_form(app,'station',{'id':'point'})
        await click(screen,'Revogar dispositivo')(None)
        with patch('chargegrid_app.screens.operator.show_key'):
            await click(screen,'Provisionar dispositivo')(None)
        await click(screen,'Restaurar ESP32 de fábrica')(None)
        await app.page.show_dialog.call_args.args[0].actions[1].on_click(None)
        self.assertEqual(app.api.request.await_args.args,('POST','devices/replacement/factory-reset'))
        self.assertNotIn(('POST','devices/old-device/factory-reset'),[call.args for call in app.api.request.await_args_list])

    async def test_expired_coupon_can_be_disabled_without_changing_expiry(self):
        app = HandlerApp()
        screen = coupons.form(app,coupon_fixture())
        next(control for control in descendants(screen) if isinstance(control,ft.Switch)).value = False
        await click(screen,'Salvar cupom')(None)
        self.assertEqual(app.api.request.await_args.args,('PATCH','coupons/coupon',{
            'description':'Desconto','discount_percent':10,'active':False,
        }))

    async def test_editing_expired_coupon_description_preserves_original_timestamp_and_state(self):
        app = HandlerApp()
        screen = coupons.form(app,coupon_fixture())
        fields(screen)['Descrição'].value = 'Descrição corrigida'
        await click(screen,'Salvar cupom')(None)
        body = app.api.request.await_args.args[2]
        self.assertEqual(body['description'],'Descrição corrigida')
        self.assertNotIn('valid_until',body)
        self.assertNotIn('active',body)

    async def test_expired_coupon_reactivation_requires_future_expiry(self):
        app = HandlerApp()
        screen = coupons.form(app,coupon_fixture(active=False))
        next(control for control in descendants(screen) if isinstance(control,ft.Switch)).value = True
        with self.assertRaisesRegex(ApiError,'validade futura'):
            await click(screen,'Salvar cupom')(None)
        app.api.request.assert_not_awaited()
        fields(screen)['Validade (dia/mês/ano hora:minuto)'].value = '01/01/2099 12:30'
        await click(screen,'Salvar cupom')(None)
        body = app.api.request.await_args.args[2]
        self.assertTrue(body['active'])
        self.assertTrue(body['valid_until'].startswith('2099-01-01'))

    async def test_coupon_pagination_keeps_owner_and_station_filters(self):
        app = HandlerApp()
        app.profile = {'operator_enabled':True}
        app.api.request.side_effect = [
            {'items':[coupon_fixture()],'total':101},
            {'items':[station_fixture()],'total':1},
        ]
        screen = await coupons.build(app,manage=True,station_id='station',offset=50)
        self.assertEqual(app.api.request.await_args_list[0].kwargs['params'],
                         {'limit':50,'offset':50,'mine':'true','station_id':'station'})
        await click(screen,'Mais cupons')(None)
        app.go.assert_awaited_with('coupons',offset=100,manage=True,station_id='station')
        await click(screen,'Cupons anteriores')(None)
        app.go.assert_awaited_with('coupons',offset=0,manage=True,station_id='station')
        self.assertIn('Expirado',texts(screen))

    async def test_new_seller_coupon_screen_explains_first_link(self):
        app = HandlerApp()
        app.profile = {'account_type':'vendor','operator_enabled':False}
        screen = await coupons.build(app,manage=True)
        self.assertIn('Vincule sua primeira tela',texts(screen))
        await click(screen,'Configurar meu primeiro ponto')(None)
        app.go.assert_awaited_with('operator')
        app.api.request.assert_not_awaited()

    async def test_existing_station_claim_shows_destination_and_skips_shared_location_edit(self):
        app = HandlerApp()
        app.api.request.side_effect = [station_fixture(),{'station_id':'station','connector_id':'new-point'}]
        screen = await ownership.build(app,station_id='station')
        self.assertIn('ADICIONAR PONTO AO POSTO',texts(screen))
        self.assertIn('Posto Central',texts(screen))
        self.assertEqual(app.api.request.await_count,1)
        self.assertEqual(app.api.request.await_args.args,('GET','stations/station'))
        fields(screen)['Código privado do QR'].value = 'a'*43
        await click(screen,'Vincular ponto à minha conta')(None)
        self.assertEqual(app.api.request.await_args.args,
                         ('POST','ownership/claim',{'token':'a'*43,'station_id':'station'}))
        app.go.assert_awaited_with('operator',station_id='station',point_id='new-point',
                                  onboarding=True,step=2,existing_station=True)

    async def test_existing_station_back_step_has_no_editable_address(self):
        app = HandlerApp()
        app.api.request.return_value = station_fixture()
        screen = await onboarding.build(app,'station','point',step=1,existing_station=True)
        self.assertFalse(fields(screen))
        self.assertIn('Posto Central',texts(screen))
        await click(screen,'Continuar para ponto e tarifa')(None)
        app.go.assert_awaited_with('operator',station_id='station',point_id='point',
                                  onboarding=True,step=2,existing_station=True)
        self.assertEqual(app.api.request.await_count,1)

    async def test_existing_station_point_save_only_updates_point_and_retains_context(self):
        app = HandlerApp()
        app.api.request.return_value = station_fixture()
        screen = await onboarding.build(app,'station','point',step=2,existing_station=True)
        fields(screen)['Tarifa por kWh (R$)'].value = '2,50'
        await click(screen,'Salvar e revisar')(None)
        self.assertEqual(app.api.request.await_args.args[:2],('PATCH','connectors/point'))
        self.assertEqual(app.api.request.await_args.args[2]['price_per_kwh'],'2.50')
        app.go.assert_awaited_with('operator',station_id='station',point_id='point',
                                  onboarding=True,step=3,existing_station=True)
        self.assertIn('código temporário #F',texts(screen))

    async def test_publishing_in_existing_disabled_station_does_not_reactivate_other_points(self):
        app = HandlerApp()
        app.api.request.return_value = station_fixture(active=False)
        screen = await onboarding.build(app,'station','point',step=3,existing_station=True)
        self.assertIn('mantém o posto desativado',texts(screen))
        await click(screen,'Publicar ponto')(None)
        self.assertEqual([call.args for call in app.api.request.await_args_list],
                         [('GET','stations/station'),('PATCH','connectors/point',{'active':True})])
        self.assertIn('continua desativado',app.notices[-1])

    async def test_disabled_point_is_not_described_as_incomplete_setup(self):
        app = HandlerApp()
        app.api.request.side_effect = [
            {'account_type':'vendor','operator_enabled':True},
            {'stations':1,'total_sessions':1,'total_energy_wh':1000,'total_estimated_cost':1},
            {'items':[station_fixture()],'total':1},
        ]
        screen = await operator.build(app)
        self.assertIn('Pontos desativados',texts(screen))
        self.assertNotIn('Configuração pendente',texts(screen))
        await click(screen,'Revisar pontos')(None)
        app.go.assert_awaited_with('operator',station_id='station')

    async def test_review_disabled_point_preserves_shared_station(self):
        app = HandlerApp()
        screen = await operator.station_form(app,station_fixture())
        await click(screen,'Revisar e ativar ponto')(None)
        app.go.assert_awaited_with('operator',station_id='station',point_id='point',
                                  onboarding=True,step=2,existing_station=True)

    async def test_invalid_coordinates_show_field_error_without_sending_patch(self):
        app = HandlerApp()
        screen = await operator.station_form(app,station_fixture())
        latitude = fields(screen)['Latitude']
        latitude.value = 'não é número'
        with self.assertRaises(ApiError):
            await click(screen,'Salvar posto')(None)
        self.assertTrue(latitude.error_text)
        app.api.request.assert_not_awaited()

    async def test_retired_point_cannot_be_resumed_in_setup(self):
        app = HandlerApp()
        station = station_fixture()
        station['connectors'][0]['retired'] = True
        app.api.request.return_value = station
        with self.assertRaisesRegex(ApiError,'desvinculado'):
            await onboarding.build(app,'station','point')

    def test_review_address_wraps_below_its_label(self):
        row = onboarding._summary_line('Endereço','Um endereço com nome de rua longo'*5)
        self.assertIsInstance(row,ft.Column)
        self.assertEqual(row.horizontal_alignment,ft.CrossAxisAlignment.STRETCH)
        self.assertIsNone(row.controls[1].max_lines)
