"""
NEXUS WALLET - Middleware
Request processing middleware
"""

from typing import Callable, Dict, Any, Awaitable
from datetime import datetime

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from utils.rate_limiter import RateLimiter
from config.settings import settings

logger = structlog.get_logger()


class UserMiddleware(BaseMiddleware):
    """Middleware to load user data for each request"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Get user ID from event
        user_id = None
        
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        
        if user_id:
            async with db_manager.session() as session:
                user_repo = UserRepository()
                user = await user_repo.get_by_telegram_id(session, user_id)
                
                if user:
                    # Update last active
                    user.last_active_at = datetime.utcnow()
                    await session.commit()
                    
                    data['db_user'] = user
        
        return await handler(event, data)


class RateLimitMiddleware(BaseMiddleware):
    """Middleware for rate limiting"""
    
    def __init__(self):
        self.rate_limiter = RateLimiter(
            max_requests=settings.security.RATE_LIMIT_REQUESTS,
            window_seconds=settings.security.RATE_LIMIT_WINDOW
        )
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        
        if user_id:
            is_allowed, retry_after = await self.rate_limiter.is_allowed(user_id)
            
            if not is_allowed:
                if isinstance(event, Message):
                    await event.answer(
                        f"⏳ Too many requests. Please wait {retry_after} seconds."
                    )
                elif isinstance(event, CallbackQuery):
                    await event.answer(
                        f"Too many requests. Wait {retry_after}s",
                        show_alert=True
                    )
                return
        
        return await handler(event, data)


class LoggingMiddleware(BaseMiddleware):
    """Middleware for request logging"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        start_time = datetime.utcnow()
        
        # Log incoming request
        user_id = None
        event_type = type(event).__name__
        
        if isinstance(event, Message):
            user_id = event.from_user.id
            text = event.text[:50] if event.text else "No text"
            logger.info(
                "Incoming message",
                user_id=user_id,
                text=text
            )
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
            logger.info(
                "Incoming callback",
                user_id=user_id,
                data=event.data
            )
        
        try:
            result = await handler(event, data)
            
            # Log success
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.info(
                "Request handled",
                user_id=user_id,
                event_type=event_type,
                duration=duration
            )
            
            return result
            
        except Exception as e:
            # Log error
            duration = (datetime.utcnow() - start_time).total_seconds()
            logger.error(
                "Request failed",
                user_id=user_id,
                event_type=event_type,
                duration=duration,
                error=str(e)
            )
            raise


class AdminOnlyMiddleware(BaseMiddleware):
    """Middleware to check admin access"""
    
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        
        if isinstance(event, Message):
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery):
            user_id = event.from_user.id
        
        if user_id not in settings.telegram.ADMIN_IDS:
            if isinstance(event, Message):
                await event.answer("⛔ Access denied. Admin only.")
            elif isinstance(event, CallbackQuery):
                await event.answer("Access denied", show_alert=True)
            return
        
        return await handler(event, data)