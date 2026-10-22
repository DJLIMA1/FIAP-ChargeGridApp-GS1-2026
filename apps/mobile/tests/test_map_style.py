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

    def test_dense_viewport_uses_real_detail_and_lossless_pixels_at_the_same_location(self):
        # A landmark at this real coordinate must stay under the interactive
        # pin after the source resolution changes, including at a tile seam.
        point = (-23.55, -46.63)

        def tile(zoom, tx, ty):
            image = Image.new('RGB', (256, 256), OSM['land'])
            px, py = maps._lonlat_to_px(*point, zoom)
            ImageDraw.Draw(image).rectangle((px - tx * 256 - 4, py - ty * 256 - 4,
                                             px - tx * 256 + 4, py - ty * 256 + 4), fill=OSM['water'])
            buffer = io.BytesIO()
            image.save(buffer, format='PNG')
            return buffer.getvalue()

        with patch.object(maps, '_tile_bytes', side_effect=tile) as fetch:
            standard = maps.build_map_png(*point, [], width=360, height=240, zoom=16, center_glyph=None)
            fetch.reset_mock()
            dense = maps.build_map_png(*point, [], width=360, height=240, zoom=16,
                                       center_glyph=None, pixel_ratio=2)
            self.assertTrue(all(call.args[0] == 17 for call in fetch.call_args_list))
            fetch.reset_mock()
            self.assertIs(maps.build_map_png(*point, [], width=360, height=240, zoom=16,
                                             center_glyph=None, pixel_ratio=2), dense)
            fetch.assert_not_called()
        self.assertEqual(Image.open(io.BytesIO(standard)).size, (360, 240))
        image = Image.open(io.BytesIO(dense))
        self.assertEqual((image.size, image.format), ((720, 480), 'PNG'))
        self.assertEqual(image.getpixel((360, 240)), rgb(maps.map_style(False)['water']))
        self.assertEqual(len(maps._map_cache), 2)

    def test_dense_viewport_respects_provider_maximum_zoom(self):
        with patch.object(maps, '_tile_bytes', return_value=png_tile()) as fetch:
            data = maps.build_map_png(0, 0, [], width=360, height=240, zoom=19,
                                      center_glyph=None, pixel_ratio=2)
        self.assertTrue(all(call.args[0] == 19 for call in fetch.call_args_list))
        self.assertEqual(Image.open(io.BytesIO(data)).size, (360, 240))


class CallerThemeTests(ThemeRestore, unittest.IsolatedAsyncioTestCase):
    station = {'id': 's1', 'name': 'Posto', 'latitude': -23.5505, 'longitude': -46.6333,
               'free_points': 2, 'price': 1.95, 'status': 'Disponível'}

    async def test_all_maps_follow_shared_light_and_dark_vector_styles(self):
        import json

        from chargegrid_map import VectorMap
        for dark in (False, True):
            theme.set_dark(dark)
            for variant in ('list', 'detail', None):
                with self.subTest(dark=dark, variant=variant):
                    screen = await maps.station_map_widget([self.station], Mock(), variant=variant, offline=True, crop='villa')
                    control = next(item for item in descendants(screen) if isinstance(item, VectorMap))
                    data = json.loads(control.style_json)
                    self.assertEqual(data['name'], 'ChargeGrid Dark' if dark else 'ChargeGrid Light')
                    self.assertEqual(data['sources']['openmaptiles']['type'], 'vector')
                    self.assertFalse(any(isinstance(item, ft.Image) for item in descendants(screen)))

    async def test_explicit_dark_argument_wins_over_current_theme(self):
        import json

        from chargegrid_map import VectorMap
        theme.set_dark(False)
        screen = await maps.station_map_widget([self.station], Mock(), dark=True)
        control = next(item for item in descendants(screen) if isinstance(item, VectorMap))
        self.assertEqual(json.loads(control.style_json)['name'], 'ChargeGrid Dark')

    async def test_vector_style_keeps_provider_labels_and_distinct_map_themes(self):
        import json

        from chargegrid_app.ui.vector_map import vector_style
        styles = [json.loads(vector_style(dark)) for dark in (False, True)]
        for data in styles:
            labels = [layer for layer in data['layers'] if layer['type'] == 'symbol']
            self.assertTrue(labels)
            self.assertTrue(any('text-size' in layer.get('layout', {}) for layer in labels))
            self.assertTrue(data['glyphs'].startswith('https://tiles.openfreemap.org/'))
        self.assertNotEqual(styles[0]['layers'], styles[1]['layers'])


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
