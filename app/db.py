from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from app.config import settings

_engine: AsyncEngine | None = None


def engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings().database_url,
            pool_size=10,
            max_overflow=10,
            pool_pre_ping=True,
            future=True,
        )
    return _engine


async def dispose() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


async def conn(request: Request) -> AsyncIterator[AsyncConnection]:
    async with engine().connect() as c:
        tx = await c.begin()
        request.state.tx = tx
        try:
            yield c
        except BaseException:
            if tx.is_active:
                await tx.rollback()
            raise
        if tx.is_active:
            await tx.commit()
