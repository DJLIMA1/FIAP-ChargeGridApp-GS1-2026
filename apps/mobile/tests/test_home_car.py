"""O Início (e o palco da recarga) mostram o carro do perfil do motorista, não sempre o BYD Dolphin."""
import unittest
from pathlib import Path
from types import SimpleNamespace

import flet as ft
from PIL import Image

from chargegrid_app.screens import home, profile, reservations
from chargegrid_app.ui import design
from chargegrid_core.driver.vehicles import PRESETS
from test_behavior import HandlerApp, descendants

ASSETS = Path(__file__).resolve().parents[1] / 'assets'


def images(screen):
    return [item.src for item in descendants(screen) if isinstance(item, ft.Image) and str(item.src).startswith('/design/car_')]


class CarImageTests(unittest.TestCase):
    def test_every_preset_has_an_existing_image(self):
        for key in [*PRESETS, 'custom']:
            src = design.car_src({'preset': key})
            self.assertTrue((ASSETS / src.lstrip('/')).is_file(), (key, src))

    def test_every_preset_has_its_own_photo_framed_like_the_dolphin(self):
        photos = set()
        for key in PRESETS:
            src = design.car_src({'preset': key})
            self.assertEqual(src, f'/design/car_{key}.png')
            photos.add(src)
            with Image.open(ASSETS / src.lstrip('/')) as image:
                self.assertEqual(image.size, (1168, 702), key)
                self.assertTrue(image.mode == 'RGBA' or 'transparency' in image.info, (key, image.mode))
                alpha = image.convert('RGBA').getchannel('A')
            width, height = alpha.size
            border = [alpha.getpixel((x, y)) for x in range(0, width, 4) for y in (0, 1)]
            border += [alpha.getpixel((x, y)) for y in range(0, height, 4) for x in (0, width - 1)]
            clear = sum(value < 32 for value in border) / len(border)
            self.assertGreater(clear, 0.6, (key, clear))  # fundo recortado, não um retângulo de foto
            self.assertLess(alpha.histogram()[0] / (width * height), 0.6, key)  # e o carro ocupa o quadro
            self.assertLess((ASSETS / src.lstrip('/')).stat().st_size, 700 * 1024, key)
        self.assertEqual(len(photos), len(PRESETS))

    def test_custom_uses_the_neutral_silhouette_and_unknown_falls_back_to_the_dolphin(self):
        self.assertEqual(design.car_src({'preset': 'byd_dolphin'}), design.CAR_SRC)
        self.assertEqual(design.car_src({'preset': 'custom'}), '/design/car_hatch.svg')
        self.assertEqual(design.car_src({'name': 'Meu carro', 'usable_battery_kwh': 50}), '/design/car_hatch.svg')
        for unknown in (None, {}, {'preset': 'carro_que_nao_existe'}, 'byd_seal'):
            self.assertEqual(design.car_src(unknown), design.CAR_SRC)

    def test_every_photo_but_the_dolphin_is_credited(self):
        credited = {model for model, _, _ in design.CAR_PHOTO_CREDITS}
        self.assertEqual(credited, {profile.name for key, profile in PRESETS.items() if key != 'byd_dolphin'})
        credits = (ASSETS / 'design' / 'CREDITS.md').read_text(encoding='utf-8')
        for key in PRESETS:
            if key != 'byd_dolphin':
                self.assertIn(f'car_{key}.png', credits)

    def test_account_screen_lists_the_photo_credits_behind_a_low_key_row(self):
        app = SimpleNamespace(page=SimpleNamespace(update=lambda: None))
        row, details = profile.photo_credits(app)
        self.assertFalse(details.visible)
        texts = ' '.join(item.value for item in descendants(details) if isinstance(item, ft.Text))
        for model, author, terms in design.CAR_PHOTO_CREDITS:
            self.assertIn(f'{model}: {author}, {terms}', texts)
        self.assertIn('Wikimedia Commons', texts)
        clickable = next(item for item in descendants(row) if getattr(item, 'on_click', None))
        clickable.on_click(None)
        self.assertTrue(details.visible)


class HomeCarTests(unittest.IsolatedAsyncioTestCase):
    async def build(self, vehicle_response):
        app = HandlerApp()
        state = {'reservations/current': None, 'charging-sessions/current': None,
                 'stations': {'items': [], 'total': 0}}

        async def request(method, path, **kwargs):
            if path == 'driver/profile':
                if isinstance(vehicle_response, Exception):
                    raise vehicle_response
                return {'vehicle': vehicle_response}
            return state.get(path)
        app.api.request.side_effect = request
        app.api.is_demo = True  # sem cair no carro salvo no aparelho
        return app, await home.build(app)

    async def test_home_shows_the_profile_car_with_its_name(self):
        app, screen = await self.build({'preset': 'byd_seal'})
        self.assertEqual(images(screen)[0], '/design/car_byd_seal.png')
        caption = next(item for item in descendants(screen) if getattr(item, 'data', None) == 'home-car-name')
        self.assertEqual(caption.content.value, 'BYD Seal')
        # O palco da recarga usa o mesmo carro (cache da sessão).
        stage = reservations._stage('40%', k=1.0, vehicle=app.vehicle_cache)
        self.assertIn('/design/car_byd_seal.png', [src for item in stage for src in images(item)])

    async def test_profile_failure_falls_back_to_the_dolphin(self):
        _, screen = await self.build(RuntimeError('offline'))
        self.assertEqual(images(screen)[0], design.CAR_SRC)
        self.assertIn('BYD Dolphin', [item.value for item in descendants(screen) if isinstance(item, ft.Text)])


if __name__ == '__main__':
    unittest.main()
