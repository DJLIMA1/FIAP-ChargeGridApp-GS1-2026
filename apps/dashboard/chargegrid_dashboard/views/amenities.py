"""Editor de comodidades do posto (``PATCH /v1/stations/{id}`` com ``amenities``).

As comodidades alimentam o Modo Motorista (refeição durante a recarga).
Tipos e rótulos vêm de ``chargegrid_core.driver`` — a mesma fonte da API e do app.
"""

import flet as ft

from chargegrid_app.ui import theme
from chargegrid_app.ui.components import field
from chargegrid_core.driver.models import AMENITY_KINDS, AMENITY_LABELS

MAX_AMENITIES = 12
MAX_NAME = 80
MAX_DISTANCE = 5000


def amenity_label(kind):
    label = AMENITY_LABELS.get(kind, kind)
    return label[:1].upper() + label[1:]


def amenities_summary(amenities):
    if not amenities:
        return 'Nenhuma comodidade cadastrada'
    parts = []
    for item in amenities:
        text = item.get('name') or amenity_label(item.get('kind'))
        if item.get('distance_m') is not None:
            text += f" ({item['distance_m']} m)"
        parts.append(text)
    return 'Comodidades: ' + ', '.join(parts)


def amenities_payload(rows):
    """Valida as linhas do formulário (``kind``, ``name``, ``distance``) como a API faria."""
    if len(rows) > MAX_AMENITIES:
        raise ValueError(f'Cadastre até {MAX_AMENITIES} comodidades.')
    result = []
    for index, row in enumerate(rows, start=1):
        kind = row.get('kind')
        if kind not in AMENITY_KINDS:
            raise ValueError(f'Escolha o tipo da comodidade {index}.')
        name = (row.get('name') or '').strip()
        if len(name) > MAX_NAME:
            raise ValueError(f'Use até {MAX_NAME} caracteres no nome da comodidade {index}.')
        distance = str(row.get('distance') or '').strip()
        item = {'kind': kind, 'name': name}
        if distance:
            try:
                meters = int(distance)
            except ValueError as exc:
                raise ValueError(f'Informe a distância da comodidade {index} em metros inteiros.') from exc
            if not 0 <= meters <= MAX_DISTANCE:
                raise ValueError(f'A distância deve ficar entre 0 e {MAX_DISTANCE} m.')
            item['distance_m'] = meters
        result.append(item)
    return result


class AmenitiesEditor:
    """Diálogo com linhas editáveis; ``on_saved`` recebe o posto atualizado."""

    def __init__(self, dash, station, on_saved):
        self.dash, self.station, self.on_saved = dash, station, on_saved
        self.rows = []
        self.list = ft.Column(spacing=10, tight=True)
        self.feedback = ft.Text('', size=12, color=theme.ERROR, visible=False)
        for item in station.get('amenities') or []:
            self.add_row(item)

    def add_row(self, item=None):
        item = item or {}
        kind = ft.Dropdown(
            label='Tipo', value=item.get('kind') or AMENITY_KINDS[0], width=170, dense=True,
            options=[ft.DropdownOption(key=key, text=amenity_label(key)) for key in AMENITY_KINDS],
            color=theme.TEXT_COLOR, bgcolor=theme.WHITE, text_size=13,
        )
        name = field('Nome (opcional)', item.get('name') or '')
        name.expand = True
        distance = field('Distância (m)', '' if item.get('distance_m') is None else str(item['distance_m']))
        distance.width = 130
        row = {'kind': kind, 'name': name, 'distance': distance}
        remove = ft.IconButton(ft.Icons.DELETE_OUTLINE, tooltip='Remover comodidade', icon_color=theme.TEXT_COLOR)
        line = ft.Row([kind, name, distance, remove], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER)

        async def drop(event=None):
            self.rows.remove(row)
            self.list.controls.remove(line)
            self.dash.update()

        remove.on_click = drop
        self.rows.append(row)
        self.list.controls.append(line)

    def values(self):
        return [{'kind': row['kind'].value, 'name': row['name'].value, 'distance': row['distance'].value}
                for row in self.rows]

    def dialog(self):
        async def add(event=None):
            if len(self.rows) >= MAX_AMENITIES:
                self.show_error(f'Cadastre até {MAX_AMENITIES} comodidades.')
                return
            self.add_row()
            self.dash.update()

        def close(event=None):
            self.dash.page.pop_dialog()

        return ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Comodidades · {self.station['name']}"),
            content=ft.Column([
                ft.Text('Mostradas aos motoristas no Modo Motorista para planejar refeições durante a recarga. '
                        'Informe a distância a pé a partir do ponto.', size=12, color=theme.GRAY_TEXT),
                self.list,
                ft.TextButton('+ Adicionar comodidade', on_click=add, style=ft.ButtonStyle(color=theme.TEXT_COLOR)),
                self.feedback,
            ], tight=True, spacing=12, width=560, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton('Cancelar', on_click=close),
                     ft.TextButton('Salvar', on_click=self.dash.action(self.save))],
        )

    def show_error(self, message):
        self.feedback.value, self.feedback.visible = message, True
        self.dash.update()

    async def save(self):
        try:
            payload = amenities_payload(self.values())
        except ValueError as exc:
            self.show_error(str(exc))
            return
        station = await self.dash.api.request('PATCH', f"stations/{self.station['id']}", {'amenities': payload})
        self.dash.page.pop_dialog()
        self.dash.notice('Comodidades atualizadas.')
        await self.on_saved(station)
