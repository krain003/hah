"""
NEXUS WALLET - User Repository
"""

from typing import Optional
from datetime import datetime
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from database.models import User

logger = structlog.get_logger()


class UserRepository:
    
    async def create(
        self,
        session: AsyncSession,
        telegram_id: int,
        username: Optional[str] = None,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        language_code: str = "en",
        status: str = "active",
        pin_hash: Optional[str] = None,
        referral_code: Optional[str] = None,
        referred_by: Optional[int] = None
    ) -> User:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            status=status,
            pin_hash=pin_hash,
            referral_code=referral_code,
            referred_by=referred_by
        )
        session.add(user)
        await session.flush()
        logger.info("User created", user_id=user.id, telegram_id=telegram_id)
        return user
    
    async def get_by_id(self, session: AsyncSession, user_id: int) -> Optional[User]:
        result = await session.execute(
            select(User).where(User.id == user_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_telegram_id(self, session: AsyncSession, telegram_id: int) -> Optional[User]:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()
    
    async def get_by_referral_code(self, session: AsyncSession, code: str) -> Optional[User]:
        result = await session.execute(
            select(User).where(User.referral_code == code)
        )
        return result.scalar_one_or_none()
    
    async def update(
        self,
        session: AsyncSession,
        user_id: int,
        **kwargs
    ) -> Optional[User]:
        user = await self.get_by_id(session, user_id)
        if not user:
            return None
        for key, value in kwargs.items():
            if hasattr(user, key):
                setattr(user, key, value)
        user.updated_at = datetime.utcnow()
        await session.flush()
        return user
    
    async def update_last_active(self, session: AsyncSession, telegram_id: int) -> None:
        await session.execute(
            update(User)
            .where(User.telegram_id == telegram_id)
            .values(last_active_at=datetime.utcnow())
        )
    
    async def update_language(self, session: AsyncSession, user_id: int, language_code: str) -> Optional[User]:
        return await self.update(session, user_id, language_code=language_code)
    
    async def update_pin(self, session: AsyncSession, user_id: int, pin_hash: str) -> Optional[User]:
        return await self.update(session, user_id, pin_hash=pin_hash)