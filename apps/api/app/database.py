import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import NullPool

from .config import settings

SUPABASE_CA_CERT = Path(__file__).resolve().parents[1] / "certs/supabase-prod-ca-2021.crt"


class Base(DeclarativeBase):
    pass


database_url = settings().database_url
connect_args = {"prepare_threshold": None}
if "sslmode=verify-full" in database_url:
    connect_args["sslrootcert"] = str(SUPABASE_CA_CERT)


def engine_options():
    """Padrão: ``NullPool`` (uma conexão nova por pedido, como sempre foi).

    ``DB_POOL_SIZE`` > 0 liga um pool pequeno por instância da função: o pedido seguinte reaproveita a
    conexão TLS já autenticada no pooler do Supabase (porta 6543, modo transação; ``prepare_threshold``
    continua desligado), com ``pre_ping`` para descartar conexões que o pooler fechou enquanto a
    instância estava parada."""
    try:
        size = int(os.getenv("DB_POOL_SIZE") or 0)
    except ValueError:
        size = 0
    if size <= 0:
        return {"poolclass": NullPool}
    return {"pool_size": size, "max_overflow": 2, "pool_pre_ping": True, "pool_recycle": 300, "pool_timeout": 10}


engine = create_engine(database_url, connect_args=connect_args, **engine_options())
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def db_session():
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
