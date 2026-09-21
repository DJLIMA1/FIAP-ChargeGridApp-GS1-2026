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
engine = create_engine(database_url, poolclass=NullPool, connect_args=connect_args)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def db_session():
    with SessionLocal() as db:
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
