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
