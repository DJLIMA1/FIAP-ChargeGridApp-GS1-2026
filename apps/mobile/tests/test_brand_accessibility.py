"""Guard contrast and intrinsic controls against regressions in both palettes."""
import unittest

import flet as ft

from chargegrid_app.ui import components, motion, theme


def luminance(color):
    values = [int(color.lstrip('#')[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [v / 12.92 if v <= .04045 else ((v + .055) / 1.055) ** 2.4 for v in values]
    return sum(v * w for v, w in zip(linear, (.2126, .7152, .0722)))


def contrast(first, second):
    a, b = sorted((luminance(first), luminance(second)))
    return (b + .05) / (a + .05)


class BrandAccessibilityTests(unittest.TestCase):
    def setUp(self):
        self.original_dark = theme.is_dark()

    def tearDown(self):
        theme.set_dark(self.original_dark)
        motion.set_reduced(False)

    def test_shared_text_and_status_badges_meet_contrast_in_both_themes(self):
        for dark in (False, True):
            theme.set_dark(dark)
            for background in (theme.WHITE, theme.BG_COLOR):
                for foreground in (theme.TEXT_COLOR, theme.GRAY_TEXT, theme.ACCENT):
                    with self.subTest(dark=dark, fg=foreground, bg=background):
                        self.assertGreaterEqual(contrast(foreground, background), 4.5)
            self.assertGreaterEqual(contrast('#FFFFFF', theme.RED), 4.5)
            for fill in (theme.GREEN, theme.AMBER, theme.BLUE, theme.SLATE, theme.RED):
                badge = components.badge('Sincronizando com o ponto', bg=fill)
                self.assertGreaterEqual(contrast(badge.content.color, fill), 4.5)
                self.assertIsNone(badge.height)

    def test_action_has_native_keyboard_focus_and_no_fixed_text_box(self):
        def action(event):
            return None
        control = components.button('Acompanhar confirmação pelo ponto', action)
        self.assertIsInstance(control, ft.TextButton)
        self.assertIs(control.on_click, action)
        self.assertIsNone(control.height)
        self.assertIsNone(control.content.max_lines)
        self.assertGreaterEqual(control.style.padding.top, 14)
        self.assertGreaterEqual(control.style.side[ft.ControlState.FOCUSED].width, 2)

    def test_brand_reuses_asset_and_remains_a_wrapping_wordmark(self):
        for compact in (False, True):
            brand = components.brand(compact=compact)
            self.assertEqual(brand.controls[0].content.src, '/icon.png')
            self.assertEqual(brand.controls[1].value, 'ChargeGrid')
            self.assertTrue(brand.controls[1].expand)
            self.assertIsNone(brand.height)
