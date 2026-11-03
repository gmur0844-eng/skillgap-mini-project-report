"""Alembic environment: URL from the validated application settings (DATABASE_URL), metadata from app.models."""
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registers every table on Base.metadata)
from app.core.config import get_settings
from app.db.session import Base

config = context.config
if config.config_file_name is not None:
    # keep the application's loggers (the JSON access log): migrations run inside a live process too
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata
URL = get_settings().database_url


def run_migrations_offline():
    context.configure(url=URL, target_metadata=target_metadata, literal_binds=True,
                      dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    engine = create_engine(URL, poolclass=pool.NullPool, future=True)
    with engine.connect() as connection:
        # the knowledge schema is managed by migration 0002 (raw SQL), not by the ORM metadata
        context.configure(connection=connection, target_metadata=target_metadata,
                          include_object=lambda obj, name, type_, reflected, compare_to:
                          not (type_ == "table" and getattr(obj, "schema", None) == "knowledge"),
                          include_schemas=False)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
