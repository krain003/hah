from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import User

class UserRepository:
    async def create(self, session: AsyncSession, **kwargs) -> User:
        user = User(**kwargs)
        session.add(user)
        await session.flush()
        return user
    
    async def get_by_telegram_id(self, session: AsyncSession, telegram_id: int) -> Optional[User]:
        result = await session.execute(select(User).where(User.telegram_id == telegram_id))
        return result.scalar_one_or_none()

    async def update(self, session: AsyncSession, user_id: int, **kwargs):
        user = await session.get(User, user_id)
        if user:
            for key, value in kwargs.items():
                setattr(user, key, value)
            await session.flush()
        return user