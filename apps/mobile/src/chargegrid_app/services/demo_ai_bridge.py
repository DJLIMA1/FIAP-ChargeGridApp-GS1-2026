"""Ponte da conta demo para a prévia local de IA (``demo_ai``).

``demo_ai`` fala direto com o OpenRouter e por isso é excluído do APK
(``[tool.flet.app].exclude`` em pyproject.toml). Sem ele, a demo responde que a
IA está indisponível e o chat usa as orientações locais.
"""

from ..api_client import ApiError


def _module():
    try:
        from . import demo_ai
    except ImportError:
        return None
    return demo_ai


def chat_available():
    module = _module()
    return bool(module and module.available())


async def handle(api, method, path, body):
    module = _module()
    if module is None:
        if (method, path) == ('POST', 'ai/owner-insights'):
            # Sem a prévia de IA, o dashboard demo mostra o exemplo local no mesmo contrato.
            from ..demo_owner import owner_for
            return owner_for(api).route(method, path, {}, body)
        raise ApiError('Assistente de IA indisponível nesta versão do app.', 503, 'ai_unavailable')
    return await module.handle(api, method, path, body)
