"""Sugestões de endereço para o cadastro de estações (autocomplete), sem chave e sem custo.

- Texto livre: Photon (photon.komoot.io), geocodificador do OpenStreetMap feito para busca
  enquanto se digita (o Nominatim proíbe esse uso). Limitado ao Brasil, com viés pela posição.
- CEP (8 dígitos): ViaCEP para rua/bairro/cidade/UF; o Photon completa as coordenadas.

Timeout curto, cache em memória e falha silenciosa: sem sugestões, o formulário continua
aceitando o endereço digitado (o app ainda geocodifica ao salvar).
"""
import logging
import re
import threading
import time
import unicodedata

import httpx

PHOTON_URL = "https://photon.komoot.io/api/"
VIACEP_URL = "https://viacep.com.br/ws/{}/json/"
USER_AGENT = "ChargeGrid/1.0 (projeto academico FIAP)"
TIMEOUT_SECONDS = 2.5
TTL_SECONDS = 24 * 60 * 60
FAILURE_TTL_SECONDS = 60
MAX_RESULTS = 6
BRAZIL_BBOX = "-74.0,-34.0,-34.7,5.3"
ATTRIBUTION = "Dados © colaboradores do OpenStreetMap"

UF = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM", "bahia": "BA", "ceara": "CE",
    "distrito federal": "DF", "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso": "MT", "mato grosso do sul": "MS", "minas gerais": "MG", "para": "PA",
    "paraiba": "PB", "parana": "PR", "pernambuco": "PE", "piaui": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE", "tocantins": "TO",
}

_cache: dict[tuple, tuple[float, list | None]] = {}
_lock = threading.Lock()
log = logging.getLogger(__name__)


def _plain(value: str) -> str:
    return " ".join("".join(c for c in unicodedata.normalize("NFKD", value.casefold())
                            if not unicodedata.combining(c)).split())


def _uf(state: str | None) -> str | None:
    if not state:
        return None
    return state.upper() if len(state) == 2 else UF.get(_plain(state))


def cep_digits(query: str) -> str | None:
    digits = re.sub(r"[\s.-]", "", query)
    return digits if re.fullmatch(r"\d{8}", digits) else None


def typed_number(query: str) -> str | None:
    """Número digitado depois do nome da rua ("av paulista 1000" -> "1000"); ignora CEP."""
    match = re.search(r"(?:^|[\s,])(\d{1,6}[a-zA-Z]?)\s*(?:,|$)", query.strip())
    return match.group(1) if match and not cep_digits(query) else None


def label(item: dict) -> str:
    """Mesmo formato dos endereços já salvos: "Rua X, 123, Bairro, Cidade - UF"."""
    street = item.get("street") or item.get("name") or ""
    parts = [street, item.get("number"), item.get("district")]
    city = item.get("city")
    if city:
        parts.append(f"{city} - {item['state']}" if item.get("state") else city)
    return ", ".join(part for part in parts if part)


def _get(url: str, params: dict | None = None):
    response = httpx.get(url, params=params, timeout=TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response.json()


def _photon(query: str, lat: float | None, lng: float | None, limit: int = MAX_RESULTS) -> list[dict]:
    params = {"q": query, "limit": limit + 4, "bbox": BRAZIL_BBOX}
    if lat is not None and lng is not None:
        params.update(lat=round(lat, 2), lon=round(lng, 2))
    number = typed_number(query)
    items, seen = [], set()
    for feature in _get(PHOTON_URL, params).get("features", []):
        props, point = feature.get("properties") or {}, (feature.get("geometry") or {}).get("coordinates")
        if props.get("countrycode") != "BR" or not point or not (props.get("street") or props.get("name")):
            continue
        street = props.get("street") or props.get("name")
        item = {
            "street": street,
            "number": props.get("housenumber") or (number if props.get("osm_key") == "highway" else None),
            "district": props.get("district") or props.get("locality") or props.get("suburb"),
            "city": props.get("city") or props.get("county"),
            "state": _uf(props.get("state")),
            "postcode": props.get("postcode"),
            "latitude": round(float(point[1]), 7),
            "longitude": round(float(point[0]), 7),
        }
        if props.get("name") and props.get("street") and props["name"] != props["street"]:
            item["place"] = props["name"]  # ex.: um shopping ou posto existente no endereço
        item["label"] = label(item)
        key = _plain(item["label"])
        if key not in seen:
            seen.add(key)
            items.append(item)
        if len(items) == limit:
            break
    return items


def _viacep(cep: str) -> list[dict]:
    data = _get(VIACEP_URL.format(cep))
    if not isinstance(data, dict) or data.get("erro") or not data.get("localidade"):
        return []
    item = {"street": data.get("logradouro") or None, "number": None, "district": data.get("bairro") or None,
            "city": data["localidade"], "state": data.get("uf"), "postcode": data.get("cep"),
            "latitude": None, "longitude": None}
    # Coordenadas: o ViaCEP não informa; o Photon localiza a rua (ou a cidade, para CEP geral).
    where = ", ".join(p for p in (item["street"], item["city"], item["state"]) if p)
    try:
        found = _photon(where, None, None, limit=1)
    except (httpx.HTTPError, ValueError):
        found = []
    if found:
        item["latitude"], item["longitude"] = found[0]["latitude"], found[0]["longitude"]
    item["label"] = label(item)
    return [item]


def suggestions(query: str, lat: float | None = None, lng: float | None = None) -> tuple[list[dict], bool]:
    """Devolve ``(itens, disponível)``; ``disponível`` é False quando o provedor falhou."""
    query = " ".join(query.split())[:120]
    cep = cep_digits(query)
    if len(query) < 3 and not cep:
        return [], True
    key = (cep or _plain(query), None if cep or lat is None else round(lat, 1),
           None if cep or lng is None else round(lng, 1))
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < (TTL_SECONDS if hit[1] is not None else FAILURE_TTL_SECONDS):
            return (hit[1] or [], hit[1] is not None)
    try:
        items = _viacep(cep) if cep else _photon(query, lat, lng)
    except (httpx.HTTPError, KeyError, TypeError, ValueError) as error:
        log.info("Sugestões de endereço indisponíveis: %s", type(error).__name__)
        items = None
    with _lock:
        if len(_cache) > 1024:
            _cache.clear()
        _cache[key] = (now, items)
    return (items or [], items is not None)


def clear_cache():
    with _lock:
        _cache.clear()
