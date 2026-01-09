# ==================== shop.py ====================
"""
NEXUS WALLET - Shop Handler
Mini-shops interface for merchants and buyers
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.exceptions import TelegramBadRequest
import structlog

from database.connection import db_manager
from database.repositories.user_repository import UserRepository
from database.models import ShopStatus, Shop, ShopProduct, ShopOrder
from services.shop_service import shop_service, SHOP_REQUIREMENTS, SUPPORTED_CRYPTOS
from services.price_service import price_service
from blockchain.wallet_manager import wallet_manager

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)
router = Router(name="shop")


# ==================== CONSTANTS ====================

class ShopLimits:
    """Shop system limits"""
    MIN_NAME_LENGTH = 3
    MAX_NAME_LENGTH = 50
    MIN_MOTIVATION_LENGTH = 50
    MAX_DESCRIPTION_LENGTH = 500
    MIN_MARGIN = 0.0
    MAX_MARGIN = 50.0
    MIN_ORDER_AMOUNT = Decimal("0.00001")
    MAX_PRODUCTS_PER_SHOP = 20


class Messages:
    """Centralized message templates"""
    
    SHOP_MAIN_OWNER = """
🏪 <b>My Shop</b>

Manage your mini-shop, add products, and process orders.
"""
    
    SHOP_MAIN_VISITOR = """
🏪 <b>Shops</b>

Browse shops from verified merchants or apply to open your own shop.

💡 Opening a shop requires meeting certain criteria and admin approval.
"""
    
    NO_SHOPS = """
🏪 <b>Shops</b>

No active shops at the moment.
Be the first to open one!
"""
    
    INVALID_AMOUNT = "❌ Invalid amount. Please enter a positive number."
    INVALID_ADDRESS = "❌ Invalid address. Please check and try again."
    PRODUCT_NOT_AVAILABLE = "❌ Product not available"
    SHOP_NOT_FOUND = "❌ Shop not found"
    INSUFFICIENT_STOCK = "❌ Not enough stock. Available: {available}"
    
    @staticmethod
    def order_created(order_id: str, amount: Decimal, symbol: str, total_usd: Decimal) -> str:
        return f"""
🎉 <b>Order Created!</b>

Order ID: <code>{order_id[:8]}</code>
Amount: <b>{amount} {symbol}</b>
Total: <b>${float(total_usd):,.2f}</b>

💳 Please complete payment to receive your crypto.

<i>The shop owner will process your order shortly.</i>
"""


# ==================== FSM STATES ====================

class ShopStates(StatesGroup):
    """Shop FSM states"""
    # Application flow
    app_name = State()
    app_description = State()
    app_motivation = State()
    app_tokens = State()
    app_confirm = State()
    
    # Shop management
    add_product_network = State()
    add_product_amount = State()
    add_product_margin = State()
    
    update_stock = State()
    
    # Settings
    edit_name = State()
    edit_description = State()
    edit_margin = State()
    
    # Order flow
    order_amount = State()
    order_address = State()
    order_confirm = State()


# ==================== KEYBOARDS ====================

class ShopKeyboards:
    """Centralized keyboard factory"""
    
    @staticmethod
    def main_menu(has_shop: bool) -> InlineKeyboardMarkup:
        """Main shop menu keyboard"""
        if has_shop:
            buttons = [
                [InlineKeyboardButton(text="📊 My Shop Dashboard", callback_data="shop:dashboard")],
                [InlineKeyboardButton(text="📦 Manage Products", callback_data="shop:products")],
                [InlineKeyboardButton(text="📋 Orders", callback_data="shop:orders")],
                [InlineKeyboardButton(text="⚙️ Shop Settings", callback_data="shop:settings")],
            ]
        else:
            buttons = [
                [InlineKeyboardButton(text="🏪 Browse Shops", callback_data="shop:browse")],
                [InlineKeyboardButton(text="📝 Apply for Shop", callback_data="shop:apply")],
            ]
        
        buttons.append([InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def back(callback_data: str = "shop:menu") -> InlineKeyboardMarkup:
        """Simple back button"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Back", callback_data=callback_data)]
        ])
    
    @staticmethod
    def cancel(callback_data: str = "shop:menu") -> InlineKeyboardMarkup:
        """Cancel button"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="❌ Cancel", callback_data=callback_data)]
        ])
    
    @staticmethod
    def confirm(confirm_data: str, cancel_data: str = "shop:menu") -> InlineKeyboardMarkup:
        """Confirm/Cancel keyboard"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data=confirm_data),
                InlineKeyboardButton(text="❌ Cancel", callback_data=cancel_data)
            ]
        ])
    
    @staticmethod
    def crypto_select(
        callback_prefix: str, 
        selected: Optional[List[str]] = None,
        multi_select: bool = True
    ) -> InlineKeyboardMarkup:
        """Crypto selection keyboard"""
        selected = selected or []
        buttons = []
        row = []
        
        for network, info in SUPPORTED_CRYPTOS.items():
            if multi_select:
                is_selected = network in selected
                prefix = "✅" if is_selected else "⬜"
                text = f"{prefix} {info['icon']} {info['symbol']}"
            else:
                text = f"{info['icon']} {info['symbol']}"
            
            row.append(InlineKeyboardButton(
                text=text,
                callback_data=f"{callback_prefix}:{network}"
            ))
            
            if len(row) == 3:
                buttons.append(row)
                row = []
        
        if row:
            buttons.append(row)
        
        if multi_select:
            buttons.append([InlineKeyboardButton(
                text="✅ Done", 
                callback_data=f"{callback_prefix}:done"
            )])
        
        buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="shop:menu")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def shop_list(shops: List[Shop]) -> InlineKeyboardMarkup:
        """Shop list keyboard"""
        buttons = []
        for shop in shops:
            buttons.append([InlineKeyboardButton(
                text=f"🏪 {shop.name}",
                callback_data=f"shop:view:{shop.id[:8]}"
            )])
        buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="shop:menu")])
        return InlineKeyboardMarkup(inline_keyboard=buttons)
    
    @staticmethod
    def dashboard() -> InlineKeyboardMarkup:
        """Shop dashboard keyboard"""
        return InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="📦 Products", callback_data="shop:products"),
                InlineKeyboardButton(text="📋 Orders", callback_data="shop:orders")
            ],
            [
                InlineKeyboardButton(text="⚙️ Settings", callback_data="shop:settings"),
                InlineKeyboardButton(text="📊 Analytics", callback_data="shop:analytics")
            ],
            [InlineKeyboardButton(text="🔙 Back", callback_data="shop:menu")]
        ])


