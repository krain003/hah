"""
NEXUS WALLET - Inline Keyboards
Reusable keyboard components
"""

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from typing import List, Optional
from blockchain.wallet_manager import NETWORKS
from locales.messages import get_text


def get_back_keyboard(callback: str, lang: str = "en") -> InlineKeyboardMarkup:
    """Simple back button"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=callback)]
    ])


def get_confirm_keyboard(confirm_callback: str, cancel_callback: str, lang: str = "en") -> InlineKeyboardMarkup:
    """Confirm/Cancel keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ " + get_text("confirm", lang), callback_data=confirm_callback),
            InlineKeyboardButton(text="❌ " + get_text("cancel", lang), callback_data=cancel_callback),
        ]
    ])


def get_networks_keyboard(
    lang: str = "en", 
    action: str = "select",
    user_wallets: Optional[List] = None
) -> InlineKeyboardMarkup:
    """Network selection keyboard"""
    buttons = []
    row = []
    
    # Filter to only show networks user has wallets for (if provided)
    available_networks = NETWORKS.keys()
    if user_wallets:
        available_networks = [w.network for w in user_wallets if w.network in NETWORKS]
    
    for network_id in available_networks:
        config = NETWORKS.get(network_id)
        if not config:
            continue
            
        btn_text = f"{config.icon} {config.symbol}"
        row.append(InlineKeyboardButton(
            text=btn_text,
            callback_data=f"{action}:{network_id}"
        ))
        
        if len(row) == 3:
            buttons.append(row)
            row = []
    
    if row:
        buttons.append(row)
    
    # Back button
    back_callback = "main_menu" if action in ["send", "receive"] else "wallet"
    buttons.append([
        InlineKeyboardButton(text=get_text("btn_back", lang), callback_data=back_callback)
    ])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_main_menu_keyboard(lang: str = "en") -> InlineKeyboardMarkup:
    """Main menu keyboard"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text=get_text("btn_wallet", lang), callback_data="wallet"),
            InlineKeyboardButton(text=get_text("btn_send", lang), callback_data="send"),
            InlineKeyboardButton(text=get_text("btn_receive", lang), callback_data="receive_menu")
        ],
        [
            InlineKeyboardButton(text=get_text("btn_swap", lang), callback_data="swap"),
            InlineKeyboardButton(text=get_text("btn_p2p", lang), callback_data="p2p")
        ],
        [
            InlineKeyboardButton(text=get_text("btn_history", lang), callback_data="history"),
            InlineKeyboardButton(text=get_text("btn_settings", lang), callback_data="settings")
        ],
        [
            InlineKeyboardButton(text=get_text("btn_help", lang), callback_data="help")
        ]
    ])