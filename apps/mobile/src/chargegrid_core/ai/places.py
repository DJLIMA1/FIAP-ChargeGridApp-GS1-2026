"""Pequeno dicionário de referências de São Paulo para buscas em linguagem natural.

Sem rede: resolve nomes conhecidos (bairros, avenidas e marcos) em coordenadas
aproximadas. Fora desta lista, a busca por texto usa nome e endereço dos postos.
"""

from __future__ import annotations

from .text import normalized

# (rótulo, latitude, longitude, apelidos normalizados)
PLACES = (
    ("Avenida Paulista", -23.5614, -46.6559, ("paulista", "av paulista", "avenida paulista", "masp")),
    ("Centro (Praça da Sé)", -23.5505, -46.6333, ("centro", "praca da se", "catedral da se", "centro de sao paulo")),
    ("Vila Mariana", -23.5895, -46.6345, ("vila mariana",)),
    ("Pinheiros", -23.5670, -46.6930, ("pinheiros", "largo da batata")),
    ("Vila Madalena", -23.5537, -46.6907, ("vila madalena",)),
    ("Itaim Bibi", -23.5846, -46.6787, ("itaim", "itaim bibi", "faria lima")),
    ("Moema", -23.6009, -46.6650, ("moema",)),
    ("Parque Ibirapuera", -23.5874, -46.6576, ("ibirapuera", "parque ibirapuera")),
    ("Brooklin", -23.6146, -46.6965, ("brooklin", "berrini")),
    ("Santana", -23.5022, -46.6253, ("santana",)),
    ("Tatuapé", -23.5404, -46.5763, ("tatuape",)),
    ("Mooca", -23.5592, -46.5999, ("mooca",)),
    ("Lapa", -23.5226, -46.7025, ("lapa",)),
    ("Butantã / USP", -23.5613, -46.7307, ("butanta", "usp", "cidade universitaria")),
    ("Morumbi", -23.6005, -46.7206, ("morumbi",)),
    ("Liberdade", -23.5587, -46.6346, ("liberdade",)),
    ("Consolação", -23.5530, -46.6600, ("consolacao", "augusta", "rua augusta")),
    ("Jardins", -23.5683, -46.6630, ("jardins", "oscar freire")),
    ("Aeroporto de Congonhas", -23.6273, -46.6566, ("congonhas", "aeroporto de congonhas")),
    ("Aeroporto de Guarulhos", -23.4356, -46.4731, ("guarulhos", "aeroporto de guarulhos", "cumbica")),
    ("FIAP Paulista", -23.5640, -46.6527, ("fiap",)),
)


def resolve_place(text: str | None) -> dict | None:
    """Retorna {'label','lat','lng'} quando o texto cita uma referência conhecida."""
    query = f" {normalized(text)} "
    if not query.strip():
        return None
    best = None
    for label, lat, lng, aliases in PLACES:
        for alias in aliases:
            if f" {alias} " in query and (best is None or len(alias) > best[0]):
                best = (len(alias), label, lat, lng)
    if best is None:
        return None
    return {"label": best[1], "lat": best[2], "lng": best[3]}
