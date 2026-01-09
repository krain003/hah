"""
NEXUS WALLET - Shop Service
Mini-shops system for verified merchants
"""

from __future__ import annotations

from decimal import Decimal
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple, TYPE_CHECKING
from enum import Enum

from sqlalchemy import select, func, desc
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession
import structlog

from database.models import (
    User, Shop, ShopProduct, ShopOrder, ShopApplication,
    ShopStatus, ShopApplicationStatus, Wallet, WalletBalance
)

if TYPE_CHECKING:
    pass

logger = structlog.get_logger(__name__)


# ==================== CONSTANTS ====================

class ShopError(Enum):
    """Shop error types"""
    USER_NOT_FOUND = "User not found"
    SHOP_NOT_FOUND = "Shop not found"
    ALREADY_HAS_SHOP = "You already have a shop"
    PENDING_APPLICATION = "You have a pending application"
    APPLICATION_NOT_FOUND = "Application not found"
    ALREADY_PROCESSED = "Application already processed"
    ACCESS_DENIED = "Access denied"
    SHOP_NOT_ACTIVE = "Shop is not active"
    UNSUPPORTED_NETWORK = "Unsupported network"
    PRODUCT_EXISTS = "Product for this network already exists"
    NO_WALLET = "No wallet found for this network"
    INSUFFICIENT_BALANCE = "Insufficient balance"
    PRODUCT_NOT_AVAILABLE = "Product not available"
    CANNOT_BUY_OWN = "Cannot buy from your own shop"
    PRICE_UNAVAILABLE = "Price unavailable"
    ORDER_TOO_SMALL = "Order amount too small"
    ORDER_TOO_LARGE = "Order amount too large"
    ORDER_NOT_FOUND = "Order not found"
    ORDER_ALREADY_PROCESSED = "Order already processed"


SHOP_REQUIREMENTS = {
    "min_trades": 50,
    "min_volume_usd": 10000.0,
    "min_success_rate": 95.0,
    "min_rating": 90.0,
    "min_account_age_days": 30,
    "no_disputes": True,
    "verified_merchant_required": False,
}

SHOP_COMMISSION_RATE = Decimal("20.0")


# ==================== SUPPORTED CRYPTOS ====================

SUPPORTED_CRYPTOS: Dict[str, Dict[str, Any]] = {
    "ton": {"symbol": "TON", "icon": "💎", "decimals": 9},
    "eth": {"symbol": "ETH", "icon": "⟠", "decimals": 18},
    "bsc": {"symbol": "BNB", "icon": "🟡", "decimals": 18},
    "polygon": {"symbol": "MATIC", "icon": "🟣", "decimals": 18},
    "tron": {"symbol": "TRX", "icon": "🔴", "decimals": 6},
    "solana": {"symbol": "SOL", "icon": "🟢", "decimals": 9},
    "bitcoin": {"symbol": "BTC", "icon": "₿", "decimals": 8},
}

SUPPORTED_FIATS: Dict[str, Dict[str, str]] = {
    "USD": {"symbol": "$", "name": "US Dollar"},
    "EUR": {"symbol": "€", "name": "Euro"},
    "RUB": {"symbol": "₽", "name": "Russian Ruble"},
}


# ==================== SHOP SERVICE CLASS ====================

