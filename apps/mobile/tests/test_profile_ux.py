"""Account viewing/editing and wizard navigation use separate, explicit states."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.app import ChargeGridApp
from chargegrid_app.navigation import SCREENS, form_route, parent_route, tab_entries
from chargegrid_app.screens import profile
from test_behavior import HandlerApp, click, descendants

PROFILE = {'id':'user','name':'Marina','phone':'11988882211','vehicle_description':'Veículo de exemplo','account_type':'consumer'}


class AccountUxTests(unittest.IsolatedAsyncioTestCase):
    async def test_account_view_has_no_editable_fields_and_edit_is_explicit(self):
        app = HandlerApp()
        app.logout = AsyncMock()
        app.api.request.return_value = PROFILE
        app.api.session.user = {'email':'marina@example.com'}
        screen = await profile.build(app)
        self.assertFalse(any(isinstance(c,ft.TextField) for c in descendants(screen)))
        labels = [c.label for c in descendants(screen) if isinstance(c,ft.Semantics)]
        self.assertIn('Nome: Marina',labels)
        self.assertIn('E-mail: marina@example.com',labels)
        await click(screen,'Editar informações')(None)
        app.go.assert_awaited_once_with('profile',mode='edit')
        self.assertFalse(form_route('profile',{}))
        self.assertTrue(form_route('profile',{'mode':'edit'}))

    async def test_edit_saves_optional_fields_and_returns_to_account(self):
        app = HandlerApp()
        app.api.request.return_value = {**PROFILE,'phone':None}
        screen = profile.edit_form(app,PROFILE)
        fields = [c for c in descendants(screen) if isinstance(c,ft.TextField)]
        fields[0].value,fields[1].value,fields[2].value = ' Marina Silva ','',' Carro '
        await click(screen,'Salvar informações')(None)
        app.api.request.assert_awaited_once_with('PATCH','me',{'name':'Marina Silva','phone':None,'vehicle_description':'Carro'})
        app.go.assert_awaited_once_with('profile')

    async def test_invalid_edit_does_not_send_and_preserves_values(self):
        for name,phone,vehicle in [('', '', ''),('N'*101,'',''),('Name','1'*31,''),('Name','','V'*201)]:
            with self.subTest(name_length=len(name),phone_length=len(phone),vehicle_length=len(vehicle)):
                app = HandlerApp()
                screen = profile.edit_form(app,PROFILE)
                fields = [c for c in descendants(screen) if isinstance(c,ft.TextField)]
                for control,value in zip(fields,(name,phone,vehicle)):
                    control.value = value
                with self.assertRaises(ApiError):
                    await click(screen,'Salvar informações')(None)
                app.api.request.assert_not_called()
                self.assertEqual([c.value for c in fields],[name,phone,vehicle])

    async def test_back_moves_between_wizard_steps_without_losing_context(self):
        data = {'step':3,'public_code':'POINT','reservation_id':'r','point_context':{'station_id':'s'}}
        app = SimpleNamespace(route='charging',data=data,go=AsyncMock(),prepare_navigation=AsyncMock(return_value=True))
        event = SimpleNamespace(control=SimpleNamespace(confirm_pop=AsyncMock()))
        await ChargeGridApp.native_back(app,event)
        event.control.confirm_pop.assert_awaited_once_with(False)
        app.go.assert_awaited_once_with('charging',**{**data,'step':2})
        self.assertEqual(parent_route('charging',{**data,'step':1}),('reservations',{}))
        self.assertFalse(form_route('charging',data))

    async def test_back_from_unconfirmed_start_leaves_wizard_without_editing_request(self):
        data = {'step':3,'pending_start':True,'public_code':'POINT','reservation_id':'r',
                'point_context':{'station_id':'station'}}
        self.assertEqual(parent_route('charging',data),('stations',{'station_id':'station'}))
        self.assertEqual(parent_route('charging',{'step':3,'pending_start':True}),('stations',{}))

    async def test_chat_replaces_help_in_both_navigation_modes(self):
        self.assertIn('chat',SCREENS)
        self.assertNotIn('help',SCREENS)
        for mode in ('consumer','vendor'):
            entries = tab_entries(mode)
            self.assertIn(('chat','Chat',{}),entries)
            self.assertNotIn('help',[route for route,_,_ in entries])

    async def test_auth_boundary_discards_only_account_scoped_ui_state(self):
        app = SimpleNamespace(charging_draft={'presence':'12345'},chat_messages=[{'role':'user','content':'private'}],
                              chat_draft='not sent',_chat_account_id='old',dark_mode=True)
        ChargeGridApp.reset_account_ui(app)
        self.assertIsNone(app.charging_draft)
        self.assertEqual(app.chat_messages,[])
        self.assertEqual(app.chat_draft,'')
        self.assertIsNone(app._chat_account_id)
        self.assertTrue(app.dark_mode)
