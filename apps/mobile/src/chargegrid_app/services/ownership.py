"""Strict parsing for private, single-use factory ownership credentials."""
import re
from urllib.parse import parse_qs, urlsplit

from ..api_client import ApiError

TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')


def claim_token(value):
    value = (value or '').strip()
    if TOKEN.fullmatch(value):
        return value
    try:
        uri = urlsplit(value)
        values = parse_qs(uri.query, strict_parsing=True)
        tokens = values.get('token', [])
        if (uri.scheme == 'chargegrid' and uri.netloc == 'claim'
                and not uri.path and not uri.fragment and set(values) == {'token'}
                and len(tokens) == 1 and TOKEN.fullmatch(tokens[0])):
            return tokens[0]
    except ValueError:
        pass
    raise ApiError('Use o QR de vinculação que acompanha o equipamento, não o código público de recarga.')
