"""
NEXUS WALLET - Inline Transfer Handler
Send crypto to any user via inline mode: @bot_username 100 TON
"""

from __future__ import annotations

import uuid
import re
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, Tuple
from aiogram import Router, Bot, F
from aiogram.types import (
    InlineQuery, InlineQueryResultArticle, InputTextMessageContent,
    CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ChosenInlineResult
)
from aiogram.fsm.context import FSMContext
import structlog

from database.connection import db_manager
from database.models import (
    User, Wallet, WalletBalance, Transaction, 
    TransactionType, TransactionStatus
)
from sqlalchemy import select
from config.settings import settings

logger = structlog.get_logger(__name__)
router = Router(name="inline_transfer")


# ==================== CONSTANTS ====================

# Supported tokens for inline transfer
SUPPORTED_TOKENS = {
    "TON": {"network": "ton", "icon": "💎", "decimals": 9},
    "ETH": {"network": "eth", "icon": "⟠", "decimals": 18},
    "BNB": {"network": "bsc", "icon": "🟡", "decimals": 18},
    "MATIC": {"network": "polygon", "icon": "🟣", "decimals": 18},
    "TRX": {"network": "tron", "icon": "🔴", "decimals": 6},
    "SOL": {"network": "solana", "icon": "🟢", "decimals": 9},
    "BTC": {"network": "bitcoin", "icon": "₿", "decimals": 8},
    "USDT": {"network": "tron", "icon": "💵", "decimals": 6},
}

# Cache for pending transfers (in production use Redis)
pending_transfers: Dict[str, Dict[str, Any]] = {}

# Transfer expiry time
TRANSFER_EXPIRY_MINUTES = 30


# ==================== HELPER FUNCTIONS ====================

def parse_inline_query(query_text: str) -> Tuple[Optional[Decimal], Optional[str], Optional[str]]:
    """
    Parse inline query text.
    Formats:
        - "100 TON" -> (100, "TON", None)
        - "50.5 ETH" -> (50.5, "ETH", None)
        - "25 USDT message" -> (25, "USDT", "message")
    """
    if not query_text or not query_text.strip():
        return None, None, None
    
    parts = query_text.strip().split()
    
    if len(parts) < 2:
        return None, None, None
    
    # Parse amount
    try:
        amount = Decimal(parts[0].replace(",", "."))
        if amount <= 0:
            return None, None, None
    except (InvalidOperation, ValueError):
        return None, None, None
    
    # Parse token
    token = parts[1].upper()
    if token not in SUPPORTED_TOKENS:
        return None, None, None
    
    # Parse optional message
    message = " ".join(parts[2:]) if len(parts) > 2 else None
    
    return amount, token, message


async def get_user_balance(user_id: str, token: str) -> Decimal:
    """Get user's balance for specific token."""
    token_info = SUPPORTED_TOKENS.get(token)
    if not token_info:
        return Decimal("0")
    
    network = token_info["network"]
    
    async with db_manager.session() as session:
        # Get wallet
        wallet = await session.scalar(
            select(Wallet).where(
                Wallet.user_id == user_id,
                Wallet.network == network,
                Wallet.is_active == True
            )
        )
        
        if not wallet:
            return Decimal("0")
        
        # Get balance
        balance = await session.scalar(
            select(WalletBalance).where(
                WalletBalance.wallet_id == wallet.id,
                WalletBalance.token_symbol == token
            )
        )
        
        if not balance:
            return Decimal("0")
        
        # Available = balance - locked
        locked = Decimal(str(getattr(balance, 'locked_balance', 0) or 0))
        available = balance.balance - locked
        
        return max(Decimal("0"), available)


async def get_user_by_telegram_id(telegram_id: int) -> Optional[User]:
    """Get user by telegram ID."""
    async with db_manager.session() as session:
        return await session.scalar(
            select(User).where(User.telegram_id == telegram_id)
        )


