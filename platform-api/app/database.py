"""SQLAlchemy 2.0 async engine and session management."""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_settings = get_settings()


def _engine_kwargs() -> dict:
    """Build engine kwargs, omitting pool args when the driver doesn't accept them."""
    kwargs: dict = {
        "echo": _settings.environment == "development",
        "future": True,
    }
    # SQLite (used in tests) doesn't accept pool sizing options.
    if not _settings.database_url.startswith("sqlite"):
        kwargs.update(
            pool_pre_ping=True,
            pool_size=_settings.database_pool_max_size,
            max_overflow=30,
            pool_timeout=60,
        )
    return kwargs


engine = create_async_engine(_settings.database_url, **_engine_kwargs())

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with SessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            await session.commit()
