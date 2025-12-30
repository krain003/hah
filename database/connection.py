"""
NEXUS WALLET - Database Connection Manager
"""
import os
from typing import AsyncGenerator
from contextlib import asynccontextmanager
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

logger = structlog.get_logger(__name__)

class DatabaseManager:
    def __init__(self):
        self._engine = None
        self._session_factory = None

    @property
    def engine(self):
        return self._engine

    async def initialize(self):
        # Используем SQLite по умолчанию
        sqlite_path = "sqlite+aiosqlite:///./nexus_wallet.db"
        self._engine = create_async_engine(sqlite_path, echo=False)
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )
        logger.info("Using SQLite database: nexus_wallet.db")

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
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

    async def close(self):
        if self._engine:
            await self._engine.dispose()
        logger.info("Database connections closed")

db_manager = DatabaseManager()