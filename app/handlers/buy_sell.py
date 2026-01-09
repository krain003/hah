"""
NEXUS WALLET - Buy/Sell Handler (Redirect Version - Fixed)
Перенаправление на биржи с реферальными ссылками
"""

from aiogram import Router, F
from aiogram.types import (
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Message
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
from decimal import Decimal
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from services.exchange_redirect_service import exchange_service
from services.price_service import price_service

logger = structlog.get_logger(__name__)
router = Router(name="buy_sell")


SUPPORTED_CRYPTOS = [
    {"symbol": "BTC", "name": "Bitcoin", "icon": "₿"},
    {"symbol": "ETH", "name": "Ethereum", "icon": "⟠"},
    {"symbol": "BNB", "name": "BNB", "icon": "💛"},
    {"symbol": "SOL", "name": "Solana", "icon": "◎"},
    {"symbol": "TON", "name": "TON", "icon": "💎"},
    {"symbol": "USDT", "name": "Tether", "icon": "💵"},
    {"symbol": "TRX", "name": "TRON", "icon": "🔴"},
]

SUPPORTED_FIATS = ["USD", "EUR", "RUB", "UAH", "KZT", "TRY", "GBP"]


class BuyStates(StatesGroup):
    select_crypto = State()
    select_fiat = State()
    enter_amount = State()


# ==================== KEYBOARDS ====================

def get_buy_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню покупки/продажи"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💰 Buy Crypto", callback_data="buy:start"),
            InlineKeyboardButton(text="💸 Sell Crypto", callback_data="sell:start")
        ],
        [
            InlineKeyboardButton(text="🤝 P2P Trading", callback_data="p2p"),
            InlineKeyboardButton(text="📊 Prices", callback_data="buy:prices")
        ],
        [
            InlineKeyboardButton(text="📋 Exchange List", callback_data="buy:exchanges")
        ],
        [
            InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")
        ]
    ])