# ==================== UTILITIES ====================

async def safe_edit(
    message: Message, 
    text: str, 
    keyboard: Optional[InlineKeyboardMarkup] = None,
    parse_mode: str = "HTML"
) -> bool:
    """Safely edit message with error handling"""
    try:
        await message.edit_text(
            text,
            reply_markup=keyboard,
            parse_mode=parse_mode,
            disable_web_page_preview=True
        )
        return True
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e).lower():
            logger.warning("Edit failed", error=str(e))
        return False
    except Exception as e:
        logger.error("Edit error", error=str(e), exc_info=True)
        return False


async def safe_answer(
    callback: CallbackQuery, 
    text: Optional[str] = None, 
    show_alert: bool = False
) -> None:
    """Safely answer callback query"""
    try:
        await callback.answer(text=text, show_alert=show_alert)
    except Exception as e:
        logger.debug("Callback answer failed", error=str(e))


def parse_decimal(value: str) -> Optional[Decimal]:
    """Parse string to Decimal with validation"""
    try:
        cleaned = value.strip().replace(",", ".")
        result = Decimal(cleaned)
        if result <= 0:
            return None
        return result
    except (InvalidOperation, ValueError):
        return None


async def validate_crypto_address(network: str, address: str) -> bool:
    """Validate cryptocurrency address"""
    try:
        return await wallet_manager.validate_address(network, address)
    except Exception as e:
        logger.warning("Address validation failed", network=network, error=str(e))
        return False


async def get_price_with_margin(symbol: str, margin_percent: float) -> Optional[Decimal]:
    """Get token price with margin applied"""
    try:
        price = await price_service.get_price(symbol)
        if price and price > 0:
            return price * (1 + Decimal(str(margin_percent)) / 100)
        return None
    except Exception as e:
        logger.error("Price fetch failed", symbol=symbol, error=str(e))
        return None


# ==================== MAIN MENU ====================

@router.callback_query(F.data.in_({"shop", "shop:menu"}))
async def shop_main_menu(callback: CallbackQuery, state: FSMContext) -> None:
    """Show shop main menu"""
    await state.clear()
    
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(
                session, callback.from_user.id
            )
            has_shop = user.has_shop if user else False
    except Exception as e:
        logger.error("Failed to check shop status", error=str(e))
        has_shop = False
    
    text = Messages.SHOP_MAIN_OWNER if has_shop else Messages.SHOP_MAIN_VISITOR
    
    await safe_edit(callback.message, text, ShopKeyboards.main_menu(has_shop))
    await safe_answer(callback)


# ==================== BROWSE SHOPS ====================

@router.callback_query(F.data == "shop:browse")
async def shop_browse(callback: CallbackQuery) -> None:
    """Browse active shops"""
    try:
        async with db_manager.session() as session:
            shops = await shop_service.get_active_shops(session, limit=10)
    except Exception as e:
        logger.error("Failed to fetch shops", error=str(e))
        shops = []
    
    if not shops:
        await safe_edit(
            callback.message, 
            Messages.NO_SHOPS, 
            ShopKeyboards.back("shop:menu")
        )
        await safe_answer(callback)
        return
    
    text = "🏪 <b>Available Shops</b>\n\n"
    
    for shop in shops:
        owner = shop.owner
        verified = "✅" if owner and owner.merchant_verified else ""
        rating = f"⭐{shop.rating:.1f}" if shop.rating else "⭐New"
        
        text += f"🏪 <b>{shop.name}</b> {verified}\n"
        text += f"   {rating} | {shop.completed_orders} orders"
        if shop.total_volume_usd:
            text += f" | ${float(shop.total_volume_usd):,.0f}"
        text += "\n\n"
    
    await safe_edit(callback.message, text, ShopKeyboards.shop_list(shops))
    await safe_answer(callback)


