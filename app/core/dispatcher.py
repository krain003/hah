"""
NEXUS WALLET - Main Dispatcher
Central routing configuration with middleware, error handling, and lifecycle management
"""

import asyncio
from typing import Callable, Dict, Any, Awaitable
from datetime import datetime

from aiogram import Dispatcher, Bot, Router
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.fsm.strategy import FSMStrategy
from aiogram.types import Update, ErrorEvent, Message, CallbackQuery
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter
import structlog

from config.settings import settings

logger = structlog.get_logger(__name__)


# ==================== MIDDLEWARE ====================

class LoggingMiddleware:
    """Логирование всех входящих обновлений"""
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        start_time = datetime.utcnow()
        
        # Определяем тип события и user_id
        user_id = None
        event_type = "unknown"
        
        if event.message:
            user_id = event.message.from_user.id if event.message.from_user else None
            event_type = "message"
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
            event_type = "callback"
        elif event.inline_query:
            user_id = event.inline_query.from_user.id
            event_type = "inline"
        
        logger.debug(
            "Incoming update",
            update_id=event.update_id,
            event_type=event_type,
            user_id=user_id
        )
        
        try:
            result = await handler(event, data)
            
            # Логируем время обработки
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            if elapsed > 1.0:  # Предупреждение для медленных хендлеров
                logger.warning(
                    "Slow handler",
                    elapsed=f"{elapsed:.2f}s",
                    event_type=event_type,
                    user_id=user_id
                )
            
            return result
            
        except Exception as e:
            elapsed = (datetime.utcnow() - start_time).total_seconds()
            logger.error(
                "Handler error",
                error=str(e),
                event_type=event_type,
                user_id=user_id,
                elapsed=f"{elapsed:.2f}s",
                exc_info=True
            )
            raise


class ThrottlingMiddleware:
    """Защита от спама - ограничение частоты запросов"""
    
    def __init__(self, rate_limit: float = 0.5):
        self.rate_limit = rate_limit  # Минимальный интервал между сообщениями
        self.user_last_request: Dict[int, datetime] = {}
        self._cleanup_task = None
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
        
        if user_id:
            now = datetime.utcnow()
            last_request = self.user_last_request.get(user_id)
            
            if last_request:
                elapsed = (now - last_request).total_seconds()
                if elapsed < self.rate_limit:
                    # Слишком частые запросы - игнорируем (для callback отвечаем)
                    if event.callback_query:
                        try:
                            await event.callback_query.answer(
                                "⏳ Too fast! Please wait...",
                                show_alert=False
                            )
                        except Exception:
                            pass
                    logger.debug("Throttled", user_id=user_id, elapsed=elapsed)
                    return None
            
            self.user_last_request[user_id] = now
        
        return await handler(event, data)
    
    async def cleanup_old_entries(self):
        """Периодическая очистка старых записей"""
        while True:
            await asyncio.sleep(300)  # Каждые 5 минут
            now = datetime.utcnow()
            old_users = [
                uid for uid, last_time in self.user_last_request.items()
                if (now - last_time).total_seconds() > 60
            ]
            for uid in old_users:
                del self.user_last_request[uid]
            
            if old_users:
                logger.debug("Throttle cleanup", removed=len(old_users))


class MaintenanceMiddleware:
    """Блокировка во время технического обслуживания"""
    
    def __init__(self, admin_ids: list):
        self.admin_ids = admin_ids
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        # Проверяем режим обслуживания
        try:
            from utils.config_manager import config_manager
            maintenance = await config_manager.get("maintenance_mode", False)
            maintenance_reason = await config_manager.get("maintenance_reason", "")
        except ImportError:
            maintenance = False
            maintenance_reason = ""
        
        if not maintenance:
            return await handler(event, data)
        
        # Получаем user_id
        user_id = None
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
        
        # Админам разрешаем
        if user_id in self.admin_ids:
            return await handler(event, data)
        
        # Остальным показываем сообщение
        maintenance_text = f"""
🔧 <b>Technical Maintenance</b>

The bot is currently undergoing maintenance.
{f"Reason: {maintenance_reason}" if maintenance_reason else ""}

Please try again later. We apologize for the inconvenience.
"""
        
        if event.message:
            await event.message.answer(maintenance_text, parse_mode="HTML")
        elif event.callback_query:
            await event.callback_query.answer(
                "🔧 Bot is under maintenance",
                show_alert=True
            )
        
        return None