async def create_pending_transfer(
    sender_id: str,
    sender_tg_id: int,
    amount: Decimal,
    token: str,
    message: Optional[str] = None
) -> str:
    """Create pending transfer and return transfer ID."""
    transfer_id = str(uuid.uuid4())[:8]
    
    pending_transfers[transfer_id] = {
        "sender_id": sender_id,
        "sender_tg_id": sender_tg_id,
        "amount": str(amount),
        "token": token,
        "message": message,
        "created_at": datetime.utcnow(),
        "status": "pending",
        "recipient_id": None,
        "recipient_tg_id": None,
    }
    
    logger.info(
        "Pending transfer created",
        transfer_id=transfer_id,
        sender_tg_id=sender_tg_id,
        amount=str(amount),
        token=token
    )
    
    return transfer_id


def get_pending_transfer(transfer_id: str) -> Optional[Dict[str, Any]]:
    """Get pending transfer by ID."""
    transfer = pending_transfers.get(transfer_id)
    
    if not transfer:
        return None
    
    # Check expiry
    created_at = transfer["created_at"]
    if datetime.utcnow() - created_at > timedelta(minutes=TRANSFER_EXPIRY_MINUTES):
        del pending_transfers[transfer_id]
        return None
    
    return transfer


def cleanup_expired_transfers():
    """Remove expired transfers from cache."""
    now = datetime.utcnow()
    expired = [
        tid for tid, data in pending_transfers.items()
        if now - data["created_at"] > timedelta(minutes=TRANSFER_EXPIRY_MINUTES)
    ]
    for tid in expired:
        del pending_transfers[tid]


# ==================== INLINE QUERY HANDLER ====================

