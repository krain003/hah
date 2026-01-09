from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr
from typing import List, Optional, Union
import json

class Settings(BaseSettings):
    # Bot Token
    BOT_TOKEN: SecretStr
    # Alias for Docker compatibility
    TG_BOT_TOKEN: Optional[SecretStr] = None 

    # Security
    SECURITY_MASTER_KEY: str = "default-master-key-change-me-32-chars!!"
    SECURITY_ENCRYPTION_SALT: str = "default-salt-16-chars!!"

    # Swap Service (ChangeNOW)
    CHANGENOW_API_KEY: Optional[str] = None

    # Database
    DATABASE_URL: str = "sqlite:///nexus_wallet.db"

    # Web App URL
    WEB_APP_URL: str = "https://nexus-wallet-production.up.railway.app/tg/"

    # Admin IDs (List of integers)
    # Can be set in .env as: ADMIN_IDS=[123456789, 987654321]
    ADMIN_IDS: List[int] = [8405499025] 

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    def model_post_init(self, __context):
        # Fallback if BOT_TOKEN is missing but TG_BOT_TOKEN exists
        if self.TG_BOT_TOKEN and not self.BOT_TOKEN:
            self.BOT_TOKEN = self.TG_BOT_TOKEN

settings = Settings()