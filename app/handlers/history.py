"""
NEXUS WALLET - Transaction History Handler
Real transaction history from database (Fixed & Standalone)
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, List
from aiogram import Router, F
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
from aiogram.fsm.context import FSMContext
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy import select, desc
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.models import Transaction, TransactionType
from blockchain.wallet_manager import NETWORKS
from locales.messages import get_text

logger = structlog.get_logger(__name__)
router = Router(name="history")

# Transaction type icons
TX_ICONS = {
    "deposit": "📥",
    "withdrawal": "📤",
    "send": "📤",
    "receive": "📥",
    "swap": "💱",
    "p2p_buy": "💰",
    "p2p_sell": "💸",
    "escrow_lock": "🔒",
    "escrow_release": "🔓",
    "direct_purchase": "💳",
    "shop_purchase": "🛍",
    "commission": "💸"
}

# Status display
STATUS_TEXT = {
    "pending": "⏳ Pending",
    "broadcasted": "📡 Broadcasted",
    "confirming": "🔄 Confirming",
    "completed": "✅ Completed",
    "failed": "❌ Failed",
    "cancelled": "🚫 Cancelled",
}

# Pagination settings
ITEMS_PER_PAGE = 10


# ==================== UTILITY FUNCTIONS ====================

async def safe_edit(message: Message, text: str, keyboard: InlineKeyboardMarkup = None) -> bool:
    """
    Безопасное редактирование сообщения.
    Обрабатывает случаи с фото/документами и ошибки Telegram.
    """
    try:
        # Если сообщение содержит медиа - удаляем и отправляем новое
        if message.photo or message.document or message.video or message.audio:
            chat_id = message.chat.id
            await message.delete()
            await message.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=keyboard,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            return True
        
        # Обычное редактирование текстового сообщения
        await message.edit_text(
            text=text,
            reply_markup=keyboard,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return True
        
    except TelegramBadRequest as e:
        error_msg = str(e).lower()
        
        # Игнорируем "message is not modified"
        if "message is not modified" in error_msg:
            return True
        
        # Сообщение удалено - отправляем новое
        if "message to edit not found" in error_msg or "message can't be edited" in error_msg:
            try:
                await message.bot.send_message(
                    chat_id=message.chat.id,
                    text=text,
                    reply_markup=keyboard,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                return True
            except Exception as send_error:
                logger.error("Failed to send new message", error=str(send_error))
                return False
        
        logger.warning("Edit failed", error=str(e))
        return False
        
    except Exception as e:
        logger.error("Unexpected edit error", error=str(e), exc_info=True)
        return False


async def safe_answer_callback(callback: CallbackQuery, text: str = None, show_alert: bool = False):
    """Безопасный ответ на callback"""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest as e:
        if "query is too old" not in str(e).lower():
            logger.warning("Callback answer failed", error=str(e))
    except Exception as e:
        logger.error("Callback answer error", error=str(e))


async def safe_delete(message: Message) -> bool:
    """Безопасное удаление сообщения"""
    try:
        await message.delete()
        return True
    except TelegramBadRequest as e:
        if "message to delete not found" not in str(e).lower():
            logger.warning("Delete failed", error=str(e))
        return False
    except Exception as e:
        logger.error("Delete error", error=str(e))
        return False


# ==================== KEYBOARD BUILDERS ====================

def get_back_keyboard(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back", callback_data=callback_data)]
    ])


def get_history_keyboard(current_filter: str = "all", page: int = 0, has_more: bool = False) -> InlineKeyboardMarkup:
    """Клавиатура фильтров истории"""
    
    def btn(text: str, filter_name: str) -> InlineKeyboardButton:
        """Создает кнопку фильтра с отметкой текущего"""
        if filter_name == current_filter:
            return InlineKeyboardButton(text=f"• {text} •", callback_data=f"history:filter:{filter_name}:0")
        return InlineKeyboardButton(text=text, callback_data=f"history:filter:{filter_name}:0")
    
    buttons = [
        [
            btn("🔄 All", "all"),
            btn("📤 Sent", "send"),
            btn("📥 Received", "receive"),
        ],
        [
            btn("💱 Swaps", "swap"),
            btn("🤝 P2P", "p2p"),
        ]
    ]
    
    # Пагинация
    pagination_row = []
    if page > 0:
        pagination_row.append(
            InlineKeyboardButton(text="◀️ Prev", callback_data=f"history:filter:{current_filter}:{page - 1}")
        )
    if has_more:
        pagination_row.append(
            InlineKeyboardButton(text="Next ▶️", callback_data=f"history:filter:{current_filter}:{page + 1}")
        )
    
    if pagination_row:
        buttons.append(pagination_row)
    
    # Кнопка возврата
    buttons.append([InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_tx_detail_keyboard(tx: Transaction) -> InlineKeyboardMarkup:
    """Клавиатура для детального просмотра транзакции"""
    buttons = []
    
    # Ссылка на эксплорер, если есть хэш
    if tx.tx_hash and tx.network:
        config = NETWORKS.get(tx.network)
        if config and hasattr(config, 'explorer_url') and config.explorer_url:
            buttons.append([
                InlineKeyboardButton(
                    text="🌐 View on Explorer",
                    url=f"{config.explorer_url}/tx/{tx.tx_hash}"
                )
            ])
    
    # Кнопки управления
    buttons.append([
        InlineKeyboardButton(text="🔙 Back to History", callback_data="history"),
        InlineKeyboardButton(text="🗑 Close", callback_data="history:close")
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ==================== FORMATTING HELPERS ====================

def format_date(dt: datetime) -> str:
    """Форматирование даты в читаемый вид"""
    if not dt:
        return "Unknown"
    
    now = datetime.utcnow()
    diff = now - dt
    
    if diff.days == 0:
        if diff.seconds < 60:
            return "just now"
        elif diff.seconds < 3600:
            mins = diff.seconds // 60
            return f"{mins}m ago"
        else:
            hours = diff.seconds // 3600
            return f"{hours}h ago"
    elif diff.days == 1:
        return "yesterday"
    elif diff.days < 7:
        return f"{diff.days}d ago"
    else:
        return dt.strftime("%d %b")


def format_address(address: str, length: int = 4) -> str:
    """Форматирование адреса для отображения"""
    if not address:
        return "Unknown"
    if len(address) <= length * 2:
        return address
    return f"{address[:length]}...{address[-length:]}"


def get_tx_type_string(tx_type) -> str:
    """Безопасное получение строки типа транзакции"""
    if hasattr(tx_type, 'value'):
        return str(tx_type.value)
    return str(tx_type)


def get_status_string(status) -> str:
    """Безопасное получение строки статуса"""
    if hasattr(status, 'value'):
        return str(status.value)
    return str(status)


def format_transaction(tx: Transaction) -> str:
    """Форматирование одной транзакции для списка"""
    tx_type_str = get_tx_type_string(tx.tx_type)
    status_str = get_status_string(tx.status)
    
    icon = TX_ICONS.get(tx_type_str, "📄")
    status = STATUS_TEXT.get(status_str, status_str.title())
    
    # Описание типа транзакции
    if tx_type_str == "send":
        type_desc = f"To {format_address(tx.to_address)}"
    elif tx_type_str == "receive":
        type_desc = f"From {format_address(tx.from_address)}"
    elif tx_type_str == "swap":
        swap_to = tx.swap_to_token if hasattr(tx, 'swap_to_token') and tx.swap_to_token else "?"
        type_desc = f"Swap → {swap_to}"
    elif tx_type_str == "withdrawal":
        type_desc = f"Withdraw to {format_address(tx.to_address)}"
    elif tx_type_str == "deposit":
        type_desc = "Deposit"
    else:
        type_desc = tx_type_str.replace("_", " ").title()
    
    # Форматирование суммы
    amount = tx.amount if tx.amount else Decimal("0")
    symbol = tx.token_symbol if tx.token_symbol else ""
    
    # Определение знака (+/-)
    outgoing_types = ["send", "withdrawal", "p2p_sell", "escrow_lock", "shop_purchase", "commission"]
    incoming_types = ["receive", "deposit", "p2p_buy", "escrow_release", "direct_purchase"]
    
    if tx_type_str in outgoing_types:
        sign = "-"
        amount_color = ""  # Можно добавить если нужно
    elif tx_type_str in incoming_types:
        sign = "+"
        amount_color = ""
    else:
        sign = ""
        amount_color = ""
    
    # Форматирование числа
    amount_formatted = f"{float(amount):.8f}".rstrip('0').rstrip('.')
    amount_str = f"{sign}{amount_formatted} {symbol}"
    
    # Время
    time_str = format_date(tx.created_at)
    
    # Иконка сети
    net_icon = ""
    if tx.network:
        config = NETWORKS.get(tx.network)
        if config and hasattr(config, 'icon'):
            net_icon = config.icon
    
    # Формируем строку
    # Используем первые 8 символов ID для команды
    tx_id_short = tx.id[:8] if tx.id else "unknown"
    
    line = f"{icon} <b>{amount_str}</b>\n"
    line += f"   {net_icon} {type_desc} • {time_str}\n"
    line += f"   {status} • /tx_{tx_id_short}"
    
    return line


def format_transaction_details(tx: Transaction) -> str:
    """Форматирование детальной информации о транзакции"""
    tx_type_str = get_tx_type_string(tx.tx_type)
    status_str = get_status_string(tx.status)
    
    # Получаем информацию о сети
    net_name = tx.network or "Unknown"
    net_icon = ""
    if tx.network:
        config = NETWORKS.get(tx.network)
        if config:
            net_name = config.name if hasattr(config, 'name') else tx.network
            net_icon = config.icon if hasattr(config, 'icon') else ""
    
    text = f"📄 <b>Transaction Details</b>\n\n"
    
    # ID и время
    text += f"🆔 ID: <code>{tx.id}</code>\n"
    if tx.created_at:
        text += f"📅 Date: {tx.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    
    # Сеть и тип
    text += f"🌐 Network: {net_icon} {net_name}\n"
    text += f"🔹 Type: <b>{tx_type_str.replace('_', ' ').upper()}</b>\n"
    text += f"📊 Status: <b>{STATUS_TEXT.get(status_str, status_str.upper())}</b>\n\n"
    
    # Сумма
    amount = tx.amount if tx.amount else Decimal("0")
    symbol = tx.token_symbol if tx.token_symbol else ""
    amount_formatted = f"{float(amount):.8f}".rstrip('0').rstrip('.')
    
    text += f"💰 Amount: <b>{amount_formatted} {symbol}</b>"
    if hasattr(tx, 'amount_usd') and tx.amount_usd:
        text += f" (~${float(tx.amount_usd):,.2f})"
    text += "\n"
    
    # Комиссия
    if hasattr(tx, 'fee_amount') and tx.fee_amount:
        fee_token = tx.fee_token if hasattr(tx, 'fee_token') and tx.fee_token else symbol
        text += f"⛽ Fee: {tx.fee_amount} {fee_token}\n"
    
    # Адреса
    if tx.from_address:
        text += f"\n📥 From: <code>{tx.from_address}</code>"
    if tx.to_address:
        text += f"\n📤 To: <code>{tx.to_address}</code>"
    
    # Хэш транзакции
    if tx.tx_hash:
        text += f"\n\n🔗 Hash:\n<code>{tx.tx_hash}</code>"
    
    # Примечание
    if hasattr(tx, 'note') and tx.note:
        text += f"\n\n📝 Note: {tx.note}"
    
    return text


# ==================== MAIN HANDLERS ====================

@router.callback_query(F.data == "history")
async def show_history(callback: CallbackQuery, state: FSMContext):
    """Показ истории транзакций"""
    await state.clear()
    
    await safe_answer_callback(callback, "📜 Loading history...")
    
    try:
        async with db_manager.session() as session:
            user_repo = UserRepository()
            user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await safe_edit(
                    callback.message,
                    "❌ User not found. Please restart the bot with /start",
                    get_back_keyboard()
                )
                return
            
            lang = user.language_code if hasattr(user, 'language_code') else "en"
            
            # Запрос транзакций
            result = await session.execute(
                select(Transaction)
                .where(Transaction.user_id == user.id)
                .order_by(desc(Transaction.created_at))
                .limit(ITEMS_PER_PAGE + 1)  # +1 для проверки наличия следующей страницы
            )
            transactions = result.scalars().all()
            
            # Проверяем есть ли ещё транзакции
            has_more = len(transactions) > ITEMS_PER_PAGE
            transactions = transactions[:ITEMS_PER_PAGE]
            
            if not transactions:
                # Пробуем получить локализованный текст
                empty_text = "📜 <b>Transaction History</b>\n\n"
                empty_text += "📭 No transactions yet.\n\n"
                empty_text += "<i>Your transaction history will appear here after you make your first transfer.</i>"
                
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="💳 Buy Crypto", callback_data="buy_crypto")],
                    [InlineKeyboardButton(text="📥 Receive", callback_data="receive")],
                    [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")]
                ])
                
                await safe_edit(callback.message, empty_text, keyboard)
                return
            
            # Формируем текст
            text = "📜 <b>Transaction History</b>\n\n"
            for tx in transactions:
                text += format_transaction(tx) + "\n\n"
            
            text += "<i>💡 Tap /tx_ID to view details</i>"
            
            keyboard = get_history_keyboard("all", 0, has_more)
            await safe_edit(callback.message, text, keyboard)
            
    except Exception as e:
        logger.error("History load error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load history. Please try again.",
            get_back_keyboard()
        )


@router.callback_query(F.data.startswith("history:filter:"))
async def filter_history(callback: CallbackQuery, state: FSMContext):
    """Фильтрация истории транзакций"""
    await state.clear()
    
    try:
        parts = callback.data.split(":")
        filter_type = parts[2]
        page = int(parts[3]) if len(parts) > 3 else 0
    except (IndexError, ValueError):
        filter_type = "all"
        page = 0
    
    await safe_answer_callback(callback)
    
    try:
        async with db_manager.session() as session:
            user_repo = UserRepository()
            user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await safe_edit(
                    callback.message,
                    "❌ User not found. Please restart the bot with /start",
                    get_back_keyboard()
                )
                return
            
            # Базовый запрос
            query = select(Transaction).where(Transaction.user_id == user.id)
            
            # Применяем фильтры
            if filter_type == "send":
                query = query.where(
                    Transaction.tx_type.in_([TransactionType.SEND, TransactionType.WITHDRAWAL])
                )
            elif filter_type == "receive":
                query = query.where(
                    Transaction.tx_type.in_([TransactionType.RECEIVE, TransactionType.DEPOSIT])
                )
            elif filter_type == "swap":
                query = query.where(Transaction.tx_type == TransactionType.SWAP)
            elif filter_type == "p2p":
                query = query.where(
                    Transaction.tx_type.in_([TransactionType.P2P_BUY, TransactionType.P2P_SELL])
                )
            # "all" - без дополнительных фильтров
            
            # Сортировка и пагинация
            query = query.order_by(desc(Transaction.created_at))
            query = query.offset(page * ITEMS_PER_PAGE).limit(ITEMS_PER_PAGE + 1)
            
            result = await session.execute(query)
            transactions = result.scalars().all()
            
            # Проверка наличия следующей страницы
            has_more = len(transactions) > ITEMS_PER_PAGE
            transactions = transactions[:ITEMS_PER_PAGE]
            
            # Заголовки для разных фильтров
            titles = {
                "all": "📜 <b>All Transactions</b>",
                "send": "📤 <b>Sent Transactions</b>",
                "receive": "📥 <b>Received Transactions</b>",
                "swap": "💱 <b>Swap History</b>",
                "p2p": "🤝 <b>P2P Trades</b>",
            }
            title = titles.get(filter_type, "📜 <b>History</b>")
            
            if not transactions:
                text = f"{title}\n\n"
                text += "📭 No transactions found for this filter.\n\n"
                text += "<i>Try a different filter or make some transactions first!</i>"
            else:
                text = f"{title}\n"
                if page > 0:
                    text += f"<i>Page {page + 1}</i>\n"
                text += "\n"
                
                for tx in transactions:
                    text += format_transaction(tx) + "\n\n"
                
                text += "<i>💡 Tap /tx_ID to view details</i>"
            
            keyboard = get_history_keyboard(filter_type, page, has_more)
            await safe_edit(callback.message, text, keyboard)
            
    except Exception as e:
        logger.error("Filter history error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to filter history. Please try again.",
            get_back_keyboard("history")
        )


# ==================== TRANSACTION DETAILS ====================

@router.message(F.text.regexp(r"^/tx_[a-zA-Z0-9]+$"))
async def show_transaction_details_command(message: Message, state: FSMContext):
    """Обработка команды /tx_ID для просмотра деталей транзакции"""
    await state.clear()
    
    try:
        # Извлекаем короткий ID
        tx_id_short = message.text.split("_")[1]
    except IndexError:
        await message.answer("❌ Invalid transaction ID format.")
        return
    
    if len(tx_id_short) < 4:
        await message.answer("❌ Transaction ID is too short.")
        return
    
    try:
        async with db_manager.session() as session:
            user_repo = UserRepository()
            user = await user_repo.get_by_telegram_id(session, message.from_user.id)
            
            if not user:
                await message.answer(
                    "❌ User not found. Please restart the bot with /start",
                    reply_markup=get_back_keyboard()
                )
                return
            
            # Поиск транзакции по частичному ID
            result = await session.execute(
                select(Transaction)
                .where(
                    Transaction.user_id == user.id,
                    Transaction.id.like(f"{tx_id_short}%")
                )
                .limit(1)
            )
            tx = result.scalar_one_or_none()
            
            if not tx:
                await message.answer(
                    "❌ Transaction not found.\n\n"
                    "<i>Make sure you're using the correct ID and that this is your transaction.</i>",
                    parse_mode="HTML",
                    reply_markup=get_back_keyboard("history")
                )
                return
            
            text = format_transaction_details(tx)
            keyboard = get_tx_detail_keyboard(tx)
            
            await message.answer(text, reply_markup=keyboard, parse_mode="HTML")
            
    except Exception as e:
        logger.error("Transaction details error", error=str(e), tx_id=tx_id_short, exc_info=True)
        await message.answer(
            "❌ Failed to load transaction details. Please try again.",
            reply_markup=get_back_keyboard("history")
        )


@router.callback_query(F.data.startswith("history:tx:"))
async def show_transaction_details_callback(callback: CallbackQuery, state: FSMContext):
    """Показ деталей транзакции через callback"""
    await state.clear()
    
    try:
        tx_id_short = callback.data.split(":")[2]
    except IndexError:
        await safe_answer_callback(callback, "❌ Invalid transaction", show_alert=True)
        return
    
    await safe_answer_callback(callback, "📄 Loading details...")
    
    try:
        async with db_manager.session() as session:
            user_repo = UserRepository()
            user = await user_repo.get_by_telegram_id(session, callback.from_user.id)
            
            if not user:
                await safe_edit(
                    callback.message,
                    "❌ User not found.",
                    get_back_keyboard("history")
                )
                return
            
            result = await session.execute(
                select(Transaction)
                .where(
                    Transaction.user_id == user.id,
                    Transaction.id.like(f"{tx_id_short}%")
                )
                .limit(1)
            )
            tx = result.scalar_one_or_none()
            
            if not tx:
                await safe_edit(
                    callback.message,
                    "❌ Transaction not found.",
                    get_back_keyboard("history")
                )
                return
            
            text = format_transaction_details(tx)
            keyboard = get_tx_detail_keyboard(tx)
            
            await safe_edit(callback.message, text, keyboard)
            
    except Exception as e:
        logger.error("Transaction details callback error", error=str(e), exc_info=True)
        await safe_edit(
            callback.message,
            "❌ Failed to load details.",
            get_back_keyboard("history")
        )


# ==================== UTILITY HANDLERS ====================

@router.callback_query(F.data == "history:close")
async def close_history_message(callback: CallbackQuery):
    """Закрытие сообщения с деталями транзакции"""
    await safe_delete(callback.message)
    await safe_answer_callback(callback)


@router.callback_query(F.data == "history:refresh")
async def refresh_history(callback: CallbackQuery, state: FSMContext):
    """Обновление истории"""
    await show_history(callback, state)


# ==================== FALLBACK HANDLER ====================

@router.callback_query(F.data.startswith("history:"))
async def history_fallback(callback: CallbackQuery, state: FSMContext):
    """Fallback для необработанных history: callbacks"""
    logger.warning("Unhandled history callback", data=callback.data)
    await show_history(callback, state)