@router.inline_query()
async def handle_inline_query(inline_query: InlineQuery) -> None:
    """
    Handle inline queries for transfers.
    Usage: @bot_username 100 TON [optional message]
    """
    query_text = inline_query.query.strip()
    user_id = inline_query.from_user.id
    
    # Get sender
    sender = await get_user_by_telegram_id(user_id)
    
    if not sender:
        # User not registered
        await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    id="not_registered",
                    title="❌ You're not registered",
                    description="Open the bot first to create an account",
                    input_message_content=InputTextMessageContent(
                        message_text="I need to register in @NEXUS_WALLET_bot first!"
                    )
                )
            ],
            cache_time=5,
            is_personal=True
        )
        return
    
    # Empty query - show help
    if not query_text:
        await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    id="help",
                    title="💸 Send Crypto",
                    description="Type: amount TOKEN (e.g., 100 TON)",
                    input_message_content=InputTextMessageContent(
                        message_text="💡 To send crypto, type: @NEXUS_WALLET_bot 100 TON"
                    )
                )
            ],
            cache_time=5,
            is_personal=True
        )
        return
    
    # Parse query
    amount, token, message = parse_inline_query(query_text)
    
    if not amount or not token:
        # Show available tokens
        tokens_list = ", ".join(SUPPORTED_TOKENS.keys())
        await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    id="invalid_format",
                    title="❓ Invalid format",
                    description=f"Use: 100 TON or 50 ETH. Available: {tokens_list}",
                    input_message_content=InputTextMessageContent(
                        message_text=f"💡 Format: @NEXUS_WALLET_bot [amount] [token]\nAvailable tokens: {tokens_list}"
                    )
                )
            ],
            cache_time=5,
            is_personal=True
        )
        return
    
    # Check balance
    balance = await get_user_balance(sender.id, token)
    token_info = SUPPORTED_TOKENS[token]
    
    if balance < amount:
        await inline_query.answer(
            results=[
                InlineQueryResultArticle(
                    id="insufficient_balance",
                    title=f"❌ Insufficient balance",
                    description=f"You have {balance} {token}, need {amount} {token}",
                    input_message_content=InputTextMessageContent(
                        message_text=f"❌ I don't have enough {token} to send."
                    )
                )
            ],
            cache_time=5,
            is_personal=True
        )
        return
    
    # Create pending transfer
    transfer_id = await create_pending_transfer(
        sender_id=sender.id,
        sender_tg_id=user_id,
        amount=amount,
        token=token,
        message=message
    )
    
    # Build result
    icon = token_info["icon"]
    title = f"{icon} Send {amount} {token}"
    description = f"Click to send • Balance: {balance} {token}"
    
    if message:
        description += f" • Message: {message[:30]}"
    
    # Message that will be sent to the chat
    transfer_text = f"""
{icon} <b>Crypto Transfer</b>

💰 <b>Amount:</b> {amount} {token}
👤 <b>From:</b> {inline_query.from_user.first_name}
"""
    
    if message:
        transfer_text += f"💬 <b>Message:</b> {message}\n"
    
    transfer_text += f"""
⏳ <b>Status:</b> Waiting for recipient

<i>Click the button below to receive this transfer.</i>
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=f"✅ Receive {amount} {token}",
            callback_data=f"inline_receive:{transfer_id}"
        )],
        [InlineKeyboardButton(
            text="❌ Cancel",
            callback_data=f"inline_cancel:{transfer_id}"
        )]
    ])
    
    await inline_query.answer(
        results=[
            InlineQueryResultArticle(
                id=transfer_id,
                title=title,
                description=description,
                input_message_content=InputTextMessageContent(
                    message_text=transfer_text,
                    parse_mode="HTML"
                ),
                reply_markup=keyboard
            )
        ],
        cache_time=0,  # Don't cache - each transfer is unique
        is_personal=True
    )


# ==================== RECEIVE TRANSFER ====================

@router.callback_query(F.data.startswith("inline_receive:"))
async def handle_receive_transfer(callback: CallbackQuery, bot: Bot) -> None:
    """Handle when someone clicks to receive the transfer."""
    transfer_id = callback.data.split(":")[1]
    recipient_tg_id = callback.from_user.id
    
    # Get pending transfer
    transfer = get_pending_transfer(transfer_id)
    
    if not transfer:
        await callback.answer("❌ Transfer expired or not found", show_alert=True)
        try:
            await callback.message.edit_text(
                "❌ <b>Transfer Expired</b>\n\nThis transfer is no longer available.",
                parse_mode="HTML"
            )
        except:
            pass
        return
    
    # Check if sender is trying to receive their own transfer
    if transfer["sender_tg_id"] == recipient_tg_id:
        await callback.answer("❌ You can't receive your own transfer!", show_alert=True)
        return
    
    # Check if already claimed
    if transfer["status"] != "pending":
        await callback.answer("❌ This transfer was already claimed", show_alert=True)
        return
    
    # Get recipient user
    recipient = await get_user_by_telegram_id(recipient_tg_id)
    
    if not recipient:
        await callback.answer(
            "❌ You need to register first! Open the bot to create an account.",
            show_alert=True
        )
        return
    
    # Mark as processing
    transfer["status"] = "processing"
    transfer["recipient_id"] = recipient.id
    transfer["recipient_tg_id"] = recipient_tg_id
    
    # Show confirmation to recipient
    amount = Decimal(transfer["amount"])
    token = transfer["token"]
    token_info = SUPPORTED_TOKENS[token]
    icon = token_info["icon"]
    
    confirm_text = f"""
{icon} <b>Confirm Transfer Receipt</b>

💰 <b>Amount:</b> {amount} {token}
👤 <b>From:</b> User {transfer["sender_tg_id"]}

