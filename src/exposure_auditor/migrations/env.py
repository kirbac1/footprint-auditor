import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from exposure_auditor.models import Base

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if not url:
        from exposure_auditor.config import get_settings

        url = get_settings().database_url
    return url


def run_offline() -> None:
    url = _url()
    context.configure(
        url=url, target_metadata=target_metadata, literal_binds=True, render_as_batch=url.startswith("sqlite")
    )
    with context.begin_transaction():
        context.run_migrations()


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        # SQLite can't ALTER most things in place; batch mode rebuilds the table.
        render_as_batch=connection.dialect.name == "sqlite",
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_online() -> None:
    engine = create_async_engine(_url())
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    run_offline()
else:
    asyncio.run(run_online())
