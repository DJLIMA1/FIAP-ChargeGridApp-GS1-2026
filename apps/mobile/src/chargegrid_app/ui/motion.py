"""Short, non-blocking motion; never use animations as operation timers."""
from contextvars import ContextVar

import flet as ft

_reduced = ContextVar('chargegrid_reduced_motion', default=False)


def set_reduced(value):
    _reduced.set(bool(value))


def duration(milliseconds=220):
    return 0 if _reduced.get() else milliseconds


def animation(milliseconds=180):
    return ft.Animation(duration(milliseconds), ft.AnimationCurve.EASE_OUT_CUBIC)


def switcher(content, milliseconds=220, **kwargs):
    return ft.AnimatedSwitcher(
        content=content, duration=duration(milliseconds), reverse_duration=duration(120),
        switch_in_curve=ft.AnimationCurve.EASE_OUT_CUBIC,
        switch_out_curve=ft.AnimationCurve.EASE_IN,
        transition=ft.AnimatedSwitcherTransition.FADE, **kwargs,
    )


async def hover(event):
    control = event.control
    if not control.disabled:
        # Event tasks may have a different ContextVar context; the control keeps
        # the accessibility setting with which it was rendered.
        reduced = getattr(getattr(control, 'animate_scale', None), 'duration', duration()) == 0
        control.scale = 1.012 if not reduced and str(event.data).lower() == 'true' else 1
        control.update()
