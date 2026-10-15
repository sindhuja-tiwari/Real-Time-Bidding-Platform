from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import get_settings
from app.core.tracing import tracer

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_timeout=settings.DB_POOL_TIMEOUT_SECONDS,
    pool_pre_ping=True,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        # Check the connection out up front (the first query would anyway) so
        # time spent waiting on an exhausted pool shows up as its own span.
        pool = engine.sync_engine.pool
        with tracer.start_as_current_span("db.pool.acquire") as span:
            span.set_attribute("db.pool.size", pool.size())
            span.set_attribute("db.pool.checked_out_before", pool.checkedout())
            await session.connection()
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
