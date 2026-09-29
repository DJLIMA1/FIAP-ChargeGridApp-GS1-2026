"""Filtering contracts, comparison accuracy and temporary plan continuity."""
import importlib.util
import unittest
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path
from unittest.mock import AsyncMock, patch

import flet as ft

from chargegrid_app.api_client import ApiError
from chargegrid_app.demo import DEMO_EMAIL, DEMO_PASSWORD, DemoApi
from chargegrid_app.navigation import parent_route
from chargegrid_app.screens import stations
from chargegrid_app.services.discovery import discover
from chargegrid_app.services.planning import (
    estimate_charge,
    estimate_text,
    intent_limits,
)
from test_behavior import HandlerApp, click, descendants
from test_consumer_flows import POINT, STATION, texts


class PlanningTests(unittest.TestCase):
    def test_shared_estimates_cap_time_and_budget_without_rounding_intermediate_values(self):
        point = {**POINT,'price_per_kwh':'2','power_kw':'22','max_duration_minutes':60}
        self.assertEqual(estimate_charge(point,30),{'energy_kwh':Decimal(11),'cost':Decimal(22)})
        self.assertEqual(estimate_charge(point,60,'5'),{'energy_kwh':Decimal('2.5'),'cost':Decimal(5)})
        self.assertEqual(intent_limits(point,{'mode':'time','minutes':120}),{'minutes':60})
        self.assertEqual(intent_limits({**point,'price_per_kwh':'0'},{'mode':'value','max_cost':'5'}),{'minutes':30})
        for amount in ('NaN','Infinity','0','-1'):
            with self.subTest(amount=amount),self.assertRaises(InvalidOperation):
                estimate_charge(point,30,amount)

    def test_multi_point_price_and_availability_belong_to_same_match(self):
        cheap = {**POINT,'id':'cheap','connector_type':'CCS2','price_per_kwh':'1','available':False}
        right = {**POINT,'id':'right','connector_type':'Tipo 2','price_per_kwh':'4'}
        station = {**STATION,'connectors':[cheap,right]}
        result = discover([station],connector_type='Type-2',available_only=True)[0]
        self.assertEqual(result['discovery']['point']['id'],'right')
        self.assertEqual(result['discovery']['available_points'],1)
        self.assertEqual(discover([station],connector_type='type2',max_price_per_kwh='3'),[])
        self.assertEqual(discover([station],connector_type='ccs2',available_only=True),[])

    def test_backend_and_demo_discovery_contracts_match(self):
        path = Path(__file__).resolve().parents[2] / 'api/app/modules/stations/discovery.py'
        spec = importlib.util.spec_from_file_location('backend_discovery_contract',path)
        backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(backend)
        records = [{**STATION,'latitude':0,'longitude':0,'connectors':[
            {**POINT,'connector_type':'Tipo 2'},
            {**POINT,'id':'offline','connector_type':'CCS2','available':False,'price_per_kwh':'0.1'}]}]
        for params in ({}, {'connector_type':'TYPE-2','available_only':True},
                       {'connector_type':'CCS','max_price_per_kwh':'0.5'},
                       {'sort':'distance','lat':0,'lng':0}, {'sort':'price'}):
            with self.subTest(params=params):
                self.assertEqual(discover(records,**params),backend.discover(records,**params))

    def test_back_keeps_comparison(self):
        values = {'station_id':'one','sort':'price','planning_intent':{'mode':'time','minutes':20}}
        self.assertEqual(parent_route('stations',values),('stations',{k:v for k,v in values.items() if k!='station_id'}))


class DiscoveryFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_comparison_and_start_use_same_plan(self):
        app = HandlerApp()
        plan = {'mode':'value','max_cost':'8'}
        app.api.request.return_value = {'items':discover([STATION]),'total':1}
        with patch.object(stations,'station_map_widget',new=AsyncMock(return_value=ft.Text('Map'))):
            screen = await stations.build(app,sort='price',planning_intent=plan)
        self.assertIn(estimate_text(POINT,**intent_limits(POINT,plan)),texts(screen))
        await click(screen,'Ver pontos')(None)
        self.assertEqual(app.go.call_args.kwargs['planning_intent'],plan)
        app.api.request.return_value = deepcopy(STATION)
        screen = await stations.build(app,**app.go.call_args.kwargs)
        await click(screen,'Já estou aqui: iniciar')(None)
        self.assertEqual(app.go.call_args.kwargs['planning_intent'],plan)
        back_route,back_data = parent_route('charging',app.go.call_args.kwargs)
        self.assertEqual(back_route,'stations')
        self.assertEqual(back_data['planning_intent'],plan)
        self.assertEqual(back_data['sort'],'price')
        search_route,search_data = parent_route(back_route,back_data)
        self.assertEqual(search_route,'stations')
        self.assertEqual(search_data,{'sort':'price','planning_intent':plan})
        await click(screen,'Reservar para chegar')(None)
        self.assertEqual(app.planning_intent,{'connector_id':POINT['id'],'intent':plan,
                                               'station_search':{'sort':'price','planning_intent':plan}})

    async def test_invalid_budget_and_distance_have_clear_errors(self):
        app = HandlerApp()
        app.api.request.return_value = {'items':[],'total':0}
        screen = await stations.build(app)
        fields = {c.label:c for c in descendants(screen) if isinstance(c,(ft.TextField,ft.Dropdown))}
        fields['Minha intenção'].value = 'value'
        for bad in ('NaN','Infinity','0','-1'):
            fields['Minutos ou valor em R$'].value = bad
            with self.subTest(bad=bad),self.assertRaises(ApiError):
                await click(screen,'Aplicar comparação')(None)
        fields['Minha intenção'].value = 'none'
        fields['Ordenar por'].value = 'distance'
        with self.assertRaises(ApiError):
            await click(screen,'Aplicar comparação')(None)
        app.go.assert_not_awaited()

    async def test_demo_filters_before_pagination_and_validates(self):
        api = DemoApi()
        await api.login(DEMO_EMAIL,DEMO_PASSWORD)
        # Add a second visible station to exercise paging; isolated in-memory fixtures.
        values = list(api._stations.values())
        values[1]['active'] = True
        points = list(api._points.values())
        points[0].update(connector_type='Tipo 2',price_per_kwh='4')
        result = await api.request('GET','stations',params={'connector_type':'TYPE-2','available_only':True,'sort':'price','limit':1})
        self.assertEqual(result['items'][0]['discovery']['point']['id'],points[0]['id'])
        self.assertEqual(result['total'],1)
        for params in ({'sort':'distance'},{'max_price_per_kwh':'NaN'},{'available_only':'maybe'},{'radius_km':0}):
            with self.subTest(params=params),self.assertRaises(ApiError):
                await api.request('GET','stations',params=params)
