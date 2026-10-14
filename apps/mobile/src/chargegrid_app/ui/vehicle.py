"""Seletor do carro elétrico: cadastro, perfil e Modo motorista usam o mesmo controle.

Modelo da lista (presets do core/API) ou "Outro carro" com nome, bateria útil e consumo.
``read(strict)`` devolve o dicionário aceito por ``PUT /v1/driver/profile`` ou ``None``.
"""
import flet as ft

from chargegrid_core.driver import PRESETS

from ..api_client import ApiError
from ..services import driver as helpers
from . import theme
from .components import field

CUSTOM, LATER = 'custom', 'later'


def _decimal(value):
    return '' if value is None else f'{float(value):g}'.replace('.', ',')


class VehiclePicker:
    def __init__(self, vehicle=None, presets=None, *, allow_later=False, on_change=None, on_submit=None,
                 label='Modelo do carro'):
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
        self.model = ft.Dropdown(label=label, value=key, expand=True, color=theme.TEXT_COLOR, bgcolor=theme.WHITE,
                                 options=[ft.DropdownOption(key=k, text=t) for k, t in options],
                                 on_select=self._changed)
        self.name = field('Nome do carro', (vehicle.get('name') or '') if key == CUSTOM else '')
        self.name.max_length, self.name.counter = 60, ''
        self.battery = field('Bateria útil (kWh)', _decimal(vehicle.get('usable_battery_kwh')))
        self.consumption = field('Consumo (kWh/100 km)', _decimal(vehicle.get('consumption_kwh_per_100km')))
        for control in (self.battery, self.consumption):
            control.keyboard_type = ft.KeyboardType.NUMBER
        for control in (self.name, self.battery, self.consumption):
            control.on_change = self._changed
            if on_submit:
                control.on_submit = on_submit
        # Empilhados: rótulos longos não quebram em telas de 360 px.
        self.custom = ft.Column([self.name, self.battery, self.consumption], spacing=8, visible=key == CUSTOM)
        self.summary = ft.Text('', size=12, color=theme.GRAY_TEXT)
        self._last_preset = key if key in self.presets else None
        self._refresh()
        self.control = ft.Column([ft.Row([self.model]), self.custom, self.summary], spacing=8,
                                 horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

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
