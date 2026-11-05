"""The PostgreSQL customer care system, in its own test database.

Needs the dev database server (`make dev`); the tests create and migrate a
separate database next to it, so the data you test with by hand stays.
"""

import asyncio
import os
import subprocess
from collections.abc import AsyncIterator, Iterator
from datetime import date

import pytest
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine

from voice_agent.config import BACKEND_DIR, Settings
from voice_agent.crm.seed import seed
from voice_agent.crm.sql import SqlCrm

TEST_DATABASE = "voice_agent_test"
# A fixed seeding day, so dates in the assertions are known
SEED_DAY = date(2026, 11, 5)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if "tests/db/" in str(item.path):
            item.add_marker(pytest.mark.db)


async def _create_database(admin_url: str) -> None:
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            exists = await connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :name"),
                {"name": TEST_DATABASE},
            )
            if not exists:
                await connection.execute(text(f"CREATE DATABASE {TEST_DATABASE}"))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    url = make_url(Settings().database_url.get_secret_value())
    test_url = url.set(database=TEST_DATABASE).render_as_string(hide_password=False)
    asyncio.run(_create_database(url.render_as_string(hide_password=False)))
    subprocess.run(
        ["alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        env={**os.environ, "VOICE_AGENT_DATABASE_URL": test_url},
        check=True,
        capture_output=True,
    )
    yield test_url


@pytest.fixture
async def crm(database_url: str) -> AsyncIterator[SqlCrm]:
    """The system with the starting data, fresh for every test."""
    settings = Settings(database_url=database_url)  # pyright: ignore[reportArgumentType]
    await seed(settings, reset=True, today=SEED_DAY)
    engine = create_async_engine(database_url)
    try:
        yield SqlCrm(engine)
    finally:
        await engine.dispose()
