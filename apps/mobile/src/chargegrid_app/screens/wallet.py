"""Tela provisória: saldo do consumidor. O agente dono desta rota substitui o corpo de ``build``."""

from ..ui import design, theme


async def build(app, **params):
    shown = ', '.join(f'{key}={value}' for key, value in params.items()) or 'sem parâmetros'
    return design.page(
        design.txt('Em construção', 16, 'semibold'),
        design.txt(shown, 13, 'regular', theme.GRAY_TEXT),
        title='Meu saldo', on_back=app.back,
    )
