from math import isfinite

from . import theme

LABELS = {
    'available': 'Disponível',
    'offline': 'Offline',
    'reserved': 'Reservado',
    'charging': 'Em recarga',
    'reconciling': 'Sincronizando',
    'disabled': 'Desativado',
    'fault': 'Falha',
    'occupied': 'Ocupado',
}


def point_status(point):
    state = point.get('availability_status')
    if state not in LABELS:
        # Backwards compatible while the API/mobile rollout is in progress.
        state = ('available' if point.get('available') else
                 'offline' if not point.get('online') else
                 'reserved' if point.get('physical_state') == 'reserved' else
                 'charging' if point.get('physical_state') == 'charging' else 'occupied')
    label = LABELS[state]
    if state == 'reconciling' and point.get('reserved_until'):
        label = 'Reservado'
    colors = {
        'available': theme.GREEN,
        'reserved': theme.AMBER,
        'charging': theme.BLUE,
        'reconciling': theme.BLUE,
        'disabled': theme.SLATE,
        'fault': theme.RED,
        'offline': theme.SLATE,
        'occupied': theme.SLATE,
    }
    return label, theme.AMBER if state == 'reconciling' and point.get('reserved_until') else colors[state]


def station_map_record(station, available):
    """Map callout data uses exactly the same availability as its station list."""
    points = station.get('connectors') or []
    free = [point for point in points if available(station,point)]
    prices = []
    for point in free:
        try:
            price = float(point.get('price_per_kwh'))
        except (TypeError,ValueError):
            continue
        if isfinite(price) and price >= 0:
            prices.append(price)
    enabled = [point for point in points if point.get('active') is not False and not point.get('retired')
               and point.get('availability_status') != 'disabled']
    if station.get('active') is False or (points and not enabled):
        status = 'Desativado'
    elif not points:
        status = 'Sem pontos'
    elif free:
        status = 'Disponível'
    elif not any(point.get('online') is not False for point in enabled):
        status = 'Offline'
    else:
        status = next((point_status(point)[0] for point in enabled
                       if point.get('online') is not False and point_status(point)[0] != 'Disponível'),'Indisponível')
    return {**station,'free_points':len(free),'status':status,'price':min(prices) if prices else None}
