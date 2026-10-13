import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import DB, ISSUER, PORT, private_key  # noqa: E402

os.environ["DATABASE_URL"] = DB
os.environ["SUPABASE_URL"] = ISSUER
os.environ.setdefault("AI_ENABLED", "false")
API = sys.argv[1]
sys.path.insert(0, API)
os.chdir(API)

import uvicorn  # noqa: E402
from app import security  # noqa: E402
from app.main import app  # noqa: E402


class LocalKey:
    def __init__(self, key):
        self.key = key


class LocalJwks:
    def get_signing_key_from_jwt(self, token):
        return LocalKey(private_key().public_key())


security.jwks = LocalJwks()
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
