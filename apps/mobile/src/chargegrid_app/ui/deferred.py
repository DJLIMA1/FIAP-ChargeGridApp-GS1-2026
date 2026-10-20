"""Show slow, optional content (maps) without holding the whole screen hostage.

A real map needs tile downloads that may take seconds. Screens wait only a
short moment for it; after that they render with a skeleton and swap the real
content in place when it is ready, unless the user already navigated away.
"""
import asyncio
import logging

import flet as ft

from . import motion, theme

# API real: conteúdo já pronto (mapa composto, resposta no cache) entra na primeira pintura; senão o
# esqueleto aparece logo e o conteúdo troca no lugar quando chegar (antes a tela esperava até 0,35 s).
FIRST_PAINT_WAIT = 0.05
# Demonstração (tudo calculado no aparelho, sem rede): espera o cálculo como antes.
LOCAL_FIRST_PAINT_WAIT = 0.35
_log = logging.getLogger(__name__)


def skeleton(height, label='Carregando mapa…'):
    """Neutral placeholder with the final size, so nothing jumps when it loads."""
    indicator = (ft.Icon(ft.Icons.MAP_OUTLINED, size=26, color=theme.GRAY_TEXT) if motion.duration() == 0
                 else ft.ProgressRing(width=22, height=22, stroke_width=2.5, color=theme.GRAY_TEXT))
    return ft.Semantics(
        label=label, live_region=False,
        content=ft.Container(
            ft.Column([indicator, ft.Text(label, size=12, color=theme.GRAY_TEXT)],
                      spacing=10, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            height=height, bgcolor=theme.LIGHT_GRAY, border_radius=18, alignment=ft.Alignment(0, 0),
        ),
    )


async def fill_when_ready(app, container, factory, *, placeholder, wait=None):
    """Put ``await factory()`` into ``container``; never block longer than ``wait``."""
    if wait is None:
        from ..api_cache import ResponseCache
        remote = isinstance(getattr(getattr(app, 'api', None), 'cache', None), ResponseCache)
        wait = FIRST_PAINT_WAIT if remote else LOCAL_FIRST_PAINT_WAIT
    generation = getattr(app, 'generation', None)
    task = asyncio.ensure_future(factory())
    try:
        container.content = await asyncio.wait_for(asyncio.shield(task), wait)
        return
    except TimeoutError:
        container.content = placeholder
    tasks = getattr(app, 'tasks', None)
    if isinstance(tasks, set):
        tasks.add(task)  # Navigation cancels it together with the screen.

    def finished(done):
        if isinstance(tasks, set):
            tasks.discard(done)
        if done.cancelled():
            return
        if done.exception() is not None:
            _log.warning('Conteúdo adiado falhou', exc_info=done.exception())
            return
        if getattr(app, 'closed', False) or getattr(app, 'generation', None) != generation:
            return
        container.content = done.result()
        app.page.update()

    task.add_done_callback(finished)
