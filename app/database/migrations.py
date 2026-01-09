"""
Database migrations for SQLite - FORCE RECREATE
"""
import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)


async def run_migrations(session):
    """Run migrations - drop and recreate problem tables"""
    
    # СНАЧАЛА УДАЛЯЕМ старые таблицы (потеряем данные, но это dev)
    drop_tables = [
        "DROP TABLE IF EXISTS giveaway_winners",
        "DROP TABLE IF EXISTS giveaway_participants", 
        "DROP TABLE IF EXISTS giveaways",
        "DROP TABLE IF EXISTS check_activations",
        "DROP TABLE IF EXISTS nexus_checks",
        "DROP TABLE IF EXISTS trades",
        "DROP TABLE IF EXISTS exchange_orders",
    ]
    
    for sql in drop_tables:
        try:
            await session.execute(text(sql))
            await session.commit()
        except Exception as e:
            await session.rollback()
    
    logger.info("Old tables dropped")
    
    # Создаём таблицы заново
    create_tables = [
        # Exchange Orders
        """
        CREATE TABLE IF NOT EXISTS exchange_orders (
            id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            pair TEXT NOT NULL,
            side TEXT NOT NULL,
            order_type TEXT DEFAULT 'limit',
            price REAL NOT NULL,
            amount REAL NOT NULL,
            remaining REAL NOT NULL,
            filled REAL DEFAULT 0,
            status TEXT DEFAULT 'open',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        
        # Trades
        """
        CREATE TABLE IF NOT EXISTS trades (
            id TEXT PRIMARY KEY,
            pair TEXT NOT NULL,
            buyer_order_id TEXT,
            seller_order_id TEXT,
            buyer_id TEXT,
            seller_id TEXT,
            price REAL NOT NULL,
            amount REAL NOT NULL,
            total REAL NOT NULL,
            fee REAL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        
        # Nexus Checks
        """
        CREATE TABLE IF NOT EXISTS nexus_checks (
            id TEXT PRIMARY KEY,
            creator_id TEXT NOT NULL,
            network TEXT NOT NULL,
            token_symbol TEXT NOT NULL,
            amount REAL NOT NULL,
            amount_per_activation REAL NOT NULL,
            max_activations INTEGER DEFAULT 1,
            activated_count INTEGER DEFAULT 0,
            code TEXT UNIQUE NOT NULL,
            password_hash TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP
        )
        """,
        
        # Check Activations
        """
        CREATE TABLE IF NOT EXISTS check_activations (
            id TEXT PRIMARY KEY,
            check_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            amount REAL NOT NULL,
            activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
        
        # Giveaways
        """
        CREATE TABLE IF NOT EXISTS giveaways (
            id TEXT PRIMARY KEY,
            creator_id TEXT NOT NULL,
            network TEXT NOT NULL,
            token_symbol TEXT NOT NULL,
            total_amount REAL NOT NULL,
            amount_per_winner REAL NOT NULL,
            winners_count INTEGER DEFAULT 1,
            code TEXT UNIQUE NOT NULL,
            caption TEXT,
            chat_id INTEGER,
            message_id INTEGER,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ends_at TIMESTAMP NOT NULL,
            completed_at TIMESTAMP
        )
        """,
        
        # Giveaway Participants
        """
        CREATE TABLE IF NOT EXISTS giveaway_participants (
            id TEXT PRIMARY KEY,
            giveaway_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(giveaway_id, user_id)
        )
        """,
        
        # Giveaway Winners
        """
        CREATE TABLE IF NOT EXISTS giveaway_winners (
            id TEXT PRIMARY KEY,
            giveaway_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            amount REAL NOT NULL,
            claimed INTEGER DEFAULT 1,
            won_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """,
    ]
    
    for sql in create_tables:
        try:
            await session.execute(text(sql.strip()))
            await session.commit()
            logger.info("Table created")
        except Exception as e:
            logger.warning(f"Create failed: {e}")
            await session.rollback()
    
    # Add locked column if missing
    try:
        await session.execute(text("ALTER TABLE wallet_balances ADD COLUMN locked REAL DEFAULT 0"))
        await session.commit()
    except:
        await session.rollback()
    
    logger.info("All migrations completed")