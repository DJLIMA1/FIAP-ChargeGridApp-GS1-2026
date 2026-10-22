"""Postos de demonstração do Modo apresentação: só exibição, nunca funcionais.

Com o Modo apresentação ligado (``vehicle_state.presentation_mode``), a aba Recarga mostra, depois dos
postos reais da API, uma rede fictícia espalhada por São Paulo com pino BRANCO no mapa (os reais
continuam vermelhos). Na tela eles parecem postos comuns, com tarifa normal, só que "Indisponível no
momento" (nenhum texto visível fala em demonstração). Eles ficam só no app, nesta lista fixa:

* nada vai para o banco nem para a API (nenhum posto real é tocado e o servidor nunca vê estes IDs);
* os IDs internos (``demo-sp-...``) não são UUID: a tela da estação monta o detalhe daqui, sem chamar a
  API, e troca "Reservar"/"Carregar agora" pelo aviso de indisponível; nenhuma tela os leva à reserva ou
  à recarga;
* aparecem sempre (sem o raio da busca: a apresentação pode ser em qualquer lugar de SP), depois dos
  reais, e respeitam os demais filtros (tipo de conector, tarifa máxima, só disponíveis → somem);
* não aparecem em "Perto de Você" no Início.
"""
from copy import deepcopy

from . import vehicle_state
from .discovery import discover, point_price

PREFIX = 'demo-sp-'
# Textos visíveis: postos normais, só indisponíveis (nada de "demonstração" na tela).
LABEL = 'Indisponível no momento'
NOTICE = 'Indisponível no momento. Este posto não aceita reservas nem recargas agora.'
GROUP_NOTE = 'Indisponível no momento'

# (slug, nome, endereço, latitude, longitude, [(conector, kW, R$/kWh)]) — endereços reais de SP,
# coordenadas conferidas no Photon/OpenStreetMap; nomes genéricos (sem marcas de terceiros).
_NETWORK = (
    ('paulista', 'Eletroposto Paulista', 'Av. Paulista, 2073, Bela Vista, São Paulo - SP',
     -23.5590234, -46.6597666, (('CCS2', 60, 2.39), ('Tipo 2', 22, 1.49))),
    ('pinheiros', 'Recarga Pinheiros', 'Rua Fradique Coutinho, 1100, Pinheiros, São Paulo - SP',
     -23.5578595, -46.6900937, (('Tipo 2', 22, 1.39),)),
    ('moema', 'Eletroposto Moema', 'Av. Ibirapuera, 3103, Moema, São Paulo - SP',
     -23.6101927, -46.6668742, (('CCS2', 50, 2.29), ('Tipo 2', 11, 1.29))),
    ('tatuape', 'Recarga Tatuapé', 'Rua Tuiuti, 2190, Tatuapé, São Paulo - SP',
     -23.5414176, -46.5753025, (('CCS2', 40, 2.19),)),
    ('santana', 'Eletroposto Santana', 'Rua Voluntários da Pátria, 1500, Santana, São Paulo - SP',
     -23.5072217, -46.6261515, (('Tipo 2', 22, 1.45),)),
    ('morumbi', 'Hub Morumbi', 'Av. Roque Petroni Júnior, 1089, Morumbi, São Paulo - SP',
     -23.6234167, -46.6985436, (('CCS2', 120, 2.79), ('CCS2', 60, 2.49))),
    ('vila-olimpia', 'Recarga Vila Olímpia', 'Rua Funchal, 418, Vila Olímpia, São Paulo - SP',
     -23.5936301, -46.6905142, (('CCS2', 60, 2.45), ('Tipo 2', 22, 1.55))),
    ('faria-lima', 'Eletroposto Faria Lima', 'Av. Brigadeiro Faria Lima, 3900, Itaim Bibi, São Paulo - SP',
     -23.5898576, -46.6818147, (('CCS2', 50, 2.35),)),
    ('lapa', 'Recarga Lapa', 'Rua Clélia, 1500, Lapa, São Paulo - SP',
     -23.5248563, -46.6971376, (('Tipo 2', 22, 1.35),)),
    ('perdizes', 'Eletroposto Perdizes', 'Rua Cardoso de Almeida, 1000, Perdizes, São Paulo - SP',
     -23.5393947, -46.6694846, (('CCS2', 40, 2.25), ('Tipo 2', 11, 1.25))),
)


def _station(slug, name, address, lat, lng, points):
    station_id = PREFIX + slug
    return {
        'id': station_id, 'name': name, 'address': address, 'latitude': lat, 'longitude': lng,
        'active': True, 'owner_id': None, 'amenities': [], 'demo': True,
        # Mesmo formato dos pontos da API, mas nunca disponíveis: "Só disponíveis" os esconde e a
        # tela não oferece reserva/início. Sem código público (nada para digitar no totem ou no app).
        'connectors': [{
            'id': f'{station_id}-{index}', 'station_id': station_id, 'public_code': '',
            'connector_type': kind, 'power_kw': f'{power:.3f}', 'price_per_kwh': f'{price:.4f}',
            'max_duration_minutes': 60, 'active': True, 'retired': False, 'online': True,
            'available': False, 'availability_status': 'disabled', 'demo': True,
        } for index, (kind, power, price) in enumerate(points, 1)],
    }


STATIONS = tuple(_station(*spec) for spec in _NETWORK)
_BY_ID = {station['id']: station for station in STATIONS}
_ORDER = {station['id']: index for index, station in enumerate(STATIONS)}


def is_demo_id(station_id) -> bool:
    return isinstance(station_id, str) and station_id in _BY_ID


def is_demo(station) -> bool:
    return isinstance(station, dict) and (station.get('demo') is True or is_demo_id(station.get('id')))


def get(station_id):
    """Cópia do posto de demonstração (``None`` se o ID não é de demonstração)."""
    station = _BY_ID.get(station_id) if isinstance(station_id, str) else None
    return deepcopy(station) if station else None


def enabled(app) -> bool:
    return vehicle_state.presentation_mode(app)


def price(station):
    """Menor tarifa do posto de demonstração (mostrada como a de qualquer posto)."""
    return float(min(point_price(point) for point in station['connectors']))


def matches(*, connector_type=None, available_only=False, max_price_per_kwh=None, sort='default',
            lat=None, lng=None):
    """Postos de demonstração que passam nos filtros da busca (sem raio), na ordem pedida."""
    sort = sort if sort == 'price' or (sort == 'distance' and lat is not None and lng is not None) else 'default'
    found = discover(deepcopy(list(STATIONS)), connector_type=connector_type, available_only=available_only,
                     max_price_per_kwh=max_price_per_kwh, sort=sort, lat=lat, lng=lng)
    if sort == 'default':
        found.sort(key=lambda station: _ORDER[station['id']])
    return found


def inject(app, items, *, offset=0, **filters):
    """``(itens, quantos_demo)``: na primeira página e com o Modo apresentação, os postos de
    demonstração entram DEPOIS dos reais. Fora disso, os itens voltam como vieram."""
    real = [item for item in items if not is_demo(item)]
    if offset or not enabled(app):
        return real, 0
    extra = matches(**filters)
    return real + extra, len(extra)
