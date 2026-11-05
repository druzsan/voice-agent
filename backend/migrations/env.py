import asyncio
import logging

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from voice_agent.config import Settings

# The models module defines the tables on Base's metadata
from voice_agent.db import models

# Configured here instead of an alembic.ini
logging.basicConfig(format="%(levelname)-5.5s [%(name)s] %(message)s")
logging.getLogger("alembic").setLevel(logging.INFO)

database_url = Settings().database_url.get_secret_value()


def run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=models.Base.metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline (SQL script) migrations are not supported")
asyncio.run(run_async_migrations())
