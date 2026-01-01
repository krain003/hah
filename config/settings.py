from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr
from typing import Optional

class Settings(BaseSettings):
    # Bot Token
    BOT_TOKEN: SecretStr
    # Alias for Docker compatibility
    TG_BOT_TOKEN: Optional[SecretStr] = None 

    # Security
    SECURITY_MASTER_KEY: str = "default-master-key-change-me-32-chars!!"
    SECURITY_ENCRYPTION_SALT: str = "default-salt-16-chars!!"

    # Database
    DATABASE_URL: str = "sqlite:///nexus_wallet.db"

    # Web App URL (Your Railway Link)
    # Important: Must end with /tg/ for Mini App routes
    WEB_APP_URL: str = "https://nexus-wallet-production.up.railway.app/tg/"

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