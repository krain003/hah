"""
NEXUS WALLET - Database Connection Manager
Production Ready (PostgreSQL + SQLite Fallback)
"""

import os
from typing import AsyncGenerator, Optional
from contextlib import asynccontextmanager
from sqlalchemy import text
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
        
        # 1. Получаем URL базы данных
        database_url = os.getenv("DATABASE_URL")
        
        # 2. Фикс для Railway/Heroku (меняем схему драйвера)
        if database_url:
            if database_url.startswith("postgres://"):
                database_url = database_url.replace("postgres://", "postgresql+asyncpg://", 1)
            elif database_url.startswith("postgresql://"):
                database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

        # 3. Пытаемся подключиться к PostgreSQL
        if database_url and "postgresql" in database_url:
            try:
                self._engine = create_async_engine(
                    database_url,
                    echo=False,
                    pool_size=20,          # Увеличил пул для нагрузки
                    max_overflow=10,
                    pool_pre_ping=True,    # Проверка соединения перед запросом
                )
                async with self._engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                logger.info("✅ PostgreSQL connected (Production)")
            except Exception as e:
                logger.error(f"❌ PostgreSQL connection failed: {e}")
                self._engine = None

        # 4. Если PostgreSQL недоступен — падаем в SQLite (Fallback)
        if not self._engine:
            logger.warning("⚠️ Using SQLite fallback (Not recommended for Production)")
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

        # Создаём таблицы
        await self.create_tables()

        logger.info("Database initialized")
        logger.info("Using in-memory cache (Redis disabled)")

    async def create_tables(self):
        """Create all database tables if they don't exist"""
        try:
            from database.models import Base
            
            async with self._engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            
            logger.info("Database tables verified/created")
        except Exception as e:
            logger.error(f"Failed to create tables: {e}")
            # Не рейзим ошибку здесь, чтобы бот не падал в циклическую перезагрузку
            # но в продакшене это критично.

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