import httpx


async def geocode_address(address):
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get('https://nominatim.openstreetmap.org/search',params={'q':address,'format':'json','limit':1,'countrycodes':'br'},headers={'User-Agent':'ChargeGridAcademic/1.0'})
        response.raise_for_status()
        results = response.json()
        if results:
            return float(results[0]['lat']), float(results[0]['lon'])
    return None
