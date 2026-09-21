"""Create a fictional station group, never equipment. Token comes from the environment."""

import argparse
import os
import sys
from urllib.parse import urlsplit

import httpx


def valid_api_url(value):
    parsed = urlsplit(value)
    return bool(
        parsed.hostname
        and parsed.scheme in ("http", "https")
        and not (parsed.username or parsed.password or parsed.query or parsed.fragment)
        and (
            parsed.scheme == "https"
            or parsed.hostname in ("localhost", "127.0.0.1", "::1")
        )
    )


def seed(client):
    me = client.get("/me")
    me.raise_for_status()
    me = me.json()
    if not me.get("operator_enabled"):
        raise ValueError(
            "Vincule primeiro um equipamento pelo QR de propriedade na conta de vendedor."
        )
    stations = []
    offset = 0
    while True:
        page = client.get("/operator/stations", params={"limit": 100, "offset": offset})
        page.raise_for_status()
        page = page.json()
        stations.extend(page["items"])
        offset += len(page["items"])
        if offset >= page["total"] or not page["items"]:
            break
    matches = [
        s
        for s in stations
        if s["owner_id"] == me["id"] and s["name"] == "ChargeGrid Demo FIAP"
    ]
    if len(matches) > 1:
        raise ValueError(
            "Há mais de um posto demo; resolva a ambiguidade antes de repetir."
        )
    if matches:
        station = matches[0]
    else:
        result = client.post(
            "/stations",
            json={
                "name": "ChargeGrid Demo FIAP",
                "address": "Endereço fictício — demonstração acadêmica",
                "latitude": -23.5505,
                "longitude": -46.6333,
            },
        )
        result.raise_for_status()
        station = result.json()
    return station["id"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url", default=os.getenv("CHARGEGRID_API_URL", "http://localhost:8000/v1")
    )
    args = parser.parse_args()
    token = os.getenv("CHARGEGRID_OPERATOR_TOKEN")
    if not token:
        parser.error(
            "Defina CHARGEGRID_OPERATOR_TOKEN com a sessão de um vendedor com ponto vinculado."
        )
    if not valid_api_url(args.api_url):
        parser.error(
            "Use HTTPS ou servidor local, sem credenciais, query ou fragmento na URL."
        )
    try:
        with httpx.Client(
            base_url=args.api_url.rstrip("/"),
            headers={"Authorization": "Bearer " + token},
            timeout=20,
        ) as client:
            station_id = seed(client)
        print(
            "Posto fictício pronto: "
            + station_id
            + ". Para adicionar equipamentos, use os QRs de fábrica; este comando não cria pontos."
        )
    except (httpx.HTTPError, ValueError, KeyError):
        print(
            "Não foi possível preparar a demonstração. Verifique API, sessão e permissão do operador.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
