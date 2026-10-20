"""Autocomplete de endereço para o cadastro/edição de estações.

As sugestões vêm da própria API (``GET geo/address-suggestions``: Photon/OpenStreetMap e ViaCEP,
sem chave). Espera ~350 ms sem digitação antes de consultar e descarta respostas atrasadas. Sem
rede ou sem resultado, a lista some e o campo segue aceitando o texto digitado.
"""
import asyncio

import flet as ft

from ..api_client import ApiError
from . import design, theme

DEBOUNCE_SECONDS = 0.35
MAX_ROWS = 5


def _title_and_detail(item):
    street = ', '.join(part for part in (item.get('street'), item.get('number')) if part)
    title = item.get('place') or street or item.get('label') or ''
    rest = [street] if item.get('place') and street else []
    rest += [part for part in (item.get('district'),) if part]
    if item.get('city'):
        rest.append(f"{item['city']} - {item['state']}" if item.get('state') else item['city'])
    if item.get('postcode'):
        rest.append(f"CEP {item['postcode']}")
    return title, ', '.join(rest)


def attach(app, field, on_pick=None):
    """Liga o autocomplete a ``field`` e devolve o painel de sugestões (colocar logo abaixo do campo).

    ``on_pick(item)`` (síncrona ou assíncrona) recebe a sugestão escolhida, já com ``label``,
    ``latitude`` e ``longitude`` (estas podem ser ``None`` para um CEP sem coordenadas).
    """
    rows = ft.Column(spacing=0)
    note = design.txt('', 9.5, 'regular', theme.GRAY_TEXT)
    panel = ft.Container(ft.Column([rows, ft.Container(note, padding=ft.Padding(left=12, right=12, top=6, bottom=8))],
                                   spacing=0),
                         bgcolor=theme.CARD, border_radius=design.RADIUS_BTN, border=ft.Border.all(1, theme.BORDER_SOFT),
                         visible=False, data='address-suggestions')
    state = {'task': None, 'picked': None, 'query': None}
    previous_change = field.on_change

    def hide():
        panel.visible = False
        rows.controls = []

    def choose(item):
        async def handler(event=None):
            state['picked'] = field.value = item['label']
            field.error_text = None
            hide()
            if on_pick:
                result = on_pick(item)
                if asyncio.iscoroutine(result):
                    await result
            app.page.update()
        return handler

    def draw(items, attribution):
        rows.controls = []
        for index, item in enumerate(items[:MAX_ROWS]):
            title, detail = _title_and_detail(item)
            rows.controls.append(ft.Container(
                ft.Row([ft.Icon(ft.Icons.PLACE_OUTLINED, size=18, color=theme.GRAY_TEXT),
                        ft.Column([design.txt(title, 12.5, 'semibold', max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                   design.txt(detail, 10.5, 'regular', theme.GRAY_TEXT, max_lines=2,
                                              overflow=ft.TextOverflow.ELLIPSIS)],
                                  spacing=1, expand=True)],
                       spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding(left=12, right=12, top=9, bottom=9), on_click=choose(item), ink=True,
                border=ft.Border(top=ft.BorderSide(1, theme.BORDER_SOFT)) if index else None,
                data='address-suggestion'))
        note.value = attribution or ''
        panel.visible = bool(rows.controls)

    async def lookup(query):
        await asyncio.sleep(DEBOUNCE_SECONDS)
        try:
            result = await app.api.request('GET', 'geo/address-suggestions', params={'q': query}) or {}
        except ApiError:
            result = {}
        if state['query'] != query or (field.value or '').strip() != query:
            return  # o usuário continuou digitando: resposta antiga
        draw(result.get('items') or [], result.get('attribution'))
        app.page.update()

    async def changed(event=None):
        if previous_change:
            outcome = previous_change(event)
            if asyncio.iscoroutine(outcome):
                await outcome
        query = (field.value or '').strip()
        if state['task'] and not state['task'].done():
            state['task'].cancel()
        state['query'] = query
        if len(query) < 3 or query == state['picked']:
            if panel.visible:
                hide()
                app.page.update()
            return
        state['task'] = asyncio.create_task(lookup(query))

    field.on_change = changed
    panel.lookup = lookup  # testes chamam a consulta sem esperar o debounce real
    return panel
