#!/usr/bin/env python3
"""
NEXUS WALLET - Monitoring Script
Health checks and alerting
"""

import asyncio
import sys
from datetime import datetime, timedelta

import httpx
import structlog

# Add project root to path
sys.path.insert(0, '/app')

from database.connection import db_manager
from blockchain.wallet_manager import wallet_manager
from config.settings import settings

logger = structlog.get_logger()


async def check_database() -> bool:
    """Check database connectivity"""
    try:
        async with db_manager.session() as session:
            await session.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error("Database check failed", error=str(e))
        return False


async def check_redis() -> bool:
    """Check Redis connectivity"""
    try:
        await db_manager.redis.ping()
        return True
    except Exception as e:
        logger.error("Redis check failed", error=str(e))
        return False


async def check_blockchain_nodes() -> dict:
    """Check blockchain node connectivity"""
    results = {}
    
    for network in wallet_manager.get_supported_networks():
        try:
            handler = wallet_manager.get_handler(network)
            # Simple balance check to verify connectivity
            await handler.get_balance("0x0000000000000000000000000000000000000000")
            results[network] = True
        except Exception as e:
            logger.warning(f"Node check failed for {network}", error=str(e))
            results[network] = False
    
    return results


async def check_pending_transactions() -> dict:
    """Check for stuck pending transactions"""
    from database.repositories.transaction_repository import TransactionRepository
    
    async with db_manager.session() as session:
        tx_repo = TransactionRepository()
        pending = await tx_repo.get_pending_transactions(session, older_than_minutes=60)
        
        return {
            'count': len(pending),
            'transactions': [str(tx.id) for tx in pending[:10]]
        }


async def check_escrow_status() -> dict:
    """Check for expired escrows"""
    from database.repositories.order_repository import OrderRepository
    
    async with db_manager.session() as session:
        order_repo = OrderRepository()
        expired = await order_repo.get_expired_escrows(session)
        
        return {
            'expired_count': len(expired),
            'escrows': [str(e.id) for e in expired[:10]]
        }


async def send_alert(message: str, severity: str = "warning") -> None:
    """Send alert notification"""
    # Telegram alert
    if settings.telegram.ADMIN_IDS:
        async with httpx.AsyncClient() as client:
            for admin_id in settings.telegram.ADMIN_IDS:
                try:
                    await client.post(
                        f"https://api.telegram.org/bot{settings.telegram.BOT_TOKEN.get_secret_value()}/sendMessage",
                        json={
                            'chat_id': admin_id,
                            'text': f"🚨 [{severity.upper()}] NEXUS WALLET\n\n{message}",
                            'parse_mode': 'HTML'
                        }
                    )
                except Exception as e:
                    logger.error("Failed to send alert", error=str(e))


async def run_health_check() -> dict:
    """Run all health checks"""
    results = {
        'timestamp': datetime.utcnow().isoformat(),
        'status': 'healthy',
        'checks': {}
    }
    
    # Database
    db_ok = await check_database()
    results['checks']['database'] = 'ok' if db_ok else 'failed'
    
    # Redis
    redis_ok = await check_redis()
    results['checks']['redis'] = 'ok' if redis_ok else 'failed'
    
    # Blockchain nodes
    node_status = await check_blockchain_nodes()
    results['checks']['nodes'] = node_status
    failed_nodes = [n for n, ok in node_status.items() if not ok]
    
    # Pending transactions
    pending = await check_pending_transactions()
    results['checks']['pending_transactions'] = pending
    
    # Escrows
    escrows = await check_escrow_status()
    results['checks']['escrows'] = escrows
    
    # Determine overall status
    if not db_ok or not redis_ok:
        results['status'] = 'critical'
        await send_alert(
            f"Critical services down!\n"
            f"Database: {'✅' if db_ok else '❌'}\n"
            f"Redis: {'✅' if redis_ok else '❌'}",
            severity="critical"
        )
    elif failed_nodes:
        results['status'] = 'degraded'
        await send_alert(
            f"Blockchain nodes unreachable: {', '.join(failed_nodes)}",
            severity="warning"
        )
    elif pending['count'] > 10:
        results['status'] = 'warning'
        await send_alert(
            f"High number of pending transactions: {pending['count']}",
            severity="warning"
        )
    elif escrows['expired_count'] > 0:
        await send_alert(
            f"Expired escrows need attention: {escrows['expired_count']}",
            severity="info"
        )
    
    return results


async def main():
    """Main monitoring loop"""
    await db_manager.initialize()
    await wallet_manager.initialize()
    
    logger.info("Starting monitoring...")
    
    while True:
        try:
            results = await run_health_check()
            logger.info("Health check completed", **results)
        except Exception as e:
            logger.error("Health check failed", error=str(e))
            await send_alert(f"Health check error: {str(e)}", severity="error")
        
        await asyncio.sleep(300)  # Check every 5 minutes


if __name__ == "__main__":
    asyncio.run(main())