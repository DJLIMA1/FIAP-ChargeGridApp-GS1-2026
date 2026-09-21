from alembic import context
from sqlalchemy import create_engine
from sqlalchemy.pool import NullPool

from app import models  # noqa: F401
from app.config import settings
from app.database import SUPABASE_CA_CERT, Base

config = context.config
url = settings().migration_database_url or settings().database_url
if context.is_offline_mode():
    context.configure(url=url, target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    connect_args = {"prepare_threshold": None}
    if "sslmode=verify-full" in url:
        connect_args["sslrootcert"] = str(SUPABASE_CA_CERT)
    engine = create_engine(
        url,
        poolclass=NullPool,
        connect_args=connect_args,
    )
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=Base.metadata)
        with context.begin_transaction():
            context.run_migrations()
