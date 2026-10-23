from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

import app.models  # noqa: F401
from app.config import get_settings
from app.db import Base

config = context.config
target_metadata = Base.metadata
SCHEMAS = ("facts", "app", "ai")


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in SCHEMAS
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        include_schemas=True,
        include_name=include_name,
        version_table_schema="public",
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.attributes.get("database_url") or get_settings().database_url
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            include_name=include_name,
            version_table_schema="public",
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
