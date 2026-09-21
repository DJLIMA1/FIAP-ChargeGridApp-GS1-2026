import math

import flet as ft

from ..api_client import ApiError
from ..services.location import geocode_address
from ..services.maps import map_widget
from ..ui import theme
from ..ui.availability import point_status
from ..ui.components import badge, button, card, field, money, title


async def build(app, lat=None, lng=None, radius=5, query='', station_id=None, offset=0):
    if station_id:
        stations = [await app.api.request('GET',f'stations/{station_id}')]
        total = 1
    else:
        params = {'limit':20,'offset':offset}
        if lat is not None and lng is not None:
            params.update(lat=lat,lng=lng,radius_km=radius)
        result = await app.api.request('GET','stations',params=params)
        stations, total = result['items'], result['total']
    address = field('Endereço para buscar',query)
    latitude, longitude, reach = field('Latitude',str(lat) if lat is not None else ''),field('Longitude',str(lng) if lng is not None else ''),field('Raio (km)',str(radius))

    async def search():
        search_lat, search_lng = None, None
        if address.value.strip():
            try:
                coordinates = await geocode_address(address.value)
            except Exception as exc:
                raise ApiError('Não foi possível localizar o endereço. Informe coordenadas ou tente novamente.') from exc
            if not coordinates:
                raise ApiError('Endereço não encontrado. Informe coordenadas.')
            search_lat,search_lng = coordinates
        elif bool(latitude.value.strip()) != bool(longitude.value.strip()):
            raise ApiError('Informe latitude e longitude juntas.')
        elif latitude.value.strip() and longitude.value.strip():
            search_lat,search_lng = float(latitude.value.replace(',','.')),float(longitude.value.replace(',','.'))
        if search_lat is not None and (not -90 <= search_lat <= 90 or not -180 <= search_lng <= 180):
            raise ApiError('Informe latitude de -90 a 90 e longitude de -180 a 180.')
        search_radius = float(reach.value.replace(',','.'))
        if not math.isfinite(search_radius) or not 0 < search_radius <= 500:
            raise ApiError('Informe um raio maior que zero e de até 500 km.')
        await app.go('stations',lat=search_lat,lng=search_lng,radius=search_radius,query=address.value)

    latitude.expand = True
    longitude.expand = True
    coordinates = ft.ExpansionTile(
        title=ft.Text('Busca por coordenadas',color=theme.TEXT_COLOR),
        controls=[ft.Row([latitude,longitude])],
        expanded=False,
        tile_padding=ft.Padding(left=0,right=0,top=0,bottom=0),
        controls_padding=ft.Padding(left=0,right=0,top=0,bottom=8),
        collapsed_text_color=theme.TEXT_COLOR,
        collapsed_icon_color=theme.GRAY_TEXT,
        icon_color=theme.RED,
    )
    controls = [title('Encontrar postos','Veja a disponibilidade antes de sair.'),card(ft.Column([address,reach,button('Buscar',app.action(search)),coordinates],spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)),button('Tenho o código do ponto',app.link('charging'),secondary=True)]
    if stations:
        map_lat, map_lng = (lat,lng) if lat is not None else (float(stations[0]['latitude']),float(stations[0]['longitude']))
        markers = [(float(s['latitude']),float(s['longitude']),'⚡' if any(c.get('available') for c in s['connectors']) else '⛔') for s in stations]
        map_preview = await map_widget(map_lat,map_lng,markers)
    else:
        map_preview = None
    listing = ft.Column(spacing=15)
    controls.append(listing)
    def station_cards(stations):
        items = []
        for station in sorted(stations, key=lambda item: not any(point.get('available') for point in item.get('connectors', []))):
            available_count = sum(bool(point.get('available')) for point in station['connectors'])
            details = [ft.Row([ft.Text(station['name'],size=18,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,expand=True),
                               badge(f'{available_count} livre' if available_count == 1 else f'{available_count} livres',
                                     bg=theme.GREEN if available_count else theme.SLATE,width=86)],spacing=8),
                       ft.Text(station['address'],size=13,color=theme.GRAY_TEXT)]
            if not station['connectors']:
                details.append(ft.Text('Este posto ainda não tem pontos de recarga.',color=theme.GRAY_TEXT))
            for connector in sorted(station['connectors'], key=lambda item: not item.get('available')):
                key = app.api.new_key()
                async def reserve(c=connector,k=key):
                    await app.api.request('POST','reservations',{'connector_id':c['id']},key=k)
                    await app.go('reservations')
                status, status_color = point_status(connector)
                details += [ft.Divider(color=theme.LIGHT_GRAY),
                            ft.Row([ft.Text(f"{connector['public_code']} · {connector['connector_type']}",color=theme.TEXT_COLOR,expand=True),
                                    badge(status,bg=status_color,width=155)],spacing=8),
                            ft.Text(f"{connector['power_kw']} kW · {money(connector['price_per_kwh'])}/kWh · até {connector['max_duration_minutes']} min",size=13,color=theme.GRAY_TEXT)]
                if connector.get('availability_status') == 'reconciling' and connector.get('reserved_until'):
                    details.append(ft.Text('O equipamento está restaurando uma reserva. Aguarde a confirmação.',size=12,color=theme.GRAY_TEXT))
                if connector.get('available'):
                    details += [button('Reservar ponto',app.action(reserve)),button('Iniciar pelo código',app.link('charging',public_code=connector['public_code'],max_duration=min(30,connector['max_duration_minutes'])),secondary=True)]
                elif status == 'Offline':
                    details.append(ft.Text('Equipamento sem comunicação no momento.',size=12,color=theme.GRAY_TEXT))
            items.append(card(details))
        return items
    listing.controls = station_cards(stations)
    empty_state = ft.Text('Nenhum posto encontrado para esta busca.',visible=not stations)
    controls.append(empty_state)
    if map_preview is not None:
        controls.append(ft.ExpansionTile(title=ft.Text('Ver no mapa',color=theme.TEXT_COLOR),controls=[map_preview],expanded=False))
    current_stations = stations
    async def update():
        nonlocal current_stations
        if station_id:
            fresh = [await app.api.request("GET",f"stations/{station_id}")]
        else:
            fresh = (await app.api.request("GET","stations",params=params))["items"]
        if fresh == current_stations:
            return
        current_stations = fresh
        listing.controls = station_cards(fresh)
        empty_state.visible = not fresh
        app.page.update()
    app.set_poll(update,10)
    if offset:
        controls.append(button('Anterior',app.link('stations',lat=lat,lng=lng,radius=radius,query=query,offset=max(0,offset-20)),secondary=True))
    if offset+20 < total and not station_id:
        controls.append(button('Mais postos',app.link('stations',lat=lat,lng=lng,radius=radius,query=query,offset=offset+20)))
    return ft.Column(controls,scroll=ft.ScrollMode.AUTO,spacing=15)
