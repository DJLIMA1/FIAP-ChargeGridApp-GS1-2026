import asyncio
from types import SimpleNamespace

import flet as ft


class FakePage(SimpleNamespace):
    def __init__(self, width=1280):
        super().__init__(width=width, controls=[], dialogs=[], updates=0, web=True)

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        self.updates += 1

    def show_dialog(self, dialog):
        self.dialogs.append(dialog)

    def pop_dialog(self):
        return self.dialogs.pop() if self.dialogs else None


class MemoryPreferences:
    def __init__(self, dark=True):
        self.dark = dark

    def load(self):
        return self.dark

    def save(self, dark):
        self.dark = dark
        return True


def descendants(item):
    yield item
    content = getattr(item, 'content', None)
    if content is not None and not isinstance(content, str):
        yield from descendants(content)
    for name in ('controls', 'actions', 'items'):
        for child in getattr(item, name, None) or []:
            yield from descendants(child)
    if isinstance(item, ft.DataTable):
        for column in item.columns:
            yield from descendants(column.label)
        for row in item.rows:
            for cell in row.cells:
                yield from descendants(cell.content)


def texts(item):
    return ' '.join(str(node.value) for node in descendants(item) if isinstance(node, ft.Text) and node.value)


def clickable(item, label):
    for node in descendants(item):
        content = getattr(node, 'content', None)
        if getattr(node, 'on_click', None) and (
                (isinstance(content, ft.Text) and content.value == label) or
                (isinstance(content, str) and content == label)):
            return node.on_click
    raise LookupError(label)


async def settle(dash):
    task = dash.view_task
    if task is not None:
        await asyncio.wait_for(task, 5)
