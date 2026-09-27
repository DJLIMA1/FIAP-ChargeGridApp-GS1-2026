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
