"""Normalização de texto e limites de tamanho usados pelo assistente."""

from __future__ import annotations

import re
import unicodedata

UUID_PATTERN = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalized(value: object) -> str:
    """Minúsculas sem acentos e com espaços simples: 'Avenida  Paulista' -> 'avenida paulista'."""
    text = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join("".join(c for c in text if not unicodedata.combining(c)).split())


def clean(value: object, limit: int) -> str:
    """Remove caracteres de controle e corta o texto em ``limit`` caracteres."""
    text = _CONTROL.sub("", str(value or "")).strip()
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


def strip_identifiers(reply: str) -> str:
    """Respostas ao usuário não exibem UUIDs internos (os botões carregam os ids)."""
    text = UUID_PATTERN.sub("", reply)
    text = re.sub(r"\(\s*(?:id|ID)?\s*:?\s*\)", "", text)
    return re.sub(r"[ \t]{2,}", " ", text).strip()


def plain_text(reply: str) -> str:
    """O chat do app mostra texto simples: remove marcações Markdown comuns."""
    text = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), reply)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^(\s*)[*-]\s+", r"\1• ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()
