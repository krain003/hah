from .start import router as start_router
from .wallet import router as wallet_router
from .send import router as send_router
from .receive import router as receive_router
from .real_swap import router as real_swap_router
from .p2p import router as p2p_router
from .history import router as history_router
from .settings import router as settings_router

__all__ = [
    "start_router",
    "wallet_router", 
    "send_router",
    "receive_router",
    "real_swap_router",
    "p2p_router",
    "history_router",
    "settings_router"
]