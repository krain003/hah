"""
NEXUS WALLET - Production Entry Point
Validated Launcher for Railway/Docker Environments
"""

import os
import sys
import uvicorn
import structlog

logger = structlog.get_logger(__name__)

def validate_environment():
    """Ensure all required secrets are present before boot"""
    required = ["BOT_TOKEN", "SECURITY_MASTER_KEY", "DATABASE_URL"]
    missing = [var for var in required if not os.getenv(var)]
    
    if missing:
        print(f"❌ CRITICAL ERROR: Missing environment variables: {', '.join(missing)}")
        sys.exit(1)

def bootstrap():
    """Pre-start configuration"""
    validate_environment()
    
    # Ensure local storage path
    data_path = "/app/data" if os.path.exists("/app") else "./data"
    os.makedirs(data_path, exist_ok=True)

def main():
    """Launches the Uvicorn high-performance server"""
    bootstrap()
    
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    
    print("""
    \033[94m
    ███╗   ██╗███████╗██╗  ██╗██╗   ██╗███████╗
    ████╗  ██║██╔════╝╚██╗██╔╝██║   ██║██╔════╝
    ██╔██╗ ██║█████╗   ╚███╔╝ ██║   ██║███████╗
    ██║╚██╗██║██╔══╝   ██╔██╗ ██║   ██║╚════██║
    ██║ ╚████║███████╗██╔╝ ██╗╚██████╔╝███████║
    ╚═╝  ╚═══╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚══════╝ v3.0
    \033[0m
    💎 NEXUS WALLET ECOSYSTEM IS STARTING...
    ────────────────────────────────────────────
    🌐 WEB:    http://0.0.0.0:8000
    🤖 BOT:    Polling Mode (Async Tasks)
    🔐 SEC:    AES-256 Enabled
    ────────────────────────────────────────────
    """)
    
    uvicorn.run(
        "web.app:app",
        host=host,
        port=port,
        workers=1, # Polling requires single worker
        log_level="info",
        access_log=True,
        proxy_headers=True,
        forwarded_allow_ips="*"
    )

if __name__ == "__main__":
    main()