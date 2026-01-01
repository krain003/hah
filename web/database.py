"""
NEXUS WALLET - Database Manager
Compatible with Railway.app and SQLite
"""

import aiosqlite
import os
from typing import Optional, List, Dict
from datetime import datetime

# Railway-compatible database path
def get_database_path() -> str:
    """Get database path - works on Railway and locally"""
    # Check for Railway volume mount
    if os.path.exists("/app/data"):
        return "/app/data/nexus_wallet.db"
    
    # Local development fallback
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "nexus_wallet.db")


DATABASE_PATH = get_database_path()


async def get_db():
    """Get database connection"""
    db = await aiosqlite.connect(DATABASE_PATH)
    db.row_factory = aiosqlite.Row
    return db


async def init_db():
    """Initialize database tables"""
    # Ensure directory exists
    db_dir = os.path.dirname(DATABASE_PATH)
    if db_dir and not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
    
    async with aiosqlite.connect(DATABASE_PATH) as db:
        # Users table
        await db.execute("""
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
        
        # Wallets table
        await db.execute("""
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
        
        # Transactions table
        await db.execute("""
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
        
        # Sessions table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS web_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                session_token TEXT UNIQUE NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES web_users(id)
            )
        """)
        
        # Create indexes for better performance
        await db.execute("CREATE INDEX IF NOT EXISTS idx_wallets_user ON web_wallets(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user ON web_transactions(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_users_telegram ON web_users(telegram_id)")
        
        await db.commit()
        
    print(f"✅ Database initialized at: {DATABASE_PATH}")


class UserDB:
    """User database operations"""
    
    @staticmethod
    async def create_user(username: str, password_hash: str, email: str = None, telegram_id: int = None) -> int:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "INSERT INTO web_users (username, email, password_hash, telegram_id) VALUES (?, ?, ?, ?)",
                (username, email, password_hash, telegram_id)
            )
            await db.commit()
            return cursor.lastrowid
    
    @staticmethod
    async def get_user_by_username(username: str) -> Optional[Dict]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM web_users WHERE username = ?", (username,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    async def get_user_by_telegram_id(telegram_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM web_users WHERE telegram_id = ?", (telegram_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    async def get_user_by_id(user_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM web_users WHERE id = ?", (user_id,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    async def update_last_login(user_id: int):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            await db.execute(
                "UPDATE web_users SET last_login = ? WHERE id = ?",
                (datetime.now().isoformat(), user_id)
            )
            await db.commit()


class WalletDB:
    """Wallet database operations"""
    
    @staticmethod
    async def create_wallet(
        user_id: int,
        network: str,
        address: str,
        encrypted_private_key: str,
        encrypted_mnemonic: str = None,
        name: str = None,
        is_primary: bool = False
    ) -> int:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO web_wallets 
                   (user_id, network, address, encrypted_private_key, encrypted_mnemonic, name, is_primary)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (user_id, network, address, encrypted_private_key, encrypted_mnemonic, name, is_primary)
            )
            await db.commit()
            return cursor.lastrowid
    
    @staticmethod
    async def get_user_wallets(user_id: int) -> List[Dict]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM web_wallets WHERE user_id = ? ORDER BY is_primary DESC, created_at DESC",
                (user_id,)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    async def get_wallet_by_id(wallet_id: int, user_id: int) -> Optional[Dict]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM web_wallets WHERE id = ? AND user_id = ?",
                (wallet_id, user_id)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
            
    @staticmethod
    async def get_user_wallet_by_network(user_id: int, network: str) -> Optional[Dict]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM web_wallets WHERE user_id = ? AND network = ?",
                (user_id, network)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    async def get_wallet_by_address(address: str) -> Optional[Dict]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                "SELECT * FROM web_wallets WHERE address = ?",
                (address,)
            )
            row = await cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    async def delete_wallet(wallet_id: int, user_id: int) -> bool:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                "DELETE FROM web_wallets WHERE id = ? AND user_id = ?",
                (wallet_id, user_id)
            )
            await db.commit()
            return cursor.rowcount > 0


class TransactionDB:
    """Transaction database operations"""
    
    @staticmethod
    async def create_transaction(
        user_id: int,
        wallet_id: int,
        network: str,
        tx_type: str,
        amount: str,
        to_address: str = None,
        from_address: str = None,
        tx_hash: str = None,
        token_symbol: str = None,
        fee_amount: str = None,
        fee_token: str = None,
        status: str = "pending"
    ) -> int:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            cursor = await db.execute(
                """INSERT INTO web_transactions 
                   (user_id, wallet_id, network, tx_type, amount, to_address, from_address, 
                    tx_hash, token_symbol, fee_amount, fee_token, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, wallet_id, network, tx_type, amount, to_address, from_address,
                 tx_hash, token_symbol, fee_amount, fee_token, status)
            )
            await db.commit()
            return cursor.lastrowid
    
    @staticmethod
    async def get_user_transactions(user_id: int, limit: int = 50) -> List[Dict]:
        async with aiosqlite.connect(DATABASE_PATH) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """SELECT t.*, w.address as wallet_address, w.name as wallet_name
                   FROM web_transactions t
                   JOIN web_wallets w ON t.wallet_id = w.id
                   WHERE t.user_id = ?
                   ORDER BY t.created_at DESC
                   LIMIT ?""",
                (user_id, limit)
            )
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
    
    @staticmethod
    async def update_transaction_status(tx_id: int, status: str, tx_hash: str = None):
        async with aiosqlite.connect(DATABASE_PATH) as db:
            if tx_hash:
                await db.execute(
                    "UPDATE web_transactions SET status = ?, tx_hash = ? WHERE id = ?",
                    (status, tx_hash, tx_id)
                )
            else:
                await db.execute(
                    "UPDATE web_transactions SET status = ? WHERE id = ?",
                    (status, tx_id)
                )
            await db.commit()