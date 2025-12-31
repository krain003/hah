"""Web routes package"""

try:
    from . import auth
    from . import wallet
    from . import api
    from . import tg_app
except ImportError as e:
    print(f"Warning importing routes: {e}")