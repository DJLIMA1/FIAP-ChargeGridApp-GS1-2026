"""Generate a small demo basemap from OSM vector data, never offline tile downloads.

Development-only: one bounded public Overpass query. The demo runtime uses the
bundled SVG and performs no network calls. Data: © OpenStreetMap contributors,
ODbL; see https://www.openstreetmap.org/copyright .
"""
import html
import json
import math
import urllib.parse
import urllib.request
from pathlib import Path

LAT, LNG = -23.5505, -46.6333
WIDTH, HEIGHT = 640, 480
SCALE = 100000
X, Y = 265, 165


def project(lat, lng):
    return X+(lng-LNG)*SCALE*math.cos(math.radians(LAT)),Y-(lat-LAT)*SCALE


def main():
    west,south = LNG-X/(SCALE*math.cos(math.radians(LAT))),LAT-(HEIGHT-Y)/SCALE
    east,north = LNG+(WIDTH-X)/(SCALE*math.cos(math.radians(LAT))),LAT+Y/SCALE
    bbox = f'{south},{west},{north},{east}'
    query = f'[out:json][timeout:25];(way[highway]({bbox});way[leisure=park]({bbox});way[landuse=grass]({bbox});way[natural=water]({bbox}););out geom;'
    request = urllib.request.Request('https://overpass-api.de/api/interpreter?'+urllib.parse.urlencode({'data':query}),
                                     headers={'User-Agent':'ChargeGridApp/0.3.7 (demo basemap generation)'})
    with urllib.request.urlopen(request,timeout=35) as response:
        data = json.load(response)
    if data.get('remark') or not data.get('elements'):
        raise RuntimeError('Incomplete map data; no asset written.')
    ways = [item for item in data['elements'] if item.get('type') == 'way' and len(item.get('geometry',[])) >= 2]
    if len(ways) > 2000:
        raise RuntimeError('Unexpectedly large extract; no asset written.')
    result = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">',
              '<!-- Geographic basemap: © OpenStreetMap contributors, ODbL. Generated from Overpass vector data, not tiles. -->',
              f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#e7edef"/>']
    paths = []
    for item in ways:
        points = [project(point['lat'],point['lon']) for point in item['geometry']]
        path = 'M'+' L'.join(f'{x:.1f},{y:.1f}' for x,y in points)
        tags = item.get('tags',{})
        if 'highway' not in tags:
            fill = '#acd69c' if tags.get('leisure') == 'park' or tags.get('landuse') == 'grass' else '#a1d1df'
            result.append(f'<path d="{path} Z" fill="{fill}" stroke="#b7cbc0" stroke-width="1"/>')
        else:
            kind = tags['highway']
            width = 16 if kind in ('primary','secondary','tertiary') else 10 if kind in ('residential','unclassified') else 6
            paths.append((path,width,tags.get('name',''),points,kind))
    for path,width,_,_,_ in paths:
        result.append(f'<path d="{path}" fill="none" stroke="#c7d3d7" stroke-width="{width+3}" stroke-linejoin="round" stroke-linecap="round"/>')
    for path,width,_,_,kind in paths:
        fill = '#fff9e8' if kind in ('primary','secondary','tertiary') else '#fff'
        result.append(f'<path d="{path}" fill="none" stroke="{fill}" stroke-width="{width}" stroke-linejoin="round" stroke-linecap="round"/>')
    labeled = set()
    labeled_names = set()
    for _,width,name,points,_ in paths:
        if not name or name in labeled_names or len(name) > 65:
            continue
        x,y = points[len(points)//2]
        if not 55 < x < WIDTH-130 or not 35 < y < HEIGHT-45 or (abs(x-X)<90 and abs(y-Y)<65):
            continue
        if any(abs(x-px)<100 and abs(y-py)<32 for _,px,py in labeled):
            continue
        label = html.escape(name)
        result.append(f'<text x="{x:.1f}" y="{y-8:.1f}" font-family="sans-serif" font-size="14" fill="#53666f" stroke="#eef2f3" stroke-width="3" paint-order="stroke">{label}</text>')
        labeled.add((name,x,y))
        labeled_names.add(name)
        if len(labeled) >= 10:
            break
    result += [f'<path d="M{X-22} {Y-7}a22 22 0 1 1 44 0c0 18-22 38-22 38s-22-20-22-38z" fill="#233949" stroke="#fff" stroke-width="5"/>',
               f'<path d="M{X+3} {Y-23}l-13 19h9l-3 14 14-21h-10z" fill="#fff"/>',
               f'<circle cx="{X}" cy="{Y+36}" r="5" fill="#233949" stroke="#fff" stroke-width="2"/>',
               '</svg>']
    target = Path(__file__).resolve().parents[1]/'apps/mobile/assets/maps/demo-centro.svg'
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text('\n'.join(result)+'\n',encoding='utf-8')
    print(f'Generated {target.name}: {len(ways)} vector features, {target.stat().st_size} bytes.')


if __name__ == '__main__':
    main()
