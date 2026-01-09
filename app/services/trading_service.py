"""
NEXUS WALLET - Trading Engine
Handles leverage, PnL calculations and order execution
"""

import httpx
from decimal import Decimal
from datetime import datetime
from sqlalchemy import select, update
from database.connection import db_manager
from database.models import TradePosition, User # Импортируй свои модели

class TradingService:
    def __init__(self):
        self.base_url = "https://api.binance.com/api/v3"

    async def get_current_price(self, symbol: str) -> float:
        """Get live price from Binance"""
        # symbol example: BTCUSDT
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.base_url}/ticker/price?symbol={symbol.upper()}")
            data = resp.json()
            return float(data['price'])

    def calculate_liquidation(self, entry_price: float, leverage: int, direction: str) -> float:
        """Calculate liquidation price"""
        # Simplified formula
        maintenance_margin = 0.005 # 0.5%
        if direction == "LONG":
            # Liq = Entry * (1 - 1/Lev + Maint)
            return entry_price * (1 - (1/leverage) + maintenance_margin)
        else:
            # Liq = Entry * (1 + 1/Lev - Maint)
            return entry_price * (1 + (1/leverage) - maintenance_margin)

    async def open_position(self, user_id: int, symbol: str, direction: str, amount: float, leverage: int):
        current_price = await self.get_current_price(symbol)
        liq_price = self.calculate_liquidation(current_price, leverage, direction)

        async with db_manager.session() as session:
            # Здесь можно добавить проверку баланса пользователя и списание средств
            
            position = TradePosition(
                user_id=user_id,
                symbol=symbol,
                direction=direction,
                amount_usd=amount,
                leverage=leverage,
                entry_price=current_price,
                liquidation_price=liq_price
            )
            session.add(position)
            await session.commit()
            return position

    async def close_position(self, position_id: int):
        async with db_manager.session() as session:
            result = await session.execute(select(TradePosition).where(TradePosition.id == position_id))
            pos = result.scalar_one_or_none()
            
            if not pos or not pos.is_open:
                return None

            current_price = await self.get_current_price(pos.symbol)
            
            # Calculate PnL
            # PnL = (Exit - Entry) * (Amount / Entry) * Leverage
            # Simplified for USD margin:
            if pos.direction == "LONG":
                pnl_percent = (current_price - pos.entry_price) / pos.entry_price
            else:
                pnl_percent = (pos.entry_price - current_price) / pos.entry_price
            
            realized_pnl = pos.amount_usd * pnl_percent * pos.leverage

            # Update DB
            pos.is_open = False
            pos.closed_at = datetime.utcnow()
            pos.pnl = realized_pnl
            
            # Здесь нужно вернуть деньги + прибыль на баланс юзера
            
            await session.commit()
            return pos

trading_service = TradingService()