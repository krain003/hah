"""
NEXUS WALLET - Maintenance Middleware
Blocks non-admin users during maintenance mode
"""

from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, Update
import structlog

from config.settings import settings
from utils.config_manager import config_manager

logger = structlog.get_logger()


class MaintenanceMiddleware(BaseMiddleware):
    """
    Middleware that blocks user interactions during maintenance mode.
    Admins are always allowed through.
    """
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        # Get user from event
        user = None
        if isinstance(event, Message):
            user = event.from_user
        elif isinstance(event, CallbackQuery):
            user = event.from_user
        elif hasattr(event, 'message') and event.message:
            user = event.message.from_user
        
        # No user = let it pass (system events)
        if not user:
            return await handler(event, data)
        
        # Admins always pass
        if user.id in settings.ADMIN_IDS:
            return await handler(event, data)
        
        # Check maintenance mode
        is_maintenance = await config_manager.is_maintenance()
        
        if is_maintenance:
            reason = await config_manager.get("maintenance_reason", "System maintenance in progress")
            
            maintenance_text = f"""
🔧 <b>Maintenance Mode</b>

NEXUS WALLET is currently undergoing maintenance.

<b>Reason:</b> {reason}

Please try again later. We apologize for the inconvenience.
"""
            
            if isinstance(event, Message):
                await event.answer(maintenance_text, parse_mode="HTML")
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "🔧 Bot is in maintenance mode. Please try again later.",
                    show_alert=True
                )
            
            return  # Block the request
        
        # All good, proceed
        return await handler(event, data)