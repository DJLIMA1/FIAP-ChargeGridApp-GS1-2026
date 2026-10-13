"""Verificação local de contratos (somente localhost; nada aqui vale para produção).

A API real valida JWT do Supabase via JWKS. Para exercitar a API local sem Supabase, ``server.py``
troca o JWKS por uma chave ES256 de teste gerada em um diretório temporário (fora do repositório),
e ``tokens.py`` assina tokens com ela. O banco precisa ser PostgreSQL local com "test" no nome.
"""
import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

KEY = Path(os.environ.get("CHARGEGRID_LIVE_KEY", Path(tempfile.gettempdir()) / "chargegrid_live_check_es256.pem"))
DB = os.environ.get("CHARGEGRID_LIVE_DATABASE_URL", "postgresql+psycopg://localhost/chargegrid_live_check_test")
ISSUER = "http://localhost.test"
PORT = int(os.environ.get("CHARGEGRID_LIVE_PORT", "8631"))
OWNER = "11111111-1111-4111-8111-111111111111"
DRIVER = "22222222-2222-4222-8222-222222222222"
RIVAL = "33333333-3333-4333-8333-333333333333"

_parsed = urlsplit(DB.replace("+psycopg", ""))
if _parsed.hostname not in (None, "", "localhost", "127.0.0.1", "::1") or "test" not in _parsed.path:
    raise SystemExit("Use somente um PostgreSQL local descartável (com 'test' no nome do banco).")


def private_key():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    if not KEY.exists():
        key = ec.generate_private_key(ec.SECP256R1())
        KEY.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        os.chmod(KEY, 0o600)
    return serialization.load_pem_private_key(KEY.read_bytes(), None)


def token(sub):
    import time

    import jwt
    now = int(time.time())
    return jwt.encode({"sub": sub, "aud": "authenticated", "iss": ISSUER + "/auth/v1", "iat": now, "exp": now + 3600},
                      private_key(), algorithm="ES256", headers={"kid": "local-test"})
