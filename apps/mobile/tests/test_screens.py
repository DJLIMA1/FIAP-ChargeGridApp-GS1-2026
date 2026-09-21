import unittest
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.app import ChargeGridApp
from chargegrid_app.screens import auth, charging, home, reservations, stations
from chargegrid_app.session import Session


class FakeApi:
    def __init__(self,responses):
        self.responses=list(responses)
        self.last_session_id=None
    async def request(self,*args,**kwargs):
        return self.responses.pop(0)
    def new_key(self):
        return 'key'
    def clear_operation(self,path):
        pass


class FakeApp:
    def __init__(self,responses):
        self.api=FakeApi(responses)
        self.poll=None
        self.page=type('Page',(),{'update':lambda self:None})()
    def action(self,callback): return lambda event:None
    def link(self,*args,**kwargs): return lambda event:None
    def set_poll(self,callback,interval): self.poll=(callback,interval)
    def notice(self,message): pass


class ScreenTests(unittest.IsolatedAsyncioTestCase):
    async def test_forgot_password_matches_recovery_flow(self):
        control=await auth.build(FakeApp([]),mode='forgot')
        texts=[]
        def visit(item):
            if isinstance(item,ft.Text): texts.append(str(item.value))
            content=getattr(item,'content',None)
            if content and not isinstance(content,str): visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(control)
        joined=' '.join(texts)
        self.assertIn('Enviaremos um link de redefinição',joined)
        self.assertIn('Voltar',joined)
        self.assertIn('Enviar link',joined)

    async def test_register_uses_returned_session_without_confirmation_screen(self):
        class RegisterApi:
            def __init__(self): self.session=Session()
            async def request(self,*args,**kwargs):
                return {'access_token':'access','refresh_token':'refresh','expires_in':3600,'user':{'id':'u','email':'novo@example.com'},'requires_email_confirmation':False}
        class RegisterApp(FakeApp):
            def __init__(self):
                super().__init__([]); self.api=RegisterApi(); self.signed=False
            def action(self,callback): return callback
            async def signed_in(self): self.signed=True
        app=RegisterApp()
        control=await auth.build(app,mode='register')
        fields=[]
        clickable=[]
        def visit(item):
            if isinstance(item,ft.TextField): fields.append(item)
            content=getattr(item,'content',None)
            if isinstance(content,ft.Text) and content.value=='Criar conta' and getattr(item,'on_click',None): clickable.append(item)
            if content and not isinstance(content,str): visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(control)
        for field,value in zip(fields,['Novo Nome','novo@example.com','teste1234']): field.value=value
        await clickable[0].on_click()
        self.assertTrue(app.signed)
        self.assertEqual(app.api.session.access_token,'access')

    async def test_register_without_session_returns_to_login_neutrally(self):
        class RegisterApi:
            def __init__(self): self.session=Session()
            async def request(self,*args,**kwargs): return {'requires_email_confirmation':False}
        class RegisterApp(FakeApp):
            def __init__(self):
                super().__init__([]); self.api=RegisterApi(); self.go_calls=[]; self.notices=[]
            def action(self,callback): return callback
            async def go(self,*args,**kwargs): self.go_calls.append((args,kwargs))
            def notice(self,message): self.notices.append(message)
        app=RegisterApp()
        control=await auth.build(app,mode='register')
        fields=[]
        clickable=[]
        def visit(item):
            if isinstance(item,ft.TextField): fields.append(item)
            content=getattr(item,'content',None)
            if isinstance(content,ft.Text) and content.value=='Criar conta' and getattr(item,'on_click',None): clickable.append(item)
            if content and not isinstance(content,str): visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(control)
        for field,value in zip(fields,['Novo Nome','novo@example.com','teste1234']): field.value=value
        await clickable[0].on_click()
        self.assertEqual(app.go_calls,[(('auth',),{'email_value':'novo@example.com'})])
        self.assertEqual(app.notices,['Confira seu e-mail. Se já tem uma conta, entre com sua senha.'])

    async def test_register_validates_fields_before_calling_api(self):
        class RegisterApi:
            def __init__(self): self.calls=[]
            async def request(self,*args,**kwargs): self.calls.append((args,kwargs))
        class RegisterApp(FakeApp):
            def __init__(self):
                super().__init__([]); self.api=RegisterApi()
            def action(self,callback): return callback

        app=RegisterApp()
        control=await auth.build(app,mode='register')
        create=next(
            item for item in control.controls
            if isinstance(getattr(item,'content',None),ft.Text)
            and item.content.value=='Criar conta'
        )
        await create.on_click()
        self.assertEqual(app.api.calls,[])
        self.assertEqual(control.controls[4].controls[2].content.value, 'Informe seu nome completo.')
        self.assertTrue(control.controls[4].controls[2].visible)

    async def test_register_rejects_short_password_locally(self):
        class RegisterApi:
            def __init__(self): self.calls=[]
            async def request(self,*args,**kwargs): self.calls.append((args,kwargs))
        class RegisterApp(FakeApp):
            def __init__(self):
                super().__init__([]); self.api=RegisterApi()
            def action(self,callback): return callback

        app=RegisterApp()
        control=await auth.build(app,mode='register')
        fields=[]
        def visit(item):
            if isinstance(item,ft.TextField): fields.append(item)
            content=getattr(item,'content',None)
            if content and not isinstance(content,str): visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(control)
        for field,value in zip(fields,['Novo Nome','novo@example.com','1234567']): field.value=value
        create=next(item for item in control.controls if isinstance(getattr(item,'content',None),ft.Text) and item.content.value=='Criar conta')
        await create.on_click()
        self.assertEqual(app.api.calls,[])
        self.assertEqual(control.controls[6].controls[2].content.value, 'A senha precisa ter pelo menos 8 caracteres.')
        self.assertTrue(control.controls[6].controls[2].visible)

    async def test_register_shows_api_error_inside_form(self):
        class RegisterApi:
            async def request(self,*args,**kwargs):
                raise auth.ApiError(
                    'Não foi possível enviar a mensagem agora',503,'auth_unavailable'
                )
        class RegisterApp(FakeApp):
            def __init__(self):
                super().__init__([]); self.api=RegisterApi(); self.notices=[]
            def action(self,callback): return callback
            def notice(self,message): self.notices.append(message)

        app=RegisterApp()
        control=await auth.build(app,mode='register')
        fields=[]
        def visit(item):
            if isinstance(item,ft.TextField): fields.append(item)
            content=getattr(item,'content',None)
            if content and not isinstance(content,str): visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(control)
        for field,value in zip(fields,['Novo Nome','novo@example.com','teste1234']): field.value=value
        create=next(
            item for item in control.controls
            if isinstance(getattr(item,'content',None),ft.Text)
            and item.content.value=='Criar conta'
        )
        await create.on_click()
        messages=[item.value for item in control.controls if isinstance(item,ft.Text) and item.visible]
        expected='Não foi possível enviar a mensagem agora'
        self.assertIn(expected,messages)
        self.assertEqual(app.notices,[])
        self.assertFalse(create.disabled)

    async def test_home_battery_uses_api_soc_and_identifies_simulation(self):
        class HomeApi:
            def __init__(self, session): self.session_data=session
            async def request(self, method, path, **kwargs):
                return {'reservations/current':None,'charging-sessions/current':self.session_data,'stations':{'items':[],'total':0,'limit':5,'offset':0},'me/summary':{'estimated_cost':'0','energy_wh':'0','sessions_count':0}}[path]
        app=FakeApp([])
        app.profile={'name':'Teste','vehicle_description':None}
        app.api=HomeApi(None)
        without_soc=await home.build(app)
        app.api=HomeApi({'id':'s','status':'charging','soc_percent':61,'source':'simulated','energy_wh':0,'cost_estimate':0,'online':True})
        with_soc=await home.build(app)
        def texts(control):
            found=[]
            def visit(item):
                if isinstance(item,ft.Text): found.append(str(item.value))
                content=getattr(item,'content',None)
                if content: visit(content)
                for child in getattr(item,'controls',[]) or []: visit(child)
            visit(control)
            return ' '.join(found)
        self.assertNotIn('42%',texts(without_soc))
        self.assertIn('Bateria 61% · Simulada pelo equipamento',texts(with_soc))

    async def test_real_app_builds_login_with_desktop_width_limit(self):
        page = type('Page', (), {})()
        page.width = 1000
        page.window = type('Window', (), {})()
        page.add = lambda control: None
        page.update = lambda: None
        app = ChargeGridApp(page)
        try:
            await app.go('auth')
            self.assertEqual(app.root.content.width, 520)
        finally:
            await app.api.close()

    async def test_reconnect_reopens_api_and_login_before_navigation(self):
        page = type('Page', (), {})()
        page.width = 390
        page.window = type('Window', (), {})()
        page.add = lambda control: None
        page.update = lambda: None
        app = ChargeGridApp(page)
        try:
            await app.go('auth')
            await app.disconnect(None)
            closed_http = app.api.http
            await app.connect(None)
            self.assertIsNot(app.api.http,closed_http)
            self.assertFalse(app.api.session.access_token)
            await app.go('auth',mode='register')
            self.assertFalse(app.closed)
            self.assertEqual(app.route,'auth')
            self.assertNotIn('Conectando',str(app.root.content))
        finally:
            await app.api.close()

    async def test_auth_fields_have_visible_labels(self):
        control=await auth.build(FakeApp([]),mode='login')
        text_fields=[]
        labels=[]
        def visit(item):
            if isinstance(item,ft.TextField): text_fields.append(item)
            if isinstance(item,ft.Text): labels.append(str(item.value))
            content=getattr(item,'content',None)
            if content: visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(control)
        self.assertEqual([f.hint_text for f in text_fields],['voce@email.com','••••••••'])
        self.assertIn('E-mail',labels)
        self.assertIn('Senha',labels)

    async def test_auth_layout_uses_full_width_fields_and_reference_heights(self):
        control=await auth.build(FakeApp([]),mode='login')
        fields=[]
        buttons=[]
        labels=[]
        def visit(item):
            if isinstance(item,ft.TextField): fields.append(item)
            if isinstance(item,ft.Text): labels.append(item.value)
            if isinstance(getattr(item,'content',None),ft.Text) and item.content.value in {'Entrar','Criar conta'}:
                buttons.append(item)
            content=getattr(item,'content',None)
            if content and not isinstance(content,str): visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(control)
        self.assertEqual([field.height for field in fields],[50,50])
        self.assertEqual([item.height for item in buttons],[48,48])
        self.assertTrue(all(field_group.horizontal_alignment==ft.CrossAxisAlignment.STRETCH for field_group in (control.controls[1],control.controls[2])))
        self.assertNotIn('Sou consumidor',labels)
        self.assertNotIn('Sou vendedor',labels)

    async def test_login_leaves_destination_to_persisted_profile(self):
        class LoginApi:
            async def login(self,email,password): pass
        class LoginApp(FakeApp):
            def __init__(self):
                super().__init__([]); self.api=LoginApi(); self.destinations=[]
            def action(self,callback): return callback
            async def signed_in(self,destination='home'): self.destinations.append(destination)
        app=LoginApp()
        control=await auth.build(app,mode='login',account_type='vendor')
        fields=[]
        def visit(item):
            if isinstance(item,ft.TextField): fields.append(item)
            content=getattr(item,'content',None)
            if content and not isinstance(content,str): visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(control)
        fields[0].value='vendedor@example.com'
        fields[1].value='12345678'
        login=next(item for item in control.controls if isinstance(getattr(item,'content',None),ft.Text) and item.content.value=='Entrar')
        await login.on_click()
        self.assertEqual(app.destinations,['home'])

    async def test_verify_screen_offers_explicit_resend_and_login_return(self):
        class VerifyApp(FakeApp):
            def __init__(self):
                super().__init__([{'message':'generic'}])
                self.go_calls=[]
                self.notices=[]
            def action(self, callback): return callback
            def link(self, route, **data):
                async def navigate(event):
                    await self.go(route, **data)
                return navigate
            async def go(self,*args,**kwargs): self.go_calls.append((args,kwargs))
            def notice(self,message): self.notices.append(message)

        app=VerifyApp()
        control=await auth.build(app,mode='verify',email_value='u@example.com')
        texts=[]
        fields=[]
        def visit(item):
            if isinstance(item,ft.Text): texts.append(str(item.value))
            if isinstance(item,ft.TextButton): texts.append(str(item.content))
            if isinstance(item,ft.TextField): fields.append(str(item.hint_text))
            content=getattr(item,'content',None)
            if content and not isinstance(content,str): visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(control)
        joined=' '.join(texts)
        self.assertIn('Reenviar confirmação',joined)
        self.assertIn('Voltar para entrar',joined)
        self.assertIn('Abra o link de confirmação',joined)
        self.assertEqual(fields,['voce@email.com'])
        def descendants(item):
            yield item
            content=getattr(item,'content',None)
            if content and not isinstance(content,str): yield from descendants(content)
            for child in getattr(item,'controls',[]) or []: yield from descendants(child)
        email=next(item for item in descendants(control) if isinstance(item,ft.TextField))
        email.value='novo@example.com'
        await control.controls[3].on_click()
        self.assertEqual(app.go_calls,[(('auth',),{'email_value':'novo@example.com'})])
        await control.controls[4].on_click()
        self.assertEqual(app.api.responses,[ ])
        self.assertEqual(app.notices,[])
        self.assertEqual(control.controls[5].value,'Se a conta ainda precisar de confirmação, uma nova mensagem será enviada.')

    async def test_charging_form_does_not_poll(self):
        app=FakeApp([None])
        screen=await charging.build(app)
        self.assertIsNone(app.poll)
        self.assertIsInstance(screen,ft.Column)

    async def test_active_charging_polls_only_state_container(self):
        session={'id':'s','status':'charging','soc_percent':50,'source':'simulated','last_measurement_at':None,'energy_wh':10,'cost_estimate':'0.01','max_duration_minutes':30,'online':True,'end_reason':None}
        app=FakeApp([session])
        await charging.build(app)
        self.assertEqual(app.poll[1],5)

    async def test_empty_reservation_screen_does_not_poll(self):
        app=FakeApp([None])
        await reservations.build(app)
        self.assertIsNone(app.poll)

    async def test_station_form_remains_while_listing_polls(self):
        response={'items':[],'total':0,'limit':20,'offset':0}
        app=FakeApp([response])
        with patch('chargegrid_app.screens.stations.map_widget',new=AsyncMock()):
            screen=await stations.build(app)
        self.assertIsInstance(screen,ft.Column)
        self.assertEqual(app.poll[1],10)
        labels=[]
        def visit(item):
            if isinstance(item,ft.TextField): labels.append(item.label)
            content=getattr(item,'content',None)
            if content: visit(content)
            for child in getattr(item,'controls',[]) or []: visit(child)
        visit(screen)
        self.assertIn('Endereço para buscar',labels)
        def descendants(item):
            yield item
            content=getattr(item,'content',None)
            if content and not isinstance(content,str): yield from descendants(content)
            for child in getattr(item,'controls',[]) or []: yield from descendants(child)
        coordinate_search=next(item for item in descendants(screen) if isinstance(item,ft.ExpansionTile))
        self.assertEqual(coordinate_search.title.value,'Busca por coordenadas')
        self.assertFalse(coordinate_search.expanded)


if __name__ == '__main__':
    unittest.main()
