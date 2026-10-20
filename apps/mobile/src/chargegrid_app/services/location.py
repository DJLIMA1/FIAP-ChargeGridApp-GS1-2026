import httpx


def geocode_demo_address(address, locations):
    """Resolve only bundled demo fixtures, without a network client or GPS."""
    import unicodedata

    def normalized(value):
        return ' '.join(''.join(character for character in unicodedata.normalize('NFKD',value.casefold())
                               if not unicodedata.combining(character)).split())

    query = normalized(address.strip())
    if len(query) < 3:
        return None
    matches = {
        (float(location['latitude']),float(location['longitude']))
        for location in locations
        if any(query in normalized(location.get(key,'')) for key in ('name','address'))
    }
    # A shared city name must not choose an arbitrary demo station.
    return next(iter(matches)) if len(matches) == 1 else None


async def geocode_address(address):
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get('https://nominatim.openstreetmap.org/search',params={'q':address,'format':'json','limit':1,'countrycodes':'br'},headers={'User-Agent':'ChargeGridAcademic/1.0'})
        response.raise_for_status()
        results = response.json()
        if results:
            return float(results[0]['lat']), float(results[0]['lon'])
    return None


async def coordinates_for(api, address, picked=None):
    """Coordenadas de um endereço sem pedir latitude/longitude ao usuário.

    ``picked``: sugestão escolhida no autocomplete (já traz coordenadas). Senão, a primeira sugestão
    da API própria (``geo/address-suggestions``: Photon/ViaCEP; na demo, endereços fixos). ``None`` se
    não houver resultado.
    """
    if picked and picked.get('label') == (address or '').strip() and picked.get('latitude') is not None:
        return float(picked['latitude']), float(picked['longitude'])
    query = ' '.join(str(address or '').split())
    if len(query) < 3:
        return None
    try:
        result = await api.request('GET', 'geo/address-suggestions', params={'q': query[:120]}) or {}
    except Exception:  # noqa: BLE001 - sem rede/sem provedor: quem chama decide a mensagem
        return None
    found = next((item for item in result.get('items') or [] if item.get('latitude') is not None), None)
    return (float(found['latitude']), float(found['longitude'])) if found else None


SAO_PAULO_CENTER = (-23.5505, -46.6333)
NOT_FOUND = 'Não encontramos este endereço. Digite a rua e o número e escolha uma das sugestões.'


async def station_location(api, address, picked=None, station=None, demo=False):
    """``(latitude, longitude)`` para salvar o posto a partir do endereço.

    Sem resultado: mantém as coordenadas salvas se o endereço não mudou; na demo usa o centro de
    São Paulo (endereços fictícios). Em conta real, levanta ``ValueError`` com a mensagem ao usuário.
    """
    found = await coordinates_for(api, address, picked)
    if found:
        return found
    station = station or {}
    saved = (station.get('latitude'), station.get('longitude'))
    if (address or '').strip() == (station.get('address') or '').strip() and None not in saved \
            and any(float(value) for value in saved):
        return float(saved[0]), float(saved[1])
    if demo:
        return SAO_PAULO_CENTER
    raise ValueError(NOT_FOUND)
