import asyncio
from datetime import datetime, timedelta, timezone

import flet as ft

from ..api_client import ApiError
from ..ui import theme
from ..ui.components import button, card, date_time, field, title


async def owned_stations(app):
    stations = []
    while True:
        result = await app.api.request('GET','operator/stations',params={'limit':100,'offset':len(stations)})
        stations.extend(result['items'])
        if not result['items'] or len(stations) >= result['total']:
            return stations


async def build(app, manage=False, coupon=None, create=False, station_id=None):
    if (manage or create or coupon) and not app.profile.get('operator_enabled'):
        return title('Cupons','Gestão disponível somente para operador aprovado.')
    if create or coupon:
        return form(app,coupon,await owned_stations(app))
    result = await app.api.request('GET','coupons',params=({'mine':'true'} if manage else {}) | ({'station_id':station_id} if station_id else {}))
    station_names = {}
    if manage:
        station_names = {station['id']: station['name'] for station in await owned_stations(app)}
    else:
        async def station_name(identifier):
            try:
                station = await app.api.request('GET',f'stations/{identifier}')
                return identifier, station['name']
            except ApiError as exc:
                if exc.status != 404:
                    raise
                return identifier, 'Posto indisponível'
        identifiers = {item['station_id'] for item in result['items'] if item.get('station_id')}
        station_names = dict(await asyncio.gather(*(station_name(identifier) for identifier in identifiers)))
    controls = [title('Cupons','Desconto sobre o custo estimado; não é pagamento real.')]
    if manage:
        controls.append(button('Criar cupom',app.link('coupons',manage=True,create=True)))
    for item in result['items']:
        scope = station_names.get(item['station_id'],'Posto indisponível') if item.get('station_id') else 'Todos os postos deste operador'
        details = [ft.Text(item['code'],size=20,weight=ft.FontWeight.BOLD),ft.Text(item['description']),ft.Text(f"{item['discount_percent']}% · validade {date_time(item['valid_until'])}"),ft.Text('Válido em: '+scope)]
        if manage:
            details.append(ft.Text('Ativo' if item.get('active',True) else 'Inativo',color=theme.GREEN if item.get('active',True) else theme.GRAY_TEXT))
            details.append(button('Editar',app.link('coupons',manage=True,coupon=item),secondary=True))
        controls.append(card(details))
    if not result['items']:
        controls.append(ft.Text('Nenhum cupom disponível.'))
    return ft.Column(controls,spacing=15,scroll=ft.ScrollMode.AUTO)


def form(app,coupon=None,stations=None):
    item = coupon or {}
    stations = stations or []
    code, description, discount = field('Código',item.get('code','')),field('Descrição',item.get('description','')),field('Desconto %',str(item.get('discount_percent','10')))
    initial_expiry = datetime.fromisoformat(item['valid_until'].replace('Z','+00:00')).astimezone() if item.get('valid_until') else datetime.now().astimezone()+timedelta(days=30)
    station = ft.Dropdown(label='Válido em',value=item.get('station_id') or '__all__',
                          options=[ft.DropdownOption(key='__all__',text='Todos os meus postos')]+[ft.DropdownOption(key=entry['id'],text=entry['name']) for entry in stations],
                          color=theme.TEXT_COLOR,bgcolor=theme.WHITE,text_size=14,expand=True)
    expiry = field('Validade (dia/mês/ano hora:minuto)',initial_expiry.strftime('%d/%m/%Y %H:%M'))
    active = ft.Switch(label='Ativo',value=item.get('active',True),visible=bool(coupon))
    async def save():
        try:
            percent = int(discount.value.strip())
        except ValueError as exc:
            raise ApiError('Informe um desconto inteiro de 0 a 100%.') from exc
        if not 0 <= percent <= 100:
            raise ApiError('Informe um desconto inteiro de 0 a 100%.')
        try:
            valid_until = datetime.strptime(expiry.value.strip(),'%d/%m/%Y %H:%M').astimezone()
        except ValueError as exc:
            raise ApiError('Use dia/mês/ano hora:minuto na validade, por exemplo 30/12/2026 18:00.') from exc
        if valid_until <= datetime.now().astimezone():
            raise ApiError('Escolha uma validade futura para o cupom.')
        if not coupon and not code.value.strip():
            raise ApiError('Informe o código do cupom.')
        body = {'description':description.value.strip(),'discount_percent':percent,'valid_until':valid_until.astimezone(timezone.utc).isoformat()}
        if coupon:
            body['active'] = active.value
        else:
            body['code'] = code.value.strip()
            if station.value and station.value != '__all__':
                body['station_id'] = station.value
        await app.api.request('PATCH' if coupon else 'POST',f"coupons/{item['id']}" if coupon else 'coupons',body)
        await app.go('coupons',manage=True)
    scope = next((entry['name'] for entry in stations if entry['id'] == item.get('station_id')), 'Posto indisponível') if item.get('station_id') else 'Todos os meus postos'
    return ft.Column([title('Editar cupom' if coupon else 'Novo cupom'),card(ft.Column(([code,ft.Row([station])] if not coupon else [ft.Text('Válido em: '+scope)])+[description,discount,expiry,active],spacing=12)),button('Salvar cupom',app.action(save)),button('Voltar',app.link('coupons',manage=True),secondary=True)],spacing=15,scroll=ft.ScrollMode.AUTO)