Do you want to receive this transfer?
"""
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Confirm",
                callback_data=f"inline_confirm:{transfer_id}"
            ),
            InlineKeyboardButton(
                text="❌ Decline",
                callback_data=f"inline_decline:{transfer_id}"
            )
        ]
    ])
    
    # Send confirmation to recipient via bot
    try:
        await bot.send_message(
            chat_id=recipient_tg_id,
            text=confirm_text,
            reply_markup=keyboard,
            parse_mode="HTML"
        )
        await callback.answer("📩 Check your bot chat to confirm the transfer!")
    except Exception as e:
        logger.error("Failed to send confirmation", error=str(e))
        transfer["status"] = "pending"  # Reset status
        await callback.answer("❌ Failed to send confirmation. Please open the bot first.", show_alert=True)


# ==================== CONFIRM TRANSFER ====================

@router.callback_query(F.data.startswith("inline_confirm:"))
async def handle_confirm_transfer(callback: CallbackQuery, bot: Bot) -> None:
    """Handle transfer confirmation."""
    transfer_id = callback.data.split(":")[1]
    recipient_tg_id = callback.from_user.id
    
    # Get pending transfer
    transfer = get_pending_transfer(transfer_id)
    
    if not transfer:
        await callback.answer("❌ Transfer expired", show_alert=True)
        await callback.message.edit_text("❌ Transfer expired or not found.")
        return
    
    if transfer["recipient_tg_id"] != recipient_tg_id:
        await callback.answer("❌ This transfer is not for you", show_alert=True)
        return
    
    if transfer["status"] not in ["pending", "processing"]:
        await callback.answer("❌ Transfer already processed", show_alert=True)
        return
    
    # Execute transfer
    amount = Decimal(transfer["amount"])
    token = transfer["token"]
    token_info = SUPPORTED_TOKENS[token]
    network = token_info["network"]
    icon = token_info["icon"]
    
    try:
        async with db_manager.session() as session:
            # Get sender
            sender = await session.scalar(
                select(User).where(User.id == transfer["sender_id"])
            )
            
            # Get recipient
            recipient = await session.scalar(
                select(User).where(User.id == transfer["recipient_id"])
            )
            
            if not sender or not recipient:
                raise ValueError("Sender or recipient not found")
            
            # Get sender wallet and balance
            sender_wallet = await session.scalar(
                select(Wallet).where(
                    Wallet.user_id == sender.id,
                    Wallet.network == network,
                    Wallet.is_active == True
                )
            )
            
            if not sender_wallet:
                raise ValueError("Sender wallet not found")
            
            sender_balance = await session.scalar(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == sender_wallet.id,
                    WalletBalance.token_symbol == token
                )
            )
            
            if not sender_balance or sender_balance.balance < amount:
                raise ValueError("Insufficient balance")
            
            # Get or create recipient wallet
            recipient_wallet = await session.scalar(
                select(Wallet).where(
                    Wallet.user_id == recipient.id,
                    Wallet.network == network,
                    Wallet.is_active == True
                )
            )
            
            if not recipient_wallet:
                # Create wallet for recipient
                from blockchain.wallet_manager import wallet_manager
                wallet_data = await wallet_manager.create_wallet(network)
                recipient_wallet = Wallet(
                    id=str(uuid.uuid4()),
                    user_id=recipient.id,
                    network=network,
                    address=wallet_data.address,
                    encrypted_private_key=wallet_data.private_key,
                    is_active=True
                )
                session.add(recipient_wallet)
                await session.flush()
            
            # Get or create recipient balance
            recipient_balance = await session.scalar(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == recipient_wallet.id,
                    WalletBalance.token_symbol == token
                )
            )
            
            if not recipient_balance:
                recipient_balance = WalletBalance(
                    wallet_id=recipient_wallet.id,
                    token_symbol=token,
                    balance=Decimal("0")
                )
                session.add(recipient_balance)
            
            # Execute transfer
            sender_balance.balance -= amount
            recipient_balance.balance += amount
            
            # Create transaction records
            tx_id = str(uuid.uuid4())
            
            # Sender transaction (outgoing)
            sender_tx = Transaction(
                id=tx_id,
                user_id=sender.id,
                wallet_id=sender_wallet.id,
                tx_type=TransactionType.TRANSFER,
                network=network,
                token_symbol=token,
                amount=amount,
                status=TransactionStatus.COMPLETED,
                from_address=sender_wallet.address,
                to_address=recipient_wallet.address,
                created_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
            session.add(sender_tx)
            
            # Recipient transaction (incoming)
            recipient_tx = Transaction(
                id=str(uuid.uuid4()),
                user_id=recipient.id,
                wallet_id=recipient_wallet.id,
                tx_type=TransactionType.TRANSFER,
                network=network,
                token_symbol=token,
                amount=amount,
                status=TransactionStatus.COMPLETED,
                from_address=sender_wallet.address,
                to_address=recipient_wallet.address,
                created_at=datetime.utcnow(),
                completed_at=datetime.utcnow()
            )
            session.add(recipient_tx)
            
            await session.commit()
            
            # Update transfer status
            transfer["status"] = "completed"
            transfer["tx_id"] = tx_id
            
            logger.info(
                "Inline transfer completed",
                transfer_id=transfer_id,
                tx_id=tx_id,
                sender_tg_id=transfer["sender_tg_id"],
                recipient_tg_id=recipient_tg_id,
                amount=str(amount),
                token=token
            )
        
        # Success message to recipient
        success_text = f"""
