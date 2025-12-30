import json
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import P2POrder

class P2PService:
    async def get_active_orders(self, session: AsyncSession, order_type: str, limit: int = 10) -> List[P2POrder]:
        result = await session.execute(
            select(P2POrder).where(P2POrder.order_type == order_type).where(P2POrder.status == 'active').limit(limit)
        )
        return list(result.scalars().all())

p2p_service = P2PService()