def get_crypto_keyboard(callback_prefix: str = "buy:crypto") -> InlineKeyboardMarkup:
    """Клавиатура выбора криптовалюты"""
    buttons = []
    row = []
    
    for crypto in SUPPORTED_CRYPTOS:
        row.append(InlineKeyboardButton(
            text=f"{crypto['icon']} {crypto['symbol']}",
            callback_data=f"{callback_prefix}:{crypto['symbol']}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Cancel возвращает в меню покупки
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="buy:back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_fiat_keyboard(callback_prefix: str = "buy:fiat") -> InlineKeyboardMarkup:
    """Клавиатура выбора фиатной валюты"""
    buttons = []
    row = []
    
    symbols = {"USD": "$", "EUR": "€", "RUB": "₽", "UAH": "₴", "KZT": "₸", "TRY": "₺", "GBP": "£"}
    
    for fiat in SUPPORTED_FIATS:
        row.append(InlineKeyboardButton(
            text=f"{symbols.get(fiat, '')} {fiat}",
            callback_data=f"{callback_prefix}:{fiat}"
        ))
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Cancel возвращает в меню покупки
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="buy:back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_cancel_keyboard() -> InlineKeyboardMarkup:
    """Клавиатура с кнопкой отмены"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Cancel", callback_data="buy:back_to_menu")]
    ])


# ==================== UTILITY ====================

async def safe_edit(message: Message, text: str, keyboard: InlineKeyboardMarkup = None) -> bool:
    """
    Безопасное редактирование сообщения.
    Обрабатывает случаи с фото/документами и ошибки Telegram.
    
    Returns:
        bool: True если успешно, False если была ошибка
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
        
        # Игнорируем "message is not modified" - это не ошибка
        if "message is not modified" in error_msg:
            return True
        
        # Сообщение удалено - пробуем отправить новое
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
    """Безопасный ответ на callback с обработкой ошибок"""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except TelegramBadRequest as e:
        if "query is too old" not in str(e).lower():
            logger.warning("Callback answer failed", error=str(e))
    except Exception as e:
        logger.error("Callback answer error", error=str(e))


# ==================== MAIN MENU ====================

@router.callback_query(F.data == "buy_crypto")
async def buy_crypto_entry(callback: CallbackQuery, state: FSMContext):
    """Точка входа из главного меню - buy_crypto"""
    await _show_buy_menu(callback, state)


@router.callback_query(F.data == "buy:back_to_menu")
async def buy_back_to_menu(callback: CallbackQuery, state: FSMContext):
    """Возврат в меню покупки (Cancel buttons)"""
    await _show_buy_menu(callback, state)


async def _show_buy_menu(callback: CallbackQuery, state: FSMContext):
    """
    Внутренняя функция показа меню покупки.
    Сбрасывает состояние и показывает главное меню Buy/Sell.
    """
    # Сбрасываем любые активные состояния
    await state.clear()
    
    text = """
💳 <b>Buy & Sell Crypto</b>

Purchase crypto instantly through trusted exchanges.
We'll help you find the best rates!

<b>Options:</b>
├ 💰 <b>Buy Crypto</b> - via card or bank
├ 💸 <b>Sell Crypto</b> - get fiat to your bank
├ 🤝 <b>P2P Trading</b> - trade with other users
└ 📋 <b>Exchanges</b> - browse all options

<i>💡 Tip: P2P usually has the best rates!</i>
"""
    
    await safe_edit(callback.message, text, get_buy_menu_keyboard())
    await safe_answer_callback(callback)


# ==================== BUY FLOW ====================

@router.callback_query(F.data == "buy:start")
async def buy_select_crypto(callback: CallbackQuery, state: FSMContext):
    """Шаг 1: Выбор криптовалюты для покупки"""
    # Очищаем предыдущие данные
    await state.clear()
    
    text = """
💰 <b>Buy Crypto</b>

Select the cryptocurrency you want to buy:
"""
    
    await safe_edit(callback.message, text, get_crypto_keyboard("buy:crypto"))
    await state.set_state(BuyStates.select_crypto)
    await safe_answer_callback(callback)


@router.callback_query(BuyStates.select_crypto, F.data.startswith("buy:crypto:"))
async def buy_select_fiat(callback: CallbackQuery, state: FSMContext):
    """Шаг 2: Выбор фиатной валюты"""
    crypto = callback.data.split(":")[2]
    
    # Валидация выбранной криптовалюты
    if not any(c['symbol'] == crypto for c in SUPPORTED_CRYPTOS):
        await safe_answer_callback(callback, "❌ Invalid cryptocurrency", show_alert=True)
        return
    
    # Получаем текущую цену
    try:
        price = await price_service.get_price(crypto)
    except Exception as e:
        logger.error("Price fetch error", crypto=crypto, error=str(e))
        price = Decimal("0")
    
    await state.update_data(crypto=crypto, price=str(price))
    
    crypto_info = next((c for c in SUPPORTED_CRYPTOS if c['symbol'] == crypto), {})
    
    price_display = f"${float(price):,.2f}" if price > 0 else "Loading..."
    
    text = f"""
💰 <b>Buy {crypto_info.get('icon', '')} {crypto}</b>

Current price: <b>{price_display}</b>

Select your payment currency:
"""
    
    await safe_edit(callback.message, text, get_fiat_keyboard("buy:fiat"))
    await state.set_state(BuyStates.select_fiat)
    await safe_answer_callback(callback)


@router.callback_query(BuyStates.select_fiat, F.data.startswith("buy:fiat:"))
async def buy_show_exchanges(callback: CallbackQuery, state: FSMContext):
    """Шаг 3: Показ доступных бирж"""
    fiat = callback.data.split(":")[2]
    
    # Валидация фиата
    if fiat not in SUPPORTED_FIATS:
        await safe_answer_callback(callback, "❌ Invalid currency", show_alert=True)
        return
    
    data = await state.get_data()
    crypto = data.get('crypto')
    
    if not crypto:
        # Данные потеряны - возвращаем в начало
        await buy_select_crypto(callback, state)
        return
    
    try:
        price = Decimal(data.get('price', '0'))
    except:
        price = Decimal("0")
    
    await state.update_data(fiat=fiat)
    
    # Получаем подходящие биржи
    try:
        exchanges = exchange_service.get_best_exchanges_for_buy(
            crypto=crypto,
            fiat=fiat,
            amount_usd=100
        )
    except Exception as e:
        logger.error("Exchange service error", error=str(e))
        exchanges = []
    
    crypto_info = next((c for c in SUPPORTED_CRYPTOS if c['symbol'] == crypto), {})
    
    if not exchanges:
        text = f"""
❌ <b>No Exchanges Available</b>

Sorry, no exchanges currently support {crypto}/{fiat}.

Try:
• Different currency
• P2P Trading (usually works everywhere!)
"""
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🤝 Try P2P", callback_data="p2p:buy")],
            [InlineKeyboardButton(text="🔄 Change Currency", callback_data="buy:start")],
            [InlineKeyboardButton(text="❌ Cancel", callback_data="buy:back_to_menu")]
        ])
    else:
        price_display = f"${float(price):,.2f}" if price > 0 else "N/A"
        
        text = f"""
💰 <b>Buy {crypto_info.get('icon', '')} {crypto}</b>
💵 Pay with: <b>{fiat}</b>
📊 Price: <b>{price_display}</b>

<b>Choose an Exchange:</b>

"""
        buttons = []
        
        for ex in exchanges[:5]:
            text += f"{ex.get('icon', '🏦')} <b>{ex.get('name', 'Exchange')}</b>\n"
            text += f"   ⭐ {ex.get('rating', 'N/A')} | 👥 {ex.get('users', 'N/A')} | Fee: {ex.get('fee', 'N/A')}\n"
            
            methods = ex.get('methods', [])
            if methods:
                text += f"   Methods: {', '.join(methods[:3])}\n"
            text += "\n"
            
            # Кнопка покупки
            buy_link = ex.get('buy_link')
            if buy_link:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"{ex.get('icon', '🏦')} Buy on {ex.get('name', 'Exchange')}",
                        url=buy_link
                    )
                ])
            
            # Кнопка P2P
            p2p_link = ex.get('p2p_link')
            if p2p_link:
                buttons.append([
                    InlineKeyboardButton(
                        text=f"   └ 🤝 {ex.get('name', 'Exchange')} P2P",
                        url=p2p_link
                    )
                ])
        
        text += """
<i>💡 After buying, withdraw to your wallet in this bot!</i>
"""
        
        buttons.append([InlineKeyboardButton(text="🤝 Use Our P2P", callback_data="p2p:buy")])
        buttons.append([InlineKeyboardButton(text="🔄 Change Options", callback_data="buy:start")])
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="buy:back_to_menu")])
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await safe_edit(callback.message, text, keyboard)
    
    # Очищаем состояние после завершения flow
    await state.clear()
    await safe_answer_callback(callback)


