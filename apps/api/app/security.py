import hashlib
import uuid

import jwt
from fastapi import Depends, Header
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from .config import settings
from .database import db_session
from .errors import fail
from .models import Device, Profile

jwks = jwt.PyJWKClient(settings().supabase_url + "/auth/v1/.well-known/jwks.json", cache_keys=True)


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def current_user(authorization: str = Header(default=""), db=Depends(db_session)):
    if not authorization.startswith("Bearer "):
        fail("unauthorized", "Autenticação necessária", 401)
    token = authorization[7:]
    try:
        key = jwks.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["ES256", "RS256"],
            audience="authenticated",
            issuer=settings().supabase_url + "/auth/v1",
            options={"require": ["exp", "sub", "iss", "aud"]},
        )
        uid = uuid.UUID(claims["sub"])
    except jwt.PyJWKClientConnectionError:
        fail("auth_unavailable", "Autenticação temporariamente indisponível; tente novamente", 503)
    except (jwt.PyJWTError, ValueError, TypeError):
        fail("unauthorized", "Token inválido", 401)
    profile = db.get(Profile, uid)
    if profile is not None:
        return profile
    metadata = claims.get("user_metadata") or {}
    account_type = "vendor" if metadata.get("account_type") == "vendor" else "consumer"
    db.execute(
        insert(Profile)
        .values(id=uid, name=str(metadata.get("name") or "")[:100], account_type=account_type)
        .on_conflict_do_nothing()
    )
    return db.get(Profile, uid)


def current_device(authorization: str = Header(default=""), db=Depends(db_session)):
    if not authorization.startswith("Device "):
        fail("unauthorized", "Chave necessária", 401)
    device = db.scalar(
        select(Device).where(Device.key_hash == digest(authorization[7:]), Device.revoked.is_(False))
    )
    if not device:
        fail("unauthorized", "Chave inválida", 401)
    return device
