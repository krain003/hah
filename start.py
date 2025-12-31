"""
NEXUS WALLET - Production Starter
"""

import os
import sys
import asyncio

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def get_port() -> int:
    return int(os.environ.get("PORT", 8000))

def get_host() -> str:
    return os.environ.get("HOST", "0.0.0.0")

def is_production() -> bool:
    return os.environ.get("RAILWAY_ENVIRONMENT") is not None

async def init_database():
    """Initialize database before starting server"""
    try:
        from web.database import init_db
        await init_db()
        print("✅ Database initialized")
    except Exception as e:
        print(f"⚠️ Database init warning: {e}")

if __name__ == "__main__":
    import uvicorn
    
    port = get_port()
    host = get_host()
    
    print(f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║     💎 NEXUS WALLET - Starting...                         ║
    ║     🌐 Host: {host}                                       ║
    ║     🔌 Port: {port}                                       ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Initialize database
    asyncio.run(init_database())
    
    # Start server
    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
        workers=1
    )