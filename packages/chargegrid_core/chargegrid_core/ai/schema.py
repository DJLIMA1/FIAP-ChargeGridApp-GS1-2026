"""Validação mínima de JSON Schema para argumentos de ferramentas.

Suporta apenas o subconjunto usado pelas ferramentas do ChargeGrid: objetos,
strings (enum, tamanho), números/inteiros (limites), booleanos e listas.
Campos desconhecidos são descartados; ``null`` em campo opcional equivale a
ausente. Modelos às vezes enviam números como texto ("2,5"); aceitamos.
"""

from __future__ import annotations

import json
import math


class ToolArgumentError(ValueError):
    """Argumentos inválidos; a mensagem é devolvida ao modelo para correção."""


class ToolDataError(RuntimeError):
    """Dado fora do escopo do usuário, inexistente ou indisponível agora.

    A fonte (API/demo) traduz seus erros de negócio (404, 403, 413, 429...) nesta
    exceção; o modelo recebe só a mensagem curta, sem detalhes internos."""


def parse_arguments(raw: object) -> dict:
    if raw is None or raw == "":
        return {}
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            value = json.loads(raw)
        except ValueError as exc:
            raise ToolArgumentError("argumentos não são um JSON válido") from exc
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
    raise ToolArgumentError("argumentos devem ser um objeto JSON")


def _number(value, spec, path):
    if isinstance(value, bool):
        raise ToolArgumentError(f"{path}: esperado número")
    if isinstance(value, str):
        try:
            value = float(value.strip().replace(",", "."))
        except ValueError as exc:
            raise ToolArgumentError(f"{path}: esperado número") from exc
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ToolArgumentError(f"{path}: esperado número")
    if spec["type"] == "integer":
        if float(value) != int(value):
            raise ToolArgumentError(f"{path}: esperado inteiro")
        value = int(value)
    if "minimum" in spec and value < spec["minimum"]:
        raise ToolArgumentError(f"{path}: mínimo {spec['minimum']}")
    if "maximum" in spec and value > spec["maximum"]:
        raise ToolArgumentError(f"{path}: máximo {spec['maximum']}")
    return value


def validate(value, spec: dict, path: str = "argumentos"):
    kind = spec.get("type")
    if kind == "object":
        if not isinstance(value, dict):
            raise ToolArgumentError(f"{path}: esperado objeto")
        properties = spec.get("properties", {})
        result = {}
        for key, item in value.items():
            if key in properties and item is not None:
                result[key] = validate(item, properties[key], f"{path}.{key}")
        missing = [key for key in spec.get("required", ()) if key not in result]
        if missing:
            raise ToolArgumentError(f"{path}: campos obrigatórios ausentes: {', '.join(missing)}")
        return result
    if kind == "string":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            raise ToolArgumentError(f"{path}: esperado texto")
        value = value.strip()
        if "enum" in spec:
            lowered = value.lower()
            match = next((option for option in spec["enum"] if option.lower() == lowered), None)
            if match is None:
                raise ToolArgumentError(f"{path}: use um de {', '.join(spec['enum'])}")
            return match
        if len(value) < spec.get("minLength", 0):
            raise ToolArgumentError(f"{path}: texto muito curto")
        if len(value) > spec.get("maxLength", 200):
            raise ToolArgumentError(f"{path}: texto muito longo")
        return value
    if kind in ("number", "integer"):
        return _number(value, spec, path)
    if kind == "boolean":
        if isinstance(value, str) and value.strip().lower() in ("true", "false", "sim", "nao", "não"):
            return value.strip().lower() in ("true", "sim")
        if not isinstance(value, bool):
            raise ToolArgumentError(f"{path}: esperado verdadeiro ou falso")
        return value
    if kind == "array":
        if not isinstance(value, list):
            value = [value]
        if len(value) > spec.get("maxItems", 10):
            raise ToolArgumentError(f"{path}: itens demais")
        return [validate(item, spec["items"], f"{path}[{index}]") for index, item in enumerate(value)]
    raise ToolArgumentError(f"{path}: tipo não suportado")