@router.callback_query(F.data.startswith("shop:view:"))
async def shop_view(callback: CallbackQuery) -> None:
    """View a specific shop"""
    shop_id_short = callback.data.split(":")[2]
    
    try:
        async with db_manager.session() as session:
            from sqlalchemy import select
            
            result = await session.execute(
                select(Shop).where(Shop.id.like(f"{shop_id_short}%"))
            )
            shop = result.scalar_one_or_none()
            
            if not shop:
                await safe_answer(callback, Messages.SHOP_NOT_FOUND, show_alert=True)
                return
            
            stats = await shop_service.get_shop_stats(session, shop.id)
            products = [p for p in (shop.products or []) if p.is_active]
    except Exception as e:
        logger.error("Failed to load shop", shop_id=shop_id_short, error=str(e))
        await safe_answer(callback, "Failed to load shop", show_alert=True)
        return
    
    owner = shop.owner
    verified = "✅ Verified" if owner and owner.merchant_verified else ""
    
    text = f"""
🏪 <b>{shop.name}</b> {verified}

{shop.description or 'No description'}

📊 <b>Stats:</b>
├ Rating: ⭐ {shop.rating:.1f}
├ Orders: {stats.get('completed_orders', 0)}
├ Volume: ${stats.get('total_volume_usd', 0):,.0f}
└ Since: {stats.get('created_at', 'N/A')}

📦 <b>Products:</b>
"""
    
    buttons = []
    
    if products:
        for p in products:
            crypto = SUPPORTED_CRYPTOS.get(p.network, {})
            icon = crypto.get('icon', '🔗')
            text += f"\n{icon} {p.token_symbol}: {p.available_amount:.4f} available"
            
            buttons.append([InlineKeyboardButton(
                text=f"💰 Buy {icon} {p.token_symbol}",
                callback_data=f"shop:buy:{p.id[:8]}"
            )])
    else:
        text += "\n<i>No products available</i>"
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="shop:browse")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback)


# ==================== BUY FROM SHOP ====================

@router.callback_query(F.data.startswith("shop:buy:"))
async def shop_buy_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start buying from shop"""
    product_id_short = callback.data.split(":")[2]
    
    try:
        async with db_manager.session() as session:
            from sqlalchemy import select
            
            result = await session.execute(
                select(ShopProduct).where(ShopProduct.id.like(f"{product_id_short}%"))
            )
            product = result.scalar_one_or_none()
            
            if not product or not product.is_active:
                await safe_answer(callback, Messages.PRODUCT_NOT_AVAILABLE, show_alert=True)
                return
            
            shop = await shop_service.get_shop_by_id(session, product.shop_id)
            if not shop:
                await safe_answer(callback, Messages.SHOP_NOT_FOUND, show_alert=True)
                return
            
            # Get price with margin
            price_with_margin = await get_price_with_margin(
                product.token_symbol, 
                product.margin_percentage
            )
            
            if not price_with_margin:
                await safe_answer(callback, "Price unavailable", show_alert=True)
                return
            
            await state.update_data(
                buy_product_id=product.id,
                buy_shop_id=shop.id,
                buy_shop_name=shop.name,
                buy_network=product.network,
                buy_symbol=product.token_symbol,
                buy_available=str(product.available_amount),
                buy_price=str(price_with_margin),
                buy_margin=product.margin_percentage
            )
    except Exception as e:
        logger.error("Buy start failed", error=str(e))
        await safe_answer(callback, "Failed to start purchase", show_alert=True)
        return
    
    crypto = SUPPORTED_CRYPTOS.get(product.network, {})
    
    text = f"""
💰 <b>Buy {crypto.get('icon', '')} {product.token_symbol}</b>

From: <b>{shop.name}</b>
Available: <b>{product.available_amount:.6f} {product.token_symbol}</b>
Price: <b>${float(price_with_margin):,.2f}</b> per {product.token_symbol}
<i>(+{product.margin_percentage}% margin)</i>

Enter the amount of <b>{product.token_symbol}</b> you want to buy:

<i>Example: 0.5</i>
"""
    
    await safe_edit(callback.message, text, ShopKeyboards.cancel())
    await state.set_state(ShopStates.order_amount)
    await safe_answer(callback)


@router.message(ShopStates.order_amount)
async def shop_buy_enter_address(message: Message, state: FSMContext) -> None:
    """Process amount and request address"""
    amount = parse_decimal(message.text)
    
    if not amount or amount < ShopLimits.MIN_ORDER_AMOUNT:
        await message.answer(Messages.INVALID_AMOUNT, reply_markup=ShopKeyboards.cancel())
        return
    
    data = await state.get_data()
    available = Decimal(data['buy_available'])
    
    if amount > available:
        await message.answer(
            Messages.INSUFFICIENT_STOCK.format(available=available),
            reply_markup=ShopKeyboards.cancel()
        )
        return
    
    price = Decimal(data['buy_price'])
    total_usd = amount * price
    
    await state.update_data(order_amount=str(amount), order_total=str(total_usd))
    
    text = f"""
