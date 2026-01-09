"""
NEXUS WALLET - Bot Entry Point
"""

import asyncio
import sys
import os

# Add app directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Try different import variants
try:
    import main
    
    # Try to find the correct function
    if hasattr(main, 'start_bot'):
        asyncio.run(main.start_bot())
    elif hasattr(main, 'main'):
        asyncio.run(main.main())
    elif hasattr(main, 'run'):
        asyncio.run(main.run())
    elif hasattr(main, 'start'):
        asyncio.run(main.start())
    else:
        # List available functions
        funcs = [f for f in dir(main) if not f.startswith('_') and callable(getattr(main, f))]
        print(f"Available functions in main.py: {funcs}")
        raise AttributeError("No start function found in main.py")
        
except Exception as e:
    print(f"Error starting bot: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)