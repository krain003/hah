# handlers/start.py
import os
from aiogram import Router
from aiogram.types import Message, WebAppInfo, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import CommandStart

router = Router()
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://yourapp.onrender.com")

@router.message(CommandStart())
async def cmd_start(message: Message):
    kb = [[InlineKeyboardButton(text="🚀 Open Web Wallet", web_app=WebAppInfo(url=WEB_APP_URL))]]
    await message.answer("Welcome to NEXUS WALLET!", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))