✅ <b>Transfer Received!</b>

{icon} <b>Amount:</b> {amount} {token}
👤 <b>From:</b> User {transfer["sender_tg_id"]}
🧾 <b>TX ID:</b> <code>{tx_id[:8]}...</code>

The funds have been added to your wallet.
"""
        
        await callback.message.edit_text(success_text, parse_mode="HTML")
        
        # Notify sender
        try:
            sender_text = f"""
✅ <b>Transfer Sent Successfully!</b>

{icon} <b>Amount:</b> {amount} {token}
👤 <b>To:</b> {callback.from_user.first_name}
🧾 <b>TX ID:</b> <code>{tx_id[:8]}...</code>

The transfer has been completed.
"""
            await bot.send_message(
                chat_id=transfer["sender_tg_id"],
                text=sender_text,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning("Failed to notify sender", error=str(e))
        
        await callback.answer("✅ Transfer received!")
        
        # Remove from pending
        if transfer_id in pending_transfers:
            del pending_transfers[transfer_id]
        
    except Exception as e:
        logger.error("Transfer execution failed", error=str(e), exc_info=True)
        transfer["status"] = "failed"
        await callback.answer(f"❌ Transfer failed: {str(e)[:50]}", show_alert=True)
        await callback.message.edit_text(
            f"❌ <b>Transfer Failed</b>\n\nError: {str(e)[:100]}",
            parse_mode="HTML"
        )


# ==================== DECLINE TRANSFER ====================

@router.callback_query(F.data.startswith("inline_decline:"))
async def handle_decline_transfer(callback: CallbackQuery) -> None:
    """Handle transfer decline."""
    transfer_id = callback.data.split(":")[1]
    
    transfer = get_pending_transfer(transfer_id)
    
    if transfer:
        transfer["status"] = "declined"
        if transfer_id in pending_transfers:
            del pending_transfers[transfer_id]
    
    await callback.message.edit_text("❌ <b>Transfer Declined</b>", parse_mode="HTML")
    await callback.answer("Transfer declined")


# ==================== CANCEL TRANSFER (by sender) ====================

@router.callback_query(F.data.startswith("inline_cancel:"))
async def handle_cancel_transfer(callback: CallbackQuery) -> None:
    """Handle transfer cancellation by sender."""
    transfer_id = callback.data.split(":")[1]
    sender_tg_id = callback.from_user.id
    
    transfer = get_pending_transfer(transfer_id)
    
    if not transfer:
        await callback.answer("❌ Transfer not found", show_alert=True)
        return
    
    # Only sender can cancel
    if transfer["sender_tg_id"] != sender_tg_id:
        await callback.answer("❌ Only the sender can cancel this transfer", show_alert=True)
        return
    
    if transfer["status"] != "pending":
        await callback.answer("❌ Cannot cancel - transfer is being processed", show_alert=True)
        return
    
    # Cancel transfer
    transfer["status"] = "cancelled"
    if transfer_id in pending_transfers:
        del pending_transfers[transfer_id]
    
    try:
        await callback.message.edit_text(
            "❌ <b>Transfer Cancelled</b>\n\nThe sender cancelled this transfer.",
            parse_mode="HTML"
        )
    except:
        pass
    
    await callback.answer("Transfer cancelled")


# ==================== REGISTER ROUTER ====================

def register_inline_transfer_handlers(dp) -> None:
    """Register inline transfer handlers."""
    dp.include_router(router)