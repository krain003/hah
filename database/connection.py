"""
NEXUS WALLET - Database Connection Manager
Works without PostgreSQL or Redis (uses SQLite + Memory)
"""

import os
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
import structlog

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

logger = structlog.get_logger()


class DatabaseManager:
    def __init__(self):
        self._engine = None
        self._session_factory = None
        self._cache = {}

    @property
    def engine(self):
        """Public access to engine"""
        return self._engine

    async def initialize(self):
        """Initialize database connections"""
        postgres_url = os.getenv("DATABASE_URL")

        if postgres_url:
            try:
                self._engine = create_async_engine(
                    postgres_url,
                    echo=False,
                    pool_size=5,
                    max_overflow=10,
                )
                async with self._engine.begin() as conn:
                    await conn.execute("SELECT 1")
                logger.info("PostgreSQL connected")
            except Exception as e:
                logger.warning(f"PostgreSQL failed: {e}")
                self._engine = None

        if not self._engine:
            sqlite_path = "sqlite+aiosqlite:///./nexus_wallet.db"
            self._engine = create_async_engine(
                sqlite_path,
                echo=False,
            )
            logger.info("Using SQLite database: nexus_wallet.db")

        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        logger.info("Database initialized")
        logger.info("Using in-memory cache (Redis disabled)")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get database session"""
        if not self._session_factory:
            raise RuntimeError("Database not initialized")

        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def cache_get(self, key: str) -> Optional[str]:
        return self._cache.get(key)

    async def cache_set(self, key: str, value: str, expire: int = 3600) -> None:
        self._cache[key] = value

    async def cache_delete(self, key: str) -> None:
        self._cache.pop(key, None)

    @property
    def redis(self):
        return None

    @property
    def redis_available(self) -> bool:
        return False

    async def close(self):
        """Close connections"""
        if self._engine:
            await self._engine.dispose()
        self._cache.clear()
        logger.info("Database connections closed")


db_manager = DatabaseManager()