📥 <b>Enter Receiving Address</b>

You're buying: <b>{amount} {data['buy_symbol']}</b>
Total: <b>${float(total_usd):,.2f}</b>

Enter your <b>{data['buy_network'].upper()}</b> wallet address:
"""
    
    await message.answer(text, reply_markup=ShopKeyboards.cancel())
    await state.set_state(ShopStates.order_address)


@router.message(ShopStates.order_address)
async def shop_buy_confirm(message: Message, state: FSMContext) -> None:
    """Validate address and show confirmation"""
    address = message.text.strip()
    data = await state.get_data()
    
    # Validate address
    is_valid = await validate_crypto_address(data['buy_network'], address)
    
    if not is_valid:
        await message.answer(Messages.INVALID_ADDRESS, reply_markup=ShopKeyboards.cancel())
        return
    
    await state.update_data(order_address=address)
    
    amount = Decimal(data['order_amount'])
    total = Decimal(data['order_total'])
    
    text = f"""
✅ <b>Confirm Order</b>

<b>Buying:</b> {amount} {data['buy_symbol']}
<b>Total:</b> ${float(total):,.2f}
<b>Network:</b> {data['buy_network'].upper()}

<b>Receiving Address:</b>
<code>{address}</code>

⚠️ Make sure the address is correct!
Crypto sent to wrong address cannot be recovered.
"""
    
    await message.answer(text, reply_markup=ShopKeyboards.confirm("shop:order_confirm"))
    await state.set_state(ShopStates.order_confirm)


@router.callback_query(ShopStates.order_confirm, F.data == "shop:order_confirm")
async def shop_buy_execute(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute the order"""
    data = await state.get_data()
    
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(
                session, callback.from_user.id
            )
            
            if not user:
                await safe_answer(callback, "User not found", show_alert=True)
                await state.clear()
                return
            
            order, error_message = await shop_service.create_order(
                session=session,
                buyer_id=user.id,
                product_id=data['buy_product_id'],
                amount=Decimal(data['order_amount']),
                buyer_address=data['order_address']
            )
            
            if not order:
                await safe_answer(callback, f"❌ {error_message}", show_alert=True)
                await state.clear()
                return
            
            await session.commit()
            
            logger.info(
                "Shop order created",
                order_id=order.id,
                buyer_id=user.id,
                amount=data['order_amount'],
                symbol=data['buy_symbol']
            )
    except Exception as e:
        logger.error("Order creation failed", error=str(e), exc_info=True)
        await safe_answer(callback, "Order failed. Please try again.", show_alert=True)
        await state.clear()
        return
    
    await state.clear()
    
    text = Messages.order_created(
        order_id=order.id,
        amount=order.amount,
        symbol=order.token_symbol,
        total_usd=order.price_usd
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏪 Browse More", callback_data="shop:browse")],
        [InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback, "Order created!")


# ==================== APPLY FOR SHOP ====================

@router.callback_query(F.data == "shop:apply")
async def shop_apply_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Show requirements and start application if eligible"""
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(
                session, callback.from_user.id
            )
            if not user:
                await safe_answer(callback, "User not found", show_alert=True)
                return
            
            is_eligible, errors, stats = await shop_service.check_eligibility(
                session, user.id
            )
    except Exception as e:
        logger.error("Eligibility check failed", error=str(e), exc_info=True)
        await safe_answer(callback, "Failed to check eligibility", show_alert=True)
        return
    
    # Check for pending application
    if "pending application" in str(errors).lower():
        text = """
📝 <b>Shop Application</b>

⏳ <b>You already have a pending application!</b>

Your application is being reviewed by our team.
You will be notified once it's processed.

<i>Contact support if you need to cancel and reapply.</i>
"""
        await safe_edit(callback.message, text, ShopKeyboards.back("shop:menu"))
        await safe_answer(callback)
        return
    
    # Check if already has shop
    if "already have a shop" in str(errors).lower():
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📊 My Dashboard", callback_data="shop:dashboard")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="shop:menu")]
        ])
        await safe_edit(callback.message, "🏪 <b>You already have a shop!</b>", keyboard)
        await safe_answer(callback)
        return
    
    # Normal requirements display
    text = "📝 <b>Shop Application</b>\n\n<b>Requirements to open a shop:</b>\n"
    
    req = SHOP_REQUIREMENTS
    
    checks = [
        (
            stats.get('total_trades', 0) >= req['min_trades'],
            f"Minimum {req['min_trades']} completed trades",
            f"You: {stats.get('total_trades', 0)}"
        ),
        (
            stats.get('volume_usd', 0) >= req['min_volume_usd'],
            f"Minimum ${req['min_volume_usd']:,} trading volume",
            f"You: ${stats.get('volume_usd', 0):,.0f}"
        ),
        (
            stats.get('success_rate', 0) >= req['min_success_rate'],
            f"Minimum {req['min_success_rate']}% success rate",
            f"You: {stats.get('success_rate', 0):.1f}%"
        ),
        (
            stats.get('rating', 0) >= req['min_rating'],
            f"Minimum {req['min_rating']} rating",
            f"You: {stats.get('rating', 0):.1f}"
        ),
        (
            stats.get('account_age_days', 0) >= req['min_account_age_days'],
            f"Account age {req['min_account_age_days']}+ days",
            f"You: {stats.get('account_age_days', 0)} days"
        ),
        (
            stats.get('disputed_trades', 0) == 0,
            "No disputed trades",
            f"You: {stats.get('disputed_trades', 0)} disputes"
        ),
    ]
    
    for passed, requirement, your_stat in checks:
        emoji = "✅" if passed else "❌"
        text += f"\n{emoji} {requirement}\n   <i>{your_stat}</i>\n"
    
    if is_eligible:
        text += "\n\n🎉 <b>You meet all requirements!</b>\nClick below to apply."
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📝 Start Application", callback_data="shop:apply_start")],
            [InlineKeyboardButton(text="🔙 Back", callback_data="shop:menu")]
        ])
    else:
        text += "\n\n❌ <b>You don't meet all requirements yet.</b>\nKeep trading to become eligible!"
        keyboard = ShopKeyboards.back("shop:menu")
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback)


@router.callback_query(F.data == "shop:apply_start")
async def shop_apply_name(callback: CallbackQuery, state: FSMContext) -> None:
    """Step 1: Enter shop name"""
    text = f"""
📝 <b>Step 1/4: Shop Name</b>

Enter a name for your shop ({ShopLimits.MIN_NAME_LENGTH}-{ShopLimits.MAX_NAME_LENGTH} characters):

<i>Example: Crypto Express</i>
"""
    
    await safe_edit(callback.message, text, ShopKeyboards.cancel())
    await state.set_state(ShopStates.app_name)
    await safe_answer(callback)


@router.message(ShopStates.app_name)
async def shop_apply_description(message: Message, state: FSMContext) -> None:
    """Step 2: Enter description"""
    name = message.text.strip()
    
    if len(name) < ShopLimits.MIN_NAME_LENGTH or len(name) > ShopLimits.MAX_NAME_LENGTH:
        await message.answer(
            f"❌ Name must be {ShopLimits.MIN_NAME_LENGTH}-{ShopLimits.MAX_NAME_LENGTH} characters",
            reply_markup=ShopKeyboards.cancel()
        )
        return
    
    await state.update_data(shop_name=name)
    
    text = """
📝 <b>Step 2/4: Description</b>

Enter a short description for your shop:

<i>Example: Fast and reliable crypto exchange. 24/7 support.</i>
"""
    
    await message.answer(text, reply_markup=ShopKeyboards.cancel())
    await state.set_state(ShopStates.app_description)


@router.message(ShopStates.app_description)
async def shop_apply_motivation(message: Message, state: FSMContext) -> None:
    """Step 3: Enter motivation"""
    description = message.text.strip()
    
    if len(description) > ShopLimits.MAX_DESCRIPTION_LENGTH:
        await message.answer(
            f"❌ Description too long (max {ShopLimits.MAX_DESCRIPTION_LENGTH} characters)",
            reply_markup=ShopKeyboards.cancel()
        )
        return
    
    await state.update_data(shop_description=description)
    
    text = f"""
📝 <b>Step 3/4: Motivation</b>

Tell us why you want to open a shop and how you plan to run it (min {ShopLimits.MIN_MOTIVATION_LENGTH} characters):

<i>This helps us understand your business plan.</i>
"""
    
    await message.answer(text, reply_markup=ShopKeyboards.cancel())
    await state.set_state(ShopStates.app_motivation)


@router.message(ShopStates.app_motivation)
async def shop_apply_tokens(message: Message, state: FSMContext) -> None:
    """Step 4: Select tokens"""
    motivation = message.text.strip()
    
    if len(motivation) < ShopLimits.MIN_MOTIVATION_LENGTH:
        await message.answer(
            f"❌ Please provide more details (min {ShopLimits.MIN_MOTIVATION_LENGTH} characters)",
            reply_markup=ShopKeyboards.cancel()
        )
        return
    
    await state.update_data(shop_motivation=motivation, selected_tokens=[])
    
    text = """
📝 <b>Step 4/4: Select Tokens</b>

Choose which cryptocurrencies you want to sell:
<i>(Select at least one)</i>
"""
    
    keyboard = ShopKeyboards.crypto_select("shop:token_sel", [])
    await message.answer(text, reply_markup=keyboard)
    await state.set_state(ShopStates.app_tokens)


@router.callback_query(ShopStates.app_tokens, F.data.startswith("shop:token_sel:"))
async def shop_apply_toggle_token(callback: CallbackQuery, state: FSMContext) -> None:
    """Toggle token selection or proceed to confirmation"""
    token = callback.data.split(":")[2]
    
    if token == "done":
        data = await state.get_data()
        selected = data.get('selected_tokens', [])
        
        if not selected:
            await safe_answer(callback, "Select at least one token", show_alert=True)
            return
        
        await show_application_confirmation(callback, state)
        return
    
    data = await state.get_data()
    selected = data.get('selected_tokens', [])
    
    if token in selected:
        selected.remove(token)
    else:
        selected.append(token)
    
    await state.update_data(selected_tokens=selected)
    
    keyboard = ShopKeyboards.crypto_select("shop:token_sel", selected)
    
    try:
        await callback.message.edit_reply_markup(reply_markup=keyboard)
    except TelegramBadRequest:
        pass
    
    await safe_answer(callback)


async def show_application_confirmation(
    callback: CallbackQuery, 
    state: FSMContext
) -> None:
    """Show application confirmation"""
    data = await state.get_data()
    
    selected_tokens = data.get('selected_tokens', [])
    token_names = [
        SUPPORTED_CRYPTOS[t]['symbol'] 
        for t in selected_tokens 
        if t in SUPPORTED_CRYPTOS
    ]
    
    motivation_preview = data['shop_motivation'][:200]
    if len(data['shop_motivation']) > 200:
        motivation_preview += "..."
    
    text = f"""
✅ <b>Confirm Application</b>

<b>Shop Name:</b> {data['shop_name']}
<b>Description:</b> {data.get('shop_description') or 'None'}
<b>Tokens:</b> {', '.join(token_names)}

<b>Motivation:</b>
<i>{motivation_preview}</i>

Submit this application?
<i>An admin will review it within 24-48 hours.</i>
"""
    
    keyboard = ShopKeyboards.confirm("shop:apply_submit")
    
    await safe_edit(callback.message, text, keyboard)
    await state.set_state(ShopStates.app_confirm)


@router.callback_query(ShopStates.app_confirm, F.data == "shop:apply_submit")
async def shop_apply_submit(callback: CallbackQuery, state: FSMContext) -> None:
    """Submit the application"""
    data = await state.get_data()
    
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(
                session, callback.from_user.id
            )
            
            if not user:
                await safe_answer(callback, "User not found", show_alert=True)
                await state.clear()
                return
            
            proposed_tokens = [{"network": t} for t in data.get('selected_tokens', [])]
            
            application, errors = await shop_service.submit_application(
                session=session,
                user_id=user.id,
                shop_name=data['shop_name'],
                description=data.get('shop_description', ''),
                motivation=data['shop_motivation'],
                proposed_tokens=proposed_tokens
            )
            
            if errors:
                text = "❌ <b>Application Failed:</b>\n\n" + "\n".join(f"• {e}" for e in errors)
                keyboard = ShopKeyboards.back("shop:menu")
            else:
                await session.commit()
                
                logger.info(
                    "Shop application submitted",
                    user_id=user.id,
                    app_id=application.id,
                    shop_name=data['shop_name']
                )
                
                text = f"""
🎉 <b>Application Submitted!</b>

Your application ID: <code>{application.id[:8]}</code>

An admin will review your application within 24-48 hours.
You'll receive a notification when it's processed.

Thank you for your interest!
"""
                keyboard = ShopKeyboards.back("shop:menu")
    except Exception as e:
        logger.error("Application submission failed", error=str(e), exc_info=True)
        text = "❌ Failed to submit application. Please try again."
        keyboard = ShopKeyboards.back("shop:menu")
    
    await safe_edit(callback.message, text, keyboard)
    await state.clear()
    await safe_answer(callback)


# ==================== SHOP DASHBOARD ====================

@router.callback_query(F.data == "shop:dashboard")
async def shop_dashboard(callback: CallbackQuery) -> None:
    """Shop owner dashboard"""
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(
                session, callback.from_user.id
            )
            if not user:
                await safe_answer(callback, "User not found", show_alert=True)
                return
            
            shop = await shop_service.get_shop_by_owner(session, user.id)
            
            if not shop:
                await safe_answer(callback, Messages.SHOP_NOT_FOUND, show_alert=True)
                return
            
            stats = await shop_service.get_shop_stats(session, shop.id)
    except Exception as e:
        logger.error("Dashboard load failed", error=str(e))
        await safe_answer(callback, "Failed to load dashboard", show_alert=True)
        return
    
    status_emoji = {
        ShopStatus.APPROVED: "🟢",
        ShopStatus.SUSPENDED: "🔴",
        ShopStatus.PENDING: "🟡"
    }
    
    text = f"""
🏪 <b>{shop.name}</b> {status_emoji.get(shop.status, '⚪')}

📊 <b>Statistics:</b>
├ Total Orders: <b>{stats.get('total_orders', 0)}</b>
├ Completed: <b>{stats.get('completed_orders', 0)}</b>
├ Pending: <b>{stats.get('pending_orders', 0)}</b>
├ Volume: <b>${stats.get('total_volume_usd', 0):,.2f}</b>
├ Commission Paid: <b>${stats.get('total_commission_paid', 0):,.2f}</b>
└ Rating: ⭐ <b>{stats.get('rating', 0):.1f}</b>

📦 <b>Products:</b> {stats.get('products_count', 0)} active

📅 <b>Today:</b>
├ Orders: {stats.get('today_orders', 0)}
└ Volume: ${stats.get('today_volume_usd', 0):,.2f}
"""
    
    await safe_edit(callback.message, text, ShopKeyboards.dashboard())
    await safe_answer(callback)


# ==================== PRODUCTS MANAGEMENT ====================

@router.callback_query(F.data == "shop:products")
async def shop_products(callback: CallbackQuery) -> None:
    """Manage shop products"""
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(
                session, callback.from_user.id
            )
            shop = await shop_service.get_shop_by_owner(session, user.id)
            
            if not shop:
                await safe_answer(callback, Messages.SHOP_NOT_FOUND, show_alert=True)
                return
            
            products = [p for p in (shop.products or []) if p.is_active]
    except Exception as e:
        logger.error("Products load failed", error=str(e))
        await safe_answer(callback, "Failed to load products", show_alert=True)
        return
    
    text = "📦 <b>My Products</b>\n\n"
    buttons = []
    
    if products:
        for p in products:
            crypto = SUPPORTED_CRYPTOS.get(p.network, {})
            icon = crypto.get('icon', '🔗')
            text += f"{icon} <b>{p.token_symbol}</b>\n"
            text += f"   Stock: {p.available_amount:.6f}\n"
            text += f"   Margin: +{p.margin_percentage}%\n\n"
            
            buttons.append([InlineKeyboardButton(
                text=f"Edit {icon} {p.token_symbol}",
                callback_data=f"shop:edit_prod:{p.id[:8]}"
            )])
    else:
        text += "<i>No products yet. Add your first product!</i>\n"
    
    if len(products) < ShopLimits.MAX_PRODUCTS_PER_SHOP:
        buttons.append([InlineKeyboardButton(
            text="➕ Add Product", 
            callback_data="shop:add_product"
        )])
    
    buttons.append([InlineKeyboardButton(text="🔙 Back", callback_data="shop:dashboard")])
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback)


@router.callback_query(F.data == "shop:add_product")
async def shop_add_product_start(callback: CallbackQuery, state: FSMContext) -> None:
    """Start adding product"""
    text = """
➕ <b>Add Product</b>

Select the cryptocurrency to sell:
"""
    
    keyboard = ShopKeyboards.crypto_select("shop:add_net", multi_select=False)
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback)


@router.callback_query(F.data.startswith("shop:add_net:"))
async def shop_add_product_amount(callback: CallbackQuery, state: FSMContext) -> None:
    """Enter product amount"""
    network = callback.data.split(":")[2]
    
    if network == "done":
        await safe_answer(callback)
        return
    
    crypto = SUPPORTED_CRYPTOS.get(network)
    
    if not crypto:
        await safe_answer(callback, "Invalid network", show_alert=True)
        return
    
    await state.update_data(add_network=network, add_symbol=crypto['symbol'])
    
    text = f"""
➕ <b>Add {crypto['icon']} {crypto['symbol']}</b>

Enter the amount of {crypto['symbol']} to stock:

<i>This amount will be locked from your wallet.</i>
"""
    
    await safe_edit(callback.message, text, ShopKeyboards.cancel())
    await state.set_state(ShopStates.add_product_amount)
    await safe_answer(callback)


@router.message(ShopStates.add_product_amount)
async def shop_add_product_margin(message: Message, state: FSMContext) -> None:
    """Enter margin percentage"""
    amount = parse_decimal(message.text)
    
    if not amount:
        await message.answer(Messages.INVALID_AMOUNT, reply_markup=ShopKeyboards.cancel())
        return
    
    data = await state.get_data()
    await state.update_data(add_amount=str(amount))
    
    text = f"""
💰 <b>Set Margin</b>

Amount: <b>{amount} {data['add_symbol']}</b>

Enter your margin percentage (e.g., 2 for +2%):
<i>Range: {ShopLimits.MIN_MARGIN}-{ShopLimits.MAX_MARGIN}%</i>

<i>This is added on top of market price.</i>
"""
    
    await message.answer(text, reply_markup=ShopKeyboards.cancel())
    await state.set_state(ShopStates.add_product_margin)


@router.message(ShopStates.add_product_margin)
async def shop_add_product_execute(message: Message, state: FSMContext) -> None:
    """Execute adding product"""
    try:
        margin = float(message.text.strip().replace(",", "."))
        if margin < ShopLimits.MIN_MARGIN or margin > ShopLimits.MAX_MARGIN:
            raise ValueError()
    except (ValueError, TypeError):
        await message.answer(
            f"❌ Margin must be {ShopLimits.MIN_MARGIN}-{ShopLimits.MAX_MARGIN}%",
            reply_markup=ShopKeyboards.cancel()
        )
        return
    
    data = await state.get_data()
    
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(
                session, message.from_user.id
            )
            shop = await shop_service.get_shop_by_owner(session, user.id)
            
            if not shop:
                await message.answer(Messages.SHOP_NOT_FOUND)
                await state.clear()
                return
            
            product, error = await shop_service.add_product(
                session=session,
                shop_id=shop.id,
                owner_id=user.id,
                network=data['add_network'],
                amount=Decimal(data['add_amount']),
                margin_percentage=margin
            )
            
            if error and not product:
                await message.answer(
                    f"❌ {error}",
                    reply_markup=ShopKeyboards.back("shop:products")
                )
            else:
                await session.commit()
                
                crypto = SUPPORTED_CRYPTOS[data['add_network']]
                text = f"""
✅ <b>Product Added!</b>

{crypto['icon']} <b>{data['add_symbol']}</b>
Stock: {data['add_amount']}
Margin: +{margin}%

Your product is now live!
"""
                await message.answer(text, reply_markup=ShopKeyboards.back("shop:products"))
                
                logger.info(
                    "Product added",
                    shop_id=shop.id,
                    network=data['add_network'],
                    amount=data['add_amount']
                )
    except Exception as e:
        logger.error("Add product failed", error=str(e), exc_info=True)
        await message.answer(
            "❌ Failed to add product",
            reply_markup=ShopKeyboards.back("shop:products")
        )
    
    await state.clear()


# ==================== SHOP ORDERS ====================

@router.callback_query(F.data == "shop:orders")
async def shop_orders(callback: CallbackQuery) -> None:
    """View shop orders"""
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(
                session, callback.from_user.id
            )
            shop = await shop_service.get_shop_by_owner(session, user.id)
            
            if not shop:
                await safe_answer(callback, Messages.SHOP_NOT_FOUND, show_alert=True)
                return
            
            from sqlalchemy import select
            
            result = await session.execute(
                select(ShopOrder)
                .where(ShopOrder.shop_id == shop.id)
                .order_by(ShopOrder.created_at.desc())
                .limit(20)
            )
            orders = result.scalars().all()
    except Exception as e:
        logger.error("Orders load failed", error=str(e))
        await safe_answer(callback, "Failed to load orders", show_alert=True)
        return
    
    if not orders:
        text = "📋 <b>Shop Orders</b>\n\nNo orders yet."
    else:
        text = "📋 <b>Shop Orders</b>\n\n"
        
        status_emoji = {
            "pending": "⏳",
            "completed": "✅",
            "cancelled": "❌"
        }
        
        for o in orders:
            emoji = status_emoji.get(o.status, "❓")
            crypto = SUPPORTED_CRYPTOS.get(o.network, {})
            icon = crypto.get('icon', '')
            
            text += f"{emoji} {icon} {o.amount:.4f} {o.token_symbol}\n"
            text += f"   ${float(o.price_usd):,.2f} | {o.created_at.strftime('%m/%d %H:%M')}\n\n"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Refresh", callback_data="shop:orders")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="shop:dashboard")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback)


# ==================== SHOP SETTINGS ====================

@router.callback_query(F.data == "shop:settings")
async def shop_settings(callback: CallbackQuery) -> None:
    """Shop settings"""
    try:
        async with db_manager.session() as session:
            user = await UserRepository().get_by_telegram_id(
                session, callback.from_user.id
            )
            shop = await shop_service.get_shop_by_owner(session, user.id)
            
            if not shop:
                await safe_answer(callback, Messages.SHOP_NOT_FOUND, show_alert=True)
                return
    except Exception as e:
        logger.error("Settings load failed", error=str(e))
        await safe_answer(callback, "Failed to load settings", show_alert=True)
        return
    
    text = f"""
⚙️ <b>Shop Settings</b>

<b>Name:</b> {shop.name}
<b>Description:</b> {shop.description or 'Not set'}
<b>Default Margin:</b> {shop.default_margin}%
<b>Min Order:</b> ${float(shop.min_order_usd):,.0f}
<b>Max Order:</b> ${float(shop.max_order_usd):,.0f}
<b>Commission:</b> {shop.commission_rate}% to platform
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Edit Name", callback_data="shop:set:name")],
        [InlineKeyboardButton(text="📝 Edit Description", callback_data="shop:set:desc")],
        [InlineKeyboardButton(text="💰 Edit Limits", callback_data="shop:set:limits")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="shop:dashboard")]
    ])
    
    await safe_edit(callback.message, text, keyboard)
    await safe_answer(callback)


# ==================== ANALYTICS ====================

@router.callback_query(F.data == "shop:analytics")
async def shop_analytics(callback: CallbackQuery) -> None:
    """Shop analytics (placeholder)"""
    await safe_answer(callback, "📊 Analytics coming soon!", show_alert=True)