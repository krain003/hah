"""
NEXUS WALLET - User Repository
Handles all database operations for User model
"""

from typing import Optional, List, Dict, Any
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User
from datetime import datetime

class UserRepository:
    
    async def get_by_id(self, session: AsyncSession, user_id: int) -> Optional[User]:
        """Get user by internal ID"""
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_telegram_id(self, session: AsyncSession, telegram_id: int) -> Optional[User]:
        """Get user by Telegram ID (Crucial for Bot)"""
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, session: AsyncSession, username: str) -> Optional[User]:
        """Get user by username"""
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def get_by_referral_code(self, session: AsyncSession, code: str) -> Optional[User]:
        """Get user by referral code"""
        result = await session.execute(select(User).where(User.referral_code == code))
        return result.scalar_one_or_none()

    async def create(
        self, 
        session: AsyncSession, 
        telegram_id: int, 
        username: str = None, 
        first_name: str = None, 
        last_name: str = None, 
        language_code: str = "en", 
        pin_hash: str = None, 
        referral_code: str = None,
        referred_by: int = None
    ) -> User:
        """Create a new user"""
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            language_code=language_code,
            pin_hash=pin_hash,
            referral_code=referral_code,
            referred_by=referred_by
        )
        session.add(user)
        await session.flush()
        return user

    async def update_last_login(self, session: AsyncSession, user_id: int):
        """Update last login timestamp"""
        await session.execute(
            update(User).where(User.id == user_id).values(last_login=datetime.utcnow())
        )

    async def update_language(self, session: AsyncSession, user_id: int, lang_code: str):
        """Update user interface language"""
        await session.execute(
            update(User).where(User.id == user_id).values(language_code=lang_code)
        )

    async def update_pin(self, session: AsyncSession, user_id: int, new_pin_hash: str):
        """Update security PIN"""
        await session.execute(
            update(User).where(User.id == user_id).values(pin_hash=new_pin_hash)
        )

    async def increment_volume(self, session: AsyncSession, user_id: int, volume_usd: float):
        """Increment total trading volume"""
        await session.execute(
            update(User).where(User.id == user_id).values(
                total_volume_usd=User.total_volume_usd + volume_usd
            )
        )

    async def update(self, session: AsyncSession, user_id: int, **kwargs):
        """Generic update method"""
        if kwargs:
            await session.execute(
                update(User).where(User.id == user_id).values(**kwargs)
            )