"""ChargeGrid map style: light and dark variants of the OSM raster, pins, callout, credit and fallbacks."""
import io
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import flet as ft
from PIL import Image, ImageDraw

from chargegrid_app.services import maps
from chargegrid_app.ui import theme
from test_behavior import descendants

ASSETS = Path(__file__).resolve().parents[1] / 'assets'

# Typical OSM Carto fills, one swatch each (left to right).
OSM = {'road': '#FFFFFF', 'land': '#F2EFE9', 'block': '#D9D0C9', 'water': '#AAD3DF', 'park': '#C8FACC',
       'forest': '#ADD19E', 'major': '#F9B29C', 'secondary': '#F7FABF', 'label': '#222222', 'bus_stop': '#0092DA'}
SWATCH = 20


def osm_fixture():
    image = Image.new('RGB', (SWATCH * len(OSM), SWATCH))
    draw = ImageDraw.Draw(image)
    for index, color in enumerate(OSM.values()):
        draw.rectangle((index * SWATCH, 0, (index + 1) * SWATCH - 1, SWATCH - 1), fill=color)
    return image


def styled_swatches(dark):
    styled = maps._style_tiles(osm_fixture(), dark)
    return {name: styled.getpixel((index * SWATCH + SWATCH // 2, SWATCH // 2)) for index, name in enumerate(OSM)}


def rgb(color):
    return maps._rgb(color)


def close(a, b, tolerance=3):
    return all(abs(x - y) <= tolerance for x, y in zip(a, b))


def luminance(color):
    channels = [c / 255 for c in color]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + .05) / (low + .05)


def over(argb, below):
    """Composite an ARGB '#AARRGGBB' token over an RGB colour."""
    value = argb.lstrip('#')
    alpha = int(value[:2], 16) / 255 if len(value) == 8 else 1
    top = rgb(argb)
    return tuple(round(t * alpha + b * (1 - alpha)) for t, b in zip(top, below))


def png_tile(color='#F2EFE9'):
    buffer = io.BytesIO()
    Image.new('RGB', (256, 256), color).save(buffer, format='PNG')
    return buffer.getvalue()


class ThemeRestore:
    def setUp(self):
        self.addCleanup(theme.set_dark, theme.is_dark())


class StyleRampTests(unittest.TestCase):
    def test_both_variants_are_complete_and_derived_from_theme_tokens(self):
        light, dark = maps.map_style(False), maps.map_style(True)
        self.assertEqual(set(light), set(dark))
        self.assertEqual(light['land'], theme.LIGHT['MAP_LAND'])
        self.assertEqual(dark['water'], theme.DARK['MAP_WATER'])
        self.assertEqual(light['pin_list'], theme.BRAND_GREEN)
        self.assertEqual(light['pin_detail'], theme.BRAND_NAVY)
        self.assertNotEqual(light['land'], dark['land'])

    def test_light_variant_maps_osm_fills_onto_the_brand_ramp(self):
        style, out = maps.map_style(False), styled_swatches(False)
        for name, token in (('road', 'road'), ('land', 'land'), ('block', 'block'), ('water', 'water'),
                            ('park', 'park'), ('forest', 'park'), ('major', 'road_major'),
                            ('secondary', 'road_major'), ('label', 'label')):
            with self.subTest(name=name):
                self.assertTrue(close(out[name], rgb(style[token])), (name, out[name], style[token]))
        # Order is kept: roads lightest, then land, then blocks; labels dark and readable.
        self.assertGreater(luminance(out['road']), luminance(out['land']))
        self.assertGreater(luminance(out['land']), luminance(out['block']))
        self.assertGreaterEqual(contrast(out['label'], out['land']), 4.5)

    def test_dark_variant_is_charcoal_with_lighter_streets_and_light_labels(self):
        style, out = maps.map_style(True), styled_swatches(True)
        for name, token in (('road', 'road'), ('land', 'land'), ('block', 'block'), ('water', 'water'),
                            ('park', 'park'), ('major', 'road_major'), ('label', 'label')):
            with self.subTest(name=name):
                self.assertTrue(close(out[name], rgb(style[token])), (name, out[name], style[token]))
        self.assertLess(luminance(out['land']), .03)  # charcoal background
        self.assertGreater(luminance(out['road']), luminance(out['block']))
        self.assertGreater(luminance(out['block']), luminance(out['land']))
        self.assertGreater(luminance(out['major']), luminance(out['road']))  # avenues stand out
        self.assertGreaterEqual(contrast(out['label'], out['land']), 4.5)
        self.assertGreaterEqual(contrast(out['label'], out['road']), 3)

    def test_water_and_parks_stay_distinguishable_from_land_in_both_variants(self):
        for dark in (False, True):
            out = styled_swatches(dark)
            with self.subTest(dark=dark):
                for feature in ('water', 'park'):
                    self.assertGreater(sum(abs(a - b) for a, b in zip(out[feature], out['land'])), 24)
                self.assertGreater(out['water'][2], out['water'][0])  # bluish
                self.assertGreater(out['park'][1], out['park'][0])  # greenish

    def test_saturated_icons_are_not_painted_as_water(self):
        for dark in (False, True):
            with self.subTest(dark=dark):
                out = styled_swatches(dark)
                water = rgb(maps.map_style(dark)['water'])
                self.assertFalse(close(out['bus_stop'], water, 10))

    def test_style_keeps_size_and_returns_rgb(self):
        image = Image.new('RGBA', (720, 497), (242, 239, 233, 255))
        for dark in (False, True):
            styled = maps._style_tiles(image, dark)
            self.assertEqual((styled.size, styled.mode), ((720, 497), 'RGB'))


class ComposeAndCacheTests(unittest.TestCase):
    def setUp(self):
        maps._map_cache.clear()
        maps._tile_bytes.cache_clear()
        maps._network_down_until = 0.0
        self.addCleanup(maps._map_cache.clear)
        self.addCleanup(maps._tile_bytes.cache_clear)

    def render(self, dark, color=None):
        kwargs = {'selected_color': color} if color else {}
        return maps.build_map_png(-23.55, -46.63, [(-23.55, -46.63, '⚡')], width=360, height=240, zoom=16,
                                  center_glyph=None, dark=dark, selected_marker=(-23.55, -46.63), **kwargs)

    def test_cache_is_separate_per_theme_while_raw_tiles_are_shared(self):
        with patch.object(maps, '_fetch_bytes', return_value=png_tile()) as fetch, \
                patch.object(maps, '_TILE_CACHE_DIR', Path(os.devnull) / 'unwritable'):
            light = self.render(False)
            downloads = fetch.call_count
            dark = self.render(True)
            self.assertEqual(fetch.call_count, downloads)  # no extra tile request for the other theme
            self.assertIs(self.render(False), light)
            self.assertIs(self.render(True), dark)
        self.assertNotEqual(light, dark)
        self.assertEqual(len(maps._map_cache), 2)
        land = {False: rgb(maps.map_style(False)['land']), True: rgb(maps.map_style(True)['land'])}
        for data, variant in ((light, False), (dark, True)):
            corner = Image.open(io.BytesIO(data)).convert('RGB').getpixel((5, 5))
            self.assertTrue(close(corner, land[variant], 6), (variant, corner))

    def test_pins_use_the_variant_tokens(self):
        for dark in (False, True):
            style = maps.map_style(dark)
            with self.subTest(dark=dark), patch.object(maps, '_tile_bytes', return_value=png_tile()):
                maps._map_cache.clear()
                image = Image.open(io.BytesIO(self.render(dark, style['pin_detail']))).convert('RGB')
                # Pin head sits just above the geographic point (image centre); sample beside the glyph.
                radius = 360 * .038
                sample = image.getpixel((round(180 - radius * .6), round(120 + radius * .1)))
                self.assertTrue(close(sample, rgb(style['pin_detail']), 20), (dark, sample))  # JPEG chroma


class CallerThemeTests(ThemeRestore, unittest.IsolatedAsyncioTestCase):
    station = {'id': 's1', 'name': 'Posto', 'latitude': -23.5505, 'longitude': -46.6333,
               'free_points': 2, 'price': 1.95, 'status': 'Disponível'}

    async def test_station_maps_follow_the_app_theme(self):
        for dark in (False, True):
            theme.set_dark(dark)
            style = maps.map_style(dark)
            for variant in ('list', 'detail', None):
                with self.subTest(dark=dark, variant=variant), \
                        patch.object(maps, 'build_map_png', return_value=b'fixture') as render:
                    screen = await maps.station_map_widget([self.station], Mock(), variant=variant)
                    self.assertIs(render.call_args.kwargs['dark'], dark)
                    if variant:
                        self.assertEqual(render.call_args.kwargs['selected_color'], style[maps.VARIANT_PIN[variant]])
                    frame = screen
                    self.assertEqual(frame.bgcolor, style['land'])
                    callout = next(item for item in descendants(screen) if isinstance(item, ft.Container) and item.on_click)
                    self.assertEqual(callout.bgcolor, style['callout'])
                    credit = next(item for item in descendants(screen) if isinstance(item, ft.Container) and item.url)
                    self.assertEqual((credit.bgcolor, credit.content.color), (style['credit_bg'], style['credit_fg']))
                    self.assertEqual(credit.content.value, '© OpenStreetMap')

    async def test_explicit_dark_argument_wins_over_theme(self):
        theme.set_dark(False)
        with patch.object(maps, 'build_map_png', return_value=b'fixture') as render:
            await maps.station_map_widget([self.station], Mock(), dark=True)
            await maps.map_widget(-23.55, -46.63, [], dark=True)
        self.assertTrue(all(call.kwargs['dark'] for call in render.call_args_list))

    async def test_generic_map_and_legend_follow_the_theme(self):
        for dark in (False, True):
            theme.set_dark(dark)
            style = maps.map_style(dark)
            with self.subTest(dark=dark), patch.object(maps, 'build_map_png', return_value=b'fixture') as render:
                screen = await maps.map_widget(-23.55, -46.63, [(-23.55, -46.63, '⚡')])
                self.assertIs(render.call_args.kwargs['dark'], dark)
                icons = [item.color for item in descendants(screen) if isinstance(item, ft.Icon)]
                self.assertIn(style['pin'], icons)

    async def test_schematic_fallback_has_both_variants(self):
        for dark in (False, True):
            theme.set_dark(dark)
            style = maps.map_style(dark)
            with self.subTest(dark=dark), patch.object(maps, 'build_map_png', side_effect=OSError('offline')):
                screen = await maps.station_map_widget([self.station], Mock())
                schematic = next(item for item in descendants(screen)
                                 if isinstance(item, ft.Container) and isinstance(item.content, ft.Stack)
                                 and item.border_radius == 18 and item.bgcolor == style['land'] and item.url is None
                                 and item is not screen)
                rings = [item for item in descendants(schematic) if isinstance(item, ft.Container) and item.border
                         and item.border.top.color == style['ring']]
                pins = [item.bgcolor for item in descendants(schematic) if isinstance(item, ft.Container)
                        and item.bgcolor in (style['pin'], style['pin_off'])]
                self.assertEqual(len(rings), 3)
                self.assertTrue(pins)
            with self.subTest(dark=dark, offline=True), patch.object(maps, 'build_map_png', side_effect=AssertionError):
                screen = await maps.map_widget(-23.55, -46.63, [(-23.55, -46.63, '⚡')], offline=True)
                self.assertTrue(any(isinstance(item, ft.Container) and item.bgcolor == style['land']
                                    and isinstance(item.content, ft.Stack) for item in descendants(screen)))

    async def test_demo_reference_raster_has_a_dark_variant(self):
        villa = {**self.station, 'name': 'Villa Lobos', 'latitude': -23.5467, 'longitude': -46.7224}
        for dark in (False, True):
            theme.set_dark(dark)
            with self.subTest(dark=dark), patch.object(maps, 'build_map_png', side_effect=AssertionError('network')):
                cropped = await maps.station_map_widget([villa], Mock(), offline=True, variant='list', crop='marginal')
                fixture = await maps.station_map_widget([villa], Mock(), offline=True)
                for screen in (cropped, fixture):
                    sources = [item.src for item in descendants(screen) if isinstance(item, ft.Image)]
                    self.assertEqual(sources, [maps.DEMO_MAP_SRC[dark]])
        for src in maps.DEMO_MAP_SRC.values():
            self.assertTrue((ASSETS / src.lstrip('/')).is_file(), src)
        light = Image.open(ASSETS / maps.DEMO_MAP_SRC[False].lstrip('/'))
        dark = Image.open(ASSETS / maps.DEMO_MAP_SRC[True].lstrip('/')).convert('RGB')
        self.assertEqual(light.size, dark.size)  # same crops (DEMO_CROPS / _RASTER_FRAMES) apply
        # Map area went charcoal while the baked callout cards stay white and readable.
        self.assertLess(luminance(dark.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))), .06)
        for x0, y0, x1, y1, _ in maps.DEMO_RASTER_CARDS:
            self.assertGreater(luminance(dark.getpixel(((x0 + x1) // 2, y1 - 12))), .85)


class AttributionTests(unittest.TestCase):
    def test_osm_credit_is_legible_on_both_variants(self):
        for dark in (False, True):
            style = maps.map_style(dark)
            with self.subTest(dark=dark):
                for below in (rgb(style['land']), rgb(style['road']), rgb(style['label'])):
                    background = over(style['credit_bg'], below)
                    self.assertGreaterEqual(contrast(rgb(style['credit_fg']), background), 4.5)

    def test_callout_text_and_chips_have_contrast_in_both_variants(self):
        for dark in (False, True):
            style = maps.map_style(dark)
            with self.subTest(dark=dark):
                self.assertGreaterEqual(contrast(rgb(style['callout_text']), rgb(style['callout'])), 7)
                self.assertGreaterEqual(contrast(rgb(style['callout_muted']), rgb(style['callout'])), 4.5)
                self.assertGreaterEqual(contrast(rgb(style['chip_free_fg']), rgb(style['chip_free'])), 4.5)
                self.assertGreaterEqual(contrast(rgb(style['chip_off_fg']), rgb(style['chip_off'])), 4.5)
                # The callout card stands apart from the map underneath.
                self.assertGreater(abs(luminance(rgb(style['callout'])) - luminance(rgb(style['land']))), .005)


if __name__ == '__main__':
    unittest.main()
