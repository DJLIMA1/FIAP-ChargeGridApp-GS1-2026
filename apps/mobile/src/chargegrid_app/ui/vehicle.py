"""Seletor do carro elétrico: cadastro, perfil e Modo motorista usam o mesmo controle.

Modelo da lista (presets do core/API) ou "Outro carro" com nome, bateria útil e consumo.
``read(strict)`` devolve o dicionário aceito por ``PUT /v1/driver/profile`` ou ``None``.
"""
import flet as ft

from chargegrid_core.driver import PRESETS

from ..api_client import ApiError
from ..services import driver as helpers
from . import design, theme

CUSTOM, LATER = 'custom', 'later'


def _rounded():
    return ft.OutlineInputBorder(border_radius=design.RADIUS_BTN + 2, side=ft.BorderSide(0, ft.Colors.TRANSPARENT))


def _decimal(value):
    return '' if value is None else f'{float(value):g}'.replace('.', ',')


class VehiclePicker:
    def __init__(self, vehicle=None, presets=None, *, allow_later=False, on_change=None, on_submit=None,
                 label='Modelo do carro', outer_labels=False):
        # ``outer_labels``: rótulos acima dos campos (como Nome/Telefone no Perfil), sem rótulo flutuante.
        self.outer_labels = outer_labels
        self.presets = {p['key']: p for p in (presets or [p.to_dict() for p in PRESETS.values()])}
        self.on_change = on_change
        self._last_preset = None
        vehicle = dict(vehicle or {})
        key = vehicle.get('preset')
        if key not in self.presets and key != CUSTOM:
            key = CUSTOM if vehicle.get('usable_battery_kwh') else LATER if allow_later else next(iter(self.presets))
        options = [(k, p['name']) for k, p in self.presets.items()] + [(CUSTOM, 'Outro carro')]
        if allow_later:
            options.append((LATER, 'Prefiro informar depois'))
        # Campo escuro arredondado do design de referência; o rótulo fica dentro do campo.
        self.model = ft.Dropdown(
            label=None if outer_labels else label, value=key, expand=True, color=theme.INPUT_TEXT, bgcolor=theme.CARD, filled=True,
            fill_color=theme.INPUT_BG, border=_rounded(), border_radius=design.RADIUS_BTN + 2,
            text_style=ft.TextStyle(size=12.5, font_family=design.FONT, color=theme.INPUT_TEXT),
            label_style=ft.TextStyle(size=11, font_family=design.FONT_BOLD, color=theme.GRAY_TEXT),
            content_padding=ft.Padding(left=13, right=13, top=13, bottom=13),
            options=[ft.DropdownOption(key=k, text=t) for k, t in options],
            on_select=self._changed)
        self.name = self._input('Nome do carro', (vehicle.get('name') or '') if key == CUSTOM else '')
        self.name.max_length, self.name.counter = 60, ''
        self.battery = self._input('Bateria útil (kWh)', _decimal(vehicle.get('usable_battery_kwh')))
        self.consumption = self._input('Consumo (kWh/100 km)', _decimal(vehicle.get('consumption_kwh_per_100km')))
        for control in (self.battery, self.consumption):
            control.keyboard_type = ft.KeyboardType.NUMBER
        for control in (self.name, self.battery, self.consumption):
            control.on_change = self._changed
            if on_submit:
                control.on_submit = on_submit
        # Empilhados: rótulos longos não quebram em telas de 360 px.
        custom = [self.name, self.battery, self.consumption]
        if outer_labels:
            custom = []
            for control in (self.name, self.battery, self.consumption):
                text, control.label = control.label, None
                custom.append(design.labeled(text, control, 14))
        self.custom = ft.Column(custom, spacing=14 if outer_labels else 8, visible=key == CUSTOM)
        self.summary = design.txt('', 11, 'regular', theme.GRAY_TEXT)
        self._last_preset = key if key in self.presets else None
        self._refresh()
        model = design.labeled(label, ft.Row([self.model]), 14) if outer_labels else ft.Row([self.model])
        self.control = ft.Column([model, self.custom, self.summary], spacing=14 if outer_labels else 8,
                                 horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    @staticmethod
    def _input(label, value=''):
        control = design.input_field(value)
        control.label = label
        control.label_style = ft.TextStyle(size=11, font_family=design.FONT_BOLD, color=theme.GRAY_TEXT)
        control.border = _rounded()
        control.height = None
        control.error_max_lines = 3
        return control

    @property
    def value(self):
        return self.model.value

    def _refresh(self):
        current = self.read(strict=False)
        if self.model.value == LATER:
            self.summary.value = 'Você pode escolher depois em Perfil ou no Modo motorista.'
        elif current is None:
            self.summary.value = 'Informe bateria útil e consumo para estimarmos a autonomia.'
        else:
            self.summary.value = helpers.vehicle_summary(current)

    async def _changed(self, event=None):
        if event is not None and event.control is self.model and self.model.value == CUSTOM \
                and not (self.battery.value or '').strip():
            # Começa do último modelo escolhido: o motorista só ajusta o que for diferente.
            base = self.presets.get(self._last_preset) or next(iter(self.presets.values()))
            self.battery.value = _decimal(base['usable_battery_kwh'])
            self.consumption.value = _decimal(base['consumption_kwh_per_100km'])
        if self.model.value in self.presets:
            self._last_preset = self.model.value
        self.custom.visible = self.model.value == CUSTOM
        self._refresh()
        if self.on_change:
            self.on_change(self.read(strict=False))
        else:
            try:
                self.control.update()
            except (RuntimeError, AssertionError, AttributeError):
                pass  # Ainda não montado (testes).

    def read(self, strict=True):
        """Carro escolhido (``{'preset': ...}`` ou personalizado) ou ``None`` ("informar depois")."""
        key = self.model.value
        if key in self.presets:
            return {'preset': key}
        if key != CUSTOM:
            return None
        try:
            name = (self.name.value or '').strip() or 'Meu carro'
            if len(name) > 60:
                raise ApiError('Use até 60 caracteres no nome do carro.')
            return {'preset': CUSTOM, 'name': name,
                    'usable_battery_kwh': helpers.number(self.battery.value, 'a bateria útil (kWh)', 5, 250),
                    'consumption_kwh_per_100km': helpers.number(self.consumption.value,
                                                                'o consumo (kWh/100 km)', 5, 60)}
        except ApiError:
            if strict:
                raise
            return None
