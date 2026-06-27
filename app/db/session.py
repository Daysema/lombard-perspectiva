from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.db.models import Base

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=10,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_SCHEMA_PATCHES = (
    "ALTER TABLE products ADD COLUMN IF NOT EXISTS removal_reason VARCHAR(16)",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS sold_count INTEGER DEFAULT 0",
    "ALTER TABLE scan_runs ADD COLUMN IF NOT EXISTS delisted_count INTEGER DEFAULT 0",
)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        for patch in _SCHEMA_PATCHES:
            await conn.execute(text(patch))


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session() as session:
        yield session
