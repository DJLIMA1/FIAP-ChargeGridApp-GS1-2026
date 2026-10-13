"""Slot opcional para o planejador do Modo Motorista (``chargegrid_core.driver``).

Se o módulo existir e expuser uma função compatível, a ferramenta
``plan_driver_shift`` é registrada automaticamente; caso contrário, nada muda.

Contrato esperado (primeiro nome encontrado):
``plan_driver_shift(request: dict, stations: list[dict]) -> dict`` ou
``assistant_plan(request: dict, stations: list[dict]) -> dict``.
``request`` contém os argumentos validados abaixo; ``stations`` usa o formato
REST de postos. O retorno deve ser JSON simples (resumo, paradas, totais).
"""

from __future__ import annotations

import importlib

SCHEMA = {
    "type": "object",
    "properties": {
        "shift_start": {"type": "string", "maxLength": 5, "description": "Início do turno HH:MM (ex.: 07:00)."},
        "shift_end": {"type": "string", "maxLength": 5, "description": "Fim do turno HH:MM (ex.: 19:00)."},
        "current_soc_percent": {"type": "number", "minimum": 0, "maximum": 100},
        "vehicle": {"type": "string", "maxLength": 60, "description": "Modelo do carro, se citado (ex.: BYD Dolphin)."},
        "lunch_time": {"type": "string", "maxLength": 5, "description": "Horário preferido de almoço HH:MM."},
        "dinner_time": {"type": "string", "maxLength": 5, "description": "Horário preferido de jantar HH:MM."},
        "near_place": {"type": "string", "maxLength": 80, "description": "Região onde vai rodar."},
    },
}
DESCRIPTION = ("Planeja o turno de um motorista de aplicativo com carro elétrico: quando e onde recarregar "
               "evitando horários de pico e combinando com refeições. Retorna estimativas.")


def planner():
    """Função de planejamento do módulo driver, ou None se ainda não existir."""
    package = __package__.rsplit(".", 1)[0]
    try:
        module = importlib.import_module(package + ".driver")
    except ImportError:
        return None
    for name in ("plan_driver_shift", "assistant_plan"):
        function = getattr(module, name, None)
        if callable(function):
            return function
    return None
