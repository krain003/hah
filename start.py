"""
NEXUS WALLET - Production Starter
Handles Railway.app deployment
"""

import os
import sys
import uvicorn

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def get_port() -> int:
    """Get port from environment (Railway sets PORT)"""
    return int(os.environ.get("PORT", 8000))


def get_host() -> str:
    """Get host - 0.0.0.0 for container"""
    return os.environ.get("HOST", "0.0.0.0")


def is_production() -> bool:
    """Check if running in production"""
    return os.environ.get("RAILWAY_ENVIRONMENT") is not None


if __name__ == "__main__":
    port = get_port()
    host = get_host()
    
    print(f"""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     💎 NEXUS WALLET - Starting...                         ║
    ║                                                           ║
    ║     🌐 Host: {host}                                   ║
    ║     🔌 Port: {port}                                       ║
    ║     🚀 Production: {is_production()}                          ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        reload=not is_production(),
        log_level="info" if is_production() else "debug",
        access_log=True,
        workers=1  # Single worker for SQLite compatibility
    )