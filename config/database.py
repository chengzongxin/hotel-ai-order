from sqlalchemy import DateTime, MetaData, String, Table, Text, func
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.sql.schema import Column

from config.settings import settings

metadata = MetaData()

conversation_logs = Table(
    "conversation_logs",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("session_id", String(128), nullable=False, index=True),
    Column("role", String(32), nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

engine: AsyncEngine = create_async_engine(
    settings.database_url,
    echo=settings.app_env == "local",
    pool_pre_ping=True,
)


async def init_database() -> None:
    if not settings.postgres_enabled:
        return

    async with engine.begin() as conn:
        await conn.run_sync(metadata.create_all)


async def close_database() -> None:
    if not settings.postgres_enabled:
        return

    await engine.dispose()
