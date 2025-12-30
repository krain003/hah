# bot/filters/admin.py
"""
NexusVault - Фильтр администратора
"""

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

from config.settings import settings


class IsAdminFilter(BaseFilter):
    """Фильтр для проверки администратора"""
    
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        user_id = event.from_user.id
        return user_id in settings.ADMIN_IDS