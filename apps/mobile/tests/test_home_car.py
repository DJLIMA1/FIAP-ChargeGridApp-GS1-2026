"""O Início (e o palco da recarga) mostram o carro do perfil do motorista, não sempre o BYD Dolphin."""
import unittest
from pathlib import Path

import flet as ft

from chargegrid_app.screens import home, reservations
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

    def test_mapping_by_body_type_with_dolphin_fallback(self):
        self.assertEqual(design.car_src({'preset': 'byd_dolphin'}), design.CAR_SRC)
        self.assertEqual(design.car_src({'preset': 'byd_seal'}), '/design/car_sedan.svg')
        self.assertEqual(design.car_src({'preset': 'volvo_ex30'}), '/design/car_suv.svg')
        self.assertEqual(design.car_src({'preset': 'renault_kwid_etech'}), '/design/car_compact.svg')
        self.assertEqual(design.car_src({'name': 'Meu carro', 'usable_battery_kwh': 50}), '/design/car_hatch.svg')
        for unknown in (None, {}, {'preset': 'carro_que_nao_existe'}, 'byd_seal'):
            self.assertEqual(design.car_src(unknown), design.CAR_SRC)


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
        self.assertEqual(images(screen)[0], '/design/car_sedan.svg')
        caption = next(item for item in descendants(screen) if getattr(item, 'data', None) == 'home-car-name')
        self.assertEqual(caption.content.value, 'BYD Seal')
        # O palco da recarga usa o mesmo carro (cache da sessão).
        stage = reservations._stage('40%', k=1.0, vehicle=app.vehicle_cache)
        self.assertIn('/design/car_sedan.svg', [src for item in stage for src in images(item)])

    async def test_profile_failure_falls_back_to_the_dolphin(self):
        _, screen = await self.build(RuntimeError('offline'))
        self.assertEqual(images(screen)[0], design.CAR_SRC)
        self.assertIn('BYD Dolphin', [item.value for item in descendants(screen) if isinstance(item, ft.Text)])


if __name__ == '__main__':
    unittest.main()