# ==================== SELL ====================

@router.callback_query(F.data == "sell:start")
async def sell_info(callback: CallbackQuery, state: FSMContext):
    """Информация о продаже криптовалюты"""
    # Очищаем состояние
    await state.clear()
    
    text = """
💸 <b>Sell Crypto</b>

To sell your crypto for fiat:

<b>Option 1: Our P2P (Recommended)</b>
├ Best rates from real buyers
├ Instant payment to your bank
└ Full escrow protection

<b>Option 2: Exchange P2P</b>
├ Binance P2P
├ Bybit P2P
└ Other exchanges

<b>Option 3: Direct on Exchange</b>
├ Sell for USDT
├ Withdraw USDT to your bank
└ May have limits

<i>💡 Our P2P usually has the best rates!</i>
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🤝 Sell via Our P2P", callback_data="p2p:sell")],
        [InlineKeyboardButton(text="🟡 Binance P2P", url="https://p2p.binance.com")],
        [InlineKeyboardButton(text="🟠 Bybit P2P", url="https://www.bybit.com/fiat/trade/otc")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="buy:back_to_menu")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)


# ==================== PRICES ====================

@router.callback_query(F.data == "buy:prices")
async def show_prices(callback: CallbackQuery, state: FSMContext):
    """Показ текущих цен"""
    await state.clear()
    
    # Показываем загрузку
    await safe_answer_callback(callback, "📊 Loading prices...")
    
    text = "📊 <b>Current Prices</b>\n\n"
    
    for crypto in SUPPORTED_CRYPTOS:
        try:
            price = await price_service.get_price(crypto['symbol'])
            change = await price_service._fetch_24h_change(crypto['symbol'])
            
            change_emoji = "🟢" if change >= 0 else "🔴"
            
            text += f"{crypto['icon']} <b>{crypto['symbol']}</b>\n"
            text += f"   ${float(price):,.2f} {change_emoji} {change:+.2f}%\n\n"
        except Exception as e:
            logger.warning("Price fetch failed", crypto=crypto['symbol'], error=str(e))
            text += f"{crypto['icon']} <b>{crypto['symbol']}</b>\n"
            text += f"   <i>Price unavailable</i>\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="buy:prices")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="buy:back_to_menu")]
    ])
    
    await safe_edit(callback.message, text, keyboard)


# ==================== EXCHANGE LIST ====================

@router.callback_query(F.data == "buy:exchanges")
async def show_exchanges(callback: CallbackQuery, state: FSMContext):
    """Показ списка всех бирж"""
    await state.clear()
    
    try:
        exchanges = exchange_service.get_all_exchanges()
    except Exception as e:
        logger.error("Failed to get exchanges", error=str(e))
        exchanges = []
    
    text = """
📋 <b>Trusted Exchanges</b>

All verified platforms for buying crypto:

"""
    
    buttons = []
    
    if exchanges:
        for ex in exchanges:
            text += f"{ex.get('icon', '🏦')} <b>{ex.get('name', 'Exchange')}</b> - ⭐ {ex.get('rating', 'N/A')}\n"
            
            ref_link = ex.get('ref_link')
            if ref_link:
                buttons.append([InlineKeyboardButton(
                    text=f"{ex.get('icon', '🏦')} Open {ex.get('name', 'Exchange')}",
                    url=ref_link
                )])
        
        text += """
<i>💡 Use these trusted exchanges to buy crypto, then withdraw to your wallet in this bot.</i>
"""
    else:
        text += "<i>No exchanges available at the moment.</i>"
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="buy:back_to_menu")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer_callback(callback)


# ==================== FALLBACK HANDLERS ====================

@router.callback_query(F.data.startswith("buy:"))
async def buy_fallback(callback: CallbackQuery, state: FSMContext):
    """
    Fallback для любых buy: callbacks, которые не были обработаны.
    Возвращает в меню покупки.
    """
    logger.warning("Unhandled buy callback", data=callback.data)
    await _show_buy_menu(callback, state)


@router.callback_query(F.data.startswith("sell:"))
async def sell_fallback(callback: CallbackQuery, state: FSMContext):
    """
    Fallback для необработанных sell: callbacks.
    """
    logger.warning("Unhandled sell callback", data=callback.data)
    await sell_info(callback, state)