class UserActivityMiddleware:
    """Обновление времени последней активности пользователя"""
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
        
        # Обновляем активность асинхронно (не блокируем обработку)
        if user_id:
            asyncio.create_task(self._update_activity(user_id))
        
        return await handler(event, data)
    
    async def _update_activity(self, user_id: int):
        """Обновление last_active_at в фоне"""
        try:
            from database.connection import db_manager
            from database.models import User
            from sqlalchemy import update
            
            async with db_manager.session() as session:
                await session.execute(
                    update(User)
                    .where(User.telegram_id == user_id)
                    .values(last_active_at=datetime.utcnow())
                )
                await session.commit()
        except Exception as e:
            # Не критично - просто логируем
            logger.debug("Activity update failed", user_id=user_id, error=str(e))


class BanCheckMiddleware:
    """Проверка забаненных пользователей"""
    
    def __init__(self):
        self._banned_cache: Dict[int, datetime] = {}
        self._cache_ttl = 60  # Кэш на 60 секунд
    
    async def __call__(
        self,
        handler: Callable[[Update, Dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: Dict[str, Any]
    ) -> Any:
        user_id = None
        
        if event.message and event.message.from_user:
            user_id = event.message.from_user.id
        elif event.callback_query:
            user_id = event.callback_query.from_user.id
        
        if user_id and await self._is_banned(user_id):
            if event.message:
                await event.message.answer(
                    "⛔ <b>Account Suspended</b>\n\n"
                    "Your account has been suspended.\n"
                    "Please contact support if you believe this is an error.",
                    parse_mode="HTML"
                )
            elif event.callback_query:
                await event.callback_query.answer(
                    "⛔ Account suspended",
                    show_alert=True
                )
            return None
        
        return await handler(event, data)
    
    async def _is_banned(self, user_id: int) -> bool:
        """Проверка бана с кэшированием"""
        now = datetime.utcnow()
        
        # Проверяем кэш
        if user_id in self._banned_cache:
            cache_time = self._banned_cache[user_id]
            if (now - cache_time).total_seconds() < self._cache_ttl:
                return True
        
        try:
            from database.connection import db_manager
            from database.models import User, UserStatus
            from sqlalchemy import select
            
            async with db_manager.session() as session:
                user = await session.scalar(
                    select(User).where(User.telegram_id == user_id)
                )
                
                if user and user.status == UserStatus.BANNED:
                    self._banned_cache[user_id] = now
                    return True
                
                # Удаляем из кэша если разбанен
                self._banned_cache.pop(user_id, None)
                return False
                
        except Exception as e:
            logger.debug("Ban check failed", user_id=user_id, error=str(e))
            return False


# ==================== ERROR HANDLERS ====================

async def error_handler(event: ErrorEvent):
    """Глобальный обработчик ошибок"""
    exception = event.exception
    update = event.update
    
    # Определяем user_id для логирования
    user_id = None
    if update:
        if update.message and update.message.from_user:
            user_id = update.message.from_user.id
        elif update.callback_query:
            user_id = update.callback_query.from_user.id
    
    # Обрабатываем разные типы ошибок
    if isinstance(exception, TelegramRetryAfter):
        logger.warning(
            "Rate limited by Telegram",
            retry_after=exception.retry_after,
            user_id=user_id
        )
        await asyncio.sleep(exception.retry_after)
        return True
    
    if isinstance(exception, TelegramForbiddenError):
        logger.info("User blocked bot", user_id=user_id)
        return True
    
    if isinstance(exception, TelegramBadRequest):
        error_text = str(exception).lower()
        
        # Игнорируем некритичные ошибки
        if any(x in error_text for x in [
            "message is not modified",
            "query is too old",
            "message to delete not found",
            "message to edit not found"
        ]):
            return True
        
        logger.warning("Telegram API error", error=str(exception), user_id=user_id)
        return True
    
    # Логируем неизвестные ошибки
    logger.error(
        "Unhandled exception",
        error=str(exception),
        error_type=type(exception).__name__,
        user_id=user_id,
        exc_info=True
    )
    
    # Пытаемся уведомить пользователя
    try:
        error_message = (
            "❌ <b>Something went wrong</b>\n\n"
            "An error occurred while processing your request.\n"
            "Please try again or contact support if the problem persists."
        )
        
        if update and update.message:
            await update.message.answer(error_message, parse_mode="HTML")
        elif update and update.callback_query:
            await update.callback_query.answer(
                "❌ An error occurred. Please try again.",
                show_alert=True
            )
    except Exception:
        pass
    
    return True


# ==================== DISPATCHER SETUP ====================

def create_dispatcher() -> Dispatcher:
    """Создание и настройка диспетчера"""
    
    # Выбор storage (Redis для production, Memory для dev)
    if hasattr(settings, 'REDIS_URL') and settings.REDIS_URL:
        try:
            storage = RedisStorage.from_url(
                settings.REDIS_URL,
                key_builder=lambda key, chat_id, user_id: f"nexus:fsm:{chat_id}:{user_id}"
            )
            logger.info("Using Redis storage for FSM")
        except Exception as e:
            logger.warning("Redis unavailable, falling back to memory", error=str(e))
            storage = MemoryStorage()
    else:
        storage = MemoryStorage()
        logger.info("Using Memory storage for FSM")
    
    # Создаём диспетчер
    dp = Dispatcher(
        storage=storage,
        fsm_strategy=FSMStrategy.USER_IN_CHAT  # FSM привязан к user+chat
    )
    
    # ==================== РЕГИСТРАЦИЯ MIDDLEWARE ====================
    # Порядок важен! Выполняются в порядке регистрации
    
    # 1. Логирование (первое)
    dp.update.outer_middleware(LoggingMiddleware())
    
    # 2. Throttling (защита от спама)
    throttling = ThrottlingMiddleware(rate_limit=0.3)
    dp.update.outer_middleware(throttling)
    
    # 3. Maintenance mode
    dp.update.outer_middleware(MaintenanceMiddleware(admin_ids=settings.ADMIN_IDS))
    
    # 4. Ban check
    dp.update.outer_middleware(BanCheckMiddleware())
    
    # 5. User activity tracking
    dp.update.outer_middleware(UserActivityMiddleware())
    
    # ==================== РЕГИСТРАЦИЯ ERROR HANDLER ====================
    dp.errors.register(error_handler)
    
    # ==================== РЕГИСТРАЦИЯ РОУТЕРОВ ====================
    
    # Импортируем роутеры
    from handlers.admin import router as admin_router
    from handlers.admin_p2p import router as admin_p2p_router
    from handlers.admin_finance import router as admin_finance_router
    from handlers.admin_test import router as admin_test_router
    from handlers.start import router as start_router
    from handlers.wallet import router as wallet_router
    from handlers.p2p import router as p2p_router
    from handlers.shop import router as shop_router
    from handlers.buy_sell import router as buy_sell_router
    from handlers.history import router as history_router
    from handlers.swap import router as swap_router
    
    # Опциональные роутеры
    optional_routers = []
    
    try:
        from handlers.settings import router as settings_router
        optional_routers.append(("settings", settings_router))
    except ImportError:
        logger.debug("Settings router not found")
    
    try:
        from handlers.referral import router as referral_router
        optional_routers.append(("referral", referral_router))
    except ImportError:
        logger.debug("Referral router not found")
    
    try:
        from handlers.support import router as support_router
        optional_routers.append(("support", support_router))
    except ImportError:
        logger.debug("Support router not found")
    
    try:
        from handlers.notifications import router as notifications_router
        optional_routers.append(("notifications", notifications_router))
    except ImportError:
        logger.debug("Notifications router not found")
    
    # Порядок регистрации роутеров ВАЖЕН!
    # Более специфичные роутеры должны быть первыми
    
    # 1. Админка (самый высокий приоритет)
    dp.include_router(admin_router)
    dp.include_router(admin_p2p_router)
    dp.include_router(admin_finance_router)
    dp.include_router(admin_test_router)
    logger.debug("Admin routers registered")
    
    # 2. Start (обработка /start и main_menu)
    dp.include_router(start_router)
    logger.debug("Start router registered")
    
    # 3. Wallet operations
    dp.include_router(wallet_router)
    logger.debug("Wallet router registered")
    
    # 4. P2P trading
    dp.include_router(p2p_router)
    logger.debug("P2P router registered")
    
    # 5. Shop
    dp.include_router(shop_router)
    logger.debug("Shop router registered")
    
    # 6. Buy/Sell (aggregator)
    dp.include_router(buy_sell_router)
    logger.debug("Buy/Sell router registered")
    
    # 7. Swap
    dp.include_router(swap_router)
    logger.debug("Swap router registered")
    
    # 8. History
    dp.include_router(history_router)
    logger.debug("History router registered")
    
    # 9. Optional routers
    for name, router in optional_routers:
        dp.include_router(router)
        logger.debug(f"{name.capitalize()} router registered")
    
    logger.info(
        "Dispatcher configured",
        routers=8 + len(optional_routers),
        middlewares=5
    )
    
    return dp, throttling


# ==================== LIFECYCLE HOOKS ====================

async def on_startup(bot: Bot, throttling: ThrottlingMiddleware = None):
    """Действия при запуске бота"""
    logger.info("Bot starting up...")
    
    # Запускаем cleanup task для throttling
    if throttling:
        asyncio.create_task(throttling.cleanup_old_entries())
    
    # Проверяем подключение к БД
    try:
        from database.connection import db_manager
        async with db_manager.session() as session:
            await session.execute("SELECT 1")
        logger.info("Database connection OK")
    except Exception as e:
        logger.error("Database connection failed", error=str(e))
    
    # Проверяем кэш цен
    try:
        from services.price_service import price_service
        await price_service.get_price("BTC")
        logger.info("Price service OK")
    except Exception as e:
        logger.warning("Price service check failed", error=str(e))
    
    # Уведомляем админов
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "🟢 <b>Bot Started</b>\n\n"
                f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    logger.info("Bot startup complete")


async def on_shutdown(bot: Bot):
    """Действия при остановке бота"""
    logger.info("Bot shutting down...")
    
    # Уведомляем админов
    for admin_id in settings.ADMIN_IDS:
        try:
            await bot.send_message(
                admin_id,
                "🔴 <b>Bot Stopping</b>\n\n"
                f"⏰ {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                parse_mode="HTML"
            )
        except Exception:
            pass
    
    # Закрываем соединения
    try:
        from database.connection import db_manager
        await db_manager.close()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error("Error closing database", error=str(e))
    
    logger.info("Bot shutdown complete")


# ==================== СОЗДАНИЕ DISPATCHER ====================

# Создаём глобальный экземпляр
dp, _throttling = create_dispatcher()

# Регистрируем lifecycle hooks
dp.startup.register(lambda: on_startup(dp["bot"], _throttling))
dp.shutdown.register(lambda: on_shutdown(dp["bot"]))