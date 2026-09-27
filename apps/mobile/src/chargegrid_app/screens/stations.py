import math
from copy import deepcopy

import flet as ft

from ..api_client import ApiError
from ..services.location import geocode_address, geocode_demo_address
from ..services.maps import station_map_widget
from ..services.search_location import SearchLocation
from ..ui import theme
from ..ui.availability import point_status, station_map_record
from ..ui.components import badge, button, card, field, money, title
from ..ui.point_summary import point_context


def _available(station, point):
    return (station.get('active') is not False and point.get('active') is not False
            and not point.get('retired') and point.get('online') is not False
            and point.get('available') is True
            and point.get('availability_status') in (None, 'available'))


def _number(value):
    return f'{float(value):g}'.replace('.', ',')


async def build(app, lat=None, lng=None, radius=5, query='', station_id=None, offset=0):
    demo = getattr(app.api,'is_demo',False) is True
    if station_id:
        stations = [deepcopy(await app.api.request('GET',f'stations/{station_id}'))]
        total = 1
    else:
        params = {'limit':20,'offset':offset}
        if lat is not None and lng is not None:
            params.update(lat=lat,lng=lng,radius_km=radius)
        result = await app.api.request('GET','stations',params=params)
        stations, total = deepcopy(result['items']), result['total']
    address = field('Endereço para buscar',query)
    address.max_length = 300
    latitude, longitude, reach = field('Latitude',str(lat) if lat is not None else ''),field('Longitude',str(lng) if lng is not None else ''),field('Raio (km)',str(radius))
    search_mode = ft.Dropdown(label='Buscar por',value='address' if query or lat is None else 'coordinates',
                              options=[ft.DropdownOption(key='address',text='Endereço'),ft.DropdownOption(key='coordinates',text='Coordenadas')],
                              color=theme.TEXT_COLOR,bgcolor=theme.WHITE)

    async def search_values():
        search_lat, search_lng = None, None
        search_query = address.value.strip() if search_mode.value == 'address' else ''
        if search_query:
            if demo:
                from ..demo import DEMO_LOCATIONS
                coordinates = geocode_demo_address(search_query,DEMO_LOCATIONS)
                if not coordinates:
                    raise ApiError('Na conta demo, busque Posto Demo Centro ou Vila Mariana, ou selecione Coordenadas. A busca não acessa a internet.')
            else:
                try:
                    coordinates = await geocode_address(search_query)
                except Exception as exc:
                    raise ApiError('Não foi possível localizar o endereço. Selecione Coordenadas em Buscar por ou tente novamente.') from exc
            if not coordinates:
                raise ApiError('Endereço não encontrado. Selecione Coordenadas em Buscar por para informar latitude e longitude.')
            search_lat,search_lng = coordinates
        elif search_mode.value == 'coordinates':
            if not latitude.value.strip() or not longitude.value.strip():
                raise ApiError('Informe latitude e longitude juntas.')
            try:
                search_lat,search_lng = float(latitude.value.replace(',','.')),float(longitude.value.replace(',','.'))
            except ValueError as exc:
                raise ApiError('Informe números válidos para latitude e longitude.') from exc
        if search_lat is not None and (not -90 <= search_lat <= 90 or not -180 <= search_lng <= 180):
            raise ApiError('Informe latitude de -90 a 90 e longitude de -180 a 180.')
        try:
            search_radius = float(reach.value.replace(',','.'))
        except ValueError as exc:
            raise ApiError('Informe um raio numérico maior que zero e de até 500 km.') from exc
        if not math.isfinite(search_radius) or not 0 < search_radius <= 500:
            raise ApiError('Informe um raio maior que zero e de até 500 km.')
        return {'lat':search_lat,'lng':search_lng,'radius':search_radius,'query':search_query}

    async def search():
        await app.go('stations',**await search_values())

    latitude.expand = True
    longitude.expand = True
    coordinates = ft.Row([latitude,longitude],visible=search_mode.value == 'coordinates')
    address.visible = search_mode.value == 'address'

    async def change_search_mode(event):
        address.visible = search_mode.value == 'address'
        coordinates.visible = not address.visible
        app.page.update()

    search_mode.on_select = change_search_mode
    profile = getattr(app,'profile',{}) or {}
    user = getattr(getattr(app.api,'session',None),'user',None) or {}
    saved_location = None if demo else SearchLocation(profile.get('id') or user.get('id'))
    saved = saved_location.load() if saved_location else None
    saved_box = ft.Column(spacing=8)

    async def remove_saved():
        nonlocal saved
        if not saved_location.remove():
            raise ApiError('Não foi possível remover a busca deste dispositivo. Tente novamente.')
        saved = None
        refresh_saved()
        app.page.update()
        app.notice('Busca salva removida deste dispositivo.')

    def refresh_saved():
        saved_box.controls = []
        if saved:
            label = saved['query'] or f"{saved['lat']:.4f}, {saved['lng']:.4f}"
            saved_box.controls = [ft.Text('Busca salva nesta conta: '+label,size=12,color=theme.GRAY_TEXT),
                                  button('Usar busca salva',app.link('stations',**saved),secondary=True),
                                  button('Remover busca salva',app.action(remove_saved),secondary=True)]

    async def save_search():
        nonlocal saved
        data = await search_values()
        if data['lat'] is None:
            raise ApiError('Informe um endereço ou coordenadas antes de salvar esta busca.')
        if not saved_location.save(data):
            raise ApiError('Não foi possível salvar a busca nesta conta e dispositivo.')
        saved = data
        refresh_saved()
        app.page.update()
        app.notice('Busca salva somente para esta conta neste dispositivo.')

    refresh_saved()
    if station_id:
        station_heading = title(stations[0]['name'],stations[0]['address'])
        controls = [station_heading,
                    card(ft.Row([
                        ft.Icon(ft.Icons.LOCATION_ON_OUTLINED,color=theme.RED,size=23),
                        ft.Text('Para iniciar, você precisa estar no ponto. Leia o código #F atual na tela do equipamento; ele muda periodicamente.',
                                size=13,color=theme.TEXT_COLOR,expand=True),
                    ],spacing=12),padding=14),
                    ft.Text('Pontos de recarga',size=20,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,font_family='BarlowCondensedBold')]
    else:
        search_controls = [search_mode,address,coordinates,reach,button('Buscar',app.action(search)),
                           ft.Text('Sem endereço, mostramos todos os postos. O raio é aplicado à localização informada.',size=12,color=theme.GRAY_TEXT)]
        if saved_location is not None and saved_location.path is not None:
            search_controls += [button('Salvar busca neste dispositivo',app.action(save_search),secondary=True),
                                ft.Text('Salvamos a localização somente ao tocar em Salvar. Você pode removê-la aqui.',size=12,color=theme.GRAY_TEXT),saved_box]
        search_section = ft.ExpansionTile(
            title=ft.Text('Buscar perto de um endereço',size=15,color=theme.TEXT_COLOR),
            leading=ft.Icons.SEARCH,
            controls=[card(ft.Column(search_controls,spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH))],
            expanded=bool(query.strip() or lat is not None or lng is not None),
            maintain_state=True,
            min_tile_height=44,
            tile_padding=ft.Padding(left=0,right=0,top=0,bottom=0),
            controls_padding=0,
            icon_color=theme.RED,
            collapsed_icon_color=theme.GRAY_TEXT,
        )
        controls = [title('Encontrar postos','Escolha um posto. Depois, veja os pontos disponíveis para iniciar no local ou reservar.'),search_section]
    map_preview = ft.Container(visible=False)
    map_signature = None
    map_section = ft.Column(
        controls=[ft.Text('Estações no mapa',size=20,color=theme.TEXT_COLOR,font_family='BarlowCondensedBold'),map_preview],
        visible=False,
        spacing=16,horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )
    map_width = max(200,min(getattr(app.page,'width',None) or 400,600)-40)
    async def resize_map_section(event):
        nonlocal map_width
        if event.width > 0:
            map_width = event.width
    map_section.on_size_change = resize_map_section

    async def refresh_map(items):
        nonlocal map_signature
        # Details already identify the chosen station. Do not repeat its map
        # or send the user back through another map disclosure.
        if station_id:
            return
        records = [station_map_record(station,_available) for station in items]
        signature = [{key:record.get(key) for key in ('id','name','latitude','longitude','free_points','status','price')}
                     for record in records]
        if signature == map_signature:
            return
        if items:
            map_preview.content = await station_map_widget(records,lambda selected_id:app.link('stations',station_id=selected_id),
                                                          offline=demo,width=map_width,
                                                          reference=(lat,lng) if lat is not None and lng is not None else None)
        else:
            map_preview.content = None
        map_preview.visible = bool(items)
        map_section.visible = bool(items)
        map_signature = signature

    await refresh_map(stations)
    if not station_id:
        controls.append(map_section)
    result_count = ft.Text(size=12,color=theme.GRAY_TEXT,visible=not bool(station_id))
    controls.append(result_count)
    listing = ft.Column(spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    controls.append(listing)
    def station_cards(stations):
        items = []
        for station in sorted(stations, key=lambda item: not any(_available(item,point) for point in item.get('connectors', []))):
            available_count = sum(_available(station,point) for point in station['connectors'])
            if not station_id:
                label = f'{available_count} ponto livre' if available_count == 1 else f'{available_count} pontos livres'
                if station.get('active') is False:
                    label = 'Posto desativado'
                elif not station['connectors']:
                    label = 'Sem pontos cadastrados'
                details = [ft.Text(station['name'],size=20,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR,font_family='BarlowCondensedBold'),
                           ft.Text(station['address'],size=13,color=theme.GRAY_TEXT),
                           ft.Row([ft.Icon(ft.Icons.EV_STATION_OUTLINED,size=18,color=theme.GREEN if available_count else theme.GRAY_TEXT),
                                   ft.Text(label,size=13,color=theme.TEXT_COLOR,expand=True)],spacing=8),
                           button('Ver pontos',app.link('stations',station_id=station['id']))]
                items.append(card(ft.Column(details,spacing=12,horizontal_alignment=ft.CrossAxisAlignment.STRETCH),padding=16))
                continue
            if not station['connectors']:
                items.append(card(ft.Text('Este posto ainda não tem pontos de recarga.',color=theme.GRAY_TEXT)))
            for connector in sorted(station['connectors'], key=lambda item: not _available(station,item)):
                key = app.api.new_key()
                async def reserve(c=connector,k=key):
                    await app.api.request('POST','reservations',{'connector_id':c['id']},key=k)
                    await app.go('reservations')
                status, status_color = point_status(connector)
                if station.get('active') is False or connector.get('active') is False or connector.get('retired'):
                    status,status_color = 'Desativado',theme.SLATE
                elif connector.get('online') is False:
                    status,status_color = 'Offline',theme.SLATE
                elif status == 'Disponível' and not _available(station,connector):
                    status,status_color = 'Indisponível',theme.SLATE
                details = [ft.Text(f"{connector['public_code']} · {connector['connector_type']}",size=18,weight=ft.FontWeight.BOLD,color=theme.TEXT_COLOR),
                           ft.Row([badge(status,bg=status_color,width=110)]),
                           ft.Text(f"{_number(connector['power_kw'])} kW · {money(connector['price_per_kwh'])}/kWh",size=14,color=theme.TEXT_COLOR),
                           ft.Text(f"Tempo máximo: {connector['max_duration_minutes']} min",size=12,color=theme.GRAY_TEXT)]
                if connector.get('availability_status') == 'reconciling' and connector.get('reserved_until'):
                    details.append(ft.Text('O equipamento está restaurando uma reserva. Aguarde a confirmação.',size=12,color=theme.GRAY_TEXT))
                if _available(station,connector):
                    details += [ft.Divider(color=theme.LIGHT_GRAY),
                                button('Já estou aqui: iniciar',app.link('charging',public_code=connector['public_code'],max_duration=min(30,connector['max_duration_minutes']),point_context=point_context(station,connector))),
                                button('Reservar para chegar',app.action(reserve),secondary=True),
                                ft.Text('A reserva precisa ser confirmada pelo equipamento antes de você se deslocar.',size=12,color=theme.GRAY_TEXT)]
                elif status == 'Offline':
                    details.append(ft.Text('Equipamento sem comunicação no momento.',size=12,color=theme.GRAY_TEXT))
                items.append(card(ft.Column(details,spacing=10,horizontal_alignment=ft.CrossAxisAlignment.STRETCH),padding=16))
            items.append(ft.TextButton(content=ft.Text('Ver cupons deste posto',color=theme.GRAY_TEXT),on_click=app.link('coupons',station_id=station['id'])))
        return items
    listing.controls = station_cards(stations)
    empty_state = ft.Text('Nenhum posto encontrado para esta busca.',visible=not stations)
    controls.append(empty_state)
    pagination = ft.Column(spacing=10)
    controls.append(pagination)

    def refresh_pagination():
        pagination.controls = []
        shown = len(current_stations)
        result_count.value = (f"{shown} {'posto' if shown == 1 else 'postos'} nesta página · "
                              f"{total} {'encontrado' if total == 1 else 'encontrados'}")
        if station_id:
            return
        if offset:
            pagination.controls.append(button('Anterior',app.link('stations',lat=lat,lng=lng,radius=radius,query=query,offset=max(0,offset-20)),secondary=True))
        if offset+20 < total:
            pagination.controls.append(button('Mais postos',app.link('stations',lat=lat,lng=lng,radius=radius,query=query,offset=offset+20)))

    current_stations = stations
    refresh_pagination()
    async def update():
        nonlocal current_stations,total
        if station_id:
            fresh = [deepcopy(await app.api.request("GET",f"stations/{station_id}"))]
            fresh_total = 1
        else:
            result = await app.api.request("GET","stations",params=params)
            fresh, fresh_total = deepcopy(result['items']),result['total']
        if fresh == current_stations and total == fresh_total:
            return
        if fresh != current_stations:
            await refresh_map(fresh)
            listing.controls = station_cards(fresh)
            if station_id and fresh:
                station_heading.controls[0].value = fresh[0]['name']
                station_heading.controls[1].value = fresh[0]['address']
        empty_state.visible = not fresh
        current_stations,total = fresh,fresh_total
        refresh_pagination()
        app.page.update()
    app.set_poll(update,10)
    return ft.Column(controls,scroll=ft.ScrollMode.AUTO,spacing=15,horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
