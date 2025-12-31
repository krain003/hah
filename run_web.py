"""
NEXUS WALLET - Web Application Runner
"""

import uvicorn
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    print("""
    ╔═══════════════════════════════════════════════════════════╗
    ║                                                           ║
    ║     💎 NEXUS WALLET - Web Interface                       ║
    ║                                                           ║
    ║     🌐 Open in browser: http://localhost:8000             ║
    ║     📚 API Docs: http://localhost:8000/docs               ║
    ║                                                           ║
    ║     Press Ctrl+C to stop                                  ║
    ║                                                           ║
    ╚═══════════════════════════════════════════════════════════╝
    """)
    
    uvicorn.run(
        "web.app:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )