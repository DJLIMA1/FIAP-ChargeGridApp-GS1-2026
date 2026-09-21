import asyncio
import time
import unittest

import httpx
from chargegrid_app.api_client import ApiClient, ApiError
from chargegrid_app.config import validate_api_url
from chargegrid_app.session import Session


def tokens(access='access-1', refresh='refresh-1', expires=3600):
    return {'access_token':access,'refresh_token':refresh,'expires_in':expires,'token_type':'bearer','user':{'id':'u','email':'u@example.com'}}


class ApiClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncTearDown(self):
        if hasattr(self, 'client'):
            await self.client.close()

    async def test_login_and_authorized_request(self):
        requests = []
        def handler(request):
            requests.append(request)
            if request.url.path.endswith('/auth/login'):
                return httpx.Response(200,json=tokens())
            return httpx.Response(200,json={'id':'u'})
        self.client = ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        await self.client.login('u@example.com','12345678')
        await self.client.request('GET','me')
        self.assertEqual(requests[-1].headers['authorization'],'Bearer access-1')

    async def test_unconfirmed_login_preserves_actionable_error_code(self):
        def handler(request):
            return httpx.Response(401,json={'error':{'code':'email_not_confirmed','message':'Confirme seu e-mail'}})
        self.client = ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        with self.assertRaises(ApiError) as raised:
            await self.client.login('u@example.com','12345678')
        self.assertEqual(raised.exception.code,'email_not_confirmed')

    async def test_expired_token_refreshes_before_request(self):
        calls = []
        def handler(request):
            calls.append(request.url.path)
            if request.url.path.endswith('/auth/refresh'):
                return httpx.Response(200,json=tokens('access-2','refresh-2'))
            self.assertEqual(request.headers['authorization'],'Bearer access-2')
            return httpx.Response(200,json={'ok':True})
        self.client = ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens(expires=1))
        self.client.session.expires_at = time.monotonic()-1
        await self.client.request('GET','me')
        self.assertEqual(calls,['/v1/auth/refresh','/v1/me'])

    async def test_same_mutation_body_reuses_key_even_after_redraw(self):
        keys = []
        def handler(request):
            keys.append(request.headers['idempotency-key'])
            return httpx.Response(202,json={'id':'session-1'})
        self.client = ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens())
        body={'public_code':'CG-01','max_duration_minutes':30}
        await self.client.request('POST','charging-sessions',body,key='first')
        await self.client.request('POST','charging-sessions',dict(body),key='new-from-redraw')
        self.assertEqual(keys,['first','first'])
        self.assertEqual(self.client.last_session_id,'session-1')

    async def test_different_body_gets_different_key(self):
        keys=[]
        def handler(request):
            keys.append(request.headers['idempotency-key'])
            return httpx.Response(202,json={'id':'session-1'})
        self.client=ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens())
        await self.client.request('POST','charging-sessions',{'public_code':'A'},key='one')
        await self.client.request('POST','charging-sessions',{'public_code':'B'},key='two')
        self.assertEqual(keys,['one','two'])

    async def test_timeout_has_friendly_error_and_does_not_retry_mutation(self):
        keys=[]
        def handler(request):
            keys.append(request.headers['idempotency-key'])
            if len(keys) == 1:
                raise httpx.ReadTimeout('late',request=request)
            return httpx.Response(202,json={'id':'reservation-1'})
        self.client=ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens())
        with self.assertRaisesRegex(ApiError,'demorou'):
            await self.client.request('POST','reservations',{'connector_id':'c'},key='stable')
        # Uma nova tela gera outra chave, mas o cliente preserva a anterior
        # enquanto o resultado do pedido que expirou é desconhecido.
        await self.client.request('POST','reservations',{'connector_id':'c'},key='from-new-screen')
        self.assertEqual(keys,['stable','stable'])

    async def test_terminal_reservation_allows_new_reservation_of_same_point(self):
        keys=[]
        reservation_number=0
        def handler(request):
            nonlocal reservation_number
            if request.url.path.endswith('/reservations/current'):
                return httpx.Response(200,json=None)
            keys.append(request.headers['idempotency-key'])
            reservation_number += 1
            return httpx.Response(202,json={'id':f'reservation-{reservation_number}'})
        self.client=ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens())
        body={'connector_id':'same-point'}
        first=await self.client.request('POST','reservations',body,key='first-intent')
        await self.client.request('GET','reservations/current')
        second=await self.client.request('POST','reservations',body,key='second-intent')
        self.assertEqual(keys,['first-intent','second-intent'])
        self.assertNotEqual(first['id'],second['id'])

    async def test_recovers_timed_out_reservation_then_clears_key_after_cancel(self):
        reservation_keys=[]
        current_reads=0
        def handler(request):
            nonlocal current_reads
            if request.url.path.endswith('/reservations/current'):
                current_reads += 1
                if current_reads == 1:
                    return httpx.Response(200,json={
                        'id':'recovered-reservation',
                        'connector_id':'same-point',
                        'status':'confirmed',
                    })
                return httpx.Response(200,json=None)
            if request.url.path.endswith('/cancel'):
                return httpx.Response(202,json={
                    'id':'recovered-reservation',
                    'connector_id':'same-point',
                    'status':'cancelling',
                })
            reservation_keys.append(request.headers['idempotency-key'])
            if len(reservation_keys) == 1:
                raise httpx.ReadTimeout('late',request=request)
            return httpx.Response(202,json={'id':'new-reservation'})
        self.client=ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens())
        body={'connector_id':'same-point'}
        with self.assertRaises(ApiError):
            await self.client.request('POST','reservations',body,key='ambiguous-key')
        active=await self.client.request('GET','reservations/current')
        self.assertEqual(active['id'],'recovered-reservation')
        self.assertEqual(self.client.last_reservation_id,'recovered-reservation')
        await self.client.request('POST','reservations/recovered-reservation/cancel')
        await self.client.request('GET','reservations/current')
        await self.client.request('POST','reservations',body,key='new-intent-key')
        self.assertEqual(reservation_keys,['ambiguous-key','new-intent-key'])

    async def test_401_refreshes_once_and_replays_with_same_key(self):
        calls=[]
        def handler(request):
            calls.append((request.url.path,request.headers.get('idempotency-key')))
            if request.url.path.endswith('/auth/refresh'):
                return httpx.Response(200,json=tokens('access-2','refresh-2'))
            if len([p for p,_ in calls if p.endswith('/reservations')]) == 1:
                return httpx.Response(401,json={'error':{'code':'expired','message':'Token expirado'}})
            return httpx.Response(202,json={'id':'r'})
        self.client=ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens())
        await self.client.request('POST','reservations',{'connector_id':'c'},key='same')
        reservation_calls=[k for p,k in calls if p.endswith('/reservations')]
        self.assertEqual(reservation_calls,['same','same'])

    async def test_terminal_charge_retires_only_known_session_key(self):
        keys = []
        def handler(request):
            if request.method == 'GET':
                return httpx.Response(200,json={'id':'session-1','status':'completed'})
            keys.append(request.headers['idempotency-key'])
            return httpx.Response(202,json={'id':f'session-{len(keys)}'})
        self.client = ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens())
        body = {'public_code':'same','max_duration_minutes':30}
        await self.client.request('POST','charging-sessions',body,key='first-intent')
        await self.client.request('GET','charging-sessions/session-1')
        await self.client.request('POST','charging-sessions',body,key='second-intent')
        self.assertEqual(keys,['first-intent','second-intent'])

    async def test_null_current_charge_does_not_discard_uncertain_timeout_key(self):
        keys = []
        def handler(request):
            if request.method == 'GET':
                return httpx.Response(200,json=None)
            keys.append(request.headers['idempotency-key'])
            if len(keys) == 1:
                raise httpx.ReadTimeout('late',request=request)
            return httpx.Response(202,json={'id':'session'})
        self.client = ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens())
        body = {'public_code':'same','max_duration_minutes':30}
        with self.assertRaises(ApiError):
            await self.client.request('POST','charging-sessions',body,key='uncertain')
        await self.client.request('GET','charging-sessions/current')
        await self.client.request('POST','charging-sessions',body,key='retry-intent')
        self.assertEqual(keys,['uncertain','uncertain'])

    async def test_concurrent_unauthorized_requests_share_one_refresh(self):
        ready = asyncio.Event()
        old_requests = 0
        refreshes = 0
        async def handler(request):
            nonlocal old_requests, refreshes
            if request.url.path.endswith('/refresh'):
                refreshes += 1
                return httpx.Response(200,json=tokens('new','new-refresh'))
            if request.headers['authorization'] == 'Bearer access-1':
                old_requests += 1
                if old_requests == 2:
                    ready.set()
                await ready.wait()
                return httpx.Response(401,json={'error':{'message':'Expired'}})
            return httpx.Response(200,json={'ok':True})
        self.client = ApiClient('https://api.example.test/v1',httpx.MockTransport(handler))
        self.client.session.update(tokens())
        await asyncio.gather(self.client.request('GET','me'),self.client.request('GET','me/summary'))
        self.assertEqual(refreshes,1)


class SessionAndConfigTests(unittest.TestCase):
    def test_clear_removes_tokens(self):
        session=Session(); session.update(tokens()); session.clear()
        self.assertIsNone(session.access_token)
        self.assertIsNone(session.refresh_token)
        self.assertIsNone(session.user)

    def test_https_required_except_local_test(self):
        self.assertEqual(validate_api_url('http://localhost:8000/v1'),'http://localhost:8000/v1')
        self.assertEqual(validate_api_url('https://api.example.com/v1'),'https://api.example.com/v1')
        with self.assertRaises(ValueError):
            validate_api_url('http://api.example.com/v1')
        with self.assertRaises(ValueError):
            validate_api_url('https://user:pass@api.example.com/v1')


if __name__ == '__main__':
    unittest.main()
