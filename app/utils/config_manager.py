# utils/config_manager.py
"""
NEXUS WALLET - Configuration Manager
Runtime configuration storage with database persistence
"""

import json
from typing import Any, Optional, Dict
from datetime import datetime
import structlog

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)


class ConfigManager:
    """
    Runtime configuration manager.
    Stores settings in memory with optional database persistence.
    """
    
    def __init__(self):
        self._cache: Dict[str, Any] = {}
        self._defaults = {
            "maintenance_mode": False,
            "maintenance_reason": "",
            "global_test_mode": False,
            "test_mode_networks": [],
            "p2p_enabled": True,
            "withdrawals_enabled": True,
            "deposits_enabled": True,
            "min_withdrawal_usd": 10,
            "max_withdrawal_usd": 50000,
        }
    
    # ========== Maintenance Methods ==========
    
    async def is_maintenance(self) -> bool:
        """Проверить, включен ли режим обслуживания"""
        return await self.get("maintenance_mode", False)
    
    async def set_maintenance(self, enabled: bool, reason: str = "") -> None:
        """Включить/выключить режим обслуживания"""
        await self.set("maintenance_mode", enabled)
        await self.set("maintenance_reason", reason)
    
    async def get_maintenance_reason(self) -> str:
        """Получить причину техобслуживания"""
        return await self.get("maintenance_reason", "")
    
    # ========== Feature Flags ==========
    
    async def is_p2p_enabled(self) -> bool:
        """Проверить, включен ли P2P"""
        return await self.get("p2p_enabled", True)
    
    async def is_withdrawals_enabled(self) -> bool:
        """Проверить, включены ли выводы"""
        return await self.get("withdrawals_enabled", True)
    
    async def is_deposits_enabled(self) -> bool:
        """Проверить, включены ли депозиты"""
        return await self.get("deposits_enabled", True)
    
    # ========== Core Get/Set Methods ==========
    
    async def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value"""
        if key in self._cache:
            return self._cache[key]
        
        # Try to load from database
        try:
            value = await self._load_from_db(key)
            if value is not None:
                self._cache[key] = value
                return value
        except Exception as e:
            logger.warning("Failed to load config from DB", key=key, error=str(e))
        
        # Return default
        if default is not None:
            return default
        return self._defaults.get(key)
    
    async def set(self, key: str, value: Any) -> bool:
        """Set configuration value"""
        self._cache[key] = value
        
        # Try to persist to database
        try:
            await self._save_to_db(key, value)
            logger.info("Config updated", key=key, value=str(value)[:50])
            return True
        except Exception as e:
            logger.warning("Failed to save config to DB", key=key, error=str(e))
            return True  # Still return True since it's in cache
    
    async def delete(self, key: str) -> None:
        """Удалить значение из кэша"""
        self._cache.pop(key, None)
    
    # ========== Database Methods ==========
    
    async def _load_from_db(self, key: str) -> Optional[Any]:
        """Load config from database"""
        try:
            from database.connection import db_manager
            from database.models import SystemConfig
            
            async with db_manager.session() as session:
                result = await session.scalar(
                    select(SystemConfig).where(SystemConfig.key == key)
                )
                if result:
                    return json.loads(result.value)
        except ImportError:
            pass  # SystemConfig model doesn't exist
        except Exception as e:
            logger.debug("DB config load failed", key=key, error=str(e))
        
        return None
    
    async def _save_to_db(self, key: str, value: Any) -> bool:
        """Save config to database"""
        try:
            from database.connection import db_manager
            from database.models import SystemConfig
            
            async with db_manager.session() as session:
                # Check if exists
                existing = await session.scalar(
                    select(SystemConfig).where(SystemConfig.key == key)
                )
                
                json_value = json.dumps(value)
                
                if existing:
                    existing.value = json_value
                    existing.updated_at = datetime.utcnow()
                else:
                    config = SystemConfig(
                        key=key,
                        value=json_value
                    )
                    session.add(config)
                
                await session.commit()
                return True
                
        except ImportError:
            # SystemConfig model doesn't exist, just use cache
            return True
        except Exception as e:
            logger.warning("DB config save failed", key=key, error=str(e))
            return False
    
    # ========== Synchronous Methods ==========
    
    def get_sync(self, key: str, default: Any = None) -> Any:
        """Synchronous get from cache only"""
        if key in self._cache:
            return self._cache[key]
        if default is not None:
            return default
        return self._defaults.get(key)
    
    def set_sync(self, key: str, value: Any) -> None:
        """Synchronous set to cache only (without DB persistence)"""
        self._cache[key] = value
    
    # ========== Utility Methods ==========
    
    def clear_cache(self):
        """Clear configuration cache"""
        self._cache.clear()
        logger.info("Config cache cleared")
    
    async def get_all(self) -> Dict[str, Any]:
        """Get all configuration values"""
        result = dict(self._defaults)
        result.update(self._cache)
        return result
    
    async def is_test_mode(self, network: str = None) -> bool:
        """Check if test mode is active for a network"""
        global_test = await self.get("global_test_mode", False)
        if global_test:
            return True
        
        if network:
            test_networks = await self.get("test_mode_networks", [])
            return network in test_networks
        
        return False
    
    # ========== Limits ==========
    
    async def get_min_withdrawal_usd(self) -> float:
        """Получить минимальную сумму вывода в USD"""
        return await self.get("min_withdrawal_usd", 10)
    
    async def get_max_withdrawal_usd(self) -> float:
        """Получить максимальную сумму вывода в USD"""
        return await self.get("max_withdrawal_usd", 50000)


# Global instance
config_manager = ConfigManager()