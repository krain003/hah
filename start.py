"""
NEXUS WALLET - Production Starter
Guaranteed Database Initialization
"""

import os
import sys
import asyncio
import uvicorn
import structlog
import sqlite3
from contextlib import asynccontextmanager

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from web.app import app as web_app
from main import main as start_bot_logic

logger = structlog.get_logger()

# Path to database
DB_DIR = "/app/data"
DB_PATH = os.path.join(DB_DIR, "nexus_wallet.db")

def init_database_sync():
    """Initialize database synchronously using sqlite3"""
    logger.info(f"🛠️ Initializing Database at {DB_PATH}...")
    
    try:
        if not os.path.exists(DB_DIR):
            os.makedirs(DB_DIR, exist_ok=True)
            logger.info(f"Created directory {DB_DIR}")
            
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        # Create Tables
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                pin_hash TEXT,
                telegram_id INTEGER UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_login TIMESTAMP,
                is_active BOOLEAN DEFAULT 1
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_wallets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                network TEXT NOT NULL,
                address TEXT NOT NULL,
                encrypted_private_key TEXT NOT NULL,
                encrypted_mnemonic TEXT,
                name TEXT,
                is_primary BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES web_users(id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                wallet_id INTEGER NOT NULL,
                network TEXT NOT NULL,
                tx_hash TEXT,
                tx_type TEXT NOT NULL,
                amount TEXT NOT NULL,
                to_address TEXT,
                from_address TEXT,
                status TEXT DEFAULT 'pending',
                token_symbol TEXT,
                fee_amount TEXT,
                fee_token TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES web_users(id),
                FOREIGN KEY (wallet_id) REFERENCES web_wallets(id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES web_users(id)
            )
        """)
        
        # Indexes
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wallets_user ON web_wallets(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON web_transactions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram ON web_users(telegram_id)")
        
        conn.commit()
        conn.close()
        logger.info("✅ Database initialized successfully (SYNC)")
        return True
    except Exception as e:
        logger.error(f"❌ Database init failed: {e}")
        return False

@asynccontextmanager
async def lifespan(app):
    # --- STARTUP ---
    logger.info("🚀 Starting NEXUS WALLET Services...")
    
    # Start Bot in background
    bot_task = asyncio.create_task(start_bot_logic())
    
    yield
    
    # --- SHUTDOWN ---
    logger.info("🛑 Shutting down...")
    bot_task.cancel()
    try:
        await bot_task
    except asyncio.CancelledError:
        logger.info("Bot stopped cleanly")

# Attach lifespan
web_app.router.lifespan_context = lifespan

if __name__ == "__main__":
    # 1. Initialize DB FIRST (Sync)
    init_database_sync()
    
    # 2. Start Web Server (which starts Bot)
    port = int(os.environ.get("PORT", 8000))
    logger.info(f"🌍 Starting Web Server on port {port}")
    
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
        workers=1
    )