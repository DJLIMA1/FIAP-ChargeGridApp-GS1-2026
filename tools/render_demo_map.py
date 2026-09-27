"""Rasterize the bundled linear OSM vector extract, including readable labels.

Offline, reproducible development step; no tile downloads or invented geography.
The source extract remains available beside the output with ODbL attribution.
"""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / 'apps/mobile/assets'
WIDTH, HEIGHT = 640, 442
SHIFT_X, SHIFT_Y = -9, 25


def render():
    source = ET.parse(ASSETS/'maps/demo-centro.svg').getroot()
    image = Image.new('RGB',(WIDTH,HEIGHT),'#e7edef')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(ASSETS/'Barlow-Regular.ttf'),14)
    for node in source:
        kind = node.tag.rsplit('}',1)[-1]
        if kind == 'path':
            path = node.attrib['d']
            # The basemap uses absolute linear paths. The source marker's curved
            # paths are redrawn below in the same geographic frame.
            if re.search(r'[a-zA-Y]',path.replace('M','').replace('L','')):
                continue
            values = [float(value) for value in re.findall(r'-?\d+(?:\.\d+)?',path)]
            points = [(x+SHIFT_X,y+SHIFT_Y) for x,y in zip(values[::2],values[1::2])]
            if len(points) < 2:
                continue
            fill = node.get('fill','none')
            if fill != 'none':
                draw.polygon(points,fill=fill)
            stroke = node.get('stroke')
            if stroke:
                thickness = round(float(node.get('stroke-width','1')))
                draw.line(points + ([points[0]] if 'Z' in path else []),fill=stroke,width=thickness,joint='curve')
                if node.get('stroke-linecap') == 'round':
                    r = thickness/2
                    for x,y in (points[0],points[-1]):
                        draw.ellipse((x-r,y-r,x+r,y+r),fill=stroke)
        elif kind == 'text':
            draw.text((float(node.get('x'))+SHIFT_X,float(node.get('y'))+SHIFT_Y),node.text or '',
                      font=font,anchor='ls',fill=node.get('fill'),stroke_width=2,stroke_fill='#eef2f3')
    # Import the same pin renderer as the online view; no runtime network use.
    from chargegrid_app.services.maps import _draw_station_pin
    _draw_station_pin(draw,265+SHIFT_X,165+SHIFT_Y,radius=WIDTH*.038)
    target = ASSETS/'maps/demo-centro.png'
    image.save(target,optimize=True)
    print(f'Generated {target.name}: {WIDTH} × {HEIGHT}, {target.stat().st_size} bytes.')


if __name__ == '__main__':
    render()