class ShopService:
    """Complete Shop Management Service"""
    
    def __init__(self, commission_rate: Decimal = SHOP_COMMISSION_RATE):
        self.commission_rate = commission_rate
        self._price_cache: Dict[str, Tuple[Decimal, datetime]] = {}
        self._cache_ttl = timedelta(seconds=30)
    
    async def check_eligibility(
        self,
        session: AsyncSession,
        user_id: str
    ) -> Tuple[bool, List[str], Dict[str, Any]]:
        """Check if user is eligible to apply for a shop."""
        user = await session.get(User, user_id)
        
        if not user:
            return False, [ShopError.USER_NOT_FOUND.value], {}
        
        # ===== COLLECT STATS FIRST (before any early returns) =====
        stats = {}
        req = SHOP_REQUIREMENTS
        
        # Trades
        total_trades = getattr(user, 'total_trades_count', 0) or 0
        stats['total_trades'] = total_trades
        
        # Volume
        volume_usd = float(getattr(user, 'total_volume_usd', 0) or 0)
        stats['volume_usd'] = volume_usd
        
        # Success rate
        successful_trades = getattr(user, 'successful_trades_count', 0) or 0
        if total_trades > 0:
            success_rate = (successful_trades / total_trades) * 100
        else:
            success_rate = 0
        stats['success_rate'] = success_rate
        
        # Rating
        rating = float(getattr(user, 'rating', 0) or 0)
        stats['rating'] = rating
        
        # Account age
        created_at = getattr(user, 'created_at', None)
        if created_at:
            account_age = (datetime.utcnow() - created_at).days
        else:
            account_age = 0
        stats['account_age_days'] = account_age
        
        # Disputes
        disputed_trades = getattr(user, 'disputed_trades_count', 0) or 0
        stats['disputed_trades'] = disputed_trades
        
        stats['is_verified'] = getattr(user, 'merchant_verified', False)
        # ===== END COLLECT STATS =====
        
        # ===== DEBUG LOG =====
        logger.info(
            "DEBUG: User attributes for eligibility check",
            user_id=user_id,
            telegram_id=getattr(user, 'telegram_id', 'N/A'),
            total_trades_count=total_trades,
            total_volume_usd=volume_usd,
            rating=rating,
            account_age_days=account_age,
            disputed_trades_count=disputed_trades,
            has_shop=getattr(user, 'has_shop', False),
            merchant_verified=stats['is_verified']
        )
        # ===== END DEBUG =====
        
        # ===== CHECK BLOCKING CONDITIONS (return stats even on early exit!) =====
        if getattr(user, 'has_shop', False):
            return False, [ShopError.ALREADY_HAS_SHOP.value], stats
        
        # Check for pending application
        existing_app = await session.execute(
            select(ShopApplication).where(
                ShopApplication.user_id == user_id,
                ShopApplication.status == ShopApplicationStatus.PENDING
            )
        )
        if existing_app.scalar_one_or_none():
            return False, [ShopError.PENDING_APPLICATION.value], stats
        
        # ===== CHECK REQUIREMENTS =====
        errors = []
        
        if total_trades < req['min_trades']:
            errors.append(f"Need {req['min_trades']} trades (you have {total_trades})")
        
        if volume_usd < req['min_volume_usd']:
            errors.append(f"Need ${req['min_volume_usd']:,.0f} volume (you have ${volume_usd:,.0f})")
        
        if success_rate < req['min_success_rate']:
            errors.append(f"Need {req['min_success_rate']}% success rate (you have {success_rate:.1f}%)")
        
        if rating < req['min_rating']:
            errors.append(f"Need {req['min_rating']} rating (you have {rating:.1f})")
        
        if account_age < req['min_account_age_days']:
            errors.append(f"Account must be {req['min_account_age_days']} days old (yours is {account_age} days)")
        
        if req['no_disputes'] and disputed_trades > 0:
            errors.append(f"Must have no disputed trades (you have {disputed_trades})")
        
        return len(errors) == 0, errors, stats
    
    async def submit_application(
        self,
        session: AsyncSession,
        user_id: str,
        shop_name: str,
        description: str,
        motivation: str,
        proposed_tokens: List[Dict[str, str]]
    ) -> Tuple[Optional[ShopApplication], List[str]]:
        """Submit shop application."""
        is_eligible, errors, _ = await self.check_eligibility(session, user_id)
        
        if not is_eligible:
            return None, errors
        
        if not shop_name or len(shop_name.strip()) < 3:
            return None, ["Shop name must be at least 3 characters"]
        
        if len(shop_name) > 50:
            return None, ["Shop name too long (max 50 characters)"]
        
        if not motivation or len(motivation.strip()) < 50:
            return None, ["Please provide more details in motivation (min 50 characters)"]
        
        if not proposed_tokens:
            return None, ["Select at least one token to sell"]
        
        valid_tokens = []
        for token in proposed_tokens:
            network = token.get('network')
            if network in SUPPORTED_CRYPTOS:
                valid_tokens.append({
                    "network": network,
                    "symbol": SUPPORTED_CRYPTOS[network]['symbol']
                })
        
        if not valid_tokens:
            return None, ["No valid tokens selected"]
        
        application = ShopApplication(
            user_id=user_id,
            shop_name=shop_name,
            description=description,
            motivation=motivation,
            proposed_tokens=valid_tokens,
            status=ShopApplicationStatus.PENDING
        )
        
        session.add(application)
        await session.flush()
        
        logger.info("Shop application submitted", user_id=user_id, app_id=application.id)
        
        return application, []
    
    async def get_pending_applications(self, session: AsyncSession) -> List[ShopApplication]:
        """Get all pending applications."""
        result = await session.execute(
            select(ShopApplication)
            .where(ShopApplication.status == ShopApplicationStatus.PENDING)
            .options(selectinload(ShopApplication.user))
            .order_by(ShopApplication.created_at.asc())
        )
        return list(result.scalars().all())
    
    async def get_application_by_id(self, session: AsyncSession, app_id: str) -> Optional[ShopApplication]:
        """Get application by ID."""
        result = await session.execute(
            select(ShopApplication)
            .where(ShopApplication.id == app_id)
            .options(selectinload(ShopApplication.user))
        )
        return result.scalar_one_or_none()
    
    async def approve_application(
        self,
        session: AsyncSession,
        app_id: str,
        admin_id: int,
        notes: str = ""
    ) -> Tuple[Optional[Shop], str]:
        """Approve shop application and create shop."""
        application = await self.get_application_by_id(session, app_id)
        
        if not application:
            return None, ShopError.APPLICATION_NOT_FOUND.value
        
        if application.status != ShopApplicationStatus.PENDING:
            return None, ShopError.ALREADY_PROCESSED.value
        
        user = await session.get(User, application.user_id)
        if not user:
            return None, ShopError.USER_NOT_FOUND.value
        
        shop = Shop(
            owner_id=user.id,
            name=application.shop_name,
            description=application.description,
            supported_tokens=application.proposed_tokens,
            status=ShopStatus.APPROVED,
            commission_rate=float(self.commission_rate),
            approved_at=datetime.utcnow()
        )
        
        session.add(shop)
        
        application.status = ShopApplicationStatus.APPROVED
        application.reviewed_by = admin_id
        application.review_notes = notes
        application.reviewed_at = datetime.utcnow()
        
        user.has_shop = True
        
        await session.flush()
        user.shop_id = shop.id
        
        logger.info("Shop approved", shop_id=shop.id, owner_id=user.id, admin_id=admin_id)
        
        return shop, "Shop created successfully"
    
    async def reject_application(
        self,
        session: AsyncSession,
        app_id: str,
        admin_id: int,
        reason: str
    ) -> Tuple[bool, str]:
        """Reject shop application."""
        application = await self.get_application_by_id(session, app_id)
        
        if not application:
            return False, ShopError.APPLICATION_NOT_FOUND.value
        
        if application.status != ShopApplicationStatus.PENDING:
            return False, ShopError.ALREADY_PROCESSED.value
        
        application.status = ShopApplicationStatus.REJECTED
        application.reviewed_by = admin_id
        application.review_notes = reason
        application.reviewed_at = datetime.utcnow()
        
        logger.info("Shop application rejected", app_id=app_id, admin_id=admin_id)
        
        return True, "Application rejected"
    
    async def get_shop_by_owner(self, session: AsyncSession, user_id: str) -> Optional[Shop]:
        """Get shop by owner ID."""
        result = await session.execute(
            select(Shop)
            .where(Shop.owner_id == user_id)
            .options(selectinload(Shop.products))
        )
        return result.scalar_one_or_none()
    
    async def get_shop_by_id(self, session: AsyncSession, shop_id: str) -> Optional[Shop]:
        """Get shop by ID."""
        result = await session.execute(
            select(Shop)
            .where(Shop.id == shop_id)
            .options(selectinload(Shop.owner), selectinload(Shop.products))
        )
        return result.scalar_one_or_none()
    
    async def get_active_shops(self, session: AsyncSession, limit: int = 20) -> List[Shop]:
        """Get all active shops."""
        result = await session.execute(
            select(Shop)
            .where(Shop.status == ShopStatus.APPROVED)
            .options(selectinload(Shop.owner))
            .order_by(desc(Shop.total_volume_usd))
            .limit(limit)
        )
        return list(result.scalars().all())
    
    async def update_shop_settings(self, session: AsyncSession, shop_id: str, owner_id: str, **kwargs) -> Tuple[bool, str]:
        """Update shop settings."""
        shop = await self.get_shop_by_id(session, shop_id)
        
        if not shop:
            return False, ShopError.SHOP_NOT_FOUND.value
        
        if shop.owner_id != owner_id:
            return False, ShopError.ACCESS_DENIED.value
        
        allowed_fields = {'name', 'description', 'default_margin', 'min_order_usd', 'max_order_usd'}
        
        for field, value in kwargs.items():
            if field in allowed_fields and value is not None:
                setattr(shop, field, value)
        
        return True, "Settings updated"
    
    async def suspend_shop(self, session: AsyncSession, shop_id: str, admin_id: int, reason: str) -> Tuple[bool, str]:
        """Suspend a shop."""
        shop = await self.get_shop_by_id(session, shop_id)
        
        if not shop:
            return False, ShopError.SHOP_NOT_FOUND.value
        
        shop.status = ShopStatus.SUSPENDED
        if hasattr(shop, 'suspended_at'):
            shop.suspended_at = datetime.utcnow()
        
        owner = await session.get(User, shop.owner_id)
        if owner:
            owner.has_shop = False
        
        logger.warning("Shop suspended", shop_id=shop_id, admin_id=admin_id, reason=reason[:200])
        
        return True, "Shop suspended"
    
    async def reactivate_shop(self, session: AsyncSession, shop_id: str, admin_id: int) -> Tuple[bool, str]:
        """Reactivate a suspended shop."""
        shop = await self.get_shop_by_id(session, shop_id)
        
        if not shop:
            return False, ShopError.SHOP_NOT_FOUND.value
        
        if shop.status != ShopStatus.SUSPENDED:
            return False, "Shop is not suspended"
        
        shop.status = ShopStatus.APPROVED
        if hasattr(shop, 'suspended_at'):
            shop.suspended_at = None
        
        owner = await session.get(User, shop.owner_id)
        if owner:
            owner.has_shop = True
        
        logger.info("Shop reactivated", shop_id=shop_id, admin_id=admin_id)
        
        return True, "Shop reactivated"
    
    async def add_product(
        self,
        session: AsyncSession,
        shop_id: str,
        owner_id: str,
        network: str,
        amount: Decimal,
        margin_percentage: float = 2.0
    ) -> Tuple[Optional[ShopProduct], str]:
        """Add a product to shop."""
        shop = await self.get_shop_by_id(session, shop_id)
        
        if not shop:
            return None, ShopError.SHOP_NOT_FOUND.value
        
        if shop.owner_id != owner_id:
            return None, ShopError.ACCESS_DENIED.value
        
        if shop.status != ShopStatus.APPROVED:
            return None, ShopError.SHOP_NOT_ACTIVE.value
        
        if network not in SUPPORTED_CRYPTOS:
            return None, ShopError.UNSUPPORTED_NETWORK.value
        
        crypto = SUPPORTED_CRYPTOS[network]
        
        existing = await session.execute(
            select(ShopProduct).where(
                ShopProduct.shop_id == shop_id,
                ShopProduct.network == network,
                ShopProduct.is_active == True
            )
        )
        if existing.scalar_one_or_none():
            return None, f"Product for {network.upper()} already exists"
        
        wallet_result = await session.execute(
            select(Wallet).where(
                Wallet.user_id == owner_id,
                Wallet.network == network,
                Wallet.is_active == True
            )
        )
        wallet = wallet_result.scalar_one_or_none()
        
        if not wallet:
            return None, f"No wallet found for {network.upper()}"
        
        balance_result = await session.execute(
            select(WalletBalance).where(
                WalletBalance.wallet_id == wallet.id,
                WalletBalance.token_symbol == crypto['symbol']
            )
        )
        balance = balance_result.scalar_one_or_none()
        
        locked = Decimal(str(getattr(balance, 'locked_balance', 0) or 0))
        available = Decimal(str(balance.balance if balance else 0)) - locked
        
        if available < amount:
            return None, f"Insufficient balance. Available: {available} {crypto['symbol']}"
        
        product = ShopProduct(
            shop_id=shop_id,
            network=network,
            token_symbol=crypto['symbol'],
            available_amount=amount,
            margin_percentage=margin_percentage,
            is_active=True
        )
        
        session.add(product)
        
        if balance:
            balance.locked_balance = locked + amount
        
        await session.flush()
        
        logger.info("Product added", shop_id=shop_id, product_id=product.id, network=network)
        
        return product, "Product added"
    
    async def update_product_stock(self, session: AsyncSession, product_id: str, owner_id: str, new_amount: Decimal) -> Tuple[bool, str]:
        """Update product stock."""
        product = await session.get(ShopProduct, product_id)
        
        if not product:
            return False, "Product not found"
        
        shop = await self.get_shop_by_id(session, product.shop_id)
        if not shop or shop.owner_id != owner_id:
            return False, ShopError.ACCESS_DENIED.value
        
        diff = new_amount - product.available_amount
        
        wallet_result = await session.execute(
            select(Wallet).where(Wallet.user_id == owner_id, Wallet.network == product.network)
        )
        wallet = wallet_result.scalar_one_or_none()
        
        if not wallet:
            return False, ShopError.NO_WALLET.value
        
        balance_result = await session.execute(
            select(WalletBalance).where(
                WalletBalance.wallet_id == wallet.id,
                WalletBalance.token_symbol == product.token_symbol
            )
        )
        balance = balance_result.scalar_one_or_none()
        
        if not balance:
            return False, "Balance not found"
        
        current_locked = Decimal(str(balance.locked_balance or 0))
        
        if diff > 0:
            available = Decimal(str(balance.balance)) - current_locked
            if available < diff:
                return False, f"Insufficient balance. Available: {available}"
            balance.locked_balance = current_locked + diff
        else:
            balance.locked_balance = max(Decimal("0"), current_locked + diff)
        
        product.available_amount = new_amount
        
        return True, "Stock updated"
    
    async def remove_product(self, session: AsyncSession, product_id: str, owner_id: str) -> Tuple[bool, str]:
        """Remove product from shop."""
        product = await session.get(ShopProduct, product_id)
        
        if not product:
            return False, "Product not found"
        
        shop = await self.get_shop_by_id(session, product.shop_id)
        if not shop or shop.owner_id != owner_id:
            return False, ShopError.ACCESS_DENIED.value
        
        wallet_result = await session.execute(
            select(Wallet).where(Wallet.user_id == owner_id, Wallet.network == product.network)
        )
        wallet = wallet_result.scalar_one_or_none()
        
        if wallet:
            balance_result = await session.execute(
                select(WalletBalance).where(
                    WalletBalance.wallet_id == wallet.id,
                    WalletBalance.token_symbol == product.token_symbol
                )
            )
            balance = balance_result.scalar_one_or_none()
            
            if balance:
                current_locked = Decimal(str(balance.locked_balance or 0))
                balance.locked_balance = max(Decimal("0"), current_locked - product.available_amount)
        
        product.is_active = False
        
        logger.info("Product removed", product_id=product_id, shop_id=shop.id)
        
        return True, "Product removed"
    
    async def create_order(
        self,
        session: AsyncSession,
        buyer_id: str,
        product_id: str,
        amount: Decimal,
        buyer_address: str
    ) -> Tuple[Optional[ShopOrder], str]:
        """Create shop order."""
        product = await session.get(ShopProduct, product_id)
        
        if not product or not product.is_active:
            return None, ShopError.PRODUCT_NOT_AVAILABLE.value
        
        shop = await self.get_shop_by_id(session, product.shop_id)
        if not shop or shop.status != ShopStatus.APPROVED:
            return None, "Shop not available"
        
        if shop.owner_id == buyer_id:
            return None, ShopError.CANNOT_BUY_OWN.value
        
        if amount > product.available_amount:
            return None, f"Not enough stock. Available: {product.available_amount}"
        
        price = await self._get_cached_price(product.token_symbol)
        
        if not price or price <= 0:
            return None, ShopError.PRICE_UNAVAILABLE.value
        
        margin_multiplier = 1 + Decimal(str(product.margin_percentage)) / 100
        price_with_margin = price * margin_multiplier
        total_usd = amount * price_with_margin
        
        min_order = Decimal(str(getattr(shop, 'min_order_usd', 1) or 1))
        max_order = Decimal(str(getattr(shop, 'max_order_usd', 10000) or 10000))
        
        if total_usd < min_order:
            return None, f"Minimum order: ${min_order}"
        
        if total_usd > max_order:
            return None, f"Maximum order: ${max_order}"
        
        commission_rate = Decimal(str(getattr(shop, 'commission_rate', self.commission_rate) or self.commission_rate))
        commission = total_usd * (commission_rate / 100)
        seller_receives = total_usd - commission
        
        order = ShopOrder(
            shop_id=shop.id,
            buyer_id=buyer_id,
            product_id=product_id,
            network=product.network,
            token_symbol=product.token_symbol,
            amount=amount,
            price_usd=total_usd,
            commission_amount=commission,
            seller_receives=seller_receives,
            buyer_address=buyer_address,
            status="pending"
        )
        
        session.add(order)
        product.available_amount -= amount
        
        await session.flush()
        
        logger.info("Shop order created", order_id=order.id, shop_id=shop.id, amount=str(amount))
        
        return order, "Order created"
    
    async def _get_cached_price(self, symbol: str) -> Optional[Decimal]:
        """Get price with caching."""
        now = datetime.utcnow()
        
        if symbol in self._price_cache:
            cached_price, cached_at = self._price_cache[symbol]
            if now - cached_at < self._cache_ttl:
                return cached_price
        
        try:
            from services.price_service import price_service
            price = await price_service.get_price(symbol)
            
            if price and price > 0:
                self._price_cache[symbol] = (price, now)
                return price
        except Exception as e:
            logger.warning("Price fetch failed", symbol=symbol, error=str(e))
        
        if symbol in self._price_cache:
            return self._price_cache[symbol][0]
        
        return None
    
    async def complete_order(self, session: AsyncSession, order_id: str, tx_hash: str) -> Tuple[bool, str]:
        """Complete shop order."""
        order = await session.get(ShopOrder, order_id)
        
        if not order:
            return False, ShopError.ORDER_NOT_FOUND.value
        
        if order.status != "pending":
            return False, ShopError.ORDER_ALREADY_PROCESSED.value
        
        order.status = "completed"
        order.tx_hash = tx_hash
        order.completed_at = datetime.utcnow()
        
        shop = await self.get_shop_by_id(session, order.shop_id)
        if shop:
            shop.total_orders = (getattr(shop, 'total_orders', 0) or 0) + 1
            shop.completed_orders = (getattr(shop, 'completed_orders', 0) or 0) + 1
            shop.total_volume_usd = Decimal(str(getattr(shop, 'total_volume_usd', 0) or 0)) + order.price_usd
            shop.total_commission_paid = Decimal(str(getattr(shop, 'total_commission_paid', 0) or 0)) + order.commission_amount
        
        logger.info("Shop order completed", order_id=order_id, tx_hash=tx_hash)
        
        return True, "Order completed"
    
    async def cancel_order(self, session: AsyncSession, order_id: str, user_id: str, reason: str = "") -> Tuple[bool, str]:
        """Cancel shop order."""
        order = await session.get(ShopOrder, order_id)
        
        if not order:
            return False, ShopError.ORDER_NOT_FOUND.value
        
        if order.status != "pending":
            return False, "Order cannot be cancelled"
        
        shop = await self.get_shop_by_id(session, order.shop_id)
        
        if order.buyer_id != user_id and (not shop or shop.owner_id != user_id):
            return False, ShopError.ACCESS_DENIED.value
        
        order.status = "cancelled"
        
        product = await session.get(ShopProduct, order.product_id)
        if product:
            product.available_amount += order.amount
        
        logger.info("Shop order cancelled", order_id=order_id, user_id=user_id)
        
        return True, "Order cancelled"
    
    async def get_shop_stats(self, session: AsyncSession, shop_id: str) -> Dict[str, Any]:
        """Get shop statistics."""
        shop = await self.get_shop_by_id(session, shop_id)
        
        if not shop:
            return {}
        
        orders_pending = await session.scalar(
            select(func.count(ShopOrder.id)).where(ShopOrder.shop_id == shop_id, ShopOrder.status == "pending")
        ) or 0
        
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        
        today_orders = await session.scalar(
            select(func.count(ShopOrder.id)).where(ShopOrder.shop_id == shop_id, ShopOrder.created_at >= today)
        ) or 0
        
        today_volume = await session.scalar(
            select(func.sum(ShopOrder.price_usd)).where(
                ShopOrder.shop_id == shop_id, ShopOrder.status == "completed", ShopOrder.completed_at >= today
            )
        ) or Decimal("0")
        
        products_count = len([p for p in (shop.products or []) if p.is_active])
        
        return {
            "shop_id": shop_id,
            "name": shop.name,
            "status": shop.status.value if hasattr(shop.status, 'value') else str(shop.status),
            "total_orders": getattr(shop, 'total_orders', 0) or 0,
            "completed_orders": getattr(shop, 'completed_orders', 0) or 0,
            "pending_orders": orders_pending,
            "total_volume_usd": float(getattr(shop, 'total_volume_usd', 0) or 0),
            "total_commission_paid": float(getattr(shop, 'total_commission_paid', 0) or 0),
            "rating": float(getattr(shop, 'rating', 0) or 0),
            "today_orders": today_orders,
            "today_volume_usd": float(today_volume),
            "products_count": products_count,
            "commission_rate": float(getattr(shop, 'commission_rate', self.commission_rate) or self.commission_rate),
            "created_at": shop.created_at.strftime("%Y-%m-%d") if shop.created_at else "N/A"
        }
    
    async def get_all_shops_stats(self, session: AsyncSession) -> Dict[str, Any]:
        """Get global shop statistics."""
        total_shops = await session.scalar(select(func.count(Shop.id))) or 0
        active_shops = await session.scalar(select(func.count(Shop.id)).where(Shop.status == ShopStatus.APPROVED)) or 0
        suspended_shops = await session.scalar(select(func.count(Shop.id)).where(Shop.status == ShopStatus.SUSPENDED)) or 0
        total_volume = await session.scalar(select(func.sum(Shop.total_volume_usd))) or Decimal("0")
        total_commission = await session.scalar(select(func.sum(Shop.total_commission_paid))) or Decimal("0")
        pending_apps = await session.scalar(
            select(func.count(ShopApplication.id)).where(ShopApplication.status == ShopApplicationStatus.PENDING)
        ) or 0
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        today_orders = await session.scalar(select(func.count(ShopOrder.id)).where(ShopOrder.created_at >= today)) or 0
        
        return {
            "total_shops": total_shops,
            "active_shops": active_shops,
            "suspended_shops": suspended_shops,
            "total_volume_usd": float(total_volume),
            "total_commission_usd": float(total_commission),
            "pending_applications": pending_apps,
            "today_orders": today_orders
        }


# ==================== GLOBAL INSTANCE ====================

shop_service = ShopService()