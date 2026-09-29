"""Discovery contract shared by the offline demo and station presentation.

Keep normalization and selection equivalent to app.modules.stations.discovery.
"""
import math
from decimal import Decimal


def normalize_connector(value):
    key = ''.join(character for character in str(value).casefold() if character.isalnum())
    return {'tipo2': 'type2', 'typeii': 'type2', 'ccs': 'ccs2', 'ccstype2': 'ccs2'}.get(key, key)


def point_available(point):
    return (point.get('active') is not False and not point.get('retired')
            and point.get('online') is not False and point.get('available') is True
            and point.get('availability_status') in (None, 'available'))


def discover(records, *, connector_type=None, available_only=False, max_price_per_kwh=None,
             sort='default', lat=None, lng=None):
    results = []
    filtered = bool(connector_type or available_only or max_price_per_kwh is not None)
    for station in records:
        points = [point for point in station.get('connectors', [])
                  if point.get('active') is not False and not point.get('retired')
                  and (not connector_type or normalize_connector(point['connector_type']) == normalize_connector(connector_type))
                  and (not available_only or point_available(point))
                  and (max_price_per_kwh is None or Decimal(str(point['price_per_kwh'])) <= Decimal(str(max_price_per_kwh)))]
        if filtered and not points:
            continue
        # Every displayed attribute refers to this same eligible point. Price sorting
        # uses the cheapest eligible point, even when it is currently occupied.
        selected = min(points, key=lambda p: (Decimal(str(p['price_per_kwh'])), str(p['id']))) if points else None
        result = dict(station)
        result['discovery'] = {'point': selected, 'matching_connector_ids': [p['id'] for p in points],
                               'available_points': sum(point_available(p) for p in points), 'distance_km': None}
        if lat is not None and lng is not None:
            first, second = math.radians(lat), math.radians(float(station['latitude']))
            cosine = (math.sin(first) * math.sin(second) + math.cos(first) * math.cos(second)
                      * math.cos(math.radians(float(station['longitude']) - lng)))
            result['discovery']['distance_km'] = 6371 * math.acos(max(-1, min(1, cosine)))
        results.append(result)
    if sort == 'price':
        results.sort(key=lambda s: (Decimal(str(s['discovery']['point']['price_per_kwh']))
                                   if s['discovery']['point'] else Decimal('Infinity'), str(s['id'])))
    elif sort == 'distance':
        results.sort(key=lambda s: (s['discovery']['distance_km'], str(s['id'])))
    else:
        results.sort(key=lambda s: str(s['id']))